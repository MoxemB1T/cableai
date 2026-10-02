FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py tools.py mcp_web.py import_data.py ./
COPY catalog.db ./
COPY data ./data
COPY entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh

# The API is intentionally published only through the Compose network by default.
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
