"""Stock lists built live from Kite (e.g. every NSE stock under Rs 100)."""
import re
import time

from .. import config

_instruments: dict = {}       # day -> list of NSE equity symbols
ETF_HINT = re.compile(r"(BEES|ETF|IETF)$", re.I)          # NIFTYBEES, GOLDETF, BANKIETF ...


def nse_equities(kite) -> list[str]:
    """All NSE equity shares (EQ), without ETFs, bonds, rights and other series. Cached per day."""
    day = config.ist_today()
    if day not in _instruments:
        out = []
        for ins in kite.instruments("NSE"):
            sym, name = str(ins.get("tradingsymbol", "")), str(ins.get("name", ""))
            if ins.get("instrument_type") != "EQ" or ins.get("segment", "NSE") != "NSE":
                continue
            if "-" in sym and not sym.endswith("-AUTO"):   # -BE, -SM, -GS, -N1 ... other series
                continue
            up = name.upper()
            if not name or ETF_HINT.search(sym) or " ETF" in up or "ETF " in up or "MUTUAL FUND" in up or up.endswith(" FUND"):
                continue
            out.append("NSE:" + sym)
        _instruments.clear()
        _instruments[day] = sorted(set(out))
    return _instruments[day]


def all_stocks(kite) -> list[str]:
    """Every NSE equity share (about 2,000)."""
    return nse_equities(kite)


def stocks_under(kite, limit: float, minimum: float = 1.0) -> list[str]:
    """NSE equities whose last price is below `limit` right now (and at least `minimum`)."""
    symbols, keep = nse_equities(kite), []
    for i in range(0, len(symbols), 500):          # Kite allows up to 1000 per LTP call
        chunk = symbols[i:i + 500]
        data = kite.ltp(chunk)
        for s in chunk:
            p = (data.get(s) or {}).get("last_price") or 0
            if minimum <= p < limit:
                keep.append(s)
        time.sleep(0.2)
    return keep


# ---- full instrument list for manual search (NSE shares + NFO futures and options)
_search_cache: dict = {}


def tradable_instruments(kite) -> list[dict]:
    """NSE equity shares and live NFO futures/options. Cached for the day (the list is large)."""
    day = config.ist_today()
    if day not in _search_cache:
        rows = []
        for ins in kite.instruments("NSE"):
            sym = str(ins.get("tradingsymbol", ""))
            if ins.get("instrument_type") != "EQ" or ("-" in sym and not sym.endswith("-AUTO")):
                continue
            rows.append({"exchange": "NSE", "symbol": sym, "name": str(ins.get("name") or ""), "type": "EQ",
                         "expiry": None, "strike": None, "lot": 1, "tick": float(ins.get("tick_size") or 0.05)})
        for ins in kite.instruments("NFO"):
            exp = ins.get("expiry")
            if not exp or (hasattr(exp, "isoformat") and exp < day):
                continue
            t = ins.get("instrument_type")
            if t not in ("FUT", "CE", "PE"):
                continue
            rows.append({"exchange": "NFO", "symbol": str(ins.get("tradingsymbol")), "name": str(ins.get("name") or ""),
                         "type": t, "expiry": exp.isoformat() if hasattr(exp, "isoformat") else str(exp),
                         "strike": float(ins.get("strike") or 0) or None, "lot": int(ins.get("lot_size") or 1),
                         "tick": float(ins.get("tick_size") or 0.05)})
        for r in rows:
            r["key"] = f'{r["symbol"]} {r["name"]} {r["type"]} {int(r["strike"]) if r["strike"] else ""}'.upper()
        _search_cache.clear()
        _search_cache[day] = rows
    return _search_cache[day]


def find_instrument(kite, full_symbol: str) -> dict | None:
    exch, sym = full_symbol.split(":", 1) if ":" in full_symbol else ("NSE", full_symbol)
    for r in tradable_instruments(kite):
        if r["exchange"] == exch and r["symbol"] == sym:
            return r
    return None


def search(kite, q: str, limit: int = 40) -> list[dict]:
    """'sbin', 'nifty 24500 ce', 'banknifty fut' ... every word must match."""
    words = [w for w in q.upper().replace(",", " ").split() if w]
    if not words:
        return []
    hits = [r for r in tradable_instruments(kite) if all(w in r["key"] for w in words)]
    first = words[0]

    def rank(r):
        return (0 if r["symbol"] == first else 1 if r["symbol"].startswith(first) else 2,
                0 if r["type"] == "EQ" else 1 if r["type"] == "FUT" else 2,
                r["expiry"] or "", r["strike"] or 0)
    hits.sort(key=rank)
    return [{k: v for k, v in r.items() if k != "key"} for r in hits[:limit]]
