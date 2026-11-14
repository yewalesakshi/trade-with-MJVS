"""
Built-in picture captcha: no outside account needed, works on a home PC.
Each captcha is single-use and expires after 5 minutes. Answers are kept only as hashes.
(Set CAPTCHA_MODE=turnstile to use Cloudflare Turnstile instead once the site is hosted.)
"""
import base64
import hashlib
import io
import random
import secrets
import threading
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I lookalikes
LENGTH = 5
TTL = 300
MAX_STORED = 20000

_store: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def _font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:          # very old Pillow
        return ImageFont.load_default()


def _hash(text: str) -> str:
    return hashlib.sha256(text.strip().upper().encode()).hexdigest()


def _render(text: str) -> bytes:
    w, h = 200, 64
    rnd = random.SystemRandom()
    img = Image.new("RGB", (w, h), (rnd.randint(235, 250), rnd.randint(235, 250), rnd.randint(240, 255)))
    draw = ImageDraw.Draw(img)
    for _ in range(6):        # background noise lines
        draw.line([(rnd.randint(0, w), rnd.randint(0, h)), (rnd.randint(0, w), rnd.randint(0, h))],
                  fill=(rnd.randint(120, 200), rnd.randint(120, 200), rnd.randint(150, 220)), width=2)
    font = _font(38)
    x = 12
    for ch in text:
        tile = Image.new("RGBA", (50, 60), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((8, 4), ch, font=font,
                                  fill=(rnd.randint(10, 80), rnd.randint(10, 60), rnd.randint(90, 170), 255))
        tile = tile.rotate(rnd.uniform(-28, 28), resample=Image.BICUBIC, expand=False)
        img.paste(tile, (x, rnd.randint(-4, 8)), tile)
        x += rnd.randint(32, 37)
    for _ in range(220):      # speckles
        draw.point((rnd.randint(0, w - 1), rnd.randint(0, h - 1)),
                   fill=(rnd.randint(60, 160), rnd.randint(60, 160), rnd.randint(60, 160)))
    draw.line([(0, rnd.randint(20, 44)), (w, rnd.randint(20, 44))], fill=(60, 50, 150), width=2)
    img = img.filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def new() -> dict:
    text = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    cid = secrets.token_urlsafe(16)
    now = time.time()
    with _lock:
        if len(_store) > MAX_STORED:
            for k in [k for k, (_, exp) in _store.items() if exp < now]:
                _store.pop(k, None)
            if len(_store) > MAX_STORED:
                _store.clear()
        _store[cid] = (_hash(text), now + TTL)
    return {"id": cid, "image": "data:image/png;base64," + base64.b64encode(_render(text)).decode()}


def check(cid: str, answer: str) -> bool:
    """Single use: the captcha is gone after one try, right or wrong."""
    with _lock:
        item = _store.pop(cid or "", None)
    if not item or item[1] < time.time():
        return False
    return secrets.compare_digest(item[0], _hash(answer or ""))
