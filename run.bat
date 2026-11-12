@echo off
cd /d "%~dp0"

rem Cree le venv s'il n'existe pas
if not exist venv\Scripts\python.exe py -m venv venv

rem Installe PyQt6 s'il manque (premiere fois, ou venv incomplet)
venv\Scripts\python.exe -c "import PyQt6" 2>nul
if errorlevel 1 (
  echo Installation de PyQt6, un instant...
  venv\Scripts\python.exe -m pip install -r requirements.txt
)

rem La carte demarre toute seule le serveur et les carrefours
venv\Scripts\python.exe carte.py
if errorlevel 1 pause
