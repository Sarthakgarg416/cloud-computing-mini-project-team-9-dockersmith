#!/usr/bin/env bash
# ───────────────────────────────────────────────
#  Docksmith GUI — Launcher
# ───────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUI_DIR="$SCRIPT_DIR/gui"
PORT="${PORT:-5000}"
HOST="${HOST:-127.0.0.1}"

echo "╔══════════════════════════════════════╗"
echo "║      Docksmith Dashboard GUI         ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "❌  python3 not found. Please install Python 3.8+."
  exit 1
fi

# Install GUI deps if needed
if ! python3 -c "import flask" 2>/dev/null; then
  echo "📦  Installing GUI dependencies..."
  pip3 install -r "$GUI_DIR/requirements.txt" --quiet --break-system-packages 2>/dev/null \
    || pip3 install -r "$GUI_DIR/requirements.txt" --quiet
fi

echo "🔧  Docksmith GUI starting on http://$HOST:$PORT"
echo "    Open that URL in your browser."
echo "    Press Ctrl+C to stop."
echo ""

cd "$SCRIPT_DIR"
exec python3 "$GUI_DIR/server.py" --host "$HOST" --port "$PORT"
