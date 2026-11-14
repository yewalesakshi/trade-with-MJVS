"""All settings come from environment variables (set in START_MJVS.bat for local use)."""
import os
import datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def ist_now() -> dt.datetime:
    """Current time in India. Always call as config.ist_now() so tests can move the clock."""
    return dt.datetime.now(IST)


def ist_today() -> dt.date:
    return ist_now().date()


def _list(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(ROOT, "mjvs.db"))
FRONTEND_ORIGINS = [o.rstrip("/") for o in _list("FRONTEND_URL")] or ["http://localhost:8000"]
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")   # tunnel / hosted address for Chartink webhooks
JWT_SECRET = os.environ.get("JWT_SECRET", "")
FERNET_KEY = os.environ.get("FERNET_KEY", "")
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET", "")
TURNSTILE_SITEKEY = os.environ.get("TURNSTILE_SITEKEY", "")
# "builtin" = picture captcha served by this app (works offline). "turnstile" = Cloudflare (hosted sites).
CAPTCHA_MODE = os.environ.get("CAPTCHA_MODE", "builtin").lower()
BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(ROOT, "backups"))
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "30"))
KITE_API_KEY = os.environ.get("KITE_API_KEY", "")
KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "")
ALLOW_LIVE = os.environ.get("ALLOW_LIVE", "0") == "1"          # real orders allowed on this server
CHARTINK_KEY = os.environ.get("CHARTINK_KEY", "")              # secret part of the webhook URL
ADMIN_EMAILS = {e.lower() for e in _list("ADMIN_EMAILS")}
SCHEDULER_ON = os.environ.get("MJVS_NO_SCHEDULER") != "1"

if not JWT_SECRET or not FERNET_KEY:
    raise RuntimeError("JWT_SECRET and FERNET_KEY must be set (see START_MJVS.bat)")
