#!/usr/bin/env bash
# Arranque al iniciar sesión: levanta la app (si no está corriendo) y abre en Chrome la app y las
# pestañas de pestanas.txt. Lo lanza ~/.config/autostart/tareas.desktop; el log queda en inicio.log.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="http://127.0.0.1:8765"
exec >>"$DIR/inicio.log" 2>&1
echo "== $(date '+%F %T')"

if ! curl -s -o /dev/null --max-time 2 "$URL"; then
  setsid nohup "$DIR/tareas" serve --no-browser >>"$DIR/inicio.log" 2>&1 &
  for _ in $(seq 1 30); do
    curl -s -o /dev/null --max-time 1 "$URL" && break
    sleep 1
  done
fi

pestanas=("$URL")
[ -f "$DIR/pestanas.txt" ] && while read -r linea; do
  [[ -z "$linea" || "$linea" == \#* ]] || pestanas+=("$linea")
done <"$DIR/pestanas.txt"
google-chrome --new-window "${pestanas[@]}" >/dev/null 2>&1 &
