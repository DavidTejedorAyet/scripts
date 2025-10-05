@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: ==========================================================
::  COMPILADOR a un único EXE (PyInstaller sin admin)
::  - Limpia __pycache__ y "Mis Scripts (build)" anteriores
::  - Empaqueta tools + deps (PTN, guessit, PyYAML, requests, bs4)
::  - Incluye app.ico (icono ventana / taskbar)
::  - Usa hook-tools.py y copia tools como datos (fallback)
:: ==========================================================

cd /d "%~dp0"
if /I "%CD%"=="%SystemRoot%\System32" cd /d "%~dp0"

set "PYTHONUTF8=1"
set "ROOT=%CD%"
set "DISTNAME=Mis Scripts (build)"
set "DIST=%ROOT%\%DISTNAME%"
set "WORK=%DIST%\.work"
set "SPEC=%WORK%\spec"
set "BUILD=%WORK%\build"
set "VENV=%WORK%\venv"
set "LOG=%TEMP%\compilador_build.log"

(
  echo ============================================
  echo COMPILADOR - %date% %time%
  echo ROOT   = %ROOT%
  echo TARGET = %DIST%
  echo TMP    = %WORK%
  echo ============================================
)> "%LOG%"
echo [0] Log: %LOG%

:: [1] Limpieza previa
echo [1] Limpiando compilaciones previas...
if exist "%DIST%" rd /s /q "%DIST%" >> "%LOG%" 2>&1
for /d /r "%ROOT%" %%D in (__pycache__) do (
  if exist "%%~fD" rd /s /q "%%~fD" >> "%LOG%" 2>&1
)
if exist "%LOCALAPPDATA%\pyinstaller" rd /s /q "%LOCALAPPDATA%\pyinstaller" >> "%LOG%" 2>&1
del /q "%ROOT%\*.spec" 2>nul

:: [2] Python
echo [2] Prerrequisitos...
python -c "import sys;print(sys.version)" >nul 2>&1 || (echo [X] Falta Python & exit /b 1)

:: [3] Carpetas
echo [3] Preparando carpetas...
mkdir "%DIST%" >> "%LOG%" 2>&1 || goto :ERR
mkdir "%WORK%" "%SPEC%" "%BUILD%" >> "%LOG%" 2>&1

:: [4] venv + dependencias
echo [4] Preparando entorno (venv)...
python -m venv "%VENV%" >> "%LOG%" 2>&1 || goto :ERR
set "VENV_PY=%VENV%\Scripts\python.exe"
"%VENV_PY%" -m pip install --upgrade pip >> "%LOG%" 2>&1 || goto :ERR
"%VENV_PY%" -m pip install --upgrade pyinstaller pyinstaller-hooks-contrib >> "%LOG%" 2>&1 || goto :ERR

echo [4.1] Instalando deps de herramientas...
"%VENV_PY%" -m pip install --upgrade parse-torrent-name guessit pyyaml babelfish rebulk >> "%LOG%" 2>&1 || goto :ERR

echo [4.2] Instalando requests + bs4 (y deps)...
"%VENV_PY%" -m pip install --upgrade requests certifi chardet idna urllib3 beautifulsoup4 >> "%LOG%" 2>&1 || goto :ERR

for /f "delims=" %%v in ('"%VENV_PY%" -m PyInstaller --version') do set "PYIV=%%v"
echo     PyInstaller: %PYIV%

:: [5] Icono
set "ICON=%ROOT%\app.ico"
if exist "%ICON%" ( set "ICON_ARG=--icon ""%ICON%""" ) else ( set "ICON_ARG=" )

:: [6] Build
echo [5] Compilando Launcher (onefile)...
>> "%LOG%" echo Ejecutando PyInstaller...

"%VENV_PY%" -m PyInstaller ^
 --clean ^
 --noconfirm ^
 --onefile --windowed ^
 --name Launcher ^
 %ICON_ARG% ^
 --collect-submodules tools ^
 --collect-all PTN ^
 --collect-all guessit ^
 --collect-all babelfish ^
 --collect-all rebulk ^
 --collect-all yaml ^
 --collect-all requests ^
 --collect-all urllib3 ^
 --collect-all idna ^
 --collect-all chardet ^
 --collect-all certifi ^
 --collect-all bs4 ^
 --collect-all soupsieve ^
 --additional-hooks-dir "%ROOT%" ^
 --add-data "%ROOT%\tools;tools" ^
 --add-data "%ROOT%\app.ico;." ^
 --workpath "%BUILD%" ^
 --distpath "%DIST%" ^
 --specpath "%SPEC%" ^
 "%ROOT%\launcher.pyw" >> "%LOG%" 2>&1

if errorlevel 1 goto :ERR
if not exist "%DIST%\Launcher.exe" goto :ERR

:: [7] Post-proceso
echo [6] Desbloqueando y limpiando...
powershell -NoProfile -Command "Unblock-File -LiteralPath '%DIST%\Launcher.exe'" >> "%LOG%" 2>&1
if exist "%WORK%" rd /s /q "%WORK%" >> "%LOG%" 2>&1

echo [OK] %DIST%\Launcher.exe
exit /b 0

:ERR
echo [X] ERROR. Revisa el log: %LOG%
exit /b 1
