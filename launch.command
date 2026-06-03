#!/bin/bash
# GStack Local Console - Streamlined Launcher for macOS
# Double-click this file in Finder to boot all servers and launch the desktop app!

cd "$(dirname "$0")"

echo "⚡ Booting GStack Local Console Services..."

# 1. Start FreeLLMAPI on Port 3001 if it's not already running
if ! lsof -i :3001 >/dev/null 2>&1; then
  echo "🚀 Starting FreeLLMAPI local proxy on Port 3001..."
  if [ -d "../freellmapi" ]; then
    (cd ../freellmapi && nohup node server/dist/index.js >/dev/null 2>&1 &)
  elif [ -d "freellmapi" ]; then
    (cd freellmapi && nohup node server/dist/index.js >/dev/null 2>&1 &)
  fi
  sleep 2
else
  echo "✓ FreeLLMAPI is already running on Port 3001."
fi

# 2. Start FastAPI server on Port 8000 if it's not already running
if ! lsof -i :8000 >/dev/null 2>&1; then
  echo "🚀 Starting FastAPI backend on Port 8000..."
  (nohup .venv/bin/python server.py >/dev/null 2>&1 &)
  sleep 2
else
  echo "✓ FastAPI server is already running on Port 8000."
fi

# 3. Open the desktop app
echo "🖥️ Launching gStack desktop app..."
if [ -d "src-tauri/target/release/bundle/macos/gStack.app" ]; then
  open src-tauri/target/release/bundle/macos/gStack.app
else
  open gStack_Installer_aarch64.dmg
fi

echo "✨ Done! Enjoy your agent sprints!"
