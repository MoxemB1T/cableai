#!/bin/bash
set -euo pipefail

export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-hf.co/Qwen/Qwen3-14B-GGUF:Q4_K_M}"
export OLLAMA_NUM_CTX="${OLLAMA_NUM_CTX:-32768}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"
export CABLE_AI_DB_PATH="${CABLE_AI_DB_PATH:-/app/persist/catalog.db}"
export WEB_MCP_URL="${WEB_MCP_URL:-http://127.0.0.1:8001/mcp}"

mkdir -p "$(dirname "$CABLE_AI_DB_PATH")" /app/web-search-data

if [ ! -f "$CABLE_AI_DB_PATH" ]; then
    cp /app/catalog.db "$CABLE_AI_DB_PATH"
    echo "[INIT] Seeded persistent catalog database."
fi

echo "[OLLAMA] Starting Ollama..."
ollama serve > /var/log/ollama.log 2>&1 &
OLLAMA_PID=$!

cleanup() {
    kill "$OLLAMA_PID" 2>/dev/null || true
    kill "$MCP_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for i in $(seq 1 120); do
    if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        break
    fi
    if ! kill -0 "$OLLAMA_PID" 2>/dev/null; then
        echo "[ERROR] Ollama exited during startup."
        cat /var/log/ollama.log || true
        exit 1
    fi
    sleep 1
done

if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "[ERROR] Ollama did not become ready."
    cat /var/log/ollama.log || true
    exit 1
fi

echo "[OLLAMA] Checking model: $OLLAMA_MODEL"
if ! ollama list | awk 'NR>1 {print $1}' | grep -Fxq "$OLLAMA_MODEL"; then
    echo "[OLLAMA] Model is not present. Downloading GGUF-backed Qwen3 14B: $OLLAMA_MODEL"
    ollama pull "$OLLAMA_MODEL"
else
    echo "[OLLAMA] Model already exists; download skipped."
fi

echo "[MCP] Starting free-search-mcp on 127.0.0.1:8001..."
search-mcp > /var/log/free-search-mcp.log 2>&1 &
MCP_PID=$!

for i in $(seq 1 60); do
    if python3 - <<'PY'
import socket
s=socket.socket()
s.settimeout(1)
try:
    s.connect(("127.0.0.1", 8001))
    raise SystemExit(0)
except OSError:
    raise SystemExit(1)
finally:
    s.close()
PY
    then
        break
    fi
    if ! kill -0 "$MCP_PID" 2>/dev/null; then
        echo "[ERROR] free-search-mcp exited during startup."
        cat /var/log/free-search-mcp.log || true
        exit 1
    fi
    sleep 1
done

if ! kill -0 "$MCP_PID" 2>/dev/null; then
    echo "[ERROR] free-search-mcp is not running."
    cat /var/log/free-search-mcp.log || true
    exit 1
fi

echo "[CABLE AI] Starting FastAPI on 0.0.0.0:8000"
exec python3 /app/app.py
