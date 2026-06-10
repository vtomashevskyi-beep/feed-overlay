"""
Парсинг товарних фідів Merchant Center: XML (RSS 2.0 з g: namespace), CSV, XLSX.
На виході - список словників з атрибутами: id, title, size, price, sale_price, image_link.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Optional

from lxml import etree
from openpyxl import load_workbook

G_NS = "http://base.google.com/ns/1.0"

# які атрибути нас цікавлять і їхні можливі назви колонок
ATTR_ALIASES = {
    "id": ["id", "g:id", "item id", "offer id", "sku"],
    "title": ["title", "g:title", "назва", "name"],
    "size": ["size", "g:size", "sizes", "розмір", "розміри"],
    "price": ["price", "g:price", "ціна"],
    "sale_price": ["sale_price", "g:sale_price", "sale price", "акційна ціна"],
    "image_link": ["image_link", "g:image_link", "image link", "image", "зображення"],
}


@dataclass
class FeedItem:
    id: str
    title: str = ""
    size: str = ""
    price: str = ""
    sale_price: str = ""
    image_link: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "size": self.size,
            "price": self.price,
            "sale_price": self.sale_price,
            "image_link": self.image_link,
        }


def _norm_header(h: str) -> str:
    return (h or "").strip().lower().replace("\ufeff", "")


def _map_headers(headers: list[str]) -> dict[str, int]:
    """Повертає мапу attr -> індекс колонки."""
    norm = [_norm_header(h) for h in headers]
    mapping: dict[str, int] = {}
    for attr, aliases in ATTR_ALIASES.items():
        for alias in aliases:
            if alias in norm:
                mapping[attr] = norm.index(alias)
                break
    return mapping


def parse_csv(data: bytes) -> list[FeedItem]:
    text = data.decode("utf-8-sig", errors="replace")
    # автодетект роздільника
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        return []
    mapping = _map_headers(rows[0])
    items = []
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        get = lambda a: (row[mapping[a]].strip() if a in mapping and mapping[a] < len(row) else "")
        item_id = get("id")
        if not item_id:
            continue
        items.append(FeedItem(
            id=item_id, title=get("title"), size=get("size"),
            price=get("price"), sale_price=get("sale_price"),
            image_link=get("image_link"),
        ))
    return items


def parse_xlsx(data: bytes) -> list[FeedItem]:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    try:
        headers = [str(h) if h is not None else "" for h in next(rows)]
    except StopIteration:
        return []
    mapping = _map_headers(headers)
    items = []
    for row in rows:
        cells = ["" if c is None else str(c).strip() for c in row]
        if not any(cells):
            continue
        get = lambda a: (cells[mapping[a]] if a in mapping and mapping[a] < len(cells) else "")
        item_id = get("id")
        if not item_id:
            continue
        items.append(FeedItem(
            id=item_id, title=get("title"), size=get("size"),
            price=get("price"), sale_price=get("sale_price"),
            image_link=get("image_link"),
        ))
    return items


def parse_xml(data: bytes) -> list[FeedItem]:
    """Google Merchant RSS 2.0 фід (channel/item з g: атрибутами). Atom теж пробуємо."""
    root = etree.fromstring(data)
    items_xml = root.findall(".//item")
    if not items_xml:
        # Atom: entry
        items_xml = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    def g(el, name):
        v = el.findtext(f"{{{G_NS}}}{name}")
        if v is None:
            v = el.findtext(name)
        return (v or "").strip()

    items = []
    for el in items_xml:
        item_id = g(el, "id")
        if not item_id:
            continue
        title = g(el, "title")
        items.append(FeedItem(
            id=item_id, title=title, size=g(el, "size"),
            price=g(el, "price"), sale_price=g(el, "sale_price"),
            image_link=g(el, "image_link"),
        ))
    return items


def parse_feed(filename: str, data: bytes) -> list[FeedItem]:
    name = filename.lower()
    if name.endswith(".xml"):
        return parse_xml(data)
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        return parse_xlsx(data)
    if name.endswith(".csv") or name.endswith(".tsv") or name.endswith(".txt"):
        return parse_csv(data)
    # пробуємо по контенту
    stripped = data.lstrip()
    if stripped.startswith(b"<"):
        return parse_xml(data)
    if data[:2] == b"PK":
        return parse_xlsx(data)
    return parse_csv(data)
