@echo off
title SisacademiChat - Deteniendo
setlocal enabledelayedexpansion

cd /d "%~dp0"

set "PORT=8090"

REM Leer puerto de config.env si existe
for /f "tokens=2 delims==" %%a in ('findstr /i "^PORT=" config.env 2^>nul') do set "PORT=%%a"

echo ============================================
echo   SisacademiChat - Deteniendo servicio
echo ============================================
echo.

REM Buscar procesos en el puerto
set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%PORT%.*LISTENING"') do (
    set "FOUND=1"
    echo Cerrando proceso PID: %%a en puerto %PORT%...
    taskkill /PID %%a /F >nul 2>&1
    if !errorlevel! equ 0 (
        echo   Proceso %%a detenido.
    ) else (
        echo   ADVERTENCIA: No se pudo detener el proceso %%a.
        echo   Intenta ejecutar este script como administrador.
    )
)

if "%FOUND%"=="0" (
    echo No se encontro ningun servicio en el puerto %PORT%.
)

REM Verificar que el puerto quedo libre
timeout /t 2 /nobreak >nul
netstat -aon 2>nul | findstr ":%PORT%.*LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo ADVERTENCIA: El puerto %PORT% sigue ocupado.
    echo Intenta cerrar el proceso manualmente.
) else (
    if "%FOUND%"=="1" (
        echo.
        echo SisacademiChat detenido correctamente.
    )
)

echo.
timeout /t 3
