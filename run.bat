@echo off
title SisacademiChat - Servicio
setlocal enabledelayedexpansion

REM Ir al directorio donde esta el .bat
cd /d "%~dp0"

set "PYTHON_EXE=%cd%\python\python.exe"
set "PORT=8090"
set "HOST=127.0.0.1"

REM Leer puerto y host de config.env
for /f "tokens=2 delims==" %%a in ('findstr /i "^PORT=" config.env 2^>nul') do set "PORT=%%a"
for /f "tokens=2 delims==" %%a in ('findstr /i "^HOST=" config.env 2^>nul') do set "HOST=%%a"

echo ============================================
echo   SisacademiChat - Servicio RAG Educativo
echo ============================================

REM ==========================================
REM  1. Verificar instalacion
REM ==========================================
if not exist "%PYTHON_EXE%" (
    echo ERROR: Python no encontrado.
    echo Ejecutando install.bat automaticamente...
    echo.
    call install.bat
    if !errorlevel! neq 0 (
        echo ERROR: La instalacion fallo.
        pause
        exit /b 1
    )
)

REM Verificar dependencias basicas
"%PYTHON_EXE%" -c "import fastapi" >nul 2>&1
if %errorlevel% neq 0 (
    echo ADVERTENCIA: Dependencias incompletas. Reinstalando...
    "%PYTHON_EXE%" -m pip install -r requirements.txt --no-warn-script-location -q
    if !errorlevel! neq 0 (
        echo ERROR: No se pudieron instalar las dependencias.
        pause
        exit /b 1
    )
)

REM ==========================================
REM  2. Verificar/iniciar Ollama
REM ==========================================
echo Verificando Ollama...
set "OLLAMA_OK=0"
set "RETRY=0"
:retry_ollama
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% equ 0 (
    set "OLLAMA_OK=1"
    echo   Ollama conectado.
    goto :ollama_ok
)
if !RETRY! equ 0 (
    echo   Iniciando Ollama...
    start "" ollama serve
)
set /a RETRY+=1
if !RETRY! lss 6 (
    echo   Esperando que Ollama responda [!RETRY!/5]...
    timeout /t 5 /nobreak >nul
    goto :retry_ollama
)
echo   ADVERTENCIA: Ollama no respondio tras 25 segundos.
echo   El chat no funcionara hasta que Ollama este corriendo.

:ollama_ok

REM ==========================================
REM  3. Verificar puerto disponible
REM ==========================================
echo Verificando puerto %PORT%...
set "PORT_FREE=1"
netstat -aon 2>nul | findstr ":%PORT%.*LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    set "PORT_FREE=0"
    echo   Puerto %PORT% esta ocupado.

    REM Verificar si es una instancia anterior de SisacademiChat
    for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%PORT%.*LISTENING"') do (
        set "OLD_PID=%%a"
    )

    REM Preguntar al usuario
    echo.
    echo   Opciones:
    echo     1. Cerrar el proceso anterior (PID: !OLD_PID!^) y usar puerto %PORT%
    echo     2. Buscar un puerto libre automaticamente
    echo     3. Cancelar
    echo.
    set "CHOICE=0"
    set /p "CHOICE=  Selecciona [1/2/3]: "

    if "!CHOICE!"=="1" (
        echo   Cerrando proceso PID: !OLD_PID!...
        taskkill /PID !OLD_PID! /F >nul 2>&1
        timeout /t 2 /nobreak >nul
        REM Verificar que se cerro
        netstat -aon 2>nul | findstr ":%PORT%.*LISTENING" >nul 2>&1
        if !errorlevel! equ 0 (
            echo   ERROR: No se pudo liberar el puerto %PORT%.
            pause
            exit /b 1
        )
        echo   Puerto %PORT% liberado.
        set "PORT_FREE=1"
    ) else if "!CHOICE!"=="2" (
        REM Buscar puerto libre desde PORT+1 hasta PORT+20
        set "FOUND_PORT=0"
        for /l %%p in (1,1,20) do (
            if !FOUND_PORT! equ 0 (
                set /a "TRY_PORT=%PORT% + %%p"
                netstat -aon 2>nul | findstr ":!TRY_PORT!.*LISTENING" >nul 2>&1
                if !errorlevel! neq 0 (
                    set "FOUND_PORT=!TRY_PORT!"
                )
            )
        )
        if !FOUND_PORT! equ 0 (
            echo   ERROR: No se encontro un puerto libre entre %PORT% y !TRY_PORT!.
            pause
            exit /b 1
        )
        set "PORT=!FOUND_PORT!"
        echo   Usando puerto alternativo: !PORT!
        set "PORT_FREE=1"
    ) else (
        echo   Cancelado por el usuario.
        pause
        exit /b 0
    )
)

if "%PORT_FREE%"=="1" (
    echo   Puerto %PORT% disponible.
)

REM ==========================================
REM  4. Sincronizar Base de Conocimiento
REM ==========================================
echo.
echo Sincronizando Base de Conocimiento...
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, '.'); import asyncio; from app.services.sync_service import sync_knowledge_base; result = asyncio.run(sync_knowledge_base()); print(f'  {result[\"message\"]}')" 2>nul
if %errorlevel% neq 0 (
    echo   ADVERTENCIA: Sincronizacion de KB no disponible.
)

REM ==========================================
REM  5. Iniciar servicio
REM ==========================================
echo.
echo Servicio disponible en: http://%HOST%:%PORT%
echo API Docs:               http://%HOST%:%PORT%/docs
echo.
echo Presiona Ctrl+C para detener.
echo ============================================

"%PYTHON_EXE%" -m uvicorn app.main:app --host %HOST% --port %PORT%
set "EXIT_CODE=%errorlevel%"

if %EXIT_CODE% neq 0 (
    echo.
    echo ============================================
    echo   El servicio se detuvo con error (codigo: %EXIT_CODE%^)
    echo ============================================
)

pause
exit /b %EXIT_CODE%
