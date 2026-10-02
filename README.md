# Cable AI — Docker Compose deployment

Этот репозиторий сохраняет существующий Cable AI и добавляет стандартное Docker Compose-развёртывание:

- `cable-ai` — существующее FastAPI-приложение;
- `ollama` — локальный Ollama с постоянным хранилищем модели;
- `web-search` — `free-search-mcp` 0.13.1 по Streamable HTTP;
- `catalog.db`, `data/catalog.pdf`, `data/stock.xlsx` — исходные данные проекта.

## Что важно

Веб-поиск выполняется Python-пайплайном для **каждой** выделенной позиции письма, а не решается моделью через tool-calling. Локальный каталог и складовая логика сохранены.

В Docker имена сервисов используются как DNS-адреса:

- Ollama: `http://ollama:11434`
- MCP: `http://web-search:8001/mcp`

Ollama и MCP не публикуются наружу. Cable AI по умолчанию публикуется только на `127.0.0.1:8000`.

## Быстрый запуск

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose ps
```

После запуска модель нужно один раз скачать в постоянное хранилище:

```bash
docker compose exec ollama ollama pull qwen3:14b
docker compose exec ollama ollama list
```

Проверка API:

```bash
curl http://127.0.0.1:8000/health
```

Ожидается JSON со статусом `ok`, моделью из `OLLAMA_MODEL` и `num_ctx`.

Логи:

```bash
docker compose logs -f cable-ai
docker compose logs -f ollama
docker compose logs -f web-search
```

## CPU

По умолчанию используется CPU-режим: отдельной GPU-конфигурации Compose нет.

Qwen3 14B в официальной библиотеке Ollama — модель около 9.3 GB в варианте `qwen3:14b` (Q4_K_M). Реальная потребность в RAM зависит от контекста и параметров запуска.

## NVIDIA GPU

Если сервер действительно имеет совместимую NVIDIA GPU и установленный NVIDIA Container Toolkit:

```bash
docker compose -f compose.yaml -f compose.gpu.yaml up -d
```

Проверяйте:

```bash
docker compose exec ollama ollama list
docker compose logs ollama
```

Если GPU нет, используйте обычный `docker compose up -d`.

## Постоянное хранение

Compose создаёт три named volumes:

- `ollama-data` — модели Ollama;
- `cable-ai-data` — рабочая `catalog.db`;
- `web-search-data` — кэш free-search-mcp.

Первый запуск Cable AI копирует исходный `catalog.db` в persistent volume только если там ещё нет БД.

Если каталог или склад обновлены и нужно пересобрать БД:

```bash
docker compose exec cable-ai \
  python import_data.py \
  --pdf data/catalog.pdf \
  --xlsx data/stock.xlsx \
  --db /app/persist/catalog.db
```

Это изменяет только persistent БД и не меняет исходные файлы в Git.

## Обновление

После изменения GitHub:

```bash
git pull
docker compose build
docker compose up -d
```

Модель Ollama при этом не скачивается заново: она находится в `ollama-data`.

## Внешний доступ

Не публикуйте `8000`, `11434` или `8001` напрямую в интернет.

Для production рекомендуется:

1. оставить `CABLE_AI_BIND=127.0.0.1`;
2. поставить перед Cable AI reverse proxy (например, Caddy/Nginx) с HTTPS;
3. добавить авторизацию на внешнем уровне;
4. проксировать только `cable-ai:8000`;
5. не проксировать Ollama и MCP.

Если QuData предоставляет собственный HTTPS ingress/прокси, используйте его вместо публикации внутренних сервисов.

## GitHub

В репозиторий можно помещать исходный код и рабочие данные проекта:

- `app.py`
- `tools.py`
- `mcp_web.py`
- `import_data.py`
- `catalog.db`
- `data/catalog.pdf`
- `data/stock.xlsx`
- `requirements.txt`
- Docker/Compose-файлы
- README и `.env.example`

Не загружайте:

- `.env`
- реальные API keys / tokens;
- `__pycache__`;
- временные БД/логи;
- Ollama model files.

## Проверка Compose

Перед запуском:

```bash
docker compose config
docker compose build
```

Если используется GPU:

```bash
docker compose -f compose.yaml -f compose.gpu.yaml config
```

В текущей среде разработки Docker не установлен, поэтому фактическая сборка/запуск контейнеров здесь не выполнялись.

## Структура

```text
.
├── app.py
├── tools.py
├── mcp_web.py
├── import_data.py
├── catalog.db
├── data/
│   ├── catalog.pdf
│   └── stock.xlsx
├── docker/
│   └── free-search-mcp/
│       └── Dockerfile
├── Dockerfile
├── entrypoint.sh
├── compose.yaml
├── compose.gpu.yaml
├── .dockerignore
├── .gitignore
├── .env.example
└── README.md
```


## Вариант для платформы, которая умеет только скачивать готовые образы

В репозитории есть GitHub Actions `.github/workflows/ghcr.yml`. Он публикует:

```text
ghcr.io/<OWNER>/cable-ai:latest
ghcr.io/<OWNER>/cable-ai-free-search-mcp:latest
```

в GitHub Container Registry.

Если QuData не выполняет `build:` из Compose, а требует готовые образы, используйте `compose.registry.yaml` и замените `REPLACE_ME` на владельца GitHub-репозитория:

```bash
GITHUB_REPOSITORY_OWNER=YOUR_GITHUB_LOGIN \
docker compose -f compose.yaml -f compose.registry.yaml up -d
```

Для приватных GHCR-образов сервер/QuData должен иметь право `packages:read`. Если репозиторий и пакеты публичные, отдельный pull secret обычно не требуется.

Сам GitHub Actions не является обязательным для обычного `docker compose build`: это запасной путь для платформ, которые не умеют собирать `build:` из Git.

## Qudata single-container deployment

For Qudata.ai use `Dockerfile.qudata` and `.github/workflows/ghcr-qudata.yml`. This variant is intentionally a single container because Qudata templates are configured around one Docker image plus an on-start Command. It starts Ollama, automatically pulls the official Qwen3-14B GGUF Q4_K_M model through Ollama when absent, starts free-search-mcp, and then starts Cable AI.

See `QUData.md` for the exact Qudata template values.
