"""
Накладання атрибутів товару поверх зображення (стиль як на прикладі Etnodim):
- логотип/назва бренду зверху зліва
- внизу: title курсивним serif, ціна справа (sale_price + перекреслена price якщо є знижка)
- під назвою: плашка з розмірами XXS | XS | S | M | L
- легкий світлий градієнт знизу для читабельності
"""
from __future__ import annotations

import io
import os
import re

from PIL import Image, ImageDraw, ImageFont, ImageEnhance

FONT_DIR = os.environ.get("FONT_DIR", "/usr/share/fonts/truetype")

# дефолтні шрифти (можна перевизначити через env)
FONT_SERIF_ITALIC = os.environ.get(
    "FONT_TITLE", f"{FONT_DIR}/dejavu/DejaVuSerif-Italic.ttf")
FONT_SERIF_BOLD_ITALIC = os.environ.get(
    "FONT_PRICE", f"{FONT_DIR}/dejavu/DejaVuSerif-BoldItalic.ttf")
FONT_MONO = os.environ.get(
    "FONT_BRAND", f"{FONT_DIR}/dejavu/DejaVuSansMono-Bold.ttf")
FONT_SANS = os.environ.get(
    "FONT_SIZES", f"{FONT_DIR}/dejavu/DejaVuSerif.ttf")


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def _parse_sizes(size_value: str) -> list[str]:
    if not size_value:
        return []
    parts = re.split(r"[,;/|]+", size_value)
    return [p.strip().upper() for p in parts if p.strip()]


def _fmt_price(p: str) -> str:
    """ '261.00 USD' -> '261$', '4 599 UAH' -> '4599 грн' """
    p = (p or "").strip()
    if not p:
        return ""
    m = re.match(r"([\d\s.,]+)\s*([A-Za-zА-Яа-яіІїЇєЄ$€₴]*)", p)
    if not m:
        return p
    num, cur = m.group(1).strip(), m.group(2).upper()
    # прибираємо копійки .00 / ,00
    num = re.sub(r"[.,]0{1,2}$", "", num).replace(" ", "")
    symbols = {"USD": "$", "EUR": "€", "UAH": " грн", "PLN": " zł", "GBP": "£",
               "$": "$", "€": "€", "₴": " грн"}
    return f"{num}{symbols.get(cur, (' ' + cur if cur else ''))}"


def render_overlay(
    image_bytes: bytes,
    *,
    brand: str = "",
    title: str = "",
    price: str = "",
    sale_price: str = "",
    sizes: str = "",
    text_color: str = "#ffffff",
    gradient: bool = True,
    out_format: str = "JPEG",
    quality: int = 88,
) -> bytes:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    W, H = img.size
    scale = W / 1000.0  # все масштабуємо від ширини 1000px

    # --- світлий градієнт знизу, щоб білий текст читався ---
    if gradient:
        grad_h = int(H * 0.28)
        overlay = Image.new("L", (1, grad_h))
        for y in range(grad_h):
            overlay.putpixel((0, y), int(110 * (y / grad_h) ** 1.5))
        alpha = overlay.resize((W, grad_h))
        dark = Image.new("RGB", (W, grad_h), (20, 20, 20))
        base = img.crop((0, H - grad_h, W, H))
        img.paste(Image.composite(dark, base, alpha), (0, H - grad_h))

    draw = ImageDraw.Draw(img)
    color = text_color
    pad = int(55 * scale)

    # --- бренд зверху ---
    if brand:
        f_brand = _font(FONT_MONO, int(34 * scale))
        # розріджений трекінг як у лого
        spaced = " ".join(list(brand.upper()))
        draw.text((pad, int(45 * scale)), spaced, font=f_brand,
                  fill="#6b6b6b")

    # --- ціни ---
    sale = _fmt_price(sale_price)
    base_price = _fmt_price(price)
    has_sale = bool(sale) and sale != base_price

    f_title = _font(FONT_SERIF_ITALIC, int(44 * scale))
    f_price = _font(FONT_SERIF_BOLD_ITALIC, int(46 * scale))
    f_price_old = _font(FONT_SERIF_ITALIC, int(32 * scale))
    f_sizes = _font(FONT_SANS, int(26 * scale))

    sizes_list = _parse_sizes(sizes)
    bottom = H - int(40 * scale)

    # --- плашка розмірів (низ-ліво, під назвою) ---
    sizes_h = 0
    if sizes_list:
        label = " | ".join(sizes_list)
        tb = draw.textbbox((0, 0), label, font=f_sizes)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        box_pad = int(12 * scale)
        x0, y1 = pad, bottom
        y0 = y1 - th - 2 * box_pad
        draw.rectangle([x0, y0, x0 + tw + 2 * box_pad, y1],
                       outline=color, width=max(2, int(2 * scale)))
        draw.text((x0 + box_pad, y0 + box_pad - tb[1]), label,
                  font=f_sizes, fill=color)
        sizes_h = (y1 - y0) + int(18 * scale)

    # --- title зліва, ціна справа на одному рівні ---
    title_y = bottom - sizes_h
    # ціна
    price_text = sale if has_sale else base_price
    if price_text:
        pb = draw.textbbox((0, 0), price_text, font=f_price)
        pw = pb[2] - pb[0]
        px = W - pad - pw
        py = title_y - (pb[3] - pb[1]) - int(8 * scale)
        draw.text((px, py - pb[1]), price_text, font=f_price, fill=color)
        left_edge = px
        if has_sale and base_price:
            ob = draw.textbbox((0, 0), base_price, font=f_price_old)
            ow, oh = ob[2] - ob[0], ob[3] - ob[1]
            ox = px - ow - int(24 * scale)
            oy = py + (pb[3] - pb[1]) - oh
            draw.text((ox, oy - ob[1]), base_price, font=f_price_old, fill=color)
            draw.line([ox - 2, oy + oh / 2, ox + ow + 2, oy + oh / 2],
                      fill=color, width=max(2, int(2 * scale)))
            left_edge = ox
        title_max_w = left_edge - pad - int(40 * scale)
    else:
        title_max_w = W - 2 * pad

    # title з обрізанням під доступну ширину
    if title:
        t = title
        while t and draw.textbbox((0, 0), t, font=f_title)[2] > title_max_w:
            t = t[:-1]
        if t != title:
            t = t.rstrip() + "…"
        tb = draw.textbbox((0, 0), t, font=f_title)
        ty = title_y - (tb[3] - tb[1]) - int(8 * scale)
        draw.text((pad, ty - tb[1]), t, font=f_title, fill=color)

    buf = io.BytesIO()
    img.save(buf, format=out_format, quality=quality, optimize=True)
    return buf.getvalue()
