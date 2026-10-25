@echo off
REM Lanceur Windows : crée l'environnement au premier démarrage puis ouvre PDF Builder.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Premiere installation de PDF Builder, merci de patienter...
    py -3 -m venv .venv || python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
start "" ".venv\Scripts\pythonw.exe" run_pdf_builder.py %*
