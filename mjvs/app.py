"""MJVS web API. The website (web/) is served from the same address."""
import json
import os
import time
import datetime as dt

import pandas as pd

from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import broker, config, engine as eng, security
from .algos import ALGOS
from .db import engine, init_db, Member, Subscription, Trade, Signal, Suggestion, AlgoState, Feedback, LoginEvent, now_ist
from . import signals as sigmod
from . import settings_store as store
from .security import current_member_id, make_token, read_token, hasher

init_db()
app = FastAPI(title="MJVS")
app.add_middleware(CORSMiddleware, allow_origins=config.FRONTEND_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")


def iso(t):
    """Times go to the browser labelled as Indian time (+05:30)."""
    if not t:
        return None
    if isinstance(t, dt.datetime) and t.tzinfo is None:
        t = t.replace(tzinfo=config.IST)
    return t.isoformat()


def get_algo(algo_id: str):
    algo = ALGOS.get(algo_id)
    if not algo:
        raise HTTPException(404, "No such algo")
    return algo


# ---------------------------------------------------------------- site + public
@app.get("/")
def home():
    return FileResponse(os.path.join(config.WEB_DIR, "index.html"), media_type="text/html")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/config")
def site_config():
    return {"captcha_mode": "turnstile" if config.CAPTCHA_MODE == "turnstile" else "builtin",
            "turnstile_sitekey": config.TURNSTILE_SITEKEY, "allow_live": store.allow_live(),
            "kite_ready": store.kite_ready(),
            "algos": [a.meta() for a in ALGOS.values()]}


# ---------------------------------------------------------------- register / login
class Register(BaseModel):
    full_name: str = Field(min_length=2, max_length=80)
    mobile: str = Field(pattern=r"^[6-9]\d{9}$")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=120)
    password: str = Field(min_length=8, max_length=128)
    captcha: str = Field(max_length=4000)
    captcha_id: str = Field(default="", max_length=64)


class Login(BaseModel):
    email: str = Field(max_length=120)
    password: str = Field(max_length=128)
    captcha: str = Field(max_length=4000)
    captcha_id: str = Field(default="", max_length=64)


def client_ip(request: Request) -> str:
    return (request.client.host if request.client else "")[:64]


def log_event(s: Session, email: str, ip: str, kind: str, ok: bool, member_id=None, note=""):
    s.add(LoginEvent(member_id=member_id, email=email[:120], ip=ip, kind=kind, success=ok, note=note[:120]))
    s.commit()


@app.get("/auth/captcha")
def new_captcha():
    """A fresh picture captcha (built-in mode)."""
    from . import captcha
    return captcha.new()


@app.post("/auth/register")
def register(b: Register, request: Request):
    security.check_captcha(b.captcha, b.captcha_id)
    if len(set(b.password)) < 4:
        raise HTTPException(400, "Please choose a stronger password")
    email, ip = b.email.lower().strip(), client_ip(request)
    with Session(engine) as s:
        if s.query(Member).filter((Member.email == email) | (Member.mobile == b.mobile)).first():
            log_event(s, email, ip, "register", False, note="already exists")
            raise HTTPException(409, "An account with this email or mobile already exists")
        m = Member(email=email, mobile=b.mobile, full_name=b.full_name.strip(),
                   password_hash=hasher.hash(b.password), last_login=now_ist())
        s.add(m)
        s.commit()
        log_event(s, email, ip, "register", True, m.id)
        return {"token": make_token(m.id)}


@app.post("/auth/login")
def login(b: Login, request: Request):
    email, ip = b.email.lower().strip(), client_ip(request)
    security.check_not_locked(email, ip)
    security.check_captcha(b.captcha, b.captcha_id)
    with Session(engine) as s:
        m = s.query(Member).filter_by(email=email).first()
        try:
            if not m:
                raise VerifyMismatchError()
            hasher.verify(m.password_hash, b.password)
        except VerifyMismatchError:
            security.record_failure(email, ip)
            log_event(s, email, ip, "login", False, m.id if m else None, "wrong password" if m else "unknown email")
            raise HTTPException(401, "Wrong email or password")
        security.clear_failures(email)
        if hasher.check_needs_rehash(m.password_hash):
            m.password_hash = hasher.hash(b.password)
        m.last_login = now_ist()
        s.commit()
        log_event(s, email, ip, "login", True, m.id)
        return {"token": make_token(m.id)}


# ---------------------------------------------------------------- profile + feedback
class Profile(BaseModel):
    full_name: str = Field(min_length=2, max_length=80)
    mobile: str = Field(pattern=r"^[6-9]\d{9}$")


@app.get("/me")
def get_me(mid: int = Depends(current_member_id)):
    with Session(engine) as s:
        m = s.get(Member, mid)
        if not m:
            raise HTTPException(401, "Please log in again")
        return {"full_name": m.full_name, "email": m.email, "mobile": m.mobile,
                "connected": bool(m.kite_token), "kite_fresh": eng.token_fresh(m),
                "is_admin": store.is_admin(s, m),
                "member_since": iso(m.created_at), "last_login": iso(m.last_login)}


@app.put("/me")
def update_me(b: Profile, mid: int = Depends(current_member_id)):
    with Session(engine) as s:
        if s.query(Member).filter(Member.mobile == b.mobile, Member.id != mid).first():
            raise HTTPException(409, "That mobile number is already in use")
        m = s.get(Member, mid)
        m.full_name, m.mobile = b.full_name.strip(), b.mobile
        s.commit()
    return {"ok": True}


TOPICS = ("Suggestion", "Problem", "Question", "Praise")


class FeedbackIn(BaseModel):
    topic: str = "Suggestion"
    message: str = Field(min_length=3, max_length=1000)


class PublicFeedbackIn(FeedbackIn):
    name: str = Field(default="", max_length=80)
    contact: str = Field(default="", max_length=120)     # email or mobile, optional
    captcha: str = Field(max_length=4000)
    captcha_id: str = Field(default="", max_length=64)


def clean_topic(t: str) -> str:
    return t if t in TOPICS else "Suggestion"


@app.post("/feedback")
def send_feedback(b: FeedbackIn, mid: int = Depends(current_member_id)):
    with Session(engine) as s:
        m = s.get(Member, mid)
        s.add(Feedback(member_id=mid, rating=0, topic=clean_topic(b.topic), message=b.message.strip(),
                       name=m.full_name if m else "", contact=m.email if m else ""))
        s.commit()
    return {"ok": True}


@app.post("/feedback/public")
def send_public_feedback(b: PublicFeedbackIn):
    """Feedback from the home page; visitors need not be logged in, so a captcha is required."""
    security.check_captcha(b.captcha, b.captcha_id)
    with Session(engine) as s:
        s.add(Feedback(member_id=0, rating=0, topic=clean_topic(b.topic), message=b.message.strip(),
                       name=b.name.strip(), contact=b.contact.strip()))
        s.commit()
    return {"ok": True}


# ---------------------------------------------------------------- Kite connection
# Browser redirects cannot send headers, so a short-lived link token carries the member id.
@app.post("/kite/link")
def kite_link(mid: int = Depends(current_member_id)):
    if not store.kite_ready():
        with Session(engine) as s:
            admin = store.is_admin(s, s.get(Member, mid))
        raise HTTPException(400, "Finish the one-time Kite setup on the Admin page first." if admin else
                                 "Zerodha connection is not switched on yet by MJVS. Please try again later.")
    return {"url": f"{config.BACKEND_URL}/kite/login?t={make_token(mid, 5, 'kite')}"}


def back_to_site(result: str, msg: str = "") -> RedirectResponse:
    from urllib.parse import quote
    return RedirectResponse(config.FRONTEND_ORIGINS[0] + f"/#/app/connect?kite={result}" + (f"&msg={quote(msg)}" if msg else ""))


@app.get("/kite/login")
def kite_login(t: str):
    mid = read_token(t, "kite")
    return RedirectResponse(broker.client().login_url() + f"&redirect_params=t%3D{make_token(mid, 10, 'kite')}")


@app.get("/kite/callback")
def kite_callback(t: str = "", request_token: str = "", status: str = "success"):
    """Zerodha sends the member back here after logging in on its own page."""
    try:
        mid = read_token(t, "kite")
    except HTTPException:
        return back_to_site("error", "The connection link expired. Please press Connect Zerodha again.")
    if status != "success" or not request_token:
        return back_to_site("cancelled")
    try:
        data = broker.client().generate_session(request_token, api_secret=store.kite_api_secret())
    except Exception as e:
        print(f"kite callback error: {e!r}")
        return back_to_site("error", "Zerodha did not accept the login. Please try again. If it keeps "
                                     "failing, the API secret on the Admin page may be wrong.")
    with Session(engine) as s:
        m = s.get(Member, mid)
        m.kite_token = security.encrypt(data["access_token"])
        m.kite_token_date = config.ist_today()
        for sub in s.query(Subscription).filter_by(member_id=mid, running=True).all():
            if sub.last_message and sub.last_message.startswith(("Waiting for", "Kite login expired")):
                sub.last_message = "Kite connected. The algo runs at its next check."
        s.commit()
    return back_to_site("ok")


def need_fresh_kite(m: Member):
    if not m.kite_token:
        raise HTTPException(400, "Connect Kite first")
    if not eng.token_fresh(m):
        raise HTTPException(400, "Your Kite login has expired. Kite logins last one day, so connect Kite again.")


# ---------------------------------------------------------------- member dashboard
def sub_view(s, sub: Subscription, prices: dict) -> dict:
    cash, held = eng.positions(s, sub)
    pos = []
    for sym, p in held.items():
        row = {"symbol": sym, "qty": p.qty, "avg": round(p.avg, 2), "ltp": prices.get(sym),
               "pnl": round((prices[sym] - p.avg) * p.qty, 2) if sym in prices else None,
               "since": iso(p.entry_at), "gtt": None}
        if not sub.paper:
            t = eng.opening_buy(s, sub, sym)
            if t and t.gtt_id:
                row["gtt"] = {"id": t.gtt_id, "status": t.gtt_status, "sl": t.gtt_sl, "target": t.gtt_target}
        pos.append(row)
    value = eng.account_value(cash, held, prices)
    if getattr(ALGOS.get(sub.algo_id), "group", "") == "fno":
        cash = value          # futures: money = amount + profit/loss (no shares bought with cash)
    return {"algo_id": sub.algo_id, "amount": sub.amount, "drawdown_pct": sub.drawdown_pct,
            "max_positions": sub.max_positions, "universe": sub.universe, "paper": sub.paper,
            "running": sub.running, "peak": round(sub.peak_value or 0, 2), "cash": round(cash, 2),
            "value": round(value, 2), "pnl": round(value - sub.amount, 2),
            "last_run_at": iso(sub.last_run_at), "last_message": sub.last_message, "positions": pos}


@app.get("/dashboard")
def dashboard(mid: int = Depends(current_member_id)):
    with Session(engine) as s:
        m = s.get(Member, mid)
        if not m:
            raise HTTPException(401, "Please log in again")
        subs = s.query(Subscription).filter_by(member_id=mid).all()
        held = set()
        for sub in subs:
            held |= set(eng.positions(s, sub)[1])
        prices = {}
        if held and eng.token_fresh(m):
            try:
                prices = broker.ltp_many(broker.client(m.kite_token), held)
            except Exception:
                prices = {}
        trades = s.query(Trade).filter_by(member_id=mid).order_by(Trade.id.desc()).limit(200).all()
        return {"kite": {"connected": bool(m.kite_token), "fresh": eng.token_fresh(m)},
                "allow_live": store.allow_live(), "is_admin": store.is_admin(s, m), "kite_ready": store.kite_ready(),
                "full_name": m.full_name,
                "subs": [sub_view(s, sub, prices) for sub in subs],
                "trades": [{"algo_id": t.algo_id, "symbol": t.symbol, "side": t.side, "qty": t.qty,
                            "price": t.price, "mode": t.mode, "status": t.status, "reason": t.reason,
                            "at": iso(t.at)} for t in trades]}


class Settings(BaseModel):
    amount: float = Field(gt=0)
    drawdown_pct: float = Field(ge=5, le=15)
    max_positions: int = Field(default=5, ge=1, le=20)
    universe: str = ""
    paper: bool = True


@app.post("/algos/{algo_id}/start")
def algo_start(algo_id: str, b: Settings, mid: int = Depends(current_member_id)):
    algo = get_algo(algo_id)
    if not algo.ready:
        raise HTTPException(400, f"{algo.name} is not ready yet: its strategy is still being added.")
    if not algo.auto_trade:
        raise HTTPException(400, f"{algo.name} only suggests stocks (scanner + TradingView). See the Suggestions page.")
    if algo.min_amount and b.amount < algo.min_amount:
        raise HTTPException(400, f"{algo.name} needs at least Rs {algo.min_amount:,.0f}")
    if b.drawdown_pct > algo.max_drawdown:
        raise HTTPException(400, f"{algo.name} allows a risk (drawdown limit) of at most {algo.max_drawdown:g}%")
    universe = b.universe or algo.default_universe
    if algo.universes and universe not in algo.universes:
        raise HTTPException(400, "Pick what to trade from the list")
    if not b.paper and not store.allow_live():
        raise HTTPException(400, "Live trading is switched off. The admin can switch it on: Admin page -> Live trading.")
    warning = ""
    with Session(engine) as s:
        m = s.get(Member, mid)
        if not m.kite_token:
            raise HTTPException(400, "Connect Kite first")
        # Money check against the member's Zerodha account: Live is refused, Paper only warned.
        cash_now = kite_cash(s, m)
        if cash_now is not None and cash_now < b.amount:
            msg = (f"Amount is less in your Zerodha account: available Rs {cash_now:,.0f}, "
                   f"but you entered Rs {b.amount:,.0f}.")
            if not b.paper:
                raise HTTPException(400, msg + " Lower the amount or add money in Kite.")
            warning = msg + " Paper mode started anyway (no real money)."
        sub = s.query(Subscription).filter_by(member_id=mid, algo_id=algo_id).first()
        if not sub:
            sub = Subscription(member_id=mid, algo_id=algo_id, last_signal_id=0)
            s.add(sub)
        sub.amount, sub.drawdown_pct, sub.paper, sub.universe = b.amount, b.drawdown_pct, b.paper, universe
        sub.max_positions = b.max_positions
        # Drawdown counts from today's value, so past losses do not re-trigger the guard at once.
        cash, held = eng.positions(s, sub)
        start_value = cash + sum(p.cost for p in held.values())
        if start_value <= 0:
            raise HTTPException(400, "This algo account has no money left. Raise the amount"
                                     + (" or clear paper trades." if sub.paper else "."))
        # Chartink alerts that arrived before starting are not acted on.
        latest = s.query(Signal.id).filter_by(algo_id=algo_id).order_by(Signal.id.desc()).first()
        sub.last_signal_id = latest[0] if latest else 0
        sub.running, sub.peak_value, sub.last_run_date = True, start_value, None
        sub.state = ""
        sub.last_run_at = None        # run at the very next check
        sub.last_message = ("Started in " + ("paper mode: no real orders. " if sub.paper else "LIVE mode: real orders. ")
                            + ("Runs once a day" if algo.once_per_day else f"Checks every {algo.run_every} min")
                            + f" between {algo.window[0]:%H:%M} and {algo.window[1]:%H:%M} on market days.")
        s.commit()
    return {"running": True, "warning": warning}


def kite_cash(s: Session, m: Member) -> float | None:
    """Available cash in Zerodha, or None when it cannot be read (the check is then skipped)."""
    if not m.kite_token or not eng.token_fresh(m):
        return None
    try:
        return broker.available_cash(broker.client(m.kite_token))
    except broker.TokenError:
        return None
    except Exception:
        return None


@app.get("/kite/funds")
def kite_funds(mid: int = Depends(current_member_id)):
    with Session(engine) as s:
        return {"cash": kite_cash(s, s.get(Member, mid))}


@app.post("/positions/sync")
def positions_sync(mid: int = Depends(current_member_id)):
    """'Sync with Zerodha' button: every live algo of this member is checked against the real account."""
    out = []
    with Session(engine) as s:
        m = s.get(Member, mid)
        if not eng.token_fresh(m):
            raise HTTPException(400, "Connect Kite first")
        for sub in s.query(Subscription).filter_by(member_id=mid, paper=False).all():
            try:
                msg = eng.sync_with_account(s, sub)
            except broker.TokenError:
                raise HTTPException(400, "Your Kite login has expired. Connect Kite again.")
            except Exception as e:
                msg = f"could not check ({str(e)[:80]})"
            if msg:
                out.append(f"{getattr(ALGOS.get(sub.algo_id), 'name', sub.algo_id)}: {msg}")
    return {"message": " | ".join(out) or "No live algo to check."}


@app.post("/algos/{algo_id}/stop")
def algo_stop(algo_id: str, mid: int = Depends(current_member_id)):
    with Session(engine) as s:
        sub = s.query(Subscription).filter_by(member_id=mid, algo_id=algo_id).first()
        if sub:
            sub.running = False
            sub.last_message = "Stopped by you. Open positions are kept; sell them in Kite if you want out."
            s.commit()
    return {"running": False}


@app.post("/algos/{algo_id}/run-now")
def algo_run_now(algo_id: str, mid: int = Depends(current_member_id)):
    get_algo(algo_id)
    with Session(engine) as s:
        sub = s.query(Subscription).filter_by(member_id=mid, algo_id=algo_id).first()
        if not sub or not sub.running:
            raise HTTPException(400, "Start the algo first")
        if not sub.paper:
            raise HTTPException(400, "Run now is only for paper mode. Live runs follow the schedule.")
        need_fresh_kite(s.get(Member, mid))
        eng.run_now(s, sub)
        return {"message": sub.last_message}


@app.post("/algos/{algo_id}/paper-reset")
def paper_reset(algo_id: str, mid: int = Depends(current_member_id)):
    with Session(engine) as s:
        s.query(Trade).filter_by(member_id=mid, algo_id=algo_id, mode="paper").delete()
        sub = s.query(Subscription).filter_by(member_id=mid, algo_id=algo_id).first()
        if sub:
            sub.peak_value = sub.amount
        s.commit()
    return {"ok": True}


class ScanIn(BaseModel):
    universe: str = ""


@app.post("/algos/{algo_id}/scan")
def algo_scan(algo_id: str, b: ScanIn, mid: int = Depends(current_member_id)):
    algo = get_algo(algo_id)
    if algo.source != "scan" or not algo.ready:
        raise HTTPException(400, "This algo gets its stocks from Chartink alerts, not its own scanner.")
    universe = b.universe or algo.default_universe
    if universe not in algo.universes:
        raise HTTPException(400, "Unknown list")
    key = f"{algo_id}:{universe}"
    with Session(engine) as s:
        m = s.get(Member, mid)
        need_fresh_kite(m)
        enc = m.kite_token
    with _jobs_lock:
        if _scan_jobs.get(key, {}).get("running"):
            return {"started": False, "job": _scan_jobs[key]}
        _scan_jobs[key] = {"running": True, "done": 0, "total": 0, "step": "Getting the stock list from Kite", "error": "", "note": ""}
    threading.Thread(target=_run_scan_job, args=(algo, universe, key, enc, mid), daemon=True).start()
    return {"started": True, "job": _scan_jobs[key]}


# Big lists (e.g. all NSE stocks under Rs 100) take minutes: Kite allows ~3 chart downloads a second.
# So "Scan now" runs in the background and the page polls its progress.
import threading
_scan_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _run_scan_job(algo, universe: str, key: str, enc_token: str, mid: int):
    job = _scan_jobs[key]
    try:
        k = broker.client(enc_token)
        symbols = eng.algo_symbols(algo, universe, k)
        job.update(step="Checking each stock with the strategy", total=len(symbols))
        rows = eng.scan(algo, k, symbols, config.ist_now(), progress=lambda n, t: job.update(done=n, total=t))
        with Session(engine) as s:
            eng.save_scan(s, algo.id, universe, rows)
        note = ""
        if algo.manual_scan and algo.auto_trade:
            job.update(step="Placing orders for running algos")
            note = eng.run_after_scan(algo, universe, rows)
        job.update(done=len(symbols), step="Done", note=note)
    except broker.TokenError:
        with Session(engine) as s:
            m = s.get(Member, mid)
            m.kite_token = None
            s.commit()
        job["error"] = "Your Kite login has expired. Connect Kite again."
    except broker.PermissionError_:
        job["error"] = broker.NO_MARKET_DATA
    except Exception as e:
        print(f"scan job {key} failed: {e!r}")
        job["error"] = f"Scan failed: {str(e)[:150]}"
    finally:
        job["running"] = False


@app.get("/algos/{algo_id}/signals")
def algo_signals(algo_id: str, universe: str = "", mid: int = Depends(current_member_id)):
    algo = get_algo(algo_id)
    with Session(engine) as s:
        st = s.get(AlgoState, f"{algo_id}:{universe or algo.default_universe}")
        alerts = s.query(Signal).filter_by(algo_id=algo_id).order_by(Signal.id.desc()).limit(100).all()
        return {"scan": json.loads(st.scan) if st else [], "scan_at": iso(st.scan_at) if st else None,
                "scan_info": scan_info(algo, st.scan_at if st else None),
                "job": _scan_jobs.get(f"{algo_id}:{universe or algo.default_universe}"),
                "scan_time": store.scan_time(), "daily_scan_last": eng._sched_scan.get("last", ""),
                "alerts": [{"symbol": a.symbol, "price": a.price, "source": a.source, "action": a.action,
                            "note": a.note, "at": iso(a.at)} for a in alerts],
                "suggestions": [suggestion_view(x) for x in s.query(Suggestion).filter_by(algo_id=algo_id)
                                .order_by(Suggestion.id.desc()).limit(50)]}


@app.get("/algos/futures/chart")
def futures_chart(mid: int = Depends(current_member_id)):
    """1-hour chart of the NIFTY future with the strategy's lines, BUY / SELL signals and this
    member's NIFTY Future swing trades. Uses completed candles only, like the algo itself."""
    from .algos import rules
    algo = get_algo("futures")
    now = config.ist_now()
    with Session(engine) as s:
        m, k = member_kite(s, mid)

        def load():
            con = algo.contract(k, now.date())
            if not con:
                raise HTTPException(400, "NIFTY future contract not found in Kite's instrument list.")
            full = f"NFO:{con['symbol']}"
            quote = k.ltp([full]).get(full) or {}
            token = quote.get("instrument_token") or con.get("token")
            df = broker.history(k, token, algo.interval, CHART_CANDLES + rules.WARMUP, now)
            return con, quote.get("last_price"), df
        con, ltp, df = kite_call(s, m, load)
        trades = (s.query(Trade).filter(Trade.member_id == mid, Trade.algo_id == "futures",
                                        Trade.status != "REJECTED").order_by(Trade.at).all())
    if df is None or df.empty:
        raise HTTPException(400, "Kite sent no 1-hour candles for the NIFTY future yet.")
    df = rules.add_indicators(df)
    c = df["close"].astype(float)
    basis = c.rolling(rules.BB_LENGTH).mean()
    dev = rules.BB_SD * c.rolling(rules.BB_LENGTH).std(ddof=0)
    df["bbu"], df["bbl"] = basis + dev, basis - dev
    stamps = pd.Series(pd.to_datetime(df.index), index=df.index)
    if stamps.dt.tz is not None:
        stamps = stamps.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    # Chart times are Indian time written as if UTC, so the chart shows IST clock times.
    df["t"] = ((stamps - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).astype("int64")
    df = df.tail(CHART_CANDLES)
    start = int(df["t"].iloc[0])

    def num(v):
        return None if pd.isna(v) else round(float(v), 2)

    def line(col):
        return [{"time": int(t), "value": num(v)} for t, v in zip(df["t"], df[col]) if not pd.isna(v)]

    # Signals in the algo's order: BUY opens a long; while long, the first exit condition is SELL
    # (long closed, short opened); while short, the next BUY covers and buys again.
    signals, side = [], None
    for r in df.itertuples():
        if r.buy_signal and side != "long":
            signals.append({"time": int(r.t), "type": "BUY", "price": num(r.close)}); side = "long"
        elif r.exit_ok and side == "long":
            signals.append({"time": int(r.t), "type": "SELL", "price": num(r.close)}); side = "short"
    tr = []
    for t in trades:
        ts = int((pd.Timestamp(t.at.replace(tzinfo=None)) - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1))
        if ts >= start:
            # put the marker on the 1-hour candle the trade happened in
            bar = int(df["t"][df["t"] <= ts].max()) if (df["t"] <= ts).any() else start
            tr.append({"time": bar, "side": t.side, "qty": t.qty, "price": t.price, "mode": t.mode,
                       "reason": t.reason, "at": iso(t.at)})
    last = df.iloc[-1]
    return {"symbol": con["symbol"], "expiry": con.get("expiry"), "ltp": ltp, "interval": "1 hour",
            "candles": [{"time": int(r.t), "open": num(r.open), "high": num(r.high), "low": num(r.low),
                         "close": num(r.close)} for r in df.itertuples()],
            "ma": line("ma"), "bbu": line("bbu"), "bbl": line("bbl"), "rsi": line("rsi"), "pctb": line("pctb"),
            "signals": signals, "trades": tr,
            "last": {"time": iso(stamps.iloc[-1].to_pydatetime()), "close": num(last["close"]), "ma": num(last["ma"]),
                     "rsi": num(last["rsi"]), "pctb": num(last["pctb"]), "trend": str(last["trend"]),
                     "buy_ok": bool(last["buy_ok"]), "exit_ok": bool(last["exit_ok"])},
            "levels": {"rsi_buy": rules.RSI_BUY, "rsi_exit": rules.RSI_EXIT,
                       "pctb_buy": rules.PCTB_BUY, "pctb_exit": rules.PCTB_EXIT}}


CHART_CANDLES = 300          # about 2 months of 1-hour candles


def scan_info(algo, scan_at) -> dict | None:
    """Plain facts for the page: when the scan ran, which day's closing candles it used, which day
    its BUY list is for, and whether it is still the current scan."""
    if not scan_at or algo.interval != "day":
        return None
    at = eng.to_ist(scan_at)
    used = broker.data_day(at)                       # last complete daily candle in this scan
    now = config.ist_now()
    after_close = at.weekday() < 5 and at.time() >= broker.MARKET_CLOSE
    trade = at.date() if not after_close else at.date() + dt.timedelta(days=1)
    while trade.weekday() >= 5:
        trade += dt.timedelta(days=1)
    return {"ran_at": iso(at), "candles_up_to": used.isoformat(), "for_day": trade.isoformat(),
            "current": used == broker.data_day(now), "today": at.date() == now.date(),
            "after_close": after_close}


def suggestion_view(x: Suggestion, ltp=None) -> dict:
    return {"id": x.id, "algo_id": x.algo_id, "symbol": x.symbol, "day": x.day.isoformat(), "price": x.price,
            "ltp": ltp, "scanner_at": iso(x.scanner_at), "tradingview_at": iso(x.tradingview_at),
            "note": x.note, "at": iso(x.at)}


@app.get("/suggestions")
def suggestions(days: int = 7, mid: int = Depends(current_member_id)):
    """Stocks that passed both the scanner and the TradingView strategy, newest first."""
    since = config.ist_today() - dt.timedelta(days=max(0, min(days, 90)))
    with Session(engine) as s:
        rows = s.query(Suggestion).filter(Suggestion.day >= since).order_by(Suggestion.id.desc()).limit(300).all()
        m = s.get(Member, mid)
        prices = {}
        today = [x.symbol for x in rows if x.day == config.ist_today()]
        if today and eng.token_fresh(m):
            try:
                prices = broker.ltp_many(broker.client(m.kite_token), set(today))
            except Exception:
                prices = {}
        return {"today": config.ist_today().isoformat(),
                "algos": [a.id for a in ALGOS.values() if a.ready and (a.require_tradingview or a.suggest)],
                "tradingview": [a.id for a in ALGOS.values() if a.require_tradingview],
                "rows": [suggestion_view(x, prices.get(x.symbol)) for x in rows]}


import csv
import io
from fastapi.responses import StreamingResponse


def csv_response(name: str, header: list[str], rows) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


TRADE_COLS = ["id", "member_id", "algo_id", "symbol", "side", "qty", "price", "mode", "status", "reason", "order_id", "at_ist"]


def trade_row(t: Trade):
    return [t.id, t.member_id, t.algo_id, t.symbol, t.side, t.qty, t.price, t.mode, t.status, t.reason, t.order_id, iso(t.at)]


@app.get("/trades.csv")
def my_trades_csv(mid: int = Depends(current_member_id)):
    with Session(engine) as s:
        rows = [trade_row(t) for t in s.query(Trade).filter_by(member_id=mid).order_by(Trade.id).all()]
    return csv_response(f"mjvs-trades-{config.ist_today()}.csv", TRADE_COLS, rows)


# ---------------------------------------------------------------- Chartink webhook
@app.post("/webhook/chartink/{algo_id}")
async def chartink_webhook(algo_id: str, request: Request, key: str = ""):
    """Chartink alert -> stocks to buy. URL: /webhook/chartink/<algo_id>?key=<CHARTINK_KEY>"""
    if not config.CHARTINK_KEY:
        raise HTTPException(503, "Chartink webhooks are not configured (set CHARTINK_KEY)")
    if key != config.CHARTINK_KEY:
        raise HTTPException(403, "Wrong key")
    algo = get_algo(algo_id)
    try:
        body = await request.json()
    except Exception:
        body = dict(await request.form())
    note = str(body.get("scan_name") or body.get("alert_name") or "")
    with Session(engine) as s:
        added = sigmod.save_signals(s, algo.id, str(body.get("stocks", "")).split(","),
                                    str(body.get("trigger_prices", "")).split(","), note, "chartink")
    return {"ok": True, "added": added}


@app.post("/webhook/tradingview/{algo_id}")
async def tradingview_webhook(algo_id: str, request: Request, key: str = ""):
    """TradingView strategy alert. URL: /webhook/tradingview/<algo_id>?key=<CHARTINK_KEY>
    Alert message (recommended): {"symbol": "{{ticker}}", "exchange": "{{exchange}}", "price": {{close}}, "action": "BUY"}"""
    if not config.CHARTINK_KEY:
        raise HTTPException(503, "Webhooks are not configured (set CHARTINK_KEY)")
    if key != config.CHARTINK_KEY:
        raise HTTPException(403, "Wrong key")
    algo = get_algo(algo_id)
    items = sigmod.parse_tradingview(await request.body())
    if not items:
        raise HTTPException(400, "No symbol found in the alert message")
    added = 0
    with Session(engine) as s:
        for it in items[:200]:
            added += sigmod.save_signals(s, algo.id, [it["symbol"]], [it["price"]], it["note"], "tradingview", it["action"])
        matched = s.query(Suggestion).filter_by(algo_id=algo.id, day=config.ist_today()).count()
    return {"ok": True, "added": added, "suggestions_today": matched}


# ---------------------------------------------------------------- disconnect Kite
@app.post("/kite/disconnect")
def kite_disconnect(mid: int = Depends(current_member_id)):
    """Logs MJVS out of Zerodha now. Running algos wait until the member connects again."""
    with Session(engine) as s:
        m = s.get(Member, mid)
        if m.kite_token:
            try:
                broker.client(m.kite_token).invalidate_access_token()
            except Exception as e:      # token may already be expired; we forget it either way
                print(f"kite logout: {e!r}")
        m.kite_token, m.kite_token_date = None, None
        for sub in s.query(Subscription).filter_by(member_id=mid, running=True).all():
            sub.last_message = "Kite disconnected by you. The algo waits until you connect Zerodha again."
        s.commit()
    return {"ok": True}


# ---------------------------------------------------------------- manual trading (Trade page)
from .algos import universe as uni_mod


def member_kite(s: Session, mid: int):
    m = s.get(Member, mid)
    need_fresh_kite(m)
    return m, broker.client(m.kite_token)


def kite_call(s: Session, m: Member, fn):
    try:
        return fn()
    except broker.TokenError:
        m.kite_token = None
        s.commit()
        raise HTTPException(400, "Your Kite login has expired. Connect Kite again.")
    except broker.PermissionError_:
        raise HTTPException(400, broker.NO_MARKET_DATA)


@app.get("/market/search")
def market_search(q: str, mid: int = Depends(current_member_id)):
    if len(q.strip()) < 2:
        return {"results": []}
    with Session(engine) as s:
        m, k = member_kite(s, mid)
        return {"results": kite_call(s, m, lambda: uni_mod.search(k, q[:60]))}


@app.get("/market/quote")
def market_quote(symbol: str, mid: int = Depends(current_member_id)):
    with Session(engine) as s:
        m, k = member_kite(s, mid)
        q = kite_call(s, m, lambda: k.quote([symbol])).get(symbol)
        if not q:
            raise HTTPException(404, "No price for this symbol")
        ohlc = q.get("ohlc") or {}
        depth = q.get("depth") or {}
        bid = (depth.get("buy") or [{}])[0].get("price")
        ask = (depth.get("sell") or [{}])[0].get("price")
        last, prev = q.get("last_price"), ohlc.get("close")
        return {"symbol": symbol, "ltp": last, "open": ohlc.get("open"), "high": ohlc.get("high"),
                "low": ohlc.get("low"), "prev_close": prev, "bid": bid or None, "ask": ask or None,
                "change_pct": round((last - prev) / prev * 100, 2) if last and prev else None,
                "volume": q.get("volume"), "oi": q.get("oi")}


class ManualOrder(BaseModel):
    symbol: str = Field(max_length=60)              # e.g. NSE:SBIN or NFO:NIFTY25NOV24500CE
    side: str = Field(pattern="^(BUY|SELL)$")
    lots: int = Field(ge=1, le=100000)              # shares for stocks, lots for futures/options
    order_type: str = Field(default="MARKET", pattern="^(MARKET|LIMIT)$")
    price: float | None = Field(default=None, gt=0)
    product: str = Field(default="CNC", pattern="^(CNC|MIS|NRML)$")
    paper: bool = True
    gtt: bool = False                                # LIVE CNC buy: also create a GTT (target + stop loss)
    target_pct: float = Field(default=8, ge=0.5, le=100)
    sl_pct: float = Field(default=5, ge=0.5, le=50)


@app.post("/orders/manual")
def manual_order(b: ManualOrder, mid: int = Depends(current_member_id)):
    if not b.paper and not store.allow_live():
        raise HTTPException(400, "Live trading is switched off. The admin can switch it on: Admin page -> Live trading.")
    if b.order_type == "LIMIT" and not b.price:
        raise HTTPException(400, "Enter a limit price")
    with Session(engine) as s:
        m, k = member_kite(s, mid)
        ins = kite_call(s, m, lambda: uni_mod.find_instrument(k, b.symbol))
        if not ins:
            raise HTTPException(404, "Symbol not found. Search again and pick it from the list.")
        is_fo = ins["exchange"] == "NFO"
        if (is_fo and b.product == "CNC") or (not is_fo and b.product == "NRML"):
            raise HTTPException(400, "Use NRML or MIS for futures and options, CNC or MIS for shares")
        qty = b.lots * ins["lot"]
        price = round(round(b.price / ins["tick"]) * ins["tick"], 2) if b.price else None
        full = f'{ins["exchange"]}:{ins["symbol"]}'
        try:
            ltp = broker.ltp_many(k, [full]).get(full)
        except broker.PermissionError_:
            ltp = None        # free "Personal" Kite plan: no prices, but live orders still work
        note = f'manual {b.order_type.lower()} {b.product}' + (f' @ {price}' if price else "")
        if b.paper:
            if not ltp:
                raise HTTPException(400, "Paper mode needs the live price to simulate a fill, and your Kite plan "
                                         "has no market data. Switch to Live to place a real order in Zerodha.")
            if b.order_type == "LIMIT" and ((b.side == "BUY" and ltp > price) or (b.side == "SELL" and ltp < price)):
                raise HTTPException(400, f"Paper mode fills a limit order only when it can fill now (price {ltp}).")
            fill = price if b.order_type == "LIMIT" else ltp
            t = Trade(member_id=mid, algo_id="manual", symbol=full, side=b.side, qty=qty, price=fill, mode="paper",
                      status="PAPER", reason=note, order_id=f"PAPER-{int(time.time() * 1000)}")
            s.add(t)
            s.commit()
            return {"ok": True, "message": f"Paper {b.side} {qty} {ins['symbol']} at {fill:.2f}"}
        try:
            order_id = broker.send_manual_order(k, ins["exchange"], ins["symbol"], b.side, qty, b.product, b.order_type, price)
        except broker.TokenError:
            m.kite_token = None
            s.commit()
            raise HTTPException(400, "Your Kite login has expired. Connect Kite again.")
        except broker.PermissionError_ as e:
            raise HTTPException(400, broker.order_refused(e))
        except Exception as e:
            raise HTTPException(400, f"Zerodha refused the order: {str(e)[:200]}")
        st, avg, filled, msg = broker.wait_for_fill(k, order_id, tries=3)
        status = "COMPLETE" if st == "COMPLETE" else "REJECTED" if st in ("REJECTED", "CANCELLED") and not filled else "PENDING"
        t = Trade(member_id=mid, algo_id="manual", symbol=full, side=b.side, qty=filled or qty,
                  price=avg or price or ltp or 0, mode="live", status=status,
                  reason=(msg if status == "REJECTED" else note)[:200], order_id=order_id)
        s.add(t)
        s.commit()
        if status == "REJECTED":
            raise HTTPException(400, f"Zerodha rejected the order: {msg or st}")
        gtt_msg = ""
        if b.gtt and b.side == "BUY" and b.product == "CNC":
            if status == "COMPLETE" and avg:
                sl, tg = avg * (1 - b.sl_pct / 100), avg * (1 + b.target_pct / 100)
                try:
                    t.gtt_id = broker.place_gtt_oco(k, full, filled or qty, sl, tg, ltp or avg, "CNC")
                    t.gtt_status, t.gtt_sl, t.gtt_target = "active", broker.tick_round(sl), broker.tick_round(tg)
                    gtt_msg = f" GTT created in Zerodha: target {t.gtt_target:.2f}, stop loss {t.gtt_sl:.2f}."
                except Exception as e:
                    t.gtt_status = "error"
                    gtt_msg = f" GTT NOT created ({str(e)[:100]}). Add it in Kite: Orders -> GTT."
                s.commit()
            else:
                gtt_msg = " The order has not filled yet, so no GTT was created: add it in Kite (Orders -> GTT) once it fills."
        return {"ok": True, "order_id": order_id,
                "message": (f"Done: {b.side} {filled or qty} {ins['symbol']} at {avg:.2f}." if status == "COMPLETE"
                            else f"Order placed (id {order_id}). Status: {st}. See Your Zerodha account below.") + gtt_msg}


def _src(tag: str | None) -> str:
    return {"mjvs": "MJVS algo", "mjvsman": "MJVS manual"}.get(tag or "", "Kite / Streak / other app")


@app.get("/kite/account")
def kite_account(mid: int = Depends(current_member_id)):
    """Everything in the member's Zerodha account today, from every app (Kite, Streak, MJVS ...)."""
    with Session(engine) as s:
        m, k = member_kite(s, mid)
        orders = kite_call(s, m, k.orders) or []
        pos = (kite_call(s, m, k.positions) or {}).get("net", [])
        hold = kite_call(s, m, k.holdings) or []
        try:
            gtts = k.get_gtts() or []
        except Exception:
            gtts = []
    return {
        "gtts": [{"id": g.get("id"), "status": g.get("status"), "type": g.get("type"),
                  "symbol": f'{(g.get("condition") or {}).get("exchange")}:{(g.get("condition") or {}).get("tradingsymbol")}',
                  "triggers": (g.get("condition") or {}).get("trigger_values") or [],
                  "qty": ((g.get("orders") or [{}])[0]).get("quantity"),
                  "side": ((g.get("orders") or [{}])[0]).get("transaction_type"),
                  "created": str(g.get("created_at") or "")} for g in gtts
                 if g.get("status") in ("active", "triggered")],
        "orders": [{"id": o.get("order_id"), "time": str(o.get("order_timestamp") or ""),
                    "symbol": f'{o.get("exchange")}:{o.get("tradingsymbol")}', "side": o.get("transaction_type"),
                    "qty": o.get("quantity"), "filled": o.get("filled_quantity"), "price": o.get("price"),
                    "avg": o.get("average_price"), "type": o.get("order_type"), "product": o.get("product"),
                    "status": o.get("status"), "message": o.get("status_message"), "variety": o.get("variety"),
                    "source": _src(o.get("tag"))} for o in reversed(orders)],
        "positions": [{"symbol": f'{p.get("exchange")}:{p.get("tradingsymbol")}', "qty": p.get("quantity"),
                       "avg": p.get("average_price"), "ltp": p.get("last_price"), "pnl": p.get("pnl"),
                       "product": p.get("product")} for p in pos if p.get("quantity") or p.get("pnl")],
        "holdings": [{"symbol": f'{h.get("exchange")}:{h.get("tradingsymbol")}',
                      "qty": (h.get("quantity") or 0) + (h.get("t1_quantity") or 0), "avg": h.get("average_price"),
                      "ltp": h.get("last_price"), "pnl": h.get("pnl")} for h in hold]}


@app.post("/kite/orders/{order_id}/cancel")
def kite_cancel(order_id: str, variety: str = "regular", mid: int = Depends(current_member_id)):
    with Session(engine) as s:
        m, k = member_kite(s, mid)
        try:
            kite_call(s, m, lambda: k.cancel_order(variety=variety, order_id=order_id))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"Zerodha could not cancel it: {str(e)[:150]}")
    return {"ok": True}


@app.get("/manual/trades")
def manual_trades(mid: int = Depends(current_member_id)):
    """Trades placed by hand on the Trade page, and the paper positions they add up to."""
    with Session(engine) as s:
        rows = s.query(Trade).filter_by(member_id=mid, algo_id="manual").order_by(Trade.id.desc()).limit(200).all()
        net: dict[str, list] = {}
        for t in reversed(rows):
            if t.mode != "paper":
                continue
            q, cost = net.get(t.symbol, [0, 0.0])
            if t.side == "BUY":
                q, cost = q + t.qty, cost + t.qty * t.price
            else:
                cost = cost * max(q - t.qty, 0) / q if q > 0 else 0.0
                q -= t.qty
            net[t.symbol] = [q, cost]
        return {"trades": [{"symbol": t.symbol, "side": t.side, "qty": t.qty, "price": t.price, "mode": t.mode,
                            "status": t.status, "note": t.reason, "at": iso(t.at)} for t in rows],
                "paper_positions": [{"symbol": k_, "qty": v[0], "avg": round(v[1] / v[0], 2)}
                                    for k_, v in net.items() if v[0] > 0]}


# ---------------------------------------------------------------- admin
def need_admin(mid: int = Depends(current_member_id)) -> int:
    with Session(engine) as s:
        m = s.get(Member, mid)
        if not store.is_admin(s, m):
            raise HTTPException(403, "Admins only")
    return mid


@app.get("/admin/overview")
def admin_overview(mid: int = Depends(need_admin)):
    base = config.PUBLIC_URL or config.BACKEND_URL
    with Session(engine) as s:
        subs = s.query(Subscription).all()
        per = {a: {"running": 0, "paper": 0, "live": 0} for a in ALGOS}
        for sub in subs:
            if sub.algo_id in per and sub.running:
                per[sub.algo_id]["running"] += 1
                per[sub.algo_id]["paper" if sub.paper else "live"] += 1
        alerts = s.query(Signal).order_by(Signal.id.desc()).limit(50).all()
        return {"members": s.query(Member).count(), "public_url": config.PUBLIC_URL,
                "chartink_ready": bool(config.CHARTINK_KEY), "allow_live": store.allow_live(),
                "algos": [{**a.meta(), **per[a.id],
                           "webhook": (f"{base}/webhook/chartink/{a.id}?key={config.CHARTINK_KEY}"
                                       if config.CHARTINK_KEY else None),
                           "tv_webhook": (f"{base}/webhook/tradingview/{a.id}?key={config.CHARTINK_KEY}"
                                          if config.CHARTINK_KEY else None)} for a in ALGOS.values()],
                "feedback": [{"topic": f.topic, "name": f.name, "contact": f.contact, "member_id": f.member_id,
                              "message": f.message, "rating": f.rating, "at": iso(f.at)}
                             for f in s.query(Feedback).order_by(Feedback.id.desc()).limit(50)],
                "alerts": [{"algo_id": x.algo_id, "symbol": x.symbol, "price": x.price, "source": x.source, "action": x.action,
                            "note": x.note, "at": iso(x.at)} for x in alerts]}


@app.get("/admin/members")
def admin_members(mid: int = Depends(need_admin)):
    with Session(engine) as s:
        out = []
        for m in s.query(Member).order_by(Member.id.desc()).all():
            subs = s.query(Subscription).filter_by(member_id=m.id).all()
            out.append({"id": m.id, "full_name": m.full_name, "email": m.email, "mobile": m.mobile,
                        "created_at": iso(m.created_at), "last_login": iso(m.last_login),
                        "kite": "today" if eng.token_fresh(m) else ("expired" if m.kite_token else "no"),
                        "running": [x.algo_id + (" (paper)" if x.paper else " (LIVE)") for x in subs if x.running],
                        "trades": s.query(Trade).filter_by(member_id=m.id).count()})
        logins = s.query(LoginEvent).order_by(LoginEvent.id.desc()).limit(100).all()
        return {"members": out,
                "logins": [{"email": e.email, "ip": e.ip, "kind": e.kind, "success": e.success, "note": e.note,
                            "at": iso(e.at)} for e in logins],
                "database": "Postgres" if config.DATABASE_URL.startswith("postgres") else "SQLite file (mjvs.db)",
                "backups": sorted(os.listdir(config.BACKUP_DIR))[-5:] if os.path.isdir(config.BACKUP_DIR) else []}


@app.get("/admin/export/{table}.csv")
def admin_export(table: str, mid: int = Depends(need_admin)):
    """Download a table. Password hashes and Kite tokens are never exported."""
    with Session(engine) as s:
        if table == "members":
            return csv_response("mjvs-members.csv", ["id", "full_name", "email", "mobile", "created_at_ist", "last_login_ist"],
                                [[m.id, m.full_name, m.email, m.mobile, iso(m.created_at), iso(m.last_login)]
                                 for m in s.query(Member).order_by(Member.id)])
        if table == "trades":
            return csv_response("mjvs-all-trades.csv", TRADE_COLS, [trade_row(t) for t in s.query(Trade).order_by(Trade.id)])
        if table == "subscriptions":
            return csv_response("mjvs-algo-settings.csv", ["id", "member_id", "algo_id", "amount", "drawdown_pct", "max_positions",
                                                           "universe", "mode", "running", "last_run_ist", "last_message"],
                                [[x.id, x.member_id, x.algo_id, x.amount, x.drawdown_pct, x.max_positions, x.universe,
                                  "paper" if x.paper else "live", x.running, iso(x.last_run_at), x.last_message]
                                 for x in s.query(Subscription).order_by(Subscription.id)])
        if table == "signals":
            return csv_response("mjvs-signals.csv", ["id", "algo_id", "symbol", "price", "source", "action", "note", "day", "at_ist"],
                                [[x.id, x.algo_id, x.symbol, x.price, x.source, x.action, x.note, x.day, iso(x.at)]
                                 for x in s.query(Signal).order_by(Signal.id)])
        if table == "logins":
            return csv_response("mjvs-logins.csv", ["id", "member_id", "email", "ip", "kind", "success", "note", "at_ist"],
                                [[x.id, x.member_id, x.email, x.ip, x.kind, x.success, x.note, iso(x.at)]
                                 for x in s.query(LoginEvent).order_by(LoginEvent.id)])
        if table == "feedback":
            return csv_response("mjvs-feedback.csv", ["id", "member_id", "topic", "name", "contact", "message", "at_ist"],
                                [[x.id, x.member_id, x.topic, x.name, x.contact, x.message, iso(x.at)] for x in s.query(Feedback).order_by(Feedback.id)])
        if table == "suggestions":
            return csv_response("mjvs-suggestions.csv", ["id", "algo_id", "symbol", "day", "price", "scanner_at_ist", "tradingview_at_ist", "note"],
                                [[x.id, x.algo_id, x.symbol, x.day, x.price, iso(x.scanner_at), iso(x.tradingview_at), x.note]
                                 for x in s.query(Suggestion).order_by(Suggestion.id)])
    raise HTTPException(404, "Unknown table")


class KiteKeys(BaseModel):
    api_key: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9]*$")
    api_secret: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9]*$")


@app.get("/admin/kite")
def admin_kite(mid: int = Depends(need_admin)):
    key = store.kite_api_key()
    return {"ready": store.kite_ready(), "source": store.kite_source(), "redirect_url": store.redirect_url(),
            "api_key": (key[:4] + "…" + key[-3:]) if len(key) > 8 else ("set" if key else ""),
            "has_secret": bool(store.kite_api_secret()), "public_ip": public_ip()}


_ip_cache: dict = {}


def public_ip() -> str:
    """This PC's internet IP (what Zerodha sees), to add to the Kite IP whitelist."""
    now = time.time()
    if _ip_cache.get("t", 0) > now - 300:
        return _ip_cache.get("ip", "")
    ip = ""
    try:
        import httpx
        ip = httpx.get("https://api.ipify.org", timeout=5).text.strip()[:45]
    except Exception:
        ip = ""
    _ip_cache.update(t=now, ip=ip)
    return ip


class LiveIn(BaseModel):
    on: bool


class ScanTimeIn(BaseModel):
    time: str = Field(pattern=r"^(off|([01]\d|2[0-3]):[0-5]\d)$")    # "HH:MM" (IST) or "off"


@app.put("/admin/scan-time")
def admin_scan_time(b: ScanTimeIn, mid: int = Depends(need_admin)):
    """Time of the automatic daily Swing / Penny scan (Mon-Fri), or "off"."""
    store.put("scan_time", b.time)
    eng._sched_scan["day"] = None          # a new time can run again today
    return {"ok": True, "scan_time": store.scan_time()}


@app.put("/admin/live")
def admin_live(b: LiveIn, mid: int = Depends(need_admin)):
    """Master switch for real orders (manual and algo) on this site."""
    store.put("allow_live", "1" if b.on else "0")
    return {"ok": True, "allow_live": store.allow_live()}


@app.post("/admin/kite/check")
def admin_kite_check(mid: int = Depends(need_admin)):
    """Tests what the Kite plan allows, with the admin's own login of today."""
    with Session(engine) as s:
        m = s.get(Member, mid)
        if not eng.token_fresh(m):
            raise HTTPException(400, "Connect your own Zerodha first (top right), then check again.")
        k = broker.client(m.kite_token)
        out = {}
        def prices():
            q = k.ltp(["NSE:NIFTY 50"])
            if not q.get("NSE:NIFTY 50", {}).get("last_price"):
                raise ValueError("no price came back")
            return q

        def charts():
            tok = prices()["NSE:NIFTY 50"]["instrument_token"]
            rows = k.historical_data(tok, config.ist_today() - dt.timedelta(days=15), config.ist_today(), "day")
            if not rows:
                raise ValueError("no candles came back")

        for name, fn in (("login", lambda: k.profile()), ("prices", prices), ("charts", charts)):
            try:
                fn()
                out[name] = "ok"
            except broker.PermissionError_:
                out[name] = "not in your plan"
            except broker.TokenError:
                out[name] = "login expired"
            except Exception as e:
                out[name] = f"error: {str(e)[:80]}"
        out["market_data"] = out["prices"] == "ok" and out["charts"] == "ok"
        return out


@app.put("/admin/kite")
def admin_kite_save(b: KiteKeys, mid: int = Depends(need_admin)):
    """One-time owner setup: the API key and secret of the MJVS app on developers.kite.trade."""
    key = b.api_key.strip() or store.kite_api_key()
    if len(key) < 6:
        raise HTTPException(400, "Paste the API key from developers.kite.trade")
    if not b.api_secret and not store.kite_api_secret():
        raise HTTPException(400, "Paste the API secret too")
    store.put("kite_api_key", key)
    if b.api_secret:
        store.put("kite_api_secret", b.api_secret.strip())
    return {"ok": True, "ready": store.kite_ready()}


class TestSignal(BaseModel):
    stocks: str = Field(min_length=1, max_length=500)
    source: str = "chartink"      # chartink | tradingview
    action: str = "BUY"


@app.post("/admin/algos/{algo_id}/test-signal")
def admin_test_signal(algo_id: str, b: TestSignal, mid: int = Depends(need_admin)):
    algo = get_algo(algo_id)
    with Session(engine) as s:
        src = "tradingview" if b.source == "tradingview" else "test"
        added = sigmod.save_signals(s, algo.id, b.stocks.split(","), [], "manual test", src, b.action)
        matched = s.query(Suggestion).filter_by(algo_id=algo.id, day=config.ist_today()).count()
        return {"added": added, "suggestions_today": matched}


if config.SCHEDULER_ON:
    eng.start_scheduler()
