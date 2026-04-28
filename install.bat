@echo off
title SisacademiChat - Instalador
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ============================================================
REM  CONFIGURACION — Editar estos valores antes de distribuir
REM ============================================================
set "INSTALL_DIR=C:\Sitios\SisacademiChat"
set "REPO_URL=https://github.com/jairoortiz19/SisacademiChat/archive/refs/heads/main.zip"
set "MAX_RETRIES=5"

set "CFG_PORT=8090"
set "CFG_HOST=127.0.0.1"
set "CFG_API_KEY=uoemm2mEzkGwxVS_6T7WPvOdgwB5kyyHScOdssq-zfI"
set "CFG_RATE_LIMIT=30"
set "CFG_OLLAMA_URL=http://localhost:11434"
set "CFG_OLLAMA_MODEL=qwen2.5:0.5b"
set "CFG_NUM_CTX=1024"
set "CFG_NUM_PREDICT=110"
set "CFG_TEMPERATURE=0.1"
set "CFG_KEEP_ALIVE=10m"
set "CFG_READ_TIMEOUT=120"
set "CFG_MIN_TOP_SCORE=0.12"
set "CFG_CACHE_TTL=3600"
set "CFG_CACHE_MAX=200"
set "CFG_TOP_K=2"
set "CFG_MAX_QUERY=500"
set "CFG_MIN_RELEVANCE=0.10"
set "CFG_MAX_CHUNK=420"
set "CFG_MAX_CONTEXT=4"
set "CFG_FICTIONAL_PATTERNS="
set "CFG_SERVER_URL=http://62.146.182.204:8091"
set "CFG_SERVER_KEY=-FV1OWvtoKDGpmoveQFv63_cZeC188zScm3i5UUrNz8"
REM Dejar vacio para generar DEVICE_ID unico por maquina automaticamente
set "CFG_DEVICE_ID="

echo ============================================
echo   SisacademiChat - Instalador
echo ============================================
echo.

REM ============================================================
REM  [1/5] Verificar requisitos del sistema
REM ============================================================
echo [1/5] Verificando requisitos del sistema...

where curl >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: curl no encontrado.
    echo   Requiere Windows 10 build 1803 o superior.
    goto :error_exit
)
where tar >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: tar no encontrado.
    echo   Requiere Windows 10 build 17063 o superior.
    goto :error_exit
)
where powershell >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: PowerShell no disponible.
    goto :error_exit
)
echo   OK

REM ============================================================
REM  [2/5] Descargar repositorio
REM ============================================================
echo.
echo [2/5] Descargando repositorio...

if exist "%INSTALL_DIR%\run.bat" (
    echo   Instalacion existente encontrada en:
    echo   %INSTALL_DIR%
    echo.
    set "REINSTALL=N"
    set /p "REINSTALL=  Reinstalar? (conserva config y python) [S/N]: "
    if /i "!REINSTALL!" neq "S" goto :write_config
    echo.
    echo   Conservando python\ y config.env para acelerar reinstalacion...
    set "REINSTALLING=1"
    if exist "%INSTALL_DIR%\python" (
        move "%INSTALL_DIR%\python" "%TEMP%\sisacademi_python_bak" >nul 2>&1
    )
    if exist "%INSTALL_DIR%\config.env" (
        copy "%INSTALL_DIR%\config.env" "%TEMP%\sisacademi_config_bak.env" >nul 2>&1
    )
    rmdir /s /q "%INSTALL_DIR%" 2>nul
)

set "ZIP_FILE=%TEMP%\sisacademi_%RANDOM%.zip"
set "EXTRACT_TMP=%TEMP%\sisacademi_extract_%RANDOM%"

set "DOWNLOAD_OK=0"
for /l %%i in (1,1,%MAX_RETRIES%) do (
    if "!DOWNLOAD_OK!"=="0" (
        if %%i gtr 1 (
            set /a "WAIT=%%i * 4"
            echo   Esperando !WAIT! segundos antes de reintentar...
            timeout /t !WAIT! /nobreak >nul
        )
        echo   Intento %%i/%MAX_RETRIES%...
        curl -L --retry 2 --retry-delay 5 --connect-timeout 30 --max-time 180 -o "!ZIP_FILE!" "%REPO_URL%"
        if !errorlevel! equ 0 (
            for %%s in ("!ZIP_FILE!") do set "FSIZE=%%~zs"
            if !FSIZE! gtr 10000 (
                set "DOWNLOAD_OK=1"
                echo   Descarga completada ^(!FSIZE! bytes^).
            ) else (
                echo   Archivo descargado vacio o corrupto. Reintentando...
                del "!ZIP_FILE!" 2>nul
            )
        ) else (
            echo   Error de red en intento %%i.
            del "!ZIP_FILE!" 2>nul
        )
    )
)

if "!DOWNLOAD_OK!"=="0" (
    echo.
    echo   ERROR: No se pudo descargar el repositorio tras %MAX_RETRIES% intentos.
    echo   Verifica tu conexion a internet e intenta nuevamente.
    goto :error_exit
)

REM ============================================================
REM  [3/5] Extraer y organizar archivos
REM ============================================================
echo.
echo [3/5] Extrayendo archivos...

if exist "!EXTRACT_TMP!" rmdir /s /q "!EXTRACT_TMP!"
mkdir "!EXTRACT_TMP!"

tar -xf "!ZIP_FILE!" -C "!EXTRACT_TMP!"
if %errorlevel% neq 0 (
    echo   ERROR: No se pudo extraer el ZIP.
    del "!ZIP_FILE!" 2>nul
    rmdir /s /q "!EXTRACT_TMP!" 2>nul
    goto :error_exit
)
del "!ZIP_FILE!" 2>nul

REM GitHub extrae en una carpeta SisacademiChat-main
set "EXTRACTED_SUBDIR="
for /d %%d in ("!EXTRACT_TMP!\*") do (
    if "!EXTRACTED_SUBDIR!"=="" set "EXTRACTED_SUBDIR=%%d"
)
if "!EXTRACTED_SUBDIR!"=="" (
    echo   ERROR: No se encontro carpeta dentro del ZIP.
    rmdir /s /q "!EXTRACT_TMP!" 2>nul
    goto :error_exit
)

if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
move "!EXTRACTED_SUBDIR!" "%INSTALL_DIR%" >nul
rmdir /s /q "!EXTRACT_TMP!" 2>nul

REM Restaurar python\ si fue preservado
if exist "%TEMP%\sisacademi_python_bak" (
    move "%TEMP%\sisacademi_python_bak" "%INSTALL_DIR%\python" >nul 2>&1
    echo   python\ restaurado.
)

if not exist "%INSTALL_DIR%\run.bat" (
    echo   ERROR: Los archivos no se copiaron correctamente.
    goto :error_exit
)
echo   Archivos instalados en: %INSTALL_DIR%

REM ============================================================
REM  [4/5] Escribir configuracion
REM ============================================================
:write_config
echo.
echo [4/5] Configurando...

REM Si hay un config.env de backup (reinstalacion), restaurarlo y usarlo tal cual
if exist "%TEMP%\sisacademi_config_bak.env" (
    move "%TEMP%\sisacademi_config_bak.env" "%INSTALL_DIR%\config.env" >nul 2>&1
    echo   config.env restaurado desde instalacion anterior.
    goto :launch
)

REM Si ya existe config.env (caso: se salto la descarga), conservarlo
if exist "%INSTALL_DIR%\config.env" (
    echo   config.env existente conservado.
    goto :launch
)

REM Preservar DEVICE_ID si existe en la instalacion actual
if "!CFG_DEVICE_ID!"=="" (
    if exist "%INSTALL_DIR%\config.env" (
        for /f "tokens=2 delims==" %%a in ('findstr /i "^DEVICE_ID=" "%INSTALL_DIR%\config.env" 2^>nul') do set "CFG_DEVICE_ID=%%a"
    )
)

REM Generar DEVICE_ID unico si sigue vacio
if "!CFG_DEVICE_ID!"=="" (
    for /f "delims=" %%g in ('powershell -NoProfile -Command "[System.Guid]::NewGuid().ToString()"') do set "CFG_DEVICE_ID=%%g"
    echo   DEVICE_ID generado: !CFG_DEVICE_ID!
)

REM Escribir config.env
(
echo # =============================================
echo #  SisacademiChat - Configuracion del Cliente
echo # =============================================
echo.
echo # Servicio
echo PORT=%CFG_PORT%
echo HOST=%CFG_HOST%
echo.
echo # Seguridad
echo API_KEY=%CFG_API_KEY%
echo RATE_LIMIT_PER_MINUTE=%CFG_RATE_LIMIT%
echo.
echo # Ollama
echo OLLAMA_BASE_URL=%CFG_OLLAMA_URL%
echo OLLAMA_MODEL=%CFG_OLLAMA_MODEL%
echo OLLAMA_MODEL_FAST=%CFG_OLLAMA_MODEL%
echo OLLAMA_MODEL_MEDIUM=%CFG_OLLAMA_MODEL%
echo OLLAMA_MODEL_SMART=%CFG_OLLAMA_MODEL%
echo OLLAMA_NUM_CTX=%CFG_NUM_CTX%
echo OLLAMA_NUM_PREDICT=%CFG_NUM_PREDICT%
echo OLLAMA_TEMPERATURE=%CFG_TEMPERATURE%
echo OLLAMA_KEEP_ALIVE=%CFG_KEEP_ALIVE%
echo OLLAMA_READ_TIMEOUT=%CFG_READ_TIMEOUT%
echo MIN_TOP_SCORE_TO_ANSWER=%CFG_MIN_TOP_SCORE%
echo.
echo # Cache de consultas
echo QUERY_CACHE_TTL=%CFG_CACHE_TTL%
echo QUERY_CACHE_MAX_SIZE=%CFG_CACHE_MAX%
echo.
echo # RAG
echo TOP_K=%CFG_TOP_K%
echo MAX_QUERY_LENGTH=%CFG_MAX_QUERY%
echo MIN_RELEVANCE_SCORE=%CFG_MIN_RELEVANCE%
echo MAX_CHUNK_LENGTH=%CFG_MAX_CHUNK%
echo MAX_CONTEXT_CHUNKS=%CFG_MAX_CONTEXT%
echo FICTIONAL_SOURCE_PATTERNS=%CFG_FICTIONAL_PATTERNS%
echo.
echo # Servidor central
echo SERVER_URL=%CFG_SERVER_URL%
echo SERVER_API_KEY=%CFG_SERVER_KEY%
echo DEVICE_ID=!CFG_DEVICE_ID!
) > "%INSTALL_DIR%\config.env"

echo   config.env creado.

REM ============================================================
REM  [5/5] Iniciar SisacademiChat
REM ============================================================
:launch
echo.
echo [5/5] Iniciando SisacademiChat...
echo.
call "%INSTALL_DIR%\run.bat"
exit /b %errorlevel%


REM ============================================================
REM  Salida de error
REM ============================================================
:error_exit
REM Si fallo durante un reinstall, restaurar la instalacion anterior
if "!REINSTALLING!"=="1" (
    echo   Restaurando instalacion anterior...
    if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
    if exist "%TEMP%\sisacademi_python_bak" (
        move "%TEMP%\sisacademi_python_bak" "%INSTALL_DIR%\python" >nul 2>&1
    )
    if exist "%TEMP%\sisacademi_config_bak.env" (
        move "%TEMP%\sisacademi_config_bak.env" "%INSTALL_DIR%\config.env" >nul 2>&1
    )
    echo   Instalacion anterior restaurada. El servicio no fue afectado.
)
echo.
echo ============================================
echo   ERROR - Instalacion fallida.
echo   Revisa los mensajes anteriores.
echo ============================================
echo.
pause
exit /b 1
