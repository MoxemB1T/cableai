@echo off
chcp 65001 >nul
title Cable AI 2.0 + free-search-mcp

echo.
echo [1/2] Starting free-search-mcp on 127.0.0.1:8001 ...
start "free-search-mcp" cmd /k "uvx free-search-mcp --transport streamable-http --host 127.0.0.1 --port 8001"
timeout /t 3 /nobreak >nul

echo [2/2] Starting Cable AI on 0.0.0.0:8000 ...
start "Cable AI" cmd /k "set OLLAMA_MODEL=qwen3-14b&& set OLLAMA_NUM_CTX=32768&& set WEB_MCP_URL=http://127.0.0.1:8001/mcp&& set WEB_MCP_RESEARCH_DEPTH=1&& set WEB_MCP_MAX_RESULT_CHARS=3500&& python app.py"

echo.
echo Both processes were started.
pause
