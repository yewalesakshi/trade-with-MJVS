"""Database tables. SQLite locally, Postgres in production (set DATABASE_URL)."""
import datetime as dt

from sqlalchemy import (create_engine, inspect, text, String, Text, Float, Boolean, Date,
                        DateTime, Integer, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from . import config

engine = create_engine(config.DATABASE_URL)


def now_ist():
    """Indian time (IST) without a timezone label: every time in the database is IST.
    Uses the same clock as the scheduler (config.ist_now)."""
    return config.ist_now().replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Member(Base):
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    full_name: Mapped[str] = mapped_column(String, default="")
    mobile: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)   # argon2 hash, never the password
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_ist)
    last_login: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    kite_token: Mapped[str | None] = mapped_column(String, nullable=True)        # encrypted
    kite_token_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)  # IST date of login
    # Legacy single-algo columns from the first version. Unused now (see Subscription), but kept
    # because old databases created them as NOT NULL.
    amount: Mapped[float] = mapped_column(Float, default=0)
    style: Mapped[str] = mapped_column(String, default="")
    drawdown_pct: Mapped[float] = mapped_column(Float, default=10)
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    peak_value: Mapped[float] = mapped_column(Float, default=0)


class Subscription(Base):
    """One member running one algo, with its own money, limit and paper/live mode."""
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("member_id", "algo_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(Integer, index=True)
    algo_id: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float, default=0)
    drawdown_pct: Mapped[float] = mapped_column(Float, default=10)
    max_positions: Mapped[int] = mapped_column(Integer, default=5)     # 0 = no limit (fixed amount per stock)
    per_stock: Mapped[float] = mapped_column(Float, default=0.0)       # money per stock when there is no limit
    last_scan_used: Mapped[str] = mapped_column(String, default="")    # Penny: time of the scan already bought from
    universe: Mapped[str] = mapped_column(String, default="")
    paper: Mapped[bool] = mapped_column(Boolean, default=True)
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    peak_value: Mapped[float] = mapped_column(Float, default=0)
    last_run_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_message: Mapped[str | None] = mapped_column(String, nullable=True)
    last_signal_id: Mapped[int] = mapped_column(Integer, default=0)   # Chartink alerts already handled
    last_suggestion_id: Mapped[int] = mapped_column(Integer, default=0)   # matched suggestions already handled
    state: Mapped[str] = mapped_column(Text, default="")                   # algo's own memory (JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_ist)


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(Integer, index=True)
    algo_id: Mapped[str] = mapped_column(String, default="swing", index=True)
    symbol: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)    # average fill price (LTP for paper/pending)
    order_id: Mapped[str] = mapped_column(String)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_ist)
    mode: Mapped[str] = mapped_column(String, default="live")         # paper | live
    status: Mapped[str] = mapped_column(String, default="COMPLETE")   # COMPLETE PENDING REJECTED PAPER
    reason: Mapped[str] = mapped_column(String, default="")
    # Zerodha GTT (OCO target + stop loss) placed after a live BUY: id, status and trigger prices
    gtt_id: Mapped[str] = mapped_column(String, default="")
    gtt_status: Mapped[str] = mapped_column(String, default="")
    gtt_sl: Mapped[float] = mapped_column(Float, default=0.0)
    gtt_target: Mapped[float] = mapped_column(Float, default=0.0)


class Signal(Base):
    """A stock an algo wants to buy: from a Chartink alert or a test."""
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    algo_id: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String)          # e.g. NSE:SBIN
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String, default="chartink")   # chartink | tradingview | test
    action: Mapped[str] = mapped_column(String, default="BUY")        # BUY | SELL
    note: Mapped[str] = mapped_column(String, default="")
    day: Mapped[dt.date] = mapped_column(Date, index=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_ist)


class Suggestion(Base):
    """A stock that passed BOTH the scanner and the TradingView strategy on the same day."""
    __tablename__ = "suggestions"
    __table_args__ = (UniqueConstraint("algo_id", "symbol", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    algo_id: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String)                  # Kite format, e.g. NSE:SBIN
    day: Mapped[dt.date] = mapped_column(Date, index=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    scanner_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    tradingview_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(String, default="")
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_ist)


class AlgoState(Base):
    """Latest scanner result per algo and universe, shared by all members."""
    __tablename__ = "algo_state"
    key: Mapped[str] = mapped_column(String, primary_key=True)   # "<algo_id>:<universe>"
    scan: Mapped[str] = mapped_column(Text, default="[]")
    scan_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class LoginEvent(Base):
    """Every login and registration attempt, kept for security checks."""
    __tablename__ = "login_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    email: Mapped[str] = mapped_column(String)
    ip: Mapped[str] = mapped_column(String, default="")
    kind: Mapped[str] = mapped_column(String, default="login")     # login | register
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String, default="")
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_ist, index=True)


class AppSetting(Base):
    """Settings changed from the Admin page (e.g. the Kite API key). Secrets are encrypted."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_ist)


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(Integer, index=True)
    rating: Mapped[int] = mapped_column(Integer, default=0)    # no longer asked (kept for old rows)
    message: Mapped[str] = mapped_column(String)
    topic: Mapped[str] = mapped_column(String, default="")      # Suggestion | Problem | Question | Praise
    name: Mapped[str] = mapped_column(String, default="")       # visitors who are not logged in
    contact: Mapped[str] = mapped_column(String, default="")
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=now_ist)


# create_all() never adds columns to existing tables, so older mjvs.db files are patched here.
NEW_COLUMNS = {
    "members": {"kite_token_date": "DATE"},
    "subscriptions": {"last_suggestion_id": "INTEGER DEFAULT 0", "state": "TEXT DEFAULT ''", "per_stock": "FLOAT DEFAULT 0",
                      "last_scan_used": "VARCHAR DEFAULT ''"},
    "signals": {"action": "VARCHAR DEFAULT 'BUY'"},
    "feedback": {"topic": "VARCHAR DEFAULT ''", "name": "VARCHAR DEFAULT ''", "contact": "VARCHAR DEFAULT ''"},
    "trades": {"algo_id": "VARCHAR DEFAULT 'swing'", "mode": "VARCHAR DEFAULT 'live'",
               "status": "VARCHAR DEFAULT 'COMPLETE'", "reason": "VARCHAR DEFAULT ''",
               "gtt_id": "VARCHAR DEFAULT ''", "gtt_status": "VARCHAR DEFAULT ''",
               "gtt_sl": "FLOAT DEFAULT 0", "gtt_target": "FLOAT DEFAULT 0"},
}


# Times were stored in UTC before; now everything is IST. Old rows are moved +5:30 once.
TIME_COLUMNS = {"members": ["created_at", "last_login"], "subscriptions": ["last_run_at", "created_at"],
                "trades": ["at"], "signals": ["at"], "suggestions": ["scanner_at", "tradingview_at", "at"],
                "algo_state": ["scan_at"], "login_events": ["at"], "feedback": ["at"], "app_settings": ["updated_at"]}


def _move_times_to_ist(c):
    done = c.execute(text("SELECT value FROM app_settings WHERE key = 'times_in_ist'")).fetchone()
    if done:
        return
    sqlite = engine.dialect.name == "sqlite"
    for table, cols in TIME_COLUMNS.items():
        for col in cols:
            expr = (f"strftime('%Y-%m-%d %H:%M:%f', {col}, '+330 minutes')" if sqlite
                    else f"{col} + interval '330 minutes'")
            c.execute(text(f"UPDATE {table} SET {col} = {expr} WHERE {col} IS NOT NULL"))
    c.execute(text("INSERT INTO app_settings (key, value, updated_at) VALUES ('times_in_ist', '1', :t)"),
              {"t": now_ist()})


def init_db():
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as c:
        for table, cols in NEW_COLUMNS.items():
            have = {col["name"] for col in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    c.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        _move_times_to_ist(c)


# ---------------------------------------------------------------- backups
def backup_sqlite() -> str | None:
    """Copies a SQLite database into backups/mjvs-YYYY-MM-DD.db (one per day, newest 30 kept).
    Safe while the app is running. Postgres hosts make their own backups, so nothing is done there."""
    import glob
    import os
    import sqlite3
    url = config.DATABASE_URL
    if not url.startswith("sqlite:///"):
        return None
    src = url[len("sqlite:///"):]
    if not os.path.isabs(src):
        src = os.path.join(os.getcwd(), src)
    if not os.path.exists(src):
        return None
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    dest = os.path.join(config.BACKUP_DIR, f"mjvs-{config.ist_today():%Y-%m-%d}.db")
    with sqlite3.connect(src) as a, sqlite3.connect(dest) as b:
        a.backup(b)
    for old in sorted(glob.glob(os.path.join(config.BACKUP_DIR, "mjvs-*.db")))[:-config.BACKUP_KEEP]:
        os.remove(old)
    return dest
