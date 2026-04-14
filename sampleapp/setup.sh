#!/bin/sh
echo "[setup] Running setup..."

if [ ! -f /app/main.py ]; then
    echo "[setup] ERROR: main.py not found in /app!"
    exit 1
fi

chmod +x /app/main.py
echo "[setup] App files:"
ls -la /app/
echo "[setup] Setup complete."