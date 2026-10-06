#!/usr/bin/env bash
# Crea el entorno de Python de planner/ con Playwright (usa el Chrome del sistema, no descarga navegadores).
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
echo "Listo: planner/.venv"
