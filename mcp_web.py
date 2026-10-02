from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mcp import Client


MCP_URL = os.getenv("WEB_MCP_URL", "http://127.0.0.1:8001/mcp")
RESEARCH_DEPTH = int(os.getenv("WEB_MCP_RESEARCH_DEPTH", "1"))
MAX_RESULT_CHARS = int(os.getenv("WEB_MCP_MAX_RESULT_CHARS", "3500"))


# Free-search-mcp is used only as a web research backend.
# The model never sees its 11 tools directly.


def _result_text(result: Any) -> str:
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        try:
            return json.dumps(structured, ensure_ascii=False)
        except TypeError:
            pass

    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        value = getattr(block, "text", None)
        if value:
            parts.append(value)
    return "\n\n".join(parts).strip()


def _compact(text: str) -> str:
    text = (text or "").strip()
    if len(text) > MAX_RESULT_CHARS:
        return text[:MAX_RESULT_CHARS] + "\n[web result truncated]"
    return text


async def _research_many(queries: list[str]) -> list[dict[str, Any]]:
    async with Client(MCP_URL) as client:
        async def one(query: str) -> dict[str, Any]:
            try:
                result = await client.call_tool(
                    "research",
                    {
                        "question": query,
                        "depth": RESEARCH_DEPTH,
                        "format": "markdown",
                    },
                )
                if getattr(result, "is_error", False):
                    return {
                        "query": query,
                        "error": _result_text(result) or "MCP tool error",
                    }
                return {
                    "query": query,
                    "result": _compact(_result_text(result)),
                }
            except Exception as exc:
                return {
                    "query": query,
                    "error": str(exc),
                }

        return await asyncio.gather(*(one(q) for q in queries))


def free_search_web_many(queries: list[str]) -> list[dict[str, Any]]:
    clean = [str(q or "").strip() for q in queries]
    clean = [q for q in clean if q]
    if not clean:
        return []

    try:
        return asyncio.run(_research_many(clean))
    except Exception as exc:
        return [
            {
                "query": q,
                "error": (
                    f"Не удалось подключиться к free-search-mcp: {exc}. "
                    f"MCP URL: {MCP_URL}"
                ),
            }
            for q in clean
        ]


def free_search_web(query: str) -> str:
    results = free_search_web_many([query])
    return json.dumps(results[0] if results else {"error": "empty query"}, ensure_ascii=False)


if __name__ == "__main__":
    result = free_search_web("LAPP KABEL X05VV-F 3G0,75 official datasheet")
    print(result)
