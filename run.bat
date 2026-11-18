@echo off
REM Relance le script dans une fenetre qui reste ouverte meme en cas d'erreur
if /i "%~1"=="--go" goto start
cmd /k call "%~f0" --go
exit /b
:start

title Projet Ozdaka
setlocal

echo ========================================
echo          PROJET OZDAKA
echo ========================================
echo.

pushd "%~dp0"
if errorlevel 1 goto err_dossier
set "RACINE=%CD%"

REM ===== 1. carte.py (programme principal) =====
echo [1/5] Recherche de carte.py...
set "MAIN="
if exist "%RACINE%\carte.py" set "MAIN=%RACINE%\carte.py"
if not defined MAIN if exist "%RACINE%\Projet_Ozdaka-main\carte.py" set "MAIN=%RACINE%\Projet_Ozdaka-main\carte.py"
if defined MAIN goto main_ok
for /f "delims=" %%F in ('dir /s /b carte.py 2^>nul ^| findstr /v /i "venv"') do if not defined MAIN set "MAIN=%%F"
if not defined MAIN goto err_main
:main_ok
for %%A in ("%MAIN%") do set "MAIN_DIR=%%~dpA"
echo Trouve : %MAIN%
echo.

REM ===== 2. Python =====
echo [2/5] Recherche de Python...
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto py_ok
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if not defined PY goto err_python
:py_ok
%PY% -c "import sys; sys.exit(sys.version_info < (3,9))"
if errorlevel 1 goto err_version
%PY% --version
echo.

REM ===== 3. venv =====
echo [3/5] Environnement virtuel...
set "VPY=%RACINE%\venv\Scripts\python.exe"
if not exist "%VPY%" goto creer_venv
"%VPY%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto venv_ok
echo venv casse, recreation...
rmdir /s /q "%RACINE%\venv"
:creer_venv
%PY% -m venv "%RACINE%\venv"
if errorlevel 1 goto err_venv
:venv_ok
echo OK
echo.

REM ===== 4. dependances =====
echo [4/5] Installation des dependances...
set "REQ=%RACINE%\requirements.txt"
if not exist "%REQ%" set "REQ=%MAIN_DIR%requirements.txt"
if not exist "%REQ%" goto err_req
"%VPY%" -m pip install --upgrade pip >nul 2>&1
"%VPY%" -m pip install --only-binary=PyQt6-sip -r "%REQ%"
if errorlevel 1 goto err_pip
"%VPY%" -c "from PyQt6.QtWidgets import QApplication"
if errorlevel 1 goto err_pyqt
echo PyQt6 OK
echo.

REM ===== 5. lancement =====
echo ========================================
echo [5/5] LANCEMENT DE PROJET OZDAKA
echo ========================================
echo.
cd /d "%MAIN_DIR%"
"%VPY%" "%MAIN%"
if errorlevel 1 echo [ERREUR] Le projet a rencontre un probleme, voir le message au-dessus.
echo.
echo Fin du programme.
goto fin

REM ===== erreurs =====
:err_dossier
echo [ERREUR] Impossible d'acceder au dossier du projet.
goto fin
:err_main
echo [ERREUR] carte.py introuvable dans %RACINE% ni dans ses sous-dossiers.
goto fin
:err_python
echo [ERREUR] Python introuvable. Installez Python 3.9+ : https://www.python.org/downloads/
goto fin
:err_version
echo [ERREUR] Python 3.9 minimum est necessaire.
goto fin
:err_venv
echo [ERREUR] Impossible de creer l'environnement virtuel.
goto fin
:err_req
echo [ERREUR] requirements.txt introuvable.
goto fin
:err_pip
echo [ERREUR] Installation des dependances impossible. Verifiez internet / le proxy.
goto fin
:err_pyqt
echo [ERREUR] PyQt6 est installe mais ne se charge pas.
goto fin

:fin
popd
echo.
pause
exit
