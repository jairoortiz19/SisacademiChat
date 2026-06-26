"""
Bootstrap de auto-actualizacion del INSTALADOR (no del chat).

Contexto del problema
---------------------
Algunos equipos quedaron instalados con el paquete del instalador en
``C:\\InstaladorSisacademi`` SIN carpeta ``.git`` (la copia a USB excluyo ``.git``).
Sin ``.git``, ni el auto-update (``Sync-PackageHard``) ni ``actualizar-instalador.bat``
pueden traer los scripts del instalador desde GitHub: el equipo se queda sin poder
auto-actualizar el instalador.

Solucion
--------
El CHAT si se actualiza solo (canal de componentes, NO necesita el ``.git`` del paquete)
y corre como SYSTEM. Aprovechamos su arranque para "enganchar" el paquete al repo:
``git init`` + ``remote`` + ``safe.directory``. Una vez hecho, la siguiente corrida del
auto-update ya sincroniza el instalador y el equipo se auto-actualiza para siempre.
Asi el fix llega a la flota SIN tocar equipo por equipo.

Garantias
---------
* **Idempotente**: si ``.git`` ya existe, no hace nada.
* **Fail-safe**: cualquier error se traga; NUNCA afecta el funcionamiento del chat.
* **Sin secretos en el repo**: el token se lee del ``.env`` local del equipo
  (este repo del chat es publico, no se puede hardcodear el token).
"""

import os
import subprocess

PKG_DIR = r"C:\InstaladorSisacademi"
REMOTE_HOST_PATH = "github.com/jairoortiz19/InstaladorSisacademi.git"


def _find_git():
    """Devuelve un ejecutable de git utilizable: el del sistema o el portable bundleado."""
    candidates = [
        "git",
        os.path.join(PKG_DIR, r"SisAcademiOffline\runtime\git\cmd\git.exe"),
        r"C:\Sitios\Runtime\git\cmd\git.exe",
    ]
    for cand in candidates:
        try:
            res = subprocess.run(
                [cand, "--version"],
                cwd=PKG_DIR,
                capture_output=True,
                timeout=15,
            )
            if res.returncode == 0:
                return cand
        except Exception:
            continue
    return None


def _read_installer_token():
    """Lee INSTALLER_TOKEN (o GIT_TOKEN) del .env local del paquete. No se hardcodea."""
    envp = os.path.join(PKG_DIR, ".env")
    if not os.path.isfile(envp):
        return ""
    try:
        with open(envp, encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                line = raw.strip()
                for key in ("INSTALLER_TOKEN=", "GIT_TOKEN="):
                    if line.startswith(key):
                        val = line.split("=", 1)[1].strip()
                        if val:
                            return val
    except Exception:
        pass
    return ""


def bootstrap_installer_git():
    """
    Si el paquete del instalador (``C:\\InstaladorSisacademi``) no es repo git, lo
    engancha al remoto para que pueda auto-actualizarse. Idempotente y fail-safe.
    """
    try:
        if not os.path.isdir(PKG_DIR):
            return  # no es un equipo con el instalador desplegado
        if os.path.isdir(os.path.join(PKG_DIR, ".git")):
            return  # ya esta enganchado: nada que hacer

        git = _find_git()
        if not git:
            return  # sin git no podemos hacer nada

        token = _read_installer_token()
        if not token:
            return  # sin token no podemos configurar el remoto autenticado

        url = "https://{0}@{1}".format(token, REMOTE_HOST_PATH)

        def run(args, timeout=60, extra_env=None):
            env = None
            if extra_env:
                env = dict(os.environ)
                env.update(extra_env)
            return subprocess.run(
                [git] + args,
                cwd=PKG_DIR,
                capture_output=True,
                timeout=timeout,
                env=env,
            )

        # Confiar en el repo para cualquier cuenta (evita "dubious ownership", git error 128).
        run(["config", "--system", "--add", "safe.directory", "*"], timeout=30)
        run(["config", "--global", "--add", "safe.directory", "*"], timeout=30)

        # Enganchar al remoto.
        run(["init"], timeout=30)
        run(["remote", "remove", "origin"], timeout=15)  # por si quedo a medias en un intento previo
        run(["remote", "add", "origin", url], timeout=15)

        # Dejar HEAD apuntando a main (sin descargar LFS pesado: el reset --hard real lo hace
        # despues Sync-PackageHard del auto-update). Asi 'git rev-parse HEAD' ya funciona.
        fetched = run(
            ["fetch", "--depth=1", "origin", "main"],
            timeout=600,
            extra_env={"GIT_LFS_SKIP_SMUDGE": "1"},
        )
        if fetched is not None and fetched.returncode == 0:
            run(["reset", "--soft", "FETCH_HEAD"], timeout=30)
    except Exception:
        # Jamas romper el chat por esto.
        pass