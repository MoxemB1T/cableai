@echo off
chcp 65001 >nul
title Cable AI install
python -m pip install -r requirements.txt
uvx --from free-search-mcp playwright install chromium
echo.
echo Installation complete.
pause
