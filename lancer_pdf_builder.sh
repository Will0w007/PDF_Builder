#!/usr/bin/env bash
# Lanceur macOS / Linux : crée l'environnement au premier démarrage puis ouvre PDF Builder.
set -e
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "Première installation de PDF Builder, merci de patienter…"
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python run_pdf_builder.py "$@"
