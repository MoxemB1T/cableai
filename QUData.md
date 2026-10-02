# Qudata deployment

This repository contains a dedicated single-container image for Qudata.ai.

Qudata templates accept a Docker image plus an on-start `Command`, environment variables and a UI port. The image runs all three Cable AI components inside one container:

- Ollama
- Qwen3-14B GGUF Q4_K_M, pulled automatically from the official Qwen Hugging Face repository through Ollama
- free-search-mcp 0.13.1
- the existing Cable AI FastAPI application

## GHCR image

After the GitHub Actions workflow finishes, use:

`ghcr.io/<YOUR_GITHUB_OWNER>/cable-ai-qudata:latest`

If the package is private, configure GHCR credentials in the Qudata template. A public package is simpler if the repository/package policy allows it.

## Qudata template

Docker Image:

`ghcr.io/<YOUR_GITHUB_OWNER>/cable-ai-qudata`

Version Tag:

`latest`

Command:

`/app/qudata-entrypoint.sh`

Port:

`8000/TCP`

Web UI / UI Port:

`8000`

Recommended minimum disk:

`30 GB` for the application plus the Qwen3-14B Q4_K_M model and runtime data. More is preferable.

Environment variables:

- `OLLAMA_MODEL=hf.co/Qwen/Qwen3-14B-GGUF:Q4_K_M`
- `OLLAMA_NUM_CTX=32768`
- `OLLAMA_KEEP_ALIVE=30m`
- `CABLE_AI_MAX_ITEMS=20`
- `CABLE_AI_MAX_TOOL_ROUNDS=8`
- `WEB_MCP_RESEARCH_DEPTH=1`
- `WEB_MCP_MAX_RESULT_CHARS=3500`

The startup script starts Ollama, waits for it, checks whether the model exists, and runs `ollama pull` only when necessary. Then it starts free-search-mcp and Cable AI.

The Qwen model is not stored in GitHub. It is downloaded into Ollama's model storage at runtime.

## Important Qudata lifecycle note

Qudata documents that instance data is deleted when the rental session ends. Therefore the GGUF/model download should be considered instance-local. A new instance will download the model again. During a running instance, the model remains in `/root/.ollama` and subsequent container restarts do not need to download it again.

## Health check

Open:

`http://<INSTANCE_HOST>:8000/health`

Expected response contains:

`"status":"ok"`

and the configured model name.

## Logs

Inside the container:

`tail -f /var/log/ollama.log`

`tail -f /var/log/free-search-mcp.log`

The Cable AI process logs directly to the container stdout.
