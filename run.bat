@echo off
title SisacademiChat
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ============================================================
REM  Configuracion (se sobreescribe con valores de config.env)
REM ============================================================
set "PYTHON_DIR=%cd%\python"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "PYTHON_VERSION=3.12.8"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip"
set "MAX_RETRIES=3"
set "PORT=8090"
set "HOST=127.0.0.1"
set "OLLAMA_MODEL=qwen2.5:0.5b"
set "OLLAMA_MODEL_FAST="
set "OLLAMA_MODEL_SMART="

for /f "tokens=2 delims==" %%a in ('findstr /i "^PORT=" config.env 2^>nul') do set "PORT=%%a"
for /f "tokens=2 delims==" %%a in ('findstr /i "^HOST=" config.env 2^>nul') do set "HOST=%%a"
for /f "tokens=2 delims==" %%a in ('findstr /i "^OLLAMA_MODEL=" config.env 2^>nul') do set "OLLAMA_MODEL=%%a"
for /f "tokens=2 delims==" %%a in ('findstr /i "^OLLAMA_MODEL_FAST=" config.env 2^>nul') do set "OLLAMA_MODEL_FAST=%%a"
for /f "tokens=2 delims==" %%a in ('findstr /i "^OLLAMA_MODEL_SMART=" config.env 2^>nul') do set "OLLAMA_MODEL_SMART=%%a"

echo ============================================
echo   SisacademiChat - Chatbot Educativo RAG
echo ============================================
echo.

REM ============================================================
REM  [1/6] Ollama instalado?
REM ============================================================
echo [1/6] Ollama...
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo   No encontrado. Descargando instalador...
    curl -L --retry %MAX_RETRIES% --retry-delay 5 -o OllamaSetup.exe https://ollama.com/download/OllamaSetup.exe
    if !errorlevel! neq 0 (
        echo   ERROR: No se pudo descargar Ollama. Verifica tu conexion a internet.
        goto :error_exit
    )
    echo   Instalando Ollama...
    start /wait OllamaSetup.exe /VERYSILENT /NORESTART
    del OllamaSetup.exe 2>nul
    set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
    where ollama >nul 2>&1
    if !errorlevel! neq 0 (
        echo   ERROR: Ollama instalado pero no encontrado en PATH.
        echo   Reinicia el equipo y vuelve a ejecutar run.bat.
        goto :error_exit
    )
    echo   Ollama instalado correctamente.
) else (
    echo   OK
)

REM ============================================================
REM  [2/6] Servicio Ollama corriendo + modelos descargados
REM ============================================================
echo.
echo [2/6] Servicio Ollama y modelos...
set "OLLAMA_OK=0"
curl -s --max-time 3 http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% equ 0 (
    set "OLLAMA_OK=1"
) else (
    echo   Iniciando Ollama...
    start "" ollama serve
    for /l %%i in (1,1,5) do (
        if !OLLAMA_OK! equ 0 (
            timeout /t 5 /nobreak >nul
            curl -s --max-time 3 http://localhost:11434/api/tags >nul 2>&1
            if !errorlevel! equ 0 (
                set "OLLAMA_OK=1"
                echo   Ollama listo.
            ) else (
                echo   Esperando [%%i/5]...
            )
        )
    )
)

if "!OLLAMA_OK!"=="1" (
    REM Descargar modelo principal
    call :pull_if_missing "%OLLAMA_MODEL%"
    REM Modelo rapido (si esta definido y es distinto)
    if defined OLLAMA_MODEL_FAST (
        if "!OLLAMA_MODEL_FAST!" neq "!OLLAMA_MODEL!" (
            call :pull_if_missing "!OLLAMA_MODEL_FAST!"
        )
    )
    REM Modelo inteligente (si esta definido y es distinto)
    if defined OLLAMA_MODEL_SMART (
        if "!OLLAMA_MODEL_SMART!" neq "!OLLAMA_MODEL!" (
            if "!OLLAMA_MODEL_SMART!" neq "!OLLAMA_MODEL_FAST!" (
                call :pull_if_missing "!OLLAMA_MODEL_SMART!"
            )
        )
    )
) else (
    echo   ADVERTENCIA: Ollama no respondio tras 25 segundos.
    echo   El chat no funcionara hasta que Ollama este corriendo.
)

REM ============================================================
REM  [3/6] Python embeddable
REM ============================================================
echo.
echo [3/6] Python...
if exist "%PYTHON_EXE%" (
    echo   OK
    goto :check_deps
)
echo   Descargando Python %PYTHON_VERSION% portable...
curl -L --retry %MAX_RETRIES% --retry-delay 5 -o python.zip "%PYTHON_URL%"
if %errorlevel% neq 0 (
    echo   ERROR: No se pudo descargar Python.
    goto :error_exit
)
echo   Extrayendo...
if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"
tar -xf python.zip -C "%PYTHON_DIR%"
del python.zip
if not exist "%PYTHON_EXE%" (
    echo   ERROR: Python no se extrajo correctamente.
    goto :error_exit
)
echo import site>> "%PYTHON_DIR%\python312._pth"
echo   Python %PYTHON_VERSION% instalado.

REM ============================================================
REM  [4/6] Dependencias Python
REM ============================================================
:check_deps
echo.
echo [4/6] Dependencias Python...
"%PYTHON_EXE%" -c "import fastapi, uvicorn, fastembed, sqlite_vec" >nul 2>&1
if %errorlevel% equ 0 (
    echo   OK
    goto :init_db
)
echo   Instalando dependencias...
"%PYTHON_EXE%" -m pip --version >nul 2>&1
if !errorlevel! neq 0 (
    echo   Instalando pip...
    curl -L --retry %MAX_RETRIES% -o "%PYTHON_DIR%\get-pip.py" https://bootstrap.pypa.io/get-pip.py
    if !errorlevel! neq 0 (
        echo   ERROR: No se pudo descargar pip.
        goto :error_exit
    )
    "%PYTHON_EXE%" "%PYTHON_DIR%\get-pip.py" --no-warn-script-location
    del "%PYTHON_DIR%\get-pip.py" 2>nul
)
"%PYTHON_EXE%" -m pip install -r requirements.txt --no-warn-script-location -q
if %errorlevel% neq 0 (
    echo   ERROR: No se pudieron instalar las dependencias.
    goto :error_exit
)
echo   Dependencias instaladas.

REM ============================================================
REM  [5/6] Base de datos y modelo de embeddings
REM ============================================================
:init_db
echo.
echo [5/6] Base de datos y embeddings...
if not exist "data" mkdir data

"%PYTHON_EXE%" -c "import sys; sys.path.insert(0,'.'); from app.database import init_all; init_all()" >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: No se pudieron inicializar las bases de datos.
    goto :error_exit
)

REM Cargar modelo de embeddings (~46MB la primera vez, instantaneo despues)
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0,'.'); from app.infrastructure.embedder import warmup; warmup()" >nul 2>&1
if %errorlevel% neq 0 (
    echo   ADVERTENCIA: El modelo de embeddings se cargara al iniciar el servicio.
) else (
    echo   OK
)

REM ============================================================
REM  [6/6] Verificar puerto e iniciar servicio
REM ============================================================
echo.
echo [6/6] Iniciando servicio...

REM Verificar puerto
netstat -aon 2>nul | findstr ":%PORT%.*LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    set "OLD_PID="
    for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%PORT%.*LISTENING"') do set "OLD_PID=%%a"
    echo   Puerto %PORT% ocupado ^(PID: !OLD_PID!^).
    echo.
    echo   1. Cerrar proceso anterior y usar puerto %PORT%
    echo   2. Buscar puerto libre automaticamente
    echo   3. Cancelar
    echo.
    set "CHOICE=0"
    set /p "CHOICE=  Selecciona [1/2/3]: "
    if "!CHOICE!"=="1" (
        taskkill /PID !OLD_PID! /F >nul 2>&1
        timeout /t 2 /nobreak >nul
        echo   Puerto liberado.
    ) else if "!CHOICE!"=="2" (
        set "FOUND_PORT=0"
        for /l %%p in (1,1,20) do (
            if !FOUND_PORT! equ 0 (
                set /a "TRY_PORT=%PORT% + %%p"
                netstat -aon 2>nul | findstr ":!TRY_PORT!.*LISTENING" >nul 2>&1
                if !errorlevel! neq 0 set "FOUND_PORT=!TRY_PORT!"
            )
        )
        if !FOUND_PORT! equ 0 (
            echo   No se encontro un puerto libre. Cancela e intenta mas tarde.
            pause
            exit /b 1
        )
        set "PORT=!FOUND_PORT!"
        echo   Usando puerto: !PORT!
    ) else (
        echo   Cancelado.
        pause
        exit /b 0
    )
)

REM Sincronizar Base de Conocimiento (si hay servidor configurado)
echo   Sincronizando base de conocimiento...
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0,'.'); import asyncio; from app.services.sync_service import sync_knowledge_base; r=asyncio.run(sync_knowledge_base()); print('  '+r['message'])" 2>nul

echo.
echo ============================================
echo   Servicio:  http://%HOST%:%PORT%
echo   API Docs:  http://%HOST%:%PORT%/docs
echo   Detener:   Ctrl+C  o  stop.bat
echo ============================================
echo.

"%PYTHON_EXE%" -m uvicorn app.main:app --host %HOST% --port %PORT%

if %errorlevel% neq 0 (
    echo.
    echo   El servicio se detuvo con un error ^(codigo: %errorlevel%^).
)
pause
exit /b %errorlevel%


REM ============================================================
REM  Subrutina: descargar modelo de Ollama si no esta instalado
REM ============================================================
:pull_if_missing
set "_M=%~1"
ollama list 2>nul | findstr /c:"%_M%" >nul 2>&1
if %errorlevel% equ 0 (
    echo   Modelo %_M%: OK
    exit /b 0
)
echo   Descargando %_M% ^(puede tardar varios minutos la primera vez^)...
ollama pull %_M%
if %errorlevel% equ 0 (echo   %_M% listo. & exit /b 0)
timeout /t 5 /nobreak >nul
ollama pull %_M%
if %errorlevel% equ 0 (echo   %_M% listo. & exit /b 0)
timeout /t 5 /nobreak >nul
ollama pull %_M%
if %errorlevel% equ 0 (echo   %_M% listo. & exit /b 0)
echo   ADVERTENCIA: No se pudo descargar %_M%.
exit /b 1


REM ============================================================
REM  Salida de error
REM ============================================================
:error_exit
echo.
echo ============================================
echo   ERROR - Revisa los mensajes anteriores.
echo ============================================
echo.
pause
exit /b 1
