FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SEARCH_MCP_CACHE_DIR=/data \
    SEARCH_MCP_TRANSPORT=streamable-http \
    SEARCH_MCP_HTTP_HOST=0.0.0.0 \
    SEARCH_MCP_HTTP_PORT=8001 \
    SEARCH_MCP_HTTP_PATH=/mcp

RUN pip install --no-cache-dir free-search-mcp==0.13.1 \
    && python -m playwright install --with-deps chromium

VOLUME ["/data"]

EXPOSE 8001

CMD ["search-mcp"]
