"""Kite API key/secret and admin rules. Admin-page values win over START_MJVS.bat values."""
from sqlalchemy.orm import Session

from . import config, security
from .db import AppSetting, Member, engine, now_ist

SECRET_KEYS = {"kite_api_secret"}
_cache: dict[str, str] = {}


def _get(key: str) -> str:
    if key not in _cache:
        with Session(engine) as s:
            row = s.get(AppSetting, key)
            val = row.value if row else ""
            if val and key in SECRET_KEYS:
                try:
                    val = security.decrypt(val)
                except Exception:
                    val = ""
            _cache[key] = val
    return _cache[key]


def put(key: str, value: str):
    stored = security.encrypt(value) if (value and key in SECRET_KEYS) else value
    with Session(engine) as s:
        row = s.get(AppSetting, key) or AppSetting(key=key)
        row.value, row.updated_at = stored, now_ist()
        s.merge(row)
        s.commit()
    _cache.pop(key, None)


def _real(v: str) -> str:
    return "" if v.strip().lower() in ("", "not-set-yet", "your_api_key_here", "your_api_secret_here") else v.strip()


def kite_api_key() -> str:
    return _real(_get("kite_api_key")) or _real(config.KITE_API_KEY)


def kite_api_secret() -> str:
    return _real(_get("kite_api_secret")) or _real(config.KITE_API_SECRET)


def kite_ready() -> bool:
    return bool(kite_api_key() and kite_api_secret())


def kite_source() -> str:
    if _real(_get("kite_api_key")):
        return "admin page"
    return "START_MJVS.bat" if _real(config.KITE_API_KEY) else ""


def allow_live() -> bool:
    """Real orders allowed? Set on the Admin page; START_MJVS.bat's ALLOW_LIVE is the starting value."""
    v = _get("allow_live")
    return v == "1" if v in ("0", "1") else config.ALLOW_LIVE


def redirect_url() -> str:
    return f"{config.BACKEND_URL}/kite/callback"


def is_admin(s: Session, m: Member | None) -> bool:
    """Emails in ADMIN_EMAILS are admins. If none are set, the first account ever created is."""
    if not m:
        return False
    if config.ADMIN_EMAILS:
        return m.email in config.ADMIN_EMAILS
    first = s.query(Member.id).order_by(Member.id).first()
    return bool(first) and first[0] == m.id
