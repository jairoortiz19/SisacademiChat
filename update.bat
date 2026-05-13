@echo off
title SisacademiChat - Actualizador
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ============================================================
REM  CONFIGURACION
REM ============================================================
set "INSTALL_DIR=%cd%"
set "REPO_URL=https://github.com/jairoortiz19/SisacademiChat/archive/refs/heads/main.zip"
set "MAX_RETRIES=3"
set "PORT=8090"
for /f "tokens=2 delims==# " %%a in ('findstr /i "^PORT=" config.env 2^>nul') do set "PORT=%%a"

echo ============================================
echo   SisacademiChat - Actualizador
echo ============================================
echo.
echo   Carpeta: %INSTALL_DIR%
echo   Puerto del servicio: %PORT%
echo.
echo   Descargara la ultima version del codigo desde GitHub
echo   y reiniciara el servicio.
echo.
echo   PRESERVA: config.env, data\, python\
echo   ACTUALIZA: app\, *.md, requirements.txt
echo.
set "CONFIRM="
set /p "CONFIRM=  Continuar? [S/N]: "
if /i not "!CONFIRM!"=="S" (
    echo.
    echo   Cancelado por el usuario.
    pause
    exit /b 0
)

REM ============================================================
REM  [1/6] Detener servicio si esta corriendo en ESTE PORT
REM ============================================================
echo.
echo [1/6] Verificando si hay servicio corriendo en puerto %PORT%...

set "SERVICE_PID="
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    set "SERVICE_PID=%%a"
)

if defined SERVICE_PID (
    echo   Deteniendo PID !SERVICE_PID!...
    taskkill /PID !SERVICE_PID! /F
    timeout /t 2 /nobreak >nul
    echo   Servicio detenido.
) else (
    echo   No hay servicio corriendo. Continuando.
)

REM ============================================================
REM  [2/6] Descargar ultima version del repo
REM ============================================================
echo.
echo [2/6] Descargando ultima version del codigo...
set "ZIP_FILE=%TEMP%\sisacademi_update_%RANDOM%.zip"
set "EXTRACT_TMP=%TEMP%\sisacademi_extract_%RANDOM%"

set "DOWNLOAD_OK=0"
for /l %%i in (1,1,%MAX_RETRIES%) do (
    if "!DOWNLOAD_OK!"=="0" (
        if %%i gtr 1 (
            echo   Esperando 5s antes de reintentar...
            timeout /t 5 /nobreak >nul
        )
        echo   Intento %%i/%MAX_RETRIES%...
        curl -L --retry 2 --connect-timeout 30 --max-time 180 -o "!ZIP_FILE!" "%REPO_URL%"
        if !errorlevel! equ 0 (
            for %%s in ("!ZIP_FILE!") do set "FSIZE=%%~zs"
            if !FSIZE! gtr 10000 (
                set "DOWNLOAD_OK=1"
                echo   Descarga completada (!FSIZE! bytes^).
            ) else (
                echo   Archivo descargado muy pequeno (!FSIZE! bytes^), reintentando.
                del "!ZIP_FILE!" 2>nul
            )
        ) else (
            echo   curl fallo con codigo !errorlevel!, reintentando.
            del "!ZIP_FILE!" 2>nul
        )
    )
)

if "!DOWNLOAD_OK!"=="0" (
    echo.
    echo   ERROR: No se pudo descargar el repo tras %MAX_RETRIES% intentos.
    echo   Verifica tu conexion. El servicio NO fue reiniciado.
    pause
    exit /b 1
)

REM ============================================================
REM  [3/6] Extraer ZIP
REM ============================================================
echo.
echo [3/6] Extrayendo...
if exist "!EXTRACT_TMP!" rmdir /s /q "!EXTRACT_TMP!"
mkdir "!EXTRACT_TMP!"
tar -xf "!ZIP_FILE!" -C "!EXTRACT_TMP!"
if !errorlevel! neq 0 (
    echo   ERROR: No se pudo extraer el ZIP.
    del "!ZIP_FILE!" 2>nul
    rmdir /s /q "!EXTRACT_TMP!" 2>nul
    pause
    exit /b 1
)
del "!ZIP_FILE!" 2>nul

REM GitHub extrae en una carpeta SisacademiChat-main\
set "SRC_DIR="
for /d %%d in ("!EXTRACT_TMP!\*") do (
    if "!SRC_DIR!"=="" set "SRC_DIR=%%d"
)
if "!SRC_DIR!"=="" (
    echo   ERROR: No se encontro carpeta dentro del ZIP.
    rmdir /s /q "!EXTRACT_TMP!" 2>nul
    pause
    exit /b 1
)
echo   Codigo extraido en: !SRC_DIR!

REM ============================================================
REM  [4/6] Aplicar actualizacion (sin tocar config.env, data\, python\)
REM ============================================================
echo.
echo [4/6] Aplicando actualizacion...

REM Backup de seguridad de config.env
copy /y "%INSTALL_DIR%\config.env" "%TEMP%\sisacademi_config_safety.env" >nul 2>&1

REM Mirror de app\ — robocopy /MIR borra los archivos que ya no existen en la nueva version
robocopy "!SRC_DIR!\app" "%INSTALL_DIR%\app" /MIR /NJH /NJS /NDL /NC /NS /NP /NFL
set "RC_ERR=!errorlevel!"
if !RC_ERR! geq 8 (
    echo   ERROR: robocopy fallo con codigo !RC_ERR! copiando app\
    goto :restore_and_exit
)
echo   app\ actualizado.

REM Copiar archivos sueltos. IMPORTANTE: excluimos update.bat (este script)
REM para evitar que CMD se confunda al leer un script auto-sobreescrito.
REM update.bat se actualizara en el proximo update (con la version actual ya descargada).
for %%f in (run.bat install.bat stop.bat chat.bat) do (
    if exist "!SRC_DIR!\%%f" (
        copy /y "!SRC_DIR!\%%f" "%INSTALL_DIR%\%%f" >nul
    )
)
for %%f in (README.md INSTALL.md API.md PROMPT_CHAT_CLIENTE.md PANEL_PROFESOR.md) do (
    if exist "!SRC_DIR!\%%f" (
        copy /y "!SRC_DIR!\%%f" "%INSTALL_DIR%\%%f" >nul
    )
)
if exist "!SRC_DIR!\requirements.txt" copy /y "!SRC_DIR!\requirements.txt" "%INSTALL_DIR%\requirements.txt" >nul
if exist "!SRC_DIR!\config.env.example" copy /y "!SRC_DIR!\config.env.example" "%INSTALL_DIR%\config.env.example" >nul
if exist "!SRC_DIR!\SisacademiChat.postman_collection.json" copy /y "!SRC_DIR!\SisacademiChat.postman_collection.json" "%INSTALL_DIR%\SisacademiChat.postman_collection.json" >nul

REM Copiar update.bat con nombre temporal — se renombrara al final (manualmente o al proximo run)
if exist "!SRC_DIR!\update.bat" (
    copy /y "!SRC_DIR!\update.bat" "%INSTALL_DIR%\update.bat.new" >nul
    echo   update.bat actualizado a update.bat.new (renombrar tras este run^).
)

echo   Scripts y docs actualizados.

REM Sanity check: config.env sigue ahi
if not exist "%INSTALL_DIR%\config.env" (
    echo   ERROR: config.env desaparecio durante la actualizacion.
    goto :restore_and_exit
)

rmdir /s /q "!EXTRACT_TMP!" 2>nul
del "%TEMP%\sisacademi_config_safety.env" 2>nul

REM ============================================================
REM  [5/6] Actualizar dependencias Python si cambiaron
REM ============================================================
echo.
echo [5/6] Verificando dependencias Python...
if not exist "%INSTALL_DIR%\python\python.exe" (
    echo   ADVERTENCIA: Python embebido no encontrado en %INSTALL_DIR%\python\
    echo   Ejecuta install.bat para hacer una instalacion completa primero.
    pause
    exit /b 1
)

"%INSTALL_DIR%\python\python.exe" -m pip install -r requirements.txt --upgrade --no-warn-script-location -q
if !errorlevel! equ 0 (
    echo   Dependencias OK.
) else (
    echo   ADVERTENCIA: pip install fallo. El servicio puede no arrancar.
    echo   Continuando de todas formas...
)

REM ============================================================
REM  [6/6] Renombrar update.bat.new (si existe) y reiniciar servicio
REM ============================================================
echo.
echo [6/6] Finalizando y reiniciando servicio...

REM Si hay update.bat.new pendiente, lo aplicamos via un .bat temporal que correra DESPUES
REM de que este script termine. Asi no auto-sobreescribimos el script en ejecucion.
if exist "%INSTALL_DIR%\update.bat.new" (
    echo   Programando reemplazo de update.bat al cierre...
    (
        echo @echo off
        echo timeout /t 2 /nobreak ^>nul
        echo move /y "%INSTALL_DIR%\update.bat.new" "%INSTALL_DIR%\update.bat" ^>nul
        echo del "%%~f0"
    ) > "%TEMP%\sisacademi_finalize_update.bat"
    start "" /B "%TEMP%\sisacademi_finalize_update.bat"
)

echo   Llamando a run.bat (sincroniza KB y logs y arranca el servicio^)...
echo.
call "%INSTALL_DIR%\run.bat"
exit /b %errorlevel%


REM ============================================================
REM  Restauracion en caso de error durante la copia
REM ============================================================
:restore_and_exit
if exist "%TEMP%\sisacademi_config_safety.env" (
    copy /y "%TEMP%\sisacademi_config_safety.env" "%INSTALL_DIR%\config.env" >nul 2>&1
    del "%TEMP%\sisacademi_config_safety.env" 2>nul
    echo   config.env restaurado desde backup de seguridad.
)
if exist "!EXTRACT_TMP!" rmdir /s /q "!EXTRACT_TMP!" 2>nul
echo.
echo ============================================
echo   ERROR - La actualizacion fallo.
echo   Tu config.env sigue intacto.
echo ============================================
echo.
pause
exit /b 1
