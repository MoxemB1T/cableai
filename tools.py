from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from rapidfuzz import fuzz

from mcp_web import free_search_web

DB_PATH = Path(os.getenv("CABLE_AI_DB_PATH", str(Path(__file__).with_name("catalog.db"))))


def _connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = s.replace("×", "x").replace("х", "x")
    s = re.sub(r"[\s_/]+", " ", s)
    return re.sub(r"[^0-9a-zа-я.,+-]+", " ", s).strip()


def _query_constraints(query: str):
    q = _norm(query)
    core_count = None
    section = None
    m = re.search(r"\b(\d{1,3})\s*[gx]\s*(\d+(?:[.,]\d+)?)\b", q)
    if not m:
        m = re.search(r"\b(\d{1,3})\s*x\s*(\d+(?:[.,]\d+)?)\b", q)
    if m:
        core_count = int(m.group(1))
        section = float(m.group(2).replace(",", "."))
    else:
        m = re.search(r"\b(\d+(?:[.,]\d+)?)\s*мм2\b", q)
        if m:
            section = float(m.group(1).replace(",", "."))
    return q, core_count, section


def _score_row(query: str, r, core_count, section) -> float:
    q = _norm(query)
    text = r["search_text"] or ""
    score = fuzz.token_set_ratio(q, text)
    score = max(score, fuzz.partial_ratio(q, text) * 0.92)

    if core_count is not None:
        if r["core_count"] == core_count:
            score += 18
        else:
            score -= 18
    if section is not None and r["section_mm2"] is not None:
        delta = abs(float(r["section_mm2"]) - section)
        if delta == 0:
            score += 22
        elif delta <= max(0.1, section * 0.10):
            score += 5
        else:
            score -= min(20, delta * 5)

    if str(r["article"]) in q.replace(" ", ""):
        score += 40
    return score


def _row_to_candidate(r, score=None):
    item = {
        "article": r["article"],
        "family": r["family"],
        "designation": r["designation"],
        "core_count": r["core_count"],
        "section_mm2": r["section_mm2"],
        "core_marking": r["core_marking"],
        "voltage": r["voltage"],
        "shielded": bool(r["shielded"]),
        "conductor_material": r["conductor_material"],
        "flexibility": r["flexibility"],
        "outer_diameter_mm": r["outer_diameter_mm"],
        "copper_weight_kg_km": r["copper_weight_kg_km"],
        "weight_kg_km": r["weight_kg_km"],
        "source_page": r["source_page"],
    }
    if score is not None:
        item["match_score"] = round(score, 1)
    if "current_stock" in r.keys():
        item["current_stock"] = float(r["current_stock"] or 0)
    return item


def search_catalog(query: str) -> str:
    """Search the complete local PDF catalog. Read-only."""
    print("[Qwen → search_catalog]")
    q, core_count, section = _query_constraints(query)

    con = _connect()
    rows = con.execute("""
        SELECT article,family,designation,core_count,section_mm2,core_marking,
               voltage,shielded,conductor_material,flexibility,
               outer_diameter_mm,copper_weight_kg_km,weight_kg_km,source_page,search_text
        FROM cables
    """).fetchall()
    con.close()

    scored = []
    for r in rows:
        score = _score_row(query, r, core_count, section)
        exact_core = core_count is not None and r["core_count"] == core_count
        exact_section = section is not None and r["section_mm2"] is not None and abs(float(r["section_mm2"]) - section) < 1e-9
        scored.append((exact_core and exact_section, exact_core, exact_section, score, r))
    scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True)
    result = [_row_to_candidate(r, score) for _, _, _, score, r in scored[:8]]
    return json.dumps({"query": query, "matches": result}, ensure_ascii=False)


def search_available_cables(query: str) -> str:
    """Search technically matching cables in current stock AND incoming shipments."""
    print("[Qwen → search_available_cables]")
    q, core_count, section = _query_constraints(query)

    con = _connect()
    rows = con.execute("""
        SELECT c.article,c.family,c.designation,c.core_count,c.section_mm2,c.core_marking,
               c.voltage,c.shielded,c.conductor_material,c.flexibility,
               c.outer_diameter_mm,c.copper_weight_kg_km,c.weight_kg_km,c.source_page,
               c.search_text,COALESCE(s.qty,0) AS current_stock,
               CASE WHEN COALESCE(s.qty,0) > 0 THEN 1 ELSE 0 END AS has_stock,
               CASE WHEN i.article IS NOT NULL THEN 1 ELSE 0 END AS has_incoming
        FROM cables c
        LEFT JOIN stock s ON s.article = c.article
        LEFT JOIN (SELECT DISTINCT article FROM incoming) i ON i.article = c.article
        WHERE COALESCE(s.qty,0) > 0 OR i.article IS NOT NULL
    """).fetchall()
    incoming = con.execute("""
        SELECT article, MIN(arrival_date) AS arrival_date, SUM(COALESCE(qty,0)) AS incoming_qty
        FROM incoming GROUP BY article
    """).fetchall()
    con.close()
    incoming_map = {r['article']: dict(r) for r in incoming}

    scored = []
    for r in rows:
        score = _score_row(query, r, core_count, section)
        exact_core = core_count is not None and r['core_count'] == core_count
        exact_section = section is not None and r['section_mm2'] is not None and abs(float(r['section_mm2']) - section) < 1e-9
        stock_bonus = 2 if r['has_stock'] else 0
        scored.append((exact_core and exact_section, exact_core, exact_section, score, stock_bonus, r))
    scored.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]), reverse=True)

    result = []
    for _,_,_,score,_,r in scored[:16]:
        item = _row_to_candidate(r, score)
        if r['has_stock']:
            item['availability_status'] = 'В наличии'
        elif r['has_incoming']:
            item['availability_status'] = 'В пути на склад'
            inc = incoming_map.get(r['article'])
            if inc:
                item['incoming_arrival_date'] = inc['arrival_date']
                item['incoming_qty'] = inc['incoming_qty']
        result.append(item)

    return json.dumps({
        'query': query,
        'search_pool': 'Товары на складе + Товары в пути',
        'technical_match_priority': True,
        'matches': result,
    }, ensure_ascii=False)


def get_cable(article: str) -> str:
    """Get full catalog characteristics for one article. Read-only."""
    print("[Qwen → get_cable]")
    article = str(article).strip()
    con = _connect()
    r = con.execute("""
        SELECT article,family,designation,core_count,section_mm2,core_marking,
               voltage,shielded,conductor_material,flexibility,
               outer_diameter_mm,copper_weight_kg_km,weight_kg_km,
               spec_text,source_page
        FROM cables WHERE article=?
    """, (article,)).fetchone()
    con.close()
    if not r:
        return json.dumps({"error": "Артикул не найден в локальном каталоге.", "article": article}, ensure_ascii=False)
    return json.dumps(dict(r), ensure_ascii=False)


def check_stock(article: str) -> str:
    """Check current stock and all planned incoming shipments. Read-only."""
    print("[Qwen → check_stock]")
    article = str(article).strip()
    con = _connect()
    stock = con.execute("SELECT qty FROM stock WHERE article=?", (article,)).fetchone()
    incoming = con.execute("""
        SELECT arrival_date, qty, name
        FROM incoming
        WHERE article=?
        ORDER BY arrival_date
    """, (article,)).fetchall()
    con.close()

    return json.dumps({
        "article": article,
        "current_stock": float(stock["qty"]) if stock else 0,
        "current_stock_source": "XLSX: Товары на складе",
        "incoming": [dict(x) for x in incoming],
        "incoming_source": "XLSX: Товары в пути",
        "quantity_unit": "not specified in XLSX",
        "data_as_of": "2026-09-15",
    }, ensure_ascii=False)


def web_search(query: str) -> str:
    """
    Search the public web through free-search-mcp.
    One model-visible tool, with research performed inside the MCP client.
    """
    print("[Qwen → web_search/free-search-mcp]")
    return free_search_web(query)


AVAILABLE_TOOLS = [search_available_cables, search_catalog, get_cable, check_stock, web_search]
AVAILABLE_FUNCTIONS = {f.__name__: f for f in AVAILABLE_TOOLS}
