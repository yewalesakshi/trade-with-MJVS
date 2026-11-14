"""
Incoming signals (Chartink scanner alerts, TradingView strategy alerts) and matching them.

A stock becomes a Suggestion when, for an algo with require_tradingview = True, on the same day:
  - the SCANNER picked it (a Chartink alert, or a BUY row in the algo's own scanner), and
  - the TRADINGVIEW strategy sent a BUY alert for it.
"""
import datetime as dt
import json
import re

from sqlalchemy.orm import Session

from . import config
from .algos import ALGOS
from .db import AlgoState, Signal, Suggestion, now_ist

SCANNER_SOURCES = ("chartink", "test")


def norm(symbol: str) -> str:
    """Compare symbols across sites: 'NSE:M&M', 'M_M' and 'm&m' are the same stock.
    TradingView writes M&M as M_M and BAJAJ-AUTO as BAJAJ_AUTO."""
    return re.sub(r"[^A-Z0-9]", "", symbol.split(":")[-1].upper())


def kite_symbol(symbol: str, exchange: str = "NSE") -> str:
    """'SBIN' -> 'NSE:SBIN'; TradingView 'NSE:M_M' -> 'NSE:M&M'."""
    symbol = symbol.strip().upper()
    if ":" in symbol:
        exchange, symbol = symbol.split(":", 1)
    exchange = {"BSE": "BSE", "NSE": "NSE"}.get(exchange.strip().upper(), "NSE")
    fixes = {"M_M": "M&M", "M_MFIN": "M&MFIN", "BAJAJ_AUTO": "BAJAJ-AUTO", "L_TFH": "L&TFH"}
    return f"{exchange}:{fixes.get(symbol, symbol)}"


def save_signals(s: Session, algo_id: str, symbols: list[str], prices: list, note: str,
                 source: str, action: str = "BUY") -> int:
    """Stores alerts. The same stock from the same source and action counts once per day."""
    today = config.ist_today()
    action = "SELL" if str(action).upper().startswith(("SELL", "EXIT", "SHORT")) else "BUY"
    added = 0
    for i, raw in enumerate(symbols):
        if not raw or not raw.strip():
            continue
        full = kite_symbol(raw)
        dup = s.query(Signal).filter_by(algo_id=algo_id, symbol=full, day=today, source=source, action=action).first()
        if dup:
            continue
        try:
            price = float(prices[i])
        except (IndexError, ValueError, TypeError):
            price = None
        s.add(Signal(algo_id=algo_id, symbol=full, price=price, source=source, action=action,
                     note=(note or "")[:120], day=today))
        added += 1
    s.commit()
    refresh_suggestions(s, algo_id, today)
    return added


def parse_tradingview(raw: bytes) -> list[dict]:
    """TradingView sends the alert message as typed. Accepted forms:
      JSON  {"symbol": "{{ticker}}", "exchange": "{{exchange}}", "price": {{close}}, "action": "BUY"}
      JSON  a list of those objects
      text  "BUY NSE:SBIN 812.5"  or just  "SBIN"
    """
    text = raw.decode("utf-8", "replace").strip()
    try:
        data = json.loads(text)
        items = data if isinstance(data, list) else [data]
        out = []
        for d in items:
            if not isinstance(d, dict):
                continue
            sym = str(d.get("symbol") or d.get("ticker") or "").strip()
            if not sym:
                continue
            exch = str(d.get("exchange") or "NSE")
            out.append({"symbol": sym if ":" in sym else f"{exch}:{sym}",
                        "price": d.get("price") or d.get("close"),
                        "action": str(d.get("action") or d.get("side") or "BUY"),
                        "note": str(d.get("strategy") or d.get("note") or "TradingView")})
        return out
    except ValueError:
        return _parse_text(text)


_ACTIONS = {"BUY": "BUY", "LONG": "BUY", "SELL": "SELL", "SHORT": "SELL", "EXIT": "SELL"}
_SYM = r"[A-Z0-9][A-Z0-9_&\-]*(?::[A-Z0-9][A-Z0-9_&\-]*)?"


def _parse_text(text: str) -> list[dict]:
    """Plain-text alerts, e.g. '🟢 BUY SIGNAL on SBIN - All Bullish Conditions Aligned!',
    'BUY NSE:SBIN 812.5' or just 'SBIN'."""
    up = text.upper()
    m = re.search(r"\b(BUY|LONG|SELL|SHORT|EXIT)\b", up)
    action = _ACTIONS[m.group(1)] if m else "BUY"
    on = re.search(r"\bON\s+(" + _SYM + r")", up)
    if on:
        sym = on.group(1)
    else:
        words = [w for w in re.findall(_SYM, up) if w not in _ACTIONS and w not in ("SIGNAL", "ALERT")
                 and not re.fullmatch(r"[0-9.]+", w)]
        if not words:
            return []
        sym = words[0]
    price = None
    after = up[up.find(sym) + len(sym):]
    pm = re.search(r"(?<![A-Z])(\d+(?:\.\d+)?)", after)
    if pm:
        price = pm.group(1)
    note = re.sub(r"\s+", " ", re.sub(r"[^\w\s:%.,&+\-]", "", text)).strip()[:80] or "TradingView"
    return [{"symbol": sym, "price": price, "action": action, "note": note}]


def _scanner_picks(s: Session, algo, day: dt.date) -> dict:
    """norm(symbol) -> (kite symbol, time, price, note) for today's scanner picks."""
    picks = {}
    if algo.source == "chartink":
        for x in (s.query(Signal).filter(Signal.algo_id == algo.id, Signal.day == day, Signal.action == "BUY",
                                         Signal.source.in_(SCANNER_SOURCES)).order_by(Signal.id)):
            picks.setdefault(norm(x.symbol), (x.symbol, x.at, x.price, x.note or "scanner"))
    else:
        for st in s.query(AlgoState).filter(AlgoState.key.like(f"{algo.id}:%")).all():
            if not st.scan_at or st.scan_at.date() != day:
                continue
            for r in json.loads(st.scan or "[]"):
                if r.get("signal") == "BUY":
                    vals = ", ".join(f"{lbl} {r.get(k)}" for k, lbl in algo.columns if r.get(k) is not None)
                    picks.setdefault(norm(r["trade_symbol"]), (r["trade_symbol"], st.scan_at, r.get("ltp"),
                                                               "fresh BUY" + (f" ({vals})" if vals else "")))
    return picks


def refresh_suggestions(s: Session, algo_id: str, day: dt.date | None = None) -> int:
    """Creates Suggestions for stocks found by both the scanner and TradingView today."""
    algo = ALGOS.get(algo_id)
    if not algo or not (algo.require_tradingview or algo.suggest):
        return 0
    day = day or config.ist_today()
    if not algo.require_tradingview:      # scanner alone decides (its rule is the strategy)
        have = {norm(x.symbol) for x in s.query(Suggestion).filter_by(algo_id=algo_id, day=day)}
        added = 0
        for key, (sym, scan_at, scan_price, scan_note) in _scanner_picks(s, algo, day).items():
            if key not in have:
                s.add(Suggestion(algo_id=algo_id, symbol=sym, day=day, price=scan_price, scanner_at=scan_at,
                                 note=f"Scanner: {scan_note}"[:200]))
                added += 1
        if added:
            s.commit()
        return added
    tv = {}
    for x in (s.query(Signal).filter(Signal.algo_id == algo_id, Signal.day == day, Signal.source == "tradingview",
                                     Signal.action == "BUY").order_by(Signal.id)):
        tv.setdefault(norm(x.symbol), x)
    if not tv:
        return 0
    picks = _scanner_picks(s, algo, day)
    have = {norm(x.symbol) for x in s.query(Suggestion).filter_by(algo_id=algo_id, day=day)}
    added = 0
    for key, (sym, scan_at, scan_price, scan_note) in picks.items():
        t = tv.get(key)
        if not t or key in have:
            continue
        if algo.match_minutes and scan_at and abs((t.at - scan_at).total_seconds()) > algo.match_minutes * 60:
            continue
        s.add(Suggestion(algo_id=algo_id, symbol=sym, day=day, price=t.price or scan_price,
                         scanner_at=scan_at, tradingview_at=t.at,
                         note=f"Scanner: {scan_note} · TradingView: {t.note or 'BUY'}"[:200]))
        added += 1
    if added:
        s.commit()
    return added


def tradingview_sells(s: Session, algo_id: str, since: dt.datetime) -> set:
    """norm(symbol) of TradingView SELL alerts received after `since` (naive UTC)."""
    return {norm(x.symbol) for x in s.query(Signal).filter(Signal.algo_id == algo_id, Signal.source == "tradingview",
                                                          Signal.action == "SELL", Signal.at >= since)}
