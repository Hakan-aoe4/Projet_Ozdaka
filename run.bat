@echo off
cd /d "%~dp0"

rem Premiere fois : creation du venv + installation de PyQt6
if not exist venv\Scripts\python.exe (
  py -m venv venv
  venv\Scripts\python.exe -m pip install -r requirements.txt
)

rem Serveur et carrefours dans leurs propres fenetres, puis la carte
start "Serveur OzdAka" venv\Scripts\python.exe serveur.py
timeout /t 1 >nul
start "Carrefours OzdAka" venv\Scripts\python.exe carrefours.py
venv\Scripts\python.exe carte.py

echo.
echo Ferme aussi les fenetres "Serveur" et "Carrefours" (Ctrl+C).
pause
