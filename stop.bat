@echo off
title SisacademiChat - Deteniendo

set "PORT=8090"

REM Leer puerto de config.env si existe
for /f "tokens=2 delims==" %%a in ('findstr /i "^PORT=" "%~dp0config.env" 2^>nul') do set "PORT=%%a"

echo Deteniendo SisacademiChat en puerto %PORT%...

REM Buscar y matar el proceso que usa el puerto
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%PORT%.*LISTENING"') do (
    echo Matando proceso PID: %%a
    taskkill /PID %%a /F >nul 2>&1
)

echo SisacademiChat detenido.
timeout /t 3
