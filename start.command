#!/bin/zsh
# Double-click to start the app, then it opens in the browser.
cd "$(dirname "$0")"
PORT=8642
URL="http://127.0.0.1:$PORT"
if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  open "$URL"
  exit 0
fi
(sleep 2; open "$URL") &
exec .venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port $PORT
