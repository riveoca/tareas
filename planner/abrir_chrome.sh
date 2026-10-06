#!/usr/bin/env bash
# Abre una ventana de Chrome aparte (perfil propio en planner/chrome-perfil) con el puerto de
# depuración 9333, para que planner.py pueda manejar Planner. Inicia sesión en esa ventana.
cd "$(dirname "$0")"
nohup /usr/bin/google-chrome --remote-debugging-port=9333 --user-data-dir="$PWD/chrome-perfil" \
  --no-first-run https://planner.cloud.microsoft/ >/dev/null 2>&1 &
echo "Chrome abierto. Inicia sesión en Planner con tu cuenta y deja la ventana abierta."
