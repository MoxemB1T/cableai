
from __future__ import annotations

import argparse
import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime
import pdfplumber
import openpyxl

FAMILY_RANGES = {
    "VicabFLEX 100": range(4, 6),
    "VicabFLEX 100 нг(А)-LS": range(6, 8),
    "VicabFLEX 100 0,6/1 кВ": range(8, 10),
    "VicabFLEX 100 нг(А)-LS 0,6/1 кВ": range(10, 12),
    "VicabFLEX 110": range(12, 16),
    "VicabFLEX 110 нг(А)-LS": range(16, 20),
    "VicabFLEX 115 CY": range(20, 23),
    "VicabFLEX 115 CY нг(А)-LS": range(23, 26),
    "VicabFLEX 105 CY 0,6/1 кВ": range(26, 28),
    "VicabFLEX 105 CY нг(А)-LS 0,6/1 кВ": range(28, 30),
    "VICABMINE EMC КГРэЭаВ нг(А)-LS": range(30, 32),
    "H07V-K": range(32, 34),
    "H05V-K": range(34, 36),
    "H07RN-F": range(36, 39),
    "NYY-J/NYY-O": range(39, 42),
    "N2XH-O/N2XH-J": range(42, 45),
    "NYCY": range(45, 47),
    "NYCWY": range(47, 49),
}

COLOR_GROUPS = [
    ["зелено-желтый", "коричневый", "черный", "серый", "голубой", "оранжевый"],
    ["темно-синий", "белый", "зеленый", "желтый", "фиолетовый", "красный"],
    ["ультрамариновый", "розовый"],
]

ARTICLE_RE = re.compile(r"\b16\d{8}\b")


def norm_text(value: str | None) -> str:
    if value is None:
        return ""
    s = str(value).lower().replace("ё", "е")
    s = s.replace("×", "x").replace("х", "x")
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"[\s_/]+", " ", s)
    return re.sub(r"[^0-9a-zа-я.+-]+", " ", s).strip()


def parse_designation(designation: str):
    d = designation.strip()
    m = re.match(r"^(\d+)\s*[gG]\s*([0-9]+(?:[.,][0-9]+)?)$", d)
    if m:
        return int(m.group(1)), m.group(2).replace(",", "."), "G"
    m = re.match(r"^(\d+)\s*[xX]\s*([0-9]+(?:[.,][0-9]+)?)(.*)$", d)
    if m:
        return int(m.group(1)), m.group(2).replace(",", "."), ("X" + m.group(3).strip() if m.group(3).strip() else "X")
    m = re.match(r"^([0-9]+(?:[.,][0-9]+)?)\s+(.+)$", d)
    if m and d[0].isdigit():
        return 1, m.group(1).replace(",", "."), m.group(2).strip()
    return None, None, None


def extract_voltage(spec_text: str):
    m = re.search(r"Номинальное напряжение:\s*([0-9]+/[0-9]+\s*В)", spec_text, re.I)
    return m.group(1).replace(" ", "") if m else None


def extract_family_specs(pdf, first_page: int):
    text = pdf.pages[first_page - 1].extract_text(x_tolerance=2, y_tolerance=3) or ""
    voltage = extract_voltage(text)
    shielded = "экранированный" in text.lower() or " CY" in text or "EMC" in text
    conductor = "медь" if "мед" in text.lower() or "Вес\nмеди" in text else "медь"
    flex = "класс 5" if "5 класс" in text.lower() or "5 класс" in text.lower() else None
    return text.strip(), voltage, int(shielded), conductor, flex


def parse_standard_line(line: str, family: str, page_no: int):
    matches = list(ARTICLE_RE.finditer(line))
    out = []
    for i, m in enumerate(matches):
        article = m.group()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
        segment = line[m.end():end].strip()
        nums = list(re.finditer(r"(?<![\w])\d+(?:[.,]\d+)?", segment))
        if len(nums) < 3:
            continue
        last = nums[-3:]
        designation = segment[:last[0].start()].strip()
        if not designation:
            continue
        diameter = float(last[0].group().replace(",", "."))
        copper_weight = float(last[1].group().replace(",", "."))
        weight = float(last[2].group().replace(",", "."))
        core_count, section, core_marking = parse_designation(designation)
        out.append({
            "article": article,
            "family": family,
            "designation": designation,
            "core_count": core_count,
            "section_mm2": section,
            "core_marking": core_marking,
            "outer_diameter_mm": diameter,
            "copper_weight_kg_km": copper_weight,
            "weight_kg_km": weight,
            "source_page": page_no,
        })
    return out


def parse_h07_h05_page(pdf, family: str, page_no: int):
    text = pdf.pages[page_no - 1].extract_text(x_tolerance=2, y_tolerance=3) or ""
    group_idx = -1
    rows = []
    for line in text.splitlines():
        if line.startswith("Сечение"):
            group_idx += 1
            continue
        if group_idx < 0:
            continue
        am = ARTICLE_RE.search(line)
        if not am:
            continue
        prefix = line[:am.start()].strip()
        m = re.match(
            r"([0-9]+(?:[.,][0-9]+)?)\s+([0-9]+(?:[.,][0-9]+)?)\s+на отрез\s+"
            r"([0-9]+(?:[.,][0-9]+)?)\s+([0-9]+(?:[.,][0-9]+)?)\s*$",
            prefix,
        )
        if not m:
            continue
        section, diameter, copper_weight, weight = m.groups()
        articles = ARTICLE_RE.findall(line)
        for j, article in enumerate(articles):
            color = COLOR_GROUPS[group_idx][j] if j < len(COLOR_GROUPS[group_idx]) else None
            designation = f"{section.replace(',', '.')} {color}" if color else section.replace(",", ".")
            rows.append({
                "article": article,
                "family": family,
                "designation": designation,
                "core_count": 1,
                "section_mm2": section.replace(",", "."),
                "core_marking": color,
                "outer_diameter_mm": float(diameter.replace(",", ".")),
                "copper_weight_kg_km": float(copper_weight.replace(",", ".")),
                "weight_kg_km": float(weight.replace(",", ".")),
                "source_page": page_no,
            })
    return rows


def parse_pdf(pdf_path: Path):
    rows = []
    family_meta = {}
    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) != 73:
            print(f"WARNING: PDF pages={len(pdf.pages)}, expected 73 for this catalog.")
        for family, pages in FAMILY_RANGES.items():
            first_page = list(pages)[0]
            spec_text, voltage, shielded, conductor, flex = extract_family_specs(pdf, first_page)
            family_meta[family] = {
                "spec_text": spec_text,
                "voltage": voltage,
                "shielded": shielded,
                "conductor_material": conductor,
                "flexibility": flex,
            }
            for page_no in pages:
                if family in ("H07V-K", "H05V-K"):
                    rows.extend(parse_h07_h05_page(pdf, family, page_no))
                else:
                    text = pdf.pages[page_no - 1].extract_text(x_tolerance=2, y_tolerance=3) or ""
                    for line in text.splitlines():
                        rows.extend(parse_standard_line(line, family, page_no))

    # Deduplicate by article; this should be zero for product pages.
    unique = {}
    duplicates = []
    for row in rows:
        if row["article"] in unique:
            duplicates.append(row["article"])
            continue
        unique[row["article"]] = row

    for row in unique.values():
        meta = family_meta[row["family"]]
        row.update({
            "voltage": meta["voltage"],
            "shielded": meta["shielded"],
            "conductor_material": meta["conductor_material"],
            "flexibility": meta["flexibility"],
            "spec_text": meta["spec_text"],
        })
        row["search_text"] = norm_text(
            " ".join([
                row["article"], row["family"], row["designation"],
                str(row.get("section_mm2") or ""),
                str(row.get("core_count") or ""),
                str(row.get("core_marking") or ""),
                str(row.get("voltage") or ""),
            ])
        )
    return list(unique.values()), family_meta, duplicates


def import_xlsx(xlsx_path: Path):
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    required = {"Товары на складе", "Товары в пути"}
    missing = required - set(wb.sheetnames)
    if missing:
        raise ValueError(f"Missing sheets: {sorted(missing)}")

    stock = {}
    ws = wb["Товары на складе"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        article, name, size, qty = row[:4]
        if article is None:
            continue
        article = str(int(article))
        qty = float(qty) if qty is not None else 0.0
        stock[article] = stock.get(article, 0.0) + qty

    incoming = []
    ws = wb["Товары в пути"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        date, article, name, qty = row[:4]
        if article is None:
            continue
        incoming.append({
            "arrival_date": date.date().isoformat() if hasattr(date, "date") else str(date),
            "article": str(int(article)),
            "name": str(name or ""),
            "qty": float(qty or 0),
        })
    return stock, incoming, wb.sheetnames


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS cables (
    article TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    designation TEXT NOT NULL,
    core_count INTEGER,
    section_mm2 REAL,
    core_marking TEXT,
    voltage TEXT,
    shielded INTEGER NOT NULL DEFAULT 0,
    conductor_material TEXT,
    flexibility TEXT,
    outer_diameter_mm REAL,
    copper_weight_kg_km REAL,
    weight_kg_km REAL,
    spec_text TEXT,
    source_page INTEGER,
    search_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock (
    article TEXT PRIMARY KEY,
    qty REAL NOT NULL DEFAULT 0,
    FOREIGN KEY(article) REFERENCES cables(article)
);

CREATE TABLE IF NOT EXISTS incoming (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article TEXT NOT NULL,
    arrival_date TEXT NOT NULL,
    qty REAL NOT NULL DEFAULT 0,
    name TEXT,
    FOREIGN KEY(article) REFERENCES cables(article)
);

CREATE INDEX IF NOT EXISTS idx_cables_family ON cables(family);
CREATE INDEX IF NOT EXISTS idx_cables_section ON cables(section_mm2);
CREATE INDEX IF NOT EXISTS idx_cables_core_count ON cables(core_count);
CREATE INDEX IF NOT EXISTS idx_incoming_article_date ON incoming(article, arrival_date);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def build_db(db_path: Path, cables, stock, incoming, sheet_names):
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    for c in cables:
        con.execute("""
            INSERT INTO cables (
                article,family,designation,core_count,section_mm2,core_marking,
                voltage,shielded,conductor_material,flexibility,outer_diameter_mm,
                copper_weight_kg_km,weight_kg_km,spec_text,source_page,search_text
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            c["article"], c["family"], c["designation"], c["core_count"], c["section_mm2"],
            c["core_marking"], c["voltage"], c["shielded"], c["conductor_material"],
            c["flexibility"], c["outer_diameter_mm"], c["copper_weight_kg_km"],
            c["weight_kg_km"], c["spec_text"], c["source_page"], c["search_text"]
        ))
    for article, qty in stock.items():
        con.execute("INSERT INTO stock(article,qty) VALUES(?,?)", (article, qty))
    for r in incoming:
        con.execute(
            "INSERT INTO incoming(article,arrival_date,qty,name) VALUES(?,?,?,?)",
            (r["article"], r["arrival_date"], r["qty"], r["name"])
        )
    con.executemany(
        "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
        [
            ("source_pdf_pages", "73"),
            ("catalog_cables", str(len(cables))),
            ("stock_unique_articles", str(len(stock))),
            ("incoming_rows", str(len(incoming))),
            ("xlsx_sheets", ", ".join(sheet_names)),
            ("price_available", "no"),
            ("imported_at", datetime.now().isoformat(timespec="seconds")),
        ],
    )
    con.commit()
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--db", default=os.getenv("CABLE_AI_DB_PATH", "catalog.db"))
    args = ap.parse_args()

    cables, family_meta, duplicates = parse_pdf(Path(args.pdf))
    stock, incoming, sheets = import_xlsx(Path(args.xlsx))

    catalog_articles = {c["article"] for c in cables}
    all_stock = set(stock) | {x["article"] for x in incoming}
    missing = sorted(all_stock - catalog_articles)
    if missing:
        raise ValueError(f"XLSX contains articles absent from PDF: {missing[:20]}")

    print(f"PDF: 73 pages, extracted product articles: {len(cables)}")
    print(f"XLSX sheets: {sheets}")
    print(f"Current stock unique articles: {len(stock)}")
    print(f"Incoming rows: {len(incoming)}")
    print(f"PDF duplicate article IDs on product pages: {len(duplicates)}")
    if duplicates:
        print("Duplicates:", sorted(set(duplicates))[:20])

    build_db(Path(args.db), cables, stock, incoming, sheets)
    print(f"DB created: {args.db}")


if __name__ == "__main__":
    main()
