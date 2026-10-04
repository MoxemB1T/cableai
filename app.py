from __future__ import annotations

import html
import json
import os
import re
from typing import Any

for key in (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
):
    os.environ.pop(key, None)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from ollama import chat

from tools import search_catalog, search_available_cables, get_cable, check_stock
from mcp_web import free_search_web_many


MODEL = os.getenv("OLLAMA_MODEL", "qwen3-14b")
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
HOST = os.getenv("CABLE_AI_HOST", "0.0.0.0")
PORT = int(os.getenv("CABLE_AI_PORT", "8000"))
MAX_ITEMS = int(os.getenv("CABLE_AI_MAX_ITEMS", "20"))
WEB_MAX_PER_ITEM = int(os.getenv("WEB_MCP_MAX_RESULT_CHARS", "3500"))


EXTRACT_PROMPT = r"""
Ты извлекаешь позиции кабелей из письма клиента.
Верни только JSON: {"items":[{"request":"..."}]}.

Правила:
- Извлеки КАЖДУЮ отдельно запрошенную позицию кабеля.
- Не объединяй разные позиции.
- Сохраняй исходное написание, но можешь убрать лишний текст.
- Учитывай опечатки, сокращения и разговорное написание.
- 3x0,75 / 3G0,75 / 3 X 0.75 — это варианты одного обозначения.
- Коммерческое название и техническая маркировка могут быть разными.
- Извлекай только кабели/провода, а не количество метров, цены и комментарии.
"""


FINAL_PROMPT = r"""
Ты — локальный AI-помощник отдела продаж кабеля.

Перед тобой уже подготовлены данные по КАЖДОЙ позиции клиента:
1) локальный каталог;
2) склад и товары в пути;
3) веб-исследование именно этой позиции.

Твоя задача — выбрать подходящий кабель ИЗ НАШЕГО каталога и наличия.

ВАЖНО:
- Обработай ВСЕ позиции из customer_items. Никогда не пропускай позицию.
- Для каждой позиции верни ровно одну строку rows.
- Не объединяй позиции.
- Веб-данные относятся к конкретной позиции, под которой они находятся.
- Не считай кабель неподходящим только потому, что коммерческое название на сайте отличается от запроса.
- Учитывай опечатки и разные записи маркировки: 3x0,75 = 3G0,75 = 3 X 0.75.
- Сравнивай технический смысл, а не буквальное совпадение названия.
- Основные признаки для аналога: тип/маркировка, количество жил, сечение,
  материал жил, напряжение, гибкость/класс жилы, экран/броня и специальные свойства.
- Если веб-источник и локальный каталог расходятся, не выдумывай. Укажи отличие.
- Не придумывай артикул, наличие, цену или срок.

О НАЛИЧИИ:
- В наличии только если local_available явно содержит такую позицию.
- В пути на склад — только если это указано в incoming.
- Если подходящего кабеля нет, верни «Не найдено».

WEB:
- Веб-исследование уже выполнено автоматически для КАЖДОЙ позиции.
- Не нужно выполнять дополнительный поиск.
- Используй веб-данные для понимания того, что именно запросил клиент, и для проверки технических признаков.

Финальный ответ — ТОЛЬКО JSON:
{
  "intro":"Короткое вступление",
  "rows":[
    {
      "request":"Исходная позиция клиента",
      "name":"Наименование нашего подходящего кабеля или Не найдено",
      "article":"Артикул или пусто",
      "price":"Уточняется",
      "delivery":"В наличии / В пути на склад / пусто",
      "comment":"Краткий комментарий о соответствии или отличии"
    }
  ],
  "closing":"Короткое завершение"
}
"""



app = FastAPI(title="Cable AI", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://webmail.sweb.ru"],
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class EmailIn(BaseModel):
    uid: str
    mbox: str = "INBOX"
    subject: str = ""
    from_: str = Field(default="", alias="from")
    to: str = ""
    date: str = ""
    text: str

    class Config:
        populate_by_name = True


class EmailsRequest(BaseModel):
    emails: list[EmailIn]


class ReplyOut(BaseModel):
    uid: str
    reply: str


class RepliesResponse(BaseModel):
    replies: list[ReplyOut]


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(text[start:end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _extract_items(email_text: str) -> list[str]:
    response = chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": email_text},
        ],
        format="json",
        think=False,
        options={"temperature": 0, "num_ctx": min(NUM_CTX, 8192)},
        keep_alive="30m",
    )
    data = _extract_json(response.message.content or "") or {}
    items: list[str] = []
    for item in data.get("items", []):
        if isinstance(item, dict):
            request = str(item.get("request") or "").strip()
            if request and request not in items:
                items.append(request)
    return items[:MAX_ITEMS]


def _compact_candidate(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "article", "family", "designation", "core_count", "section_mm2",
        "core_marking", "voltage", "shielded", "conductor_material",
        "flexibility", "outer_diameter_mm", "availability_status",
        "incoming_arrival_date", "match_score",
    )
    return {k: item.get(k) for k in keys if k in item}


def _local_package(request: str) -> dict[str, Any]:
    catalog = json.loads(search_catalog(request)).get("matches", [])
    available = json.loads(search_available_cables(request)).get("matches", [])

    # Keep only the most useful local candidates to control context size.
    catalog = [_compact_candidate(x) for x in catalog[:5]]
    available = [_compact_candidate(x) for x in available[:8]]

    return {
        "request": request,
        "catalog": catalog,
        "local_available": available,
    }


def _web_query(request: str) -> str:
    return (
        f'Find the exact cable requested as "{request}". '
        "Treat spelling mistakes, alternate notation and commercial names as possible matches. "
        "Find manufacturer technical documentation/datasheet first. "
        "Identify the exact technical marking, number of cores, cross-section, conductor material, "
        "voltage, insulation/sheath, flexibility, shielding/armour and applicable standard. "
        "Do not mix different models or sizes."
    )


def _prepare_data(email_text: str, items: list[str]) -> dict[str, Any]:
    local = [_local_package(item) for item in items]
    web = free_search_web_many([_web_query(item) for item in items])
    web_by_query: dict[str, Any] = {}
    for entry in web:
        web_by_query[entry.get("query", "")] = entry.get("result", "") or entry.get("error", "")

    package = []
    for item, local_data in zip(items, local):
        # Match by sequence: free_search_web_many preserves input order.
        package.append({
            **local_data,
        })

    for idx, item in enumerate(items):
        package[idx]["web_research"] = (
            web[idx].get("result", "") if idx < len(web) else ""
        )
        if idx < len(web) and web[idx].get("error"):
            package[idx]["web_error"] = web[idx]["error"]

    return {
        "customer_items": items,
        "source_email": email_text,
        "items": package,
    }


def _finalize(email_text: str, items: list[str]) -> dict[str, Any]:
    research = _prepare_data(email_text, items)
    prompt = (
        FINAL_PROMPT
        + "\n\nДАННЫЕ ИССЛЕДОВАНИЯ:\n"
        + json.dumps(research, ensure_ascii=False, separators=(",", ":"))
    )

    response = chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": FINAL_PROMPT},
            {"role": "user", "content": prompt},
        ],
        format="json",
        think=False,
        options={"temperature": 0, "num_ctx": NUM_CTX},
        keep_alive="30m",
    )

    data = _extract_json(response.message.content or "")
    if not data:
        raise RuntimeError("Qwen returned invalid JSON")

    rows = data.get("rows") if isinstance(data.get("rows"), list) else []
    by_request: dict[str, dict] = {}
    for row in rows:
        if isinstance(row, dict):
            req = str(row.get("request") or "").strip()
            if req:
                by_request[req.lower()] = row

    # Hard guarantee: one output row per extracted customer item.
    fixed_rows = []
    for request in items:
        row = by_request.get(request.lower())
        if row is None:
            row = {
                "request": request,
                "name": "Не найдено",
                "article": "",
                "price": "Уточняется",
                "delivery": "",
                "comment": "Позиция не была корректно обработана автоматически.",
            }
        row.setdefault("request", request)
        row.setdefault("price", "Уточняется")
        fixed_rows.append(row)

    return {
        "intro": str(data.get("intro") or ""),
        "rows": fixed_rows,
        "closing": str(data.get("closing") or ""),
    }


def _clean(value: Any) -> str:
    return html.escape(str(value or "")).replace("\n", "<br>")


def render_reply(data: dict[str, Any]) -> str:
    parts = ['<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.4;">']
    intro = _clean(data.get("intro"))
    if intro:
        parts.append(f"<p>{intro}</p>")

    parts.append(
        '<table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;max-width:1100px;">'
        "<thead><tr>"
        "<th>Запрос</th><th>Наименование</th><th>Артикул</th>"
        "<th>Цена за 1 м</th><th>Срок поставки</th><th>Комментарий</th>"
        "</tr></thead><tbody>"
    )
    for row in data.get("rows", []):
        parts.append(
            "<tr>"
            f"<td>{_clean(row.get('request'))}</td>"
            f"<td>{_clean(row.get('name'))}</td>"
            f"<td>{_clean(row.get('article'))}</td>"
            f"<td>{_clean(row.get('price') or 'Уточняется')}</td>"
            f"<td>{_clean(row.get('delivery'))}</td>"
            f"<td>{_clean(row.get('comment'))}</td>"
            "</tr>"
        )
    parts.append("</tbody></table>")

    closing = _clean(data.get("closing"))
    if closing:
        parts.append(f"<p>{closing}</p>")
    parts.append("</div>")
    return "".join(parts)


def run_agent(email: EmailIn) -> str:
    email_text = (
        f"UID: {email.uid}\n"
        f"Папка: {email.mbox}\n"
        f"Тема: {email.subject}\n"
        f"От: {email.from_}\n"
        f"Кому: {email.to}\n"
        f"Дата: {email.date}\n\n"
        f"Текст письма:\n{email.text}"
    )

    print("[AI] extracting customer cable requests...")
    items = _extract_items(email_text)
    print(f"[AI] extracted {len(items)} items: {items}")

    if not items:
        return render_reply({
            "intro": "В письме не удалось определить позиции кабеля.",
            "rows": [],
            "closing": "",
        })

    print("[PIPELINE] local catalog + stock + web research for EVERY item")
    data = _finalize(email_text, items)
    return render_reply(data)


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL, "num_ctx": NUM_CTX}


@app.post("/process-emails", response_model=RepliesResponse)
def process_emails(payload: EmailsRequest):
    replies = []
    for email in payload.emails:
        if not email.text.strip():
            raise HTTPException(status_code=400, detail=f"Пустой текст письма uid={email.uid}")
        try:
            reply = run_agent(email)
        except Exception as exc:
            print(f"[ERROR] uid={email.uid}: {exc}")
            raise HTTPException(status_code=500, detail=f"Ошибка обработки uid={email.uid}: {exc}") from exc
        replies.append({"uid": email.uid, "reply": reply})
    return {"replies": replies}


def main():
    if not os.path.exists("catalog.db"):
        print("Ошибка: catalog.db не найден. Сначала запустите import_data.py")
        raise SystemExit(1)

    import uvicorn

    print("======================================")
    print("        CABLE AI SERVER 2.0")
    print("======================================")
    print(f"Model:   {MODEL}")
    print(f"Context: {NUM_CTX}")
    print(f"Server:  http://{HOST}:{PORT}")
    print("Web MCP: http://127.0.0.1:8001/mcp")
    print("Thinking: OFF")
    print("======================================")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
