@echo off
chcp 65001 >nul
title CABLE AI SERVER 2.0
set OLLAMA_MODEL=qwen3-14b
set OLLAMA_NUM_CTX=32768
set WEB_MCP_URL=http://127.0.0.1:8001/mcp
set WEB_MCP_RESEARCH_DEPTH=1
set WEB_MCP_MAX_RESULT_CHARS=3500
python app.py
pause
