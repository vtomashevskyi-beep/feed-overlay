"""
Опціональний крок через Anthropic API:
- скорочує/чистить title під накладання на банер (без SKU, кодів кольору, зайвих хвостів)
- нормалізує розміри в єдиний формат (XXS|XS|S|M|L), дістає їх з title якщо атрибут size пустий

Працює батчами, відповідь строго JSON. Якщо ANTHROPIC_API_KEY не заданий - крок пропускається.
"""
from __future__ import annotations

import json
import os

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

SYSTEM = """Ти готуєш атрибути товарів для накладання тексту на банер.
Для кожного товару поверни:
- display_title: коротка чиста назва до 45 символів, без артикулів, SKU, кодів кольору і дублювань бренду
- sizes: розміри у форматі через кому (XXS,XS,S,M,L). Якщо в size пусто, спробуй дістати з title. Якщо розмірів нема - пустий рядок.
Мову title не змінюй. Відповідай СУВОРО валідним JSON масивом об'єктів {"id","display_title","sizes"} без markdown."""


def enrich_items(items: list[dict], api_key: str | None = None) -> dict[str, dict]:
    """items: [{id,title,size}] -> {id: {display_title, sizes}}"""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key or not items:
        return {}
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    result: dict[str, dict] = {}
    BATCH = 25
    for i in range(0, len(items), BATCH):
        batch = items[i:i + BATCH]
        payload = json.dumps(
            [{"id": it["id"], "title": it.get("title", ""), "size": it.get("size", "")} for it in batch],
            ensure_ascii=False,
        )
        try:
            msg = client.messages.create(
                model=MODEL, max_tokens=4000, system=SYSTEM,
                messages=[{"role": "user", "content": payload}],
            )
            text = "".join(b.text for b in msg.content if b.type == "text")
            text = text.replace("```json", "").replace("```", "").strip()
            for row in json.loads(text):
                result[str(row["id"])] = {
                    "display_title": row.get("display_title", ""),
                    "sizes": row.get("sizes", ""),
                }
        except Exception:
            continue  # фейл батча не валить весь джоб, просто беремо сирі атрибути
    return result
