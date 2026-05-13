@echo off
title SisacademiChat - Firewall
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ============================================================
REM  Gestiona la regla de Windows Firewall para exponer el puerto
REM  del chat en la red local / internet.
REM
REM  Uso:
REM    firewall.bat        -> abrir (default)
REM    firewall.bat open   -> abrir
REM    firewall.bat close  -> cerrar
REM    firewall.bat status -> ver estado actual
REM ============================================================

set "RULE_NAME=SisacademiChat"
set "PORT=8090"
for /f "tokens=2 delims==# " %%a in ('findstr /i "^PORT=" config.env 2^>nul') do set "PORT=%%a"

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=open"

echo ============================================
echo   SisacademiChat - Firewall (%ACTION% puerto %PORT%)
echo ============================================
echo.

REM Verificar privilegios de admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo   Esta operacion requiere permisos de administrador.
    echo   Solicitando elevacion...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%ACTION%' -Verb RunAs"
    exit /b 0
)

REM Si llegamos aqui, estamos como admin
if /i "%ACTION%"=="status" goto :status
if /i "%ACTION%"=="open" goto :open
if /i "%ACTION%"=="close" goto :close

echo   Accion no reconocida: %ACTION%
echo   Uso: firewall.bat [open^|close^|status]
pause
exit /b 1

:open
echo   Abriendo puerto %PORT% TCP en Windows Firewall...
REM Borrar regla previa si existe (idempotencia)
netsh advfirewall firewall delete rule name="%RULE_NAME%" >nul 2>&1
REM Crear la regla
netsh advfirewall firewall add rule name="%RULE_NAME%" dir=in action=allow protocol=TCP localport=%PORT% profile=any
if %errorlevel% equ 0 (
    echo.
    echo   OK - Regla creada. El puerto %PORT% acepta conexiones entrantes.
    echo.
    echo   Pasos adicionales para acceso desde INTERNET (publico):
    echo     1. Configura port forwarding en tu router:
    echo        IP publica:%PORT%  -^>  IP local de este PC:%PORT%
    echo     2. Identifica la IP publica del router (https://ifconfig.me^).
    echo     3. Prueba desde otro lugar:
    echo        curl http://^<IP-publica^>:%PORT%/api/v1/health
    echo.
    echo   IMPORTANTE: La API key viaja en TEXTO PLANO sin HTTPS.
    echo   Considera regenerar la API_KEY en config.env antes de exponerlo.
) else (
    echo.
    echo   ERROR creando la regla. Codigo: %errorlevel%
)
pause
exit /b %errorlevel%

:close
echo   Cerrando puerto %PORT% TCP en Windows Firewall...
netsh advfirewall firewall delete rule name="%RULE_NAME%"
if %errorlevel% equ 0 (
    echo   OK - Regla eliminada. El puerto ya no acepta conexiones externas.
) else (
    echo   ERROR (puede que la regla no existiera^). Codigo: %errorlevel%
)
pause
exit /b %errorlevel%

:status
echo   Estado actual de la regla "%RULE_NAME%":
echo.
netsh advfirewall firewall show rule name="%RULE_NAME%"
echo.
echo   Puerto %PORT% escuchando localmente:
netstat -aon | findstr ":%PORT% " | findstr "LISTENING"
echo.
pause
exit /b 0
