"""Everything that talks to Zerodha Kite lives here."""
import os
import pickle
import threading
import time
import datetime as dt

import pandas as pd
from kiteconnect import KiteConnect
from kiteconnect import exceptions as kite_errors

from . import config, security, settings_store

# Zerodha's order IP whitelist works with this PC's IPv4 address. Many connections (e.g. Jio) also
# have IPv6, which Windows prefers and changes often; orders sent over IPv6 are then refused.
# So every call to Zerodha is made over IPv4.
import socket
import urllib3.util.connection as _urllib3_conn
_urllib3_conn.allowed_gai_family = lambda: socket.AF_INET

TokenError = kite_errors.TokenException
PermissionError_ = kite_errors.PermissionException
NO_MARKET_DATA = ("Your Kite app's plan does not include market data (live prices and charts), so Zerodha "
                  "refused the scan. The free \"Personal\" plan only allows orders. On developers.kite.trade, "
                  "switch the MJVS app to the paid \"Connect\" plan (includes live and historical data), then "
                  "press Connect Zerodha again and try once more.")
HISTORY_PAUSE = 0.35       # Kite allows about 3 historical-data calls per second
HISTORY_RATE = 2.9         # chart downloads started per second, shared by all threads (Kite's limit is 3)
SCAN_THREADS = 4           # parallel downloads during a scan (the rate above is still respected)


class _RateLimiter:
    """Spaces out calls so at most `per_sec` start each second, across all threads."""
    def __init__(self, per_sec: float):
        self.gap, self.next, self.lock = 1.0 / per_sec, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            start = max(time.monotonic(), self.next)
            self.next = start + self.gap
        delay = start - time.monotonic()
        if delay > 0:
            time.sleep(delay)


_history_limit = _RateLimiter(HISTORY_RATE)
INTERVAL_MINUTES = {"minute": 1, "3minute": 3, "5minute": 5, "10minute": 10, "15minute": 15,
                    "30minute": 30, "60minute": 60}


def client(enc_token: str | None = None) -> KiteConnect:
    k = KiteConnect(api_key=settings_store.kite_api_key())
    if enc_token:
        k.set_access_token(security.decrypt(enc_token))
    return k


def ltp_many(k, symbols) -> dict:
    symbols = list(symbols)
    if not symbols:
        return {}
    data = k.ltp(symbols)
    return {s: float(data[s]["last_price"]) for s in symbols if s in data}


MARKET_CLOSE = dt.time(15, 30)  # from now on today's daily candle counts as complete


def data_day(now: dt.datetime) -> dt.date:
    """The last trading session whose daily candle is complete: today after 15:30 (Mon-Fri), else the
    previous weekday. Saved charts and scans are keyed by it, so a 15:30 scan is reused next morning."""
    d = now.date()
    if d.weekday() < 5 and now.time() >= MARKET_CLOSE:
        return d
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


DAY_FETCH = 340                 # daily candles fetched per stock: enough for weekly (Penny) and daily (Swing)
_day_cache: dict = {}           # (date, token) -> completed daily candles, shared by all algos for the day
_day_lock = threading.Lock()
# The day's candles are also saved to disk, so a restart or a second scan the same day needs no downloads.
CANDLE_CACHE = os.path.join(os.path.dirname(config.BACKUP_DIR.rstrip("/\\")) or ".", "candles-today.pkl")


def _load_day_cache(today: dt.date):
    try:
        with open(CANDLE_CACHE, "rb") as f:
            saved = pickle.load(f)
        if saved.get("date") == today:
            _day_cache.update({(today, tok): df for tok, df in saved["data"].items()})
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"candle cache not loaded: {e!r}")


def save_day_cache():
    """Writes today's downloaded daily candles to disk (called after each scan)."""
    with _day_lock:
        items = list(_day_cache.items())
    if not items:
        return
    day = items[0][0][0]
    try:
        tmp = CANDLE_CACHE + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump({"date": day, "data": {tok: df for (d, tok), df in items if d == day}}, f)
        os.replace(tmp, CANDLE_CACHE)
    except Exception as e:
        print(f"candle cache not saved: {e!r}")


def history(k, instrument_token: int, interval: str, candles: int, now: dt.datetime) -> pd.DataFrame:
    """Completed candles only: a candle still forming is dropped.
    Daily candles are fetched once per stock per day and reused (Swing and Penny share them)."""
    if interval == "day":
        key = (data_day(now), instrument_token)
        with _day_lock:
            if _day_cache and next(iter(_day_cache))[0] != key[0]:
                _day_cache.clear()
            if not _day_cache:
                _load_day_cache(key[0])
            have = key in _day_cache
        if not have:
            df = _fetch(k, instrument_token, interval, max(candles, DAY_FETCH), now)
            with _day_lock:
                _day_cache[key] = df
        return _day_cache[key].tail(candles)
    return _fetch(k, instrument_token, interval, candles, now)


def _fetch(k, instrument_token: int, interval: str, candles: int, now: dt.datetime) -> pd.DataFrame:
    if interval == "day":
        start = now.date() - dt.timedelta(days=int(candles * 1.6) + 60)
    else:
        mins = INTERVAL_MINUTES[interval]
        start = now.date() - dt.timedelta(days=max(5, int(candles * mins / 375 * 1.6) + 5))
    for attempt in range(3):
        _history_limit.wait()
        try:
            data = k.historical_data(instrument_token, start, now.replace(tzinfo=None), interval)
            break
        except kite_errors.NetworkException as e:        # "Too many requests": wait and try again
            if attempt == 2 or "too many" not in str(e).lower():
                raise
            time.sleep(1.0 + attempt)
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df = df[["date", "open", "high", "low", "close", "volume"]]
    stamps = pd.to_datetime(df["date"])
    if interval == "day":
        df = df[stamps.dt.date <= data_day(now)]     # today's candle only once the market has closed
    else:
        naive_now = pd.Timestamp(now.replace(tzinfo=None))
        if stamps.dt.tz is not None:
            stamps = stamps.dt.tz_localize(None)
        df = df[stamps + pd.Timedelta(minutes=INTERVAL_MINUTES[interval]) <= naive_now]
    return df.set_index("date").tail(candles)


# ---------------------------------------------------------------- GTT (Good Till Triggered)
SL_LIMIT_GAP = 0.02      # the stop-loss leg sells at a LIMIT 2% below its trigger, so it fills in a fast fall


def tick_round(price: float, tick: float = 0.05, down: bool = False) -> float:
    import math
    n = price / tick
    return round((math.floor(n + 1e-9) if down else round(n)) * tick, 2)


def place_gtt_oco(k, symbol: str, qty: int, sl_trigger: float, target_trigger: float,
                  last_price: float, product: str = "CNC") -> str:
    """One GTT with two exits (OCO): when either price is touched, Zerodha places that SELL order
    and cancels the other. Returns the GTT id."""
    exch, name = symbol.split(":")
    sl_t, tg_t = tick_round(sl_trigger), tick_round(target_trigger)
    leg = dict(exchange=exch, tradingsymbol=name, transaction_type=k.TRANSACTION_TYPE_SELL,
               quantity=qty, order_type=k.ORDER_TYPE_LIMIT, product=product)
    res = k.place_gtt(trigger_type=k.GTT_TYPE_OCO, tradingsymbol=name, exchange=exch,
                      trigger_values=[sl_t, tg_t], last_price=last_price,
                      orders=[{**leg, "price": tick_round(sl_t * (1 - SL_LIMIT_GAP), down=True)},
                              {**leg, "price": tg_t}])
    return str(res["trigger_id"] if isinstance(res, dict) else res)


def gtt_info(k, gtt_id: str) -> dict:
    """Kite's GTT record: status (active, triggered, cancelled, deleted, expired, disabled, rejected)
    and, once triggered, the order Zerodha placed (orders[i]['result']['order_result']['order_id'])."""
    try:
        return k.get_gtt(int(gtt_id))
    except TokenError:
        raise
    except Exception:
        # Kite sometimes answers the single-GTT call with "Error during internal conversion";
        # the list of all GTTs still works, so find it there.
        for g in k.get_gtts() or []:
            if str(g.get("id")) == str(gtt_id):
                return g
        raise


def delete_gtt(k, gtt_id: str):
    try:
        k.delete_gtt(int(gtt_id))
    except Exception as e:
        print(f"delete_gtt {gtt_id} failed: {e!r}")


def available_cash(k) -> float | None:
    """Money free to trade in the member's Zerodha equity account (Kite 'margins'), or None
    if Kite does not answer. Shares and F&O use the same equity balance at Zerodha."""
    try:
        eq = k.margins("equity")
        return float(eq.get("net", eq.get("available", {}).get("live_balance", 0)))
    except TokenError:
        raise
    except Exception as e:
        print(f"available_cash failed: {e!r}")
        return None


def market_open_today(k, today: dt.date) -> bool:
    """On a holiday NIFTY's last tick is from an earlier day. Unknown -> assume open."""
    try:
        q = k.quote(["NSE:NIFTY 50"])["NSE:NIFTY 50"]
        ts = q.get("timestamp") or q.get("last_trade_time")
        if isinstance(ts, str):
            ts = dt.datetime.fromisoformat(ts)
        return ts is None or ts.date() == today
    except TokenError:
        raise
    except Exception:
        return True


def order_refused(e: Exception) -> str:
    """Zerodha's own words when it refuses an ORDER, plus the fix for the static-IP rule."""
    msg = str(e).strip() or e.__class__.__name__
    if "IP (" in msg and ":" in msg.split("IP (", 1)[1].split(")", 1)[0]:
        return (f"Zerodha refused the order: \"{msg}\". That is an IPv6 address. MJVS now always uses IPv4: "
                "restart START_MJVS.bat (close the black window first) and try again. Zerodha should then see the "
                "IPv4 address shown on the Admin page, which must be in your IP Whitelist.")
    return (f"Zerodha refused the order: \"{msg}\". Since 1 April 2026 Zerodha accepts orders from apps only "
            "from a registered static IP address. Fix: developers.kite.trade -> your Profile -> IP Whitelist -> "
            "add this PC's internet IP (shown on the Admin page), wait a few minutes, then try again. Home internet "
            "IPs usually change, so ask your internet provider for a static IP, or run MJVS on a server with one.")


class OrderRefused(Exception):
    pass


def send_order(k, symbol: str, side: str, qty: int, product: str) -> str:
    exch, name = symbol.split(":")
    return str(k.place_order(
        variety=k.VARIETY_REGULAR, exchange=exch, tradingsymbol=name,
        transaction_type=k.TRANSACTION_TYPE_BUY if side == "BUY" else k.TRANSACTION_TYPE_SELL,
        quantity=qty, product=product, order_type=k.ORDER_TYPE_MARKET, market_protection=-1, tag="mjvs"))


def send_manual_order(k, exchange: str, tradingsymbol: str, side: str, qty: int, product: str,
                      order_type: str, price: float | None = None) -> str:
    """An order placed by hand from the Trade page. MARKET orders use Zerodha's automatic
    market protection (-1), which Kite asks for on API market orders."""
    kw = dict(variety=k.VARIETY_REGULAR, exchange=exchange, tradingsymbol=tradingsymbol,
              transaction_type=k.TRANSACTION_TYPE_BUY if side == "BUY" else k.TRANSACTION_TYPE_SELL,
              quantity=qty, product=product, tag="mjvsman")
    if order_type == "LIMIT":
        kw.update(order_type=k.ORDER_TYPE_LIMIT, price=price)
    else:
        kw.update(order_type=k.ORDER_TYPE_MARKET, market_protection=-1)
    return str(k.place_order(**kw))


def wait_for_fill(k, order_id, tries: int = 6):
    """Market orders usually fill in a second. Returns (status, avg_price, filled_qty, message)."""
    last = {}
    for _ in range(tries):
        time.sleep(1)
        try:
            hist = k.order_history(order_id)
        except Exception:
            continue
        if hist:
            last = hist[-1]
            if last.get("status") in ("COMPLETE", "REJECTED", "CANCELLED"):
                break
    return (last.get("status", "PENDING"), float(last.get("average_price") or 0),
            int(last.get("filled_quantity") or 0), last.get("status_message") or "")


def available_qty(k, symbol: str, product: str) -> int:
    """Units really in the Kite account: holdings + T1 + today's net position."""
    name = symbol.split(":")[1]
    have = 0
    if product == "CNC":
        have = sum(int(h.get("quantity", 0)) + int(h.get("t1_quantity", 0))
                   for h in k.holdings() if h.get("tradingsymbol") == name)
    have += sum(int(p.get("quantity", 0)) for p in k.positions().get("net", [])
                if p.get("tradingsymbol") == name and p.get("product") == product)
    return max(have, 0)
