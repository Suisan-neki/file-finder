#!/bin/bash
# File Finder Launcher
# サーバーを起動してブラウザを開く

SERVER_DIR="$HOME/.gemini/antigravity/scratch/file-finder"
PORT=8765
PID_FILE="/tmp/file-finder.pid"

# Check if server is already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        # Server is running, just open browser
        open "http://localhost:$PORT"
        exit 0
    fi
fi

# Start the server
cd "$SERVER_DIR"
python3 server.py &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

# Wait for server to be ready
for i in $(seq 1 30); do
    if curl -s "http://localhost:$PORT/api/stats" > /dev/null 2>&1; then
        break
    fi
    sleep 0.3
done

# Open in browser
open "http://localhost:$PORT"
