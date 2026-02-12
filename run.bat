@echo off
title SisacademiChat - Servicio

REM Ir al directorio donde esta el .bat
cd /d "%~dp0"

set "PYTHON_EXE=%cd%\python\python.exe"
set "PORT=8090"

REM Leer puerto de config.env
for /f "tokens=2 delims==" %%a in ('findstr /i "^PORT=" config.env 2^>nul') do set "PORT=%%a"

echo ============================================
echo   SisacademiChat - Servicio RAG Educativo
echo ============================================

REM Verificar que la instalacion existe
if not exist "%PYTHON_EXE%" (
    echo ERROR: Python no encontrado. Ejecuta install.bat primero.
    pause
    exit /b 1
)

REM Verificar que Ollama esta corriendo
echo Verificando Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo Iniciando Ollama...
    start "" ollama serve
    timeout /t 5 /nobreak >nul
)

echo.
echo Servicio disponible en: http://127.0.0.1:%PORT%
echo API Docs:               http://127.0.0.1:%PORT%/docs
echo.
echo Presiona Ctrl+C para detener.
echo ============================================

"%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%

pause
