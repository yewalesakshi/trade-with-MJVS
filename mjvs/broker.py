"""Everything that talks to Zerodha Kite lives here."""
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


DAY_FETCH = 340                 # daily candles fetched per stock: enough for weekly (Penny) and daily (Swing)
_day_cache: dict = {}           # (date, token) -> completed daily candles, shared by all algos for the day


def history(k, instrument_token: int, interval: str, candles: int, now: dt.datetime) -> pd.DataFrame:
    """Completed candles only: a candle still forming is dropped.
    Daily candles are fetched once per stock per day and reused (Swing and Penny share them)."""
    if interval == "day":
        key = (now.date(), instrument_token)
        if key not in _day_cache:
            if _day_cache and next(iter(_day_cache))[0] != now.date():
                _day_cache.clear()
            _day_cache[key] = _fetch(k, instrument_token, interval, max(candles, DAY_FETCH), now)
        return _day_cache[key].tail(candles)
    return _fetch(k, instrument_token, interval, candles, now)


def _fetch(k, instrument_token: int, interval: str, candles: int, now: dt.datetime) -> pd.DataFrame:
    if interval == "day":
        start = now.date() - dt.timedelta(days=int(candles * 1.6) + 60)
    else:
        mins = INTERVAL_MINUTES[interval]
        start = now.date() - dt.timedelta(days=max(5, int(candles * mins / 375 * 1.6) + 5))
    df = pd.DataFrame(k.historical_data(instrument_token, start, now.replace(tzinfo=None), interval))
    if df.empty:
        return df
    df = df[["date", "open", "high", "low", "close", "volume"]]
    stamps = pd.to_datetime(df["date"])
    if interval == "day":
        df = df[stamps.dt.date < now.date()]
    else:
        naive_now = pd.Timestamp(now.replace(tzinfo=None))
        if stamps.dt.tz is not None:
            stamps = stamps.dt.tz_localize(None)
        df = df[stamps + pd.Timedelta(minutes=INTERVAL_MINUTES[interval]) <= naive_now]
    return df.set_index("date").tail(candles)


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
