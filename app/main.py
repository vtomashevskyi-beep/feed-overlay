"""
Feed Image Overlay - сервіс генерації банерів з товарного фіда.

Потік:
1. POST /api/jobs - завантажуєш фід (xml/csv/xlsx) + налаштування
2. фоновий джоб: парсинг -> (опц. Claude чистить title/sizes) -> качає зображення
   по image_link -> накладає title/size/price -> зберігає в сховище -> формує URL
3. GET /api/jobs/{id} - прогрес і результати (id -> нове посилання)
4. GET /api/jobs/{id}/feed.csv | feed.xml - оновлений фід з підміненим image_link

Запуск:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import csv
import io
import os
import time
import uuid
from xml.sax.saxutils import escape

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .claude_enrich import enrich_items
from .feed_parser import parse_feed
from .renderer import render_overlay
from .storage import get_storage

app = FastAPI(title="Feed Image Overlay")
storage = get_storage()

JOBS: dict[str, dict] = {}  # для прод-версії винести в Redis/Postgres

MAX_CONCURRENCY = int(os.environ.get("DOWNLOAD_CONCURRENCY", "8"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "20"))


# ---------- фоновий процесинг ----------

async def process_job(job_id: str):
    job = JOBS[job_id]
    items = job["items"]
    s = job["settings"]

    # 1. опціональне збагачення через Claude
    if s.get("use_claude"):
        enriched = await asyncio.to_thread(
            enrich_items,
            [{"id": it["id"], "title": it["title"], "size": it["size"]} for it in items],
        )
        for it in items:
            e = enriched.get(str(it["id"]))
            if e:
                if e.get("display_title"):
                    it["display_title"] = e["display_title"]
                if e.get("sizes"):
                    it["size"] = e["sizes"]

    # 2. завантаження + рендер + збереження
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def handle(client: httpx.AsyncClient, it: dict):
        async with sem:
            try:
                if not it.get("image_link"):
                    raise ValueError("empty image_link")
                r = await client.get(it["image_link"], follow_redirects=True)
                r.raise_for_status()
                rendered = await asyncio.to_thread(
                    render_overlay, r.content,
                    brand=s.get("brand", ""),
                    title=it.get("display_title") or it.get("title", ""),
                    price=it.get("price", ""),
                    sale_price=it.get("sale_price", ""),
                    sizes=it.get("size", ""),
                    text_color=s.get("text_color", "#ffffff"),
                    gradient=s.get("gradient", True),
                )
                safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(it["id"]))
                key = f"{job_id}/{safe_id}.jpg"
                url = await asyncio.to_thread(storage.save, key, rendered)
                it["new_image_link"] = url
                it["status"] = "done"
            except Exception as exc:
                it["status"] = "error"
                it["error"] = str(exc)[:200]
            finally:
                job["processed"] += 1

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"User-Agent": "FeedOverlay/1.0"}) as client:
        await asyncio.gather(*(handle(client, it) for it in items))

    job["status"] = "done"
    job["finished_at"] = time.time()


# ---------- API ----------

@app.post("/api/jobs")
async def create_job(
    background: BackgroundTasks,
    feed: UploadFile = File(...),
    brand: str = Form(""),
    text_color: str = Form("#ffffff"),
    gradient: bool = Form(True),
    use_claude: bool = Form(False),
    limit: int = Form(0),
):
    data = await feed.read()
    try:
        parsed = parse_feed(feed.filename or "feed", data)
    except Exception as exc:
        raise HTTPException(400, f"Не вдалось розпарсити фід: {exc}")
    if not parsed:
        raise HTTPException(400, "У фіді не знайдено жодного товару з id")

    items = [p.as_dict() | {"status": "pending"} for p in parsed]
    if limit > 0:
        items = items[:limit]

    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "id": job_id, "status": "processing",
        "total": len(items), "processed": 0,
        "created_at": time.time(),
        "settings": {"brand": brand, "text_color": text_color,
                     "gradient": gradient, "use_claude": use_claude},
        "items": items,
    }
    background.add_task(process_job, job_id)
    return {"job_id": job_id, "total": len(items)}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job не знайдено")
    return {
        "id": job["id"], "status": job["status"],
        "total": job["total"], "processed": job["processed"],
        "items": [
            {"id": it["id"], "title": it.get("display_title") or it["title"],
             "status": it["status"], "new_image_link": it.get("new_image_link", ""),
             "image_link": it.get("image_link", ""), "error": it.get("error", "")}
            for it in job["items"]
        ],
    }


@app.get("/api/jobs/{job_id}/feed.csv")
async def export_csv(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job не знайдено")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "title", "size", "price", "sale_price", "image_link"])
    for it in job["items"]:
        w.writerow([it["id"], it["title"], it["size"], it["price"],
                    it["sale_price"], it.get("new_image_link") or it["image_link"]])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=feed_{job_id}.csv"})


@app.get("/api/jobs/{job_id}/feed.xml")
async def export_xml(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job не знайдено")
    rows = []
    for it in job["items"]:
        rows.append(
            "<item>"
            f"<g:id>{escape(str(it['id']))}</g:id>"
            f"<g:title>{escape(it['title'])}</g:title>"
            + (f"<g:size>{escape(it['size'])}</g:size>" if it["size"] else "")
            + (f"<g:price>{escape(it['price'])}</g:price>" if it["price"] else "")
            + (f"<g:sale_price>{escape(it['sale_price'])}</g:sale_price>" if it["sale_price"] else "")
            + f"<g:image_link>{escape(it.get('new_image_link') or it['image_link'])}</g:image_link>"
            "</item>"
        )
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>'
           + "".join(rows) + "</channel></rss>")
    return Response(xml, media_type="application/xml",
                    headers={"Content-Disposition": f"attachment; filename=feed_{job_id}.xml"})


# ---------- статика ----------

media_dir = os.environ.get("MEDIA_DIR", "media")
os.makedirs(media_dir, exist_ok=True)
app.mount("/media", StaticFiles(directory=media_dir), name="media")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "..", "static", "index.html"))
