# SisacademiChat — Guia de Instalacion e Integracion

---

## Requisitos del sistema

| Requisito | Detalle |
|---|---|
| Sistema operativo | Windows 10 (build 1803+) o Windows 11, 64-bit |
| RAM minima | 4 GB (recomendado 8 GB+) |
| Disco | ~5 GB libres (Python embebido + Ollama + 2 modelos LLM + embeddings + KB) |
| Internet | Requerido solo en la primera instalacion (descarga ~3 GB) |
| Software previo | Ninguno — el instalador descarga todo automaticamente |

**Modelos descargados automaticamente:**
- `qwen2.5:1.5b` (~1 GB) — chat de estudiantes en espanol
- `llama3.2:1b` (~1.3 GB) — chat de estudiantes en ingles
- `paraphrase-multilingual-MiniLM-L12-v2` (~46 MB) — embeddings vectoriales

---

## Instalacion en PC nuevo

Hay **3 caminos** segun el escenario. El **Camino 1 es el recomendado** para despliegues estandar.

### Camino 1 — Instalador automatico (Recomendado)

Descarga el repo, escribe `config.env` con valores correctos y arranca el servicio. Sin pasos manuales.

#### Paso 1 — Obtener `install.bat`

Opcion A (terminal):
```cmd
curl -L -o install.bat https://raw.githubusercontent.com/jairoortiz19/SisacademiChat/main/install.bat
```

Opcion B (manual): descargar `install.bat` desde el repositorio y guardarlo en cualquier ubicacion (Escritorio, USB, etc.).

#### Paso 2 — Ejecutar

Doble clic en `install.bat`. El proceso es completamente automatico:

```
[1/5] Verificando requisitos del sistema
[2/5] Descargando repositorio desde GitHub
[3/5] Extrayendo archivos en C:\Sitios\SisacademiChat
[4/5] Escribiendo configuracion (config.env con todos los valores)
[5/5] Iniciando SisacademiChat
        └── [1/6] Ollama (instala si falta)
        └── [2/6] Servicio Ollama y descarga de modelos LLM
        └── [3/6] Python 3.12 embebido (portable)
        └── [4/6] Dependencias Python
        └── [5/6] Base de datos y embeddings
        └── [6/6] Servicio HTTP en puerto 8090
```

La primera instalacion tarda **10-20 minutos** segun la conexion a internet (descarga ~3 GB entre Ollama, los 2 modelos LLM y el modelo de embeddings).

#### Paso 3 — Verificar

Al finalizar, la terminal muestra:

```
============================================
  Servicio:  http://127.0.0.1:8090
  API Docs:  http://127.0.0.1:8090/docs
  Detener:   Ctrl+C  o  stop.bat
============================================
```

Abrir `http://127.0.0.1:8090/api/v1/health` en el navegador debe retornar `{"status":"ok",...}`.

#### Reinstalacion / actualizacion

Volver a ejecutar `install.bat` y responder `S` cuando pregunta. Comportamiento:
- Descarga la version mas reciente del repo desde GitHub.
- **Conserva** `python\` (evita re-descargar 25 MB) y el `DEVICE_ID` original.
- **Reescribe** el resto de `config.env` con los valores actualizados de la nueva version.
- Si la descarga falla, restaura automaticamente la instalacion anterior.

### Camino 2 — `git clone` + `run.bat` (manual, mas control)

Para desarrolladores o cuando se necesita personalizar antes del primer arranque:

```cmd
git clone https://github.com/jairoortiz19/SisacademiChat.git C:\Sitios\SisacademiChat
cd C:\Sitios\SisacademiChat
copy config.env.example config.env
notepad config.env       REM Editar API_KEY, SERVER_URL, SERVER_API_KEY antes de arrancar
run.bat
```

`run.bat` lee `config.env` y descarga lo que falte. Si `config.env` no existe, usa los defaults hardcoded en el script (que apuntan a los modelos correctos).

### Camino 3 — Clonar instalacion existente (transferir entre maquinas)

Util cuando ya hay una maquina funcionando y quieres replicarla sin descargas:

1. **Copiar la carpeta completa** `C:\Sitios\SisacademiChat\` (incluye `python\`, `data\`, todo).
2. **En la maquina destino:**
   - Borrar `data\logs.db` (logs de la maquina vieja, no son utiles).
   - Editar `config.env` y borrar la linea `DEVICE_ID=...` (se generara uno nuevo en el primer arranque).
3. **Asegurarse de que Ollama este instalado** y los modelos descargados:
   ```cmd
   ollama list
   REM Debe aparecer qwen2.5:1.5b y llama3.2:1b
   ```
   Si falta alguno: `ollama pull qwen2.5:1.5b` y `ollama pull llama3.2:1b`.
4. Ejecutar `run.bat`.

---

## Directorio de instalacion

El instalador crea todo en:

```
C:\Sitios\SisacademiChat\
├── app\                   # Codigo fuente de la aplicacion
├── data\
│   ├── knowledge.db       # Base de conocimiento (vectores + documentos)
│   └── logs.db            # Logs de uso
├── python\                # Python 3.12 embebido (portable, no afecta el sistema)
├── config.env             # Configuracion local del servicio
├── requirements.txt       # Dependencias Python
├── run.bat                # Inicia el servicio
└── stop.bat               # Detiene el servicio
```

> `python\` y `config.env` **no se sobreescriben** en reinstalaciones, preservando la configuracion y evitando rebajar Python.

---

## Iniciar y detener el servicio

| Accion | Comando | Que hace |
|---|---|---|
| Iniciar | Doble clic en `C:\Sitios\SisacademiChat\run.bat` | Arranca el servicio. Si hay internet, sincroniza KB del server y sube logs pendientes antes de arrancar. |
| Detener | Doble clic en `C:\Sitios\SisacademiChat\stop.bat` o `Ctrl+C` en la terminal | Detiene el servicio. |
| **Actualizar codigo + KB** | Doble clic en `update.bat` | Detiene el servicio, descarga la ultima version del codigo desde GitHub, actualiza dependencias, sincroniza KB del server, reinicia. **PRESERVA `config.env`, `data\`, `python\`**. |
| Reinstalar (limpio) | Doble clic en `install.bat` → `S` | Borra todo (excepto `python\` y `DEVICE_ID`), descarga repo desde cero, escribe `config.env` nuevo desde plantilla. **Pierde personalizaciones de `config.env`**. |

El servicio **no arranca automaticamente** con Windows. Para configurar inicio automatico, crear una tarea en el Programador de tareas de Windows apuntando a `run.bat`.

---

## Puerto y direccion del servicio

| Parametro | Valor por defecto | Donde cambiarlo |
|---|---|---|
| Host | `127.0.0.1` (solo local) | `HOST` en `config.env` |
| Puerto | `8090` | `PORT` en `config.env` |
| Prefijo de API | `/api/v1` | Fijo en el codigo |

**URL base:** `http://127.0.0.1:8090/api/v1`

> Por defecto el servicio escucha **solo en localhost**. Para exponerlo en la red local
> cambiar `HOST=0.0.0.0` en `config.env` y reiniciar con `run.bat`.

### Exponer el servicio (red local o internet)

Por defecto el servicio escucha en `127.0.0.1` (solo localhost) y **el firewall de Windows no permite conexiones externas**.

Para exponerlo se necesitan **dos pasos**:

#### Paso 1 — Cambiar HOST a `0.0.0.0`

Editar `C:\Sitios\SisacademiChat\config.env`:

```env
HOST=0.0.0.0
PORT=8090
```

Esto hace que uvicorn escuche en todas las interfaces de red.

#### Paso 2 — Abrir el puerto en Windows Firewall

```cmd
firewall.bat
```

`firewall.bat` se auto-eleva a administrador via UAC y crea la regla `SisacademiChat` que permite TCP entrante al puerto configurado. Subcomandos:

| Comando | Que hace |
|---|---|
| `firewall.bat` o `firewall.bat open` | Crea/recrea la regla |
| `firewall.bat close` | Borra la regla (cierra el puerto) |
| `firewall.bat status` | Muestra el estado actual |

Reiniciar el servicio. Otros equipos en la **misma red** podran acceder via:
```
http://<IP-LAN-del-PC>:8090/api/v1
```

Si `run.bat` detecta `HOST=0.0.0.0` sin regla de firewall, avisa al arrancar.

#### Paso 3 (solo internet publico) — Port forwarding en el router

Para que el servicio sea accesible desde **fuera** de la red local:

1. Entrar al panel del router.
2. Configurar port forwarding: `IP-publica:8090` → `IP-LAN-del-PC:8090` (TCP).
3. Probar desde otro lugar:
   ```
   curl http://<IP-publica>:8090/api/v1/health -H "X-API-Key: <tu-api-key>"
   ```

> **AVISO de seguridad:** sin HTTPS la `API_KEY` viaja en texto plano. Para uso publico real:
> - Regenera la `API_KEY` antes de exponer (la actual ya pudo haber quedado en repos/logs).
> - Pon un reverse proxy con HTTPS delante (Caddy es el mas simple: maneja certificados Let's Encrypt automaticamente).
> - Limita CORS si solo un cliente conocido va a consumir (`ALLOWED_ORIGINS` esta en `app/main.py`).

---

## Integracion desde otro sistema

### Autenticacion

Todas las peticiones (excepto `/health`) deben incluir la cabecera:

```
X-API-Key: <valor-de-API_KEY-en-config.env>
```

### Verificar que el servicio esta activo

Antes de hacer peticiones, consultar el health check:

```bash
curl http://127.0.0.1:8090/api/v1/health
```

Respuesta esperada:
```json
{
  "status": "ok",
  "ollama": "connected",
  "knowledge_chunks": 9332,
  "knowledge_sources": 109
}
```

Si `status` es `"degraded"`, el LLM no esta disponible pero el servicio puede responder con datos de cache.

### Enviar una pregunta (chat)

```bash
curl -X POST http://127.0.0.1:8090/api/v1/chat \
  -H "X-API-Key: uoemm2mEzkGwxVS_6T7WPvOdgwB5kyyHScOdssq-zfI" \
  -H "Content-Type: application/json" \
  -d '{"message": "Que es la fotosintesis?"}'
```

Respuesta:
```json
{
  "answer": "La fotosintesis es el proceso mediante el cual...",
  "sources": [
    {
      "source_name": "biologia.pdf",
      "page_number": 12,
      "score": 0.87,
      "chunk_text": "..."
    }
  ],
  "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "tokens_in": 312,
  "tokens_out": 128,
  "latency_ms": 3200
}
```

### Enviar una pregunta (streaming)

Recomendado para interfaces de usuario que muestran la respuesta en tiempo real:

```bash
curl -X POST http://127.0.0.1:8090/api/v1/chat/stream \
  -H "X-API-Key: uoemm2mEzkGwxVS_6T7WPvOdgwB5kyyHScOdssq-zfI" \
  -H "Content-Type: application/json" \
  -d '{"message": "Que es la fotosintesis?"}' \
  --no-buffer
```

La respuesta llega como eventos SSE en este orden:

```
data: {"type":"sources","sources":[...],"conversation_id":"uuid"}

data: {"type":"token","content":"La "}
data: {"type":"token","content":"fotosintesis "}
...
data: {"type":"done","tokens_in":312,"tokens_out":128,"latency_ms":3200}
```

**Consumir SSE desde JavaScript:**

```javascript
const response = await fetch('http://127.0.0.1:8090/api/v1/chat/stream', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': 'tu-api-key'
  },
  body: JSON.stringify({ message: 'Que es la fotosintesis?' })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const lines = decoder.decode(value).split('\n');
  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    const event = JSON.parse(line.slice(6));

    if (event.type === 'token') {
      process.stdout.write(event.content); // mostrar token en pantalla
    } else if (event.type === 'sources') {
      console.log('Fuentes:', event.sources);
    } else if (event.type === 'done') {
      console.log('Latencia:', event.latency_ms, 'ms');
    }
  }
}
```

**Consumir SSE desde Python:**

```python
import httpx, json

with httpx.Client() as client:
    with client.stream(
        "POST",
        "http://127.0.0.1:8090/api/v1/chat/stream",
        headers={"X-API-Key": "tu-api-key", "Content-Type": "application/json"},
        json={"message": "Que es la fotosintesis?"},
        timeout=120,
    ) as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            if event["type"] == "token":
                print(event["content"], end="", flush=True)
            elif event["type"] == "done":
                print(f"\nLatencia: {event['latency_ms']}ms")
```

---

## Configuracion en `config.env`

El archivo `C:\Sitios\SisacademiChat\config.env` controla todo el comportamiento del servicio.
Editar con cualquier editor de texto y reiniciar `run.bat` para aplicar cambios.

```env
# Servicio
PORT=8090
HOST=127.0.0.1

# Autenticacion
API_KEY=cambiar-esta-clave-en-produccion
RATE_LIMIT_PER_MINUTE=30

# Modelos LLM (Ollama) — routing automatico por idioma de la pregunta
OLLAMA_MODEL=qwen2.5:1.5b           # base (multilingue, fuerte en espanol)
OLLAMA_MODEL_FAST=qwen2.5:1.5b      # chat estudiantes (espanol)
OLLAMA_MODEL_ENGLISH=llama3.2:1b    # chat estudiantes (ingles)
OLLAMA_MODEL_SMART=qwen2.5:1.5b     # reportes profesor (subir a qwen2.5:3b si hay RAM)

# Anti-alucinacion
MIN_TOP_SCORE_TO_ANSWER=0.28        # umbral; debajo = "no encontre informacion"
STRICT_SPANISH_ONLY=false           # true fuerza espanol siempre

# Servidor central (sincronizacion de base de conocimiento)
SERVER_URL=http://servidor-central:8091
SERVER_API_KEY=clave-del-servidor
DEVICE_ID=                          # vacio = se autogenera en el primer arranque
```

Para referencia completa de **todas las 28 variables** ver `config.env.example` en el repo, [API.md](API.md) seccion Configuracion, o el [README.md](README.md) seccion Configuracion.

### Defensas anti-alucinacion incluidas

Por defecto el sistema combina **6 capas** que previenen que el modelo invente contenido fuera del KB:

1. **Pre-filtro off-topic** — preguntas tipo "cuentame un chiste", "que tal el clima", o intentos de jailbreak (`ignora tus instrucciones`) se detectan antes de tocar Ollama.
2. **Umbral de retrieval** (`MIN_TOP_SCORE_TO_ANSWER`) — si los chunks recuperados tienen scores muy bajos, responde NO_INFO sin invocar el LLM.
3. **Filtro de fuentes ficticias** (`FICTIONAL_SOURCE_PATTERNS`) — cuentos y narrativa no se usan para preguntas factuales.
4. **Prompt estricto** — system prompt prohibe inventar y usar conocimiento general.
5. **Stop sequences** — 13 patrones que cortan la generacion si el modelo intenta divagar (`\nPregunta:`, `\nNota:`, etc.).
6. **Grounding check post-respuesta** — verifica que las palabras clave de la respuesta aparezcan literalmente en el contexto recuperado. Si overlap < 35%, reemplaza por NO_INFO.

Detalles en `README.md` seccion **Defensas Anti-Alucinacion**.

---

## Solucion de problemas

| Problema | Causa probable | Solucion |
|---|---|---|
| `install.bat` falla en descarga | Repositorio privado o sin internet | Verificar conexion; si el repo es privado contactar al administrador |
| Puerto 8090 ocupado | Otro proceso usa el puerto | `run.bat` lo detecta y ofrece liberar el puerto o usar otro |
| `status: degraded` en `/health` | Ollama no esta corriendo | Ejecutar `ollama serve` o reiniciar con `run.bat` |
| `knowledge_chunks: 0` | Base de conocimiento vacia | Ejecutar `POST /api/v1/sync/knowledge` con la API key |
| El servicio se cierra solo | Error en la app | Revisar la terminal para ver el mensaje de error |
| Respuestas muy lentas | Hardware limitado o modelo grande | Bajar a `qwen2.5:0.5b` en config.env y reducir `OLLAMA_NUM_CTX` |
| Respuestas cortadas a media frase | `OLLAMA_NUM_PREDICT` muy bajo | Aumentar a `400` o `500` en `config.env` |
| Demasiados "no encontre informacion" | Umbral muy estricto o KB pobre | Bajar `MIN_TOP_SCORE_TO_ANSWER` (default 0.28) o regenerar KB |
| Respuestas mezclan espanol/ingles | Modelo pequeno mezclando idiomas | Activar `STRICT_SPANISH_ONLY=true` |
| `503` en endpoints `/professor/` | Datos academicos no sincronizados | Ejecutar `POST /api/v1/sync/knowledge` |
