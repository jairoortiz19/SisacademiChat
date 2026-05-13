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
echo   Esto descargara la ultima version del codigo
echo   desde GitHub y reiniciara el servicio.
echo.
echo   Se PRESERVAN: config.env, data\, python\
echo   Se ACTUALIZAN: app\, *.bat, *.md, requirements.txt
echo.
set "CONFIRM=N"
set /p "CONFIRM=  Continuar? [S/N]: "
if /i "!CONFIRM!" neq "S" (
    echo   Cancelado.
    pause
    exit /b 0
)

REM ============================================================
REM  [1/6] Detener servicio si esta corriendo
REM ============================================================
echo.
echo [1/6] Deteniendo servicio...
netstat -aon 2>nul | findstr ":%PORT%.*LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%PORT%.*LISTENING"') do (
        taskkill /PID %%a /F >nul 2>&1
    )
    timeout /t 2 /nobreak >nul
    echo   Servicio detenido (puerto %PORT% liberado).
) else (
    echo   El servicio no estaba corriendo.
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
                echo   Descarga completada (!FSIZE! bytes).
            )
        )
    )
)

if "!DOWNLOAD_OK!"=="0" (
    echo   ERROR: No se pudo descargar el repo tras %MAX_RETRIES% intentos.
    echo   El servicio NO fue reiniciado.
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

REM ============================================================
REM  [4/6] Aplicar actualizacion (sin tocar config.env, data\, python\)
REM ============================================================
echo.
echo [4/6] Aplicando actualizacion...

REM Backup de seguridad de config.env por si algo sale mal
copy /y "%INSTALL_DIR%\config.env" "%TEMP%\sisacademi_config_safety.env" >nul 2>&1

REM Mirror de app\ — robocopy /MIR borra los archivos que ya no existen en la nueva version
robocopy "!SRC_DIR!\app" "%INSTALL_DIR%\app" /MIR /NJH /NJS /NDL /NC /NS /NP /NFL >nul
if !errorlevel! geq 8 (
    echo   ERROR: Falla copiando app\
    goto :restore_and_exit
)
echo   app\ actualizado.

REM Copiar archivos sueltos (no sobrescribe config.env porque no esta en el repo)
xcopy /y /q "!SRC_DIR!\*.bat" "%INSTALL_DIR%\" >nul
xcopy /y /q "!SRC_DIR!\*.md" "%INSTALL_DIR%\" >nul
xcopy /y /q "!SRC_DIR!\requirements.txt" "%INSTALL_DIR%\" >nul
xcopy /y /q "!SRC_DIR!\config.env.example" "%INSTALL_DIR%\" >nul
xcopy /y /q "!SRC_DIR!\*.json" "%INSTALL_DIR%\" >nul 2>nul
echo   Scripts y docs actualizados.

REM Verificar que config.env sigue ahi (sanity check)
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
REM  [6/6] Reiniciar servicio (run.bat sincroniza KB + logs y arranca)
REM ============================================================
echo.
echo [6/6] Reiniciando servicio...
echo   (run.bat se encarga de sincronizar KB y subir logs pendientes)
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
rmdir /s /q "!EXTRACT_TMP!" 2>nul
echo.
echo ============================================
echo   ERROR - La actualizacion fallo.
echo   Tu config.env sigue intacto.
echo ============================================
echo.
pause
exit /b 1
