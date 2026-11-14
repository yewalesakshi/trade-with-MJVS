"""Login tokens, captcha, password hashing and encryption of Kite tokens."""
import datetime as dt

import httpx
import jwt
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from fastapi import Header, HTTPException

from . import config

fernet = Fernet(config.FERNET_KEY)
hasher = PasswordHasher()


def encrypt(s: str) -> str:
    return fernet.encrypt(s.encode()).decode()


def decrypt(s: str) -> str:
    return fernet.decrypt(s.encode()).decode()


def make_token(member_id: int, minutes: int = 60 * 12, purpose: str = "session") -> str:
    exp = dt.datetime.utcnow() + dt.timedelta(minutes=minutes)
    return jwt.encode({"sub": str(member_id), "exp": exp, "purpose": purpose},
                      config.JWT_SECRET, algorithm="HS256")


def read_token(token: str, purpose: str = "session") -> int:
    try:
        data = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Please log in again")
    if data.get("purpose") != purpose:
        raise HTTPException(401, "Please log in again")
    return int(data["sub"])


def current_member_id(authorization: str = Header(default="")) -> int:
    return read_token(authorization.removeprefix("Bearer ").strip())


def check_captcha(token: str, captcha_id: str = ""):
    """Built-in picture captcha, or Cloudflare Turnstile. Verified on the server; fails closed."""
    if config.CAPTCHA_MODE != "turnstile":
        from . import captcha
        if not captcha.check(captcha_id, token):
            raise HTTPException(400, "The captcha letters did not match. Please try the new picture.")
        return
    if not config.TURNSTILE_SECRET:
        raise HTTPException(500, "Captcha is not configured")
    r = httpx.post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                   data={"secret": config.TURNSTILE_SECRET, "response": token}, timeout=10)
    if not r.json().get("success"):
        raise HTTPException(400, "Captcha failed. Please try again.")


# ---- wrong-password lockout (kept in memory; resets when the app restarts)
import threading
import time

LOCK_AFTER = 5            # wrong passwords for one email ...
LOCK_WINDOW = 15 * 60     # ... within 15 minutes locks it for 15 minutes
IP_LIMIT = 20             # wrong passwords from one address within 15 minutes
_fails: dict[str, list[float]] = {}
_fails_lock = threading.Lock()


def _recent(key: str) -> list[float]:
    now = time.time()
    with _fails_lock:
        hits = [t for t in _fails.get(key, []) if now - t < LOCK_WINDOW]
        _fails[key] = hits
        return hits


def check_not_locked(email: str, ip: str):
    for key, limit in ((f"e:{email}", LOCK_AFTER), (f"i:{ip}", IP_LIMIT)):
        hits = _recent(key)
        if len(hits) >= limit:
            mins = max(1, int((LOCK_WINDOW - (time.time() - hits[0])) // 60) + 1)
            raise HTTPException(429, f"Too many wrong passwords. For your safety, try again in {mins} minutes.")


def record_failure(email: str, ip: str):
    with _fails_lock:
        for key in (f"e:{email}", f"i:{ip}"):
            _fails.setdefault(key, []).append(time.time())


def clear_failures(email: str):
    with _fails_lock:
        _fails.pop(f"e:{email}", None)
