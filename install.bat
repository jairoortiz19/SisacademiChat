@echo off
title SisacademiChat - Instalador

REM Ir al directorio donde esta el .bat
cd /d "%~dp0"

echo ============================================
echo   SisacademiChat - Instalador
echo   Chatbot Educativo RAG Local
echo ============================================
echo.

set "PYTHON_DIR=%cd%\python"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "PYTHON_VERSION=3.12.8"
set "PYTHON_ZIP=python-%PYTHON_VERSION%-embed-amd64.zip"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/%PYTHON_ZIP%"
set "OLLAMA_MODEL=qwen2.5:3b"

REM ==========================================
REM  1. Verificar/instalar Ollama
REM ==========================================
echo [1/5] Verificando Ollama...
where ollama >nul 2>&1
if %errorlevel% equ 0 (
    echo   Ollama ya esta instalado.
    goto :ollama_model
)

echo   Ollama no encontrado. Descargando...
curl -L -o OllamaSetup.exe https://ollama.com/download/OllamaSetup.exe
if %errorlevel% neq 0 (
    echo   ERROR: No se pudo descargar Ollama.
    echo   Verifica tu conexion a internet.
    goto :error_exit
)
echo   Instalando Ollama (esto puede tardar)...
start /wait OllamaSetup.exe /VERYSILENT /NORESTART
del OllamaSetup.exe 2>nul
echo   Ollama instalado correctamente.

REM ==========================================
REM  2. Iniciar Ollama y descargar modelo
REM ==========================================
:ollama_model
echo.
echo [2/5] Configurando modelo LLM (%OLLAMA_MODEL%)...

curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo   Iniciando Ollama...
    start "" ollama serve
    echo   Esperando que Ollama inicie...
    timeout /t 8 /nobreak >nul
)

echo   Descargando modelo %OLLAMA_MODEL%...
echo   (Esto puede tardar varios minutos la primera vez)
ollama pull %OLLAMA_MODEL%
if %errorlevel% neq 0 (
    echo   ADVERTENCIA: No se pudo descargar el modelo.
    echo   Se intentara descargar cuando uses el chatbot.
)

REM ==========================================
REM  3. Instalar Python embeddable
REM ==========================================
echo.
echo [3/5] Verificando Python embeddable...
if exist "%PYTHON_EXE%" (
    echo   Python embeddable ya esta instalado.
    goto :check_pip
)

echo   Descargando Python %PYTHON_VERSION% embeddable...
curl -L -o "%PYTHON_ZIP%" "%PYTHON_URL%"
if %errorlevel% neq 0 (
    echo   ERROR: No se pudo descargar Python.
    goto :error_exit
)

echo   Extrayendo Python...
if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"
tar -xf "%PYTHON_ZIP%" -C "%PYTHON_DIR%"
del "%PYTHON_ZIP%"
echo   Python extraido correctamente.

REM Habilitar import site para pip
echo import site>> "%PYTHON_DIR%\python312._pth"
echo   Habilitado soporte de pip.

REM ==========================================
REM  4. Instalar pip + dependencias
REM ==========================================
:check_pip
echo.
echo [4/5] Verificando pip...
"%PYTHON_EXE%" -m pip --version >nul 2>&1
if %errorlevel% equ 0 (
    echo   pip ya esta instalado.
    goto :install_deps
)

echo   Instalando pip...
curl -L -o "%PYTHON_DIR%\get-pip.py" https://bootstrap.pypa.io/get-pip.py
if %errorlevel% neq 0 (
    echo   ERROR: No se pudo descargar get-pip.py.
    goto :error_exit
)
"%PYTHON_EXE%" "%PYTHON_DIR%\get-pip.py" --no-warn-script-location
del "%PYTHON_DIR%\get-pip.py"
echo   pip instalado correctamente.

:install_deps
echo.
echo   Instalando dependencias Python...
echo   (Esto puede tardar unos minutos la primera vez)
"%PYTHON_EXE%" -m pip install -r requirements.txt --no-warn-script-location -q
if %errorlevel% neq 0 (
    echo   ERROR: Fallo la instalacion de dependencias.
    goto :error_exit
)
echo   Dependencias instaladas correctamente.

REM ==========================================
REM  5. Inicializar DBs + modelo embeddings
REM ==========================================
echo.
echo [5/5] Inicializando servicio...

if not exist "data" mkdir data

echo   Creando bases de datos...
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, '.'); from app.database import init_all; init_all(); print('  OK')"
if %errorlevel% neq 0 (
    echo   ERROR: No se pudieron crear las bases de datos.
    goto :error_exit
)

echo   Descargando modelo de embeddings (~46MB primera vez)...
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, '.'); from app.infrastructure.embedder import warmup; warmup(); print('  OK')"
if %errorlevel% neq 0 (
    echo   ADVERTENCIA: El modelo se descargara al iniciar el servicio.
)

echo   Generando Device ID...
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, '.'); from app.config import settings; print(f'  ID: {settings.DEVICE_ID}')"

echo.
echo ============================================
echo   Instalacion completada exitosamente!
echo.
echo   Para iniciar: run.bat
echo   Servicio en:  http://127.0.0.1:8090
echo   API Docs:     http://127.0.0.1:8090/docs
echo.
echo   Configura SERVER_URL en config.env para
echo   sincronizar con el servidor central.
echo ============================================
echo.
pause
exit /b 0

:error_exit
echo.
echo ============================================
echo   ERROR EN LA INSTALACION
echo   Revisa los mensajes anteriores.
echo ============================================
echo.
pause
exit /b 1
