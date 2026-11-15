@echo off
cd /d "%~dp0"

rem Cree le venv s'il n'existe pas (Python 3.12 en priorite, sinon la version par defaut)
if not exist venv\Scripts\python.exe (
  py -3.12 -m venv venv 2>nul || py -m venv venv
)

rem PyQt6 6.10 demande Python 3.9 ou plus recent
venv\Scripts\python.exe -c "import sys; sys.exit(sys.version_info < (3, 9))"
if errorlevel 1 (
  echo.
  echo Python 3.9 ou plus recent est necessaire ^(Python 3.12 conseille^).
  echo 1. Installez Python 3.12 depuis https://www.python.org/downloads/
  echo    en cochant "Add python.exe to PATH".
  echo 2. Supprimez le dossier venv de ce projet.
  echo 3. Relancez run.bat.
  echo.
  pause
  exit /b 1
)

rem Installe PyQt6 s'il manque (premiere fois, ou venv incomplet)
venv\Scripts\python.exe -c "import PyQt6" 2>nul
if errorlevel 1 (
  echo Installation de PyQt6, un instant...
  venv\Scripts\python.exe -m pip install --upgrade pip
  venv\Scripts\python.exe -m pip install -r requirements.txt
)

rem La carte demarre toute seule le serveur et les carrefours
venv\Scripts\python.exe carte.py
if errorlevel 1 pause
