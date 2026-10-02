Cable AI - fixed web search and fallback logic

Files:
- app.py
- tools.py

Changes:
1. web_search now tries Jina Search first and DuckDuckGo as fallback.
2. Empty web search is explicitly non-fatal.
3. Qwen is instructed to continue with local catalog + stock/incoming search when web search is empty.
4. Technical matching remains more important than stock status.
5. Our article numbers must come only from the local catalog/DB.
6. Prices were not changed.

Replace the existing app.py and tools.py on the server and restart the FastAPI/Uvicorn process.
