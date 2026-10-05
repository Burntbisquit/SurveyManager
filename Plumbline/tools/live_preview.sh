#!/usr/bin/env bash
# Live, clickable preview of the real Plumbline window in a web browser - for a headless Linux box such as the Arena sandbox.
#
#   Xvfb (virtual screen) -> openbox (window manager) -> Plumbline -> x11vnc (this machine only) -> noVNC (web page, port 6080)
#
# Usage:  tools/live_preview.sh [file.plb | a CSV/DXF/LandXML/GIS file to import]
#         (no argument: opens a scratch copy of the sample project, so saving never touches sample_data/)
# Stop:   Ctrl+C, or kill the script - everything it started goes with it.
# Needs:  Python 3.14 with the libraries from requirements.txt (PYTHON=/path/to/python tools/live_preview.sh picks the interpreter),
#         the Qt system libraries (see README) and:  sudo apt-get install -y xvfb openbox x11vnc novnc websockify wmctrl
# Settings and scratch files go to ~/.cache/plumbline_preview, never into the project folder.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISP="${PREVIEW_DISPLAY:-:99}"
SIZE="${PREVIEW_SIZE:-1600x900}"
PORT="${PREVIEW_PORT:-6080}"
WORK="${PREVIEW_WORK:-${XDG_CACHE_HOME:-$HOME/.cache}/plumbline_preview}"
PY="${PYTHON:-$(command -v python3.14 || echo python3)}"
VNC_PORT=5900
NOVNC=/usr/share/novnc

missing=()
for c in Xvfb openbox x11vnc websockify wmctrl; do command -v "$c" >/dev/null 2>&1 || missing+=("$c"); done
[ -d "$NOVNC" ] || missing+=("novnc")
if [ ${#missing[@]} -gt 0 ]; then
  echo "Missing: ${missing[*]}"
  echo "Install with:  sudo apt-get install -y xvfb openbox x11vnc novnc websockify wmctrl"
  exit 1
fi

if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 14) else 1)' 2>/dev/null; then
  echo "Plumbline needs Python 3.14, but '$PY' is: $("$PY" -V 2>&1)"
  echo "Point PYTHON at a 3.14 interpreter, e.g.  PYTHON=.venv/bin/python tools/live_preview.sh"
  exit 1
fi

mkdir -p "$WORK/home" "$WORK/log"
cleanup() { trap - EXIT INT TERM; kill 0 2>/dev/null; }
trap cleanup EXIT INT TERM
rm -f "/tmp/.X${DISP#:}-lock" "/tmp/.X11-unix/X${DISP#:}"       # leftovers from an earlier run

# 1. the virtual screen, window manager and the VNC server (only reachable from this machine)
Xvfb "$DISP" -screen 0 "${SIZE}x24" -dpi 96 -nolisten tcp >"$WORK/log/xvfb.log" 2>&1 &
for _ in $(seq 100); do [ -S "/tmp/.X11-unix/X${DISP#:}" ] && break; sleep 0.1; done
export DISPLAY="$DISP"
openbox >"$WORK/log/openbox.log" 2>&1 &
x11vnc -display "$DISP" -localhost -rfbport "$VNC_PORT" -forever -shared -nopw -noxdamage -quiet >"$WORK/log/x11vnc.log" 2>&1 &

# 2. the web page: noVNC's files plus an index page that connects straight away
WEB="$WORK/web"
rm -rf "$WEB"; mkdir -p "$WEB"; cp -r "$NOVNC"/. "$WEB"/
cat > "$WEB/index.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>Plumbline</title>
<script>location.replace("vnc.html?autoconnect=true&resize=scale&reconnect=true&show_dot=true");</script>
<p><a href="vnc.html?autoconnect=true&resize=scale&reconnect=true">Open Plumbline</a></p>
HTML
websockify --web "$WEB" "$PORT" "127.0.0.1:$VNC_PORT" >"$WORK/log/websockify.log" 2>&1 &

# 3. the program itself; if it is closed it comes back after two seconds (a preview should not just go blank)
FILE="${1:-}"
if [ -z "$FILE" ]; then
  FILE="$WORK/home/sample_site.plb"
  cp "$ROOT/sample_data/sample_site.plb" "$FILE"
fi
(
  while true; do
    ( for _ in $(seq 120); do
        if wmctrl -l 2>/dev/null | grep -q "Plumbline"; then wmctrl -r Plumbline -b add,maximized_vert,maximized_horz; break; fi
        sleep 0.5
      done ) &
    ( cd "$ROOT" && PLUMBLINE_HOME="$WORK/home" QT_QPA_PLATFORM=xcb exec "$PY" -m plumbline "$FILE" ) >>"$WORK/log/plumbline.log" 2>&1
    echo "[preview] Plumbline exited with code $? - starting it again in 2 s" >>"$WORK/log/plumbline.log"
    sleep 2
  done
) &

echo "Plumbline preview is up: open port $PORT in a browser. Logs are in $WORK/log"
wait
