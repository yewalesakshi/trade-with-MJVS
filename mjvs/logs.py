"""Application log: everything the app does or prints goes to logs/mjvs.log in the data folder
(next to the database backups), so the admin can read it on the Admin page.

- Rotating file: 5 files x 5 MB (the oldest is deleted automatically).
- Secrets are blanked out before writing: Kite request/access tokens, API secret, passwords,
  Authorization headers and JWTs.
- print() output and anything written to stderr (library tracebacks) are captured too.
"""
import logging
import logging.handlers
import os
import re
import sys

from . import config

LOG_DIR = os.path.join(os.path.dirname(config.BACKUP_DIR.rstrip("/\\")) or ".", "logs")
LOG_FILE = os.path.join(LOG_DIR, "mjvs.log")
FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

_SECRETS = [
    (re.compile(r"\b(request_token|access_token|api_secret|password|secret|token|t)=([^&\s\"']+)", re.I), r"\1=***"),
    (re.compile(r"(Authorization:?\s*Bearer\s+)[A-Za-z0-9._\-]+", re.I), r"\1***"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "***jwt***"),
    (re.compile(r"(\"(?:password|api_secret|access_token|request_token)\"\s*:\s*\")[^\"]*\"", re.I), r'\1***"'),
]


def redact(text: str) -> str:
    for pat, rep in _SECRETS:
        text = pat.sub(rep, text)
    return text


class _Redact(logging.Filter):
    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return True
        record.msg, record.args = redact(msg), None
        return True


class _IST(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        import datetime as dt
        t = dt.datetime.fromtimestamp(record.created, tz=config.IST)
        return t.strftime("%Y-%m-%d %H:%M:%S")


class _Tee:
    """Keeps print() and stderr working as before, and also writes each line to the log."""
    def __init__(self, stream, logger, level):
        self.stream, self.logger, self.level, self.buf = stream, logger, level, ""

    def write(self, data):
        try:
            self.stream.write(data)
        except Exception:
            pass
        self.buf += data
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line.rstrip())
        return len(data)

    def flush(self):
        try:
            self.stream.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self.stream, name)


_done = False
log = logging.getLogger("mjvs")


def setup():
    """Called once when the app starts."""
    global _done
    if _done:
        return
    _done = True
    log.setLevel(logging.INFO)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8")
    except Exception as e:                       # e.g. read-only folder: keep running without a file
        print(f"log file not available: {e!r}")
        return
    fh.setFormatter(_IST(FORMAT))
    fh.addFilter(_Redact())
    fh.setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    # uvicorn and apscheduler keep their own loggers (some do not pass messages up): attach directly
    for name in ("uvicorn", "uvicorn.error", "apscheduler"):
        lg = logging.getLogger(name)
        if fh not in lg.handlers and lg.propagate is False:
            lg.addHandler(fh)
    stdout_log = logging.getLogger("mjvs.print")
    stderr_log = logging.getLogger("mjvs.stderr")
    for lg in (stdout_log, stderr_log):
        lg.propagate = False
        lg.addHandler(fh)
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout, stdout_log, logging.INFO)
    if not isinstance(sys.stderr, _Tee):
        sys.stderr = _Tee(sys.stderr, stderr_log, logging.ERROR)

    def _uncaught(exc_type, exc, tb):
        log.critical("Uncaught error", exc_info=(exc_type, exc, tb))
    sys.excepthook = _uncaught

    import threading
    def _thread_uncaught(args):
        log.critical(f"Uncaught error in thread {args.thread.name if args.thread else ''}",
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = _thread_uncaught
    log.info("MJVS started; log file %s", LOG_FILE)


def tail(lines: int = 500, level: str = "", q: str = "") -> list[str]:
    """Last log entries (newest last), across the rotated files, filtered by level and text.
    A traceback stays with the entry it belongs to."""
    files = [LOG_FILE + f".{i}" for i in range(4, 0, -1)] + [LOG_FILE]
    entries: list[str] = []
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.rstrip("\n")
                    if re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \|", line) or not entries:
                        entries.append(line)
                    else:
                        entries[-1] += "\n" + line            # traceback lines join their entry
        except FileNotFoundError:
            continue
    want = {"ERROR": ("ERROR", "CRITICAL"), "WARNING": ("WARNING", "ERROR", "CRITICAL")}.get(level.upper())
    if want:
        entries = [e for e in entries if any(f"| {w}" in e[:40] for w in want)]
    if q:
        ql = q.lower()
        entries = [e for e in entries if ql in e.lower()]
    return entries[-max(1, min(lines, 5000)):]
