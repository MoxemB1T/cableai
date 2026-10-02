@echo off
chcp 65001 >nul
title free-search-mcp
uvx free-search-mcp --transport streamable-http --host 127.0.0.1 --port 8001
pause
