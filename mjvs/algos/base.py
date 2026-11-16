"""
The shape every MJVS algo follows. To add or change an algo you only edit its own file.

Two kinds of entry signal:
  source = "scan"      the algo scans its own symbol list with its own indicator rule
                       (fill in indicators() and signal())
  source = "chartink"  a Chartink scanner alert sends the stocks to buy
                       (webhook URL is shown on the Admin page; nothing to code)

Exits come from the risk settings below (stop loss, target, time limits, square-off)
and, for scan algos, from signal() returning "SELL" on a held symbol.
The engine handles orders, paper mode, position sizing, drawdown and all the Kite details.
"""
import datetime as dt
import os

import pandas as pd

from .. import config

WATCHLIST_DIR = os.path.join(config.ROOT, "watchlists")


def read_watchlist(name: str) -> list[str]:
    """watchlists/<name>.txt: one NSE symbol per line, '#' starts a comment."""
    path = os.path.join(WATCHLIST_DIR, name + ".txt")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            sym = line.split("#", 1)[0].strip().upper()
            if sym:
                out.append(sym if ":" in sym else "NSE:" + sym)
    return list(dict.fromkeys(out))


class Algo:
    # ---- shown on the website
    id = ""
    name = ""
    group = "equity"          # "equity" or "fno"
    stars = 2                 # rating out of 2, as in the plan
    holding = ""              # e.g. "3–6 months"
    blurb = ""
    risk_note = ""
    ready = False             # False until the strategy is filled in -> cannot be started

    # ---- where entries come from
    source = "scan"           # "scan" or "chartink"
    interval = "day"          # Kite candle size for scans: day, 5minute, 15minute ...
    candles = 80              # how many completed candles the rule needs
    universes: dict = {}      # choice name -> label; symbols come from symbols()
    default_universe = ""
    columns: list = []        # [(key, label)] indicator values shown in the scanner table

    # ---- TradingView confirmation (optional)
    # True: a stock is only taken when it passes BOTH the scanner above AND your TradingView
    # strategy (its alert calls this algo's TradingView webhook). Matches become Suggestions.
    require_tradingview = False
    suggest = False           # True: the scanner's fresh BUY signals are listed on the Suggestions page
    match_minutes = None      # both must arrive within this many minutes (None = same day)
    auto_trade = True         # False = only suggest the matched stocks, never place orders

    # ---- orders
    product = "CNC"           # CNC delivery, MIS intraday, NRML futures and options
    max_positions = 5         # default number of positions held at once
    min_amount = 0            # any amount the member chooses (F&O algos set a minimum for margin)
    max_drawdown = 15         # highest drawdown limit (risk %) a member may choose for this algo
    default_drawdown = 10     # starting value of the drawdown slider
    max_price = None          # only stocks whose price is below this (Rs) are scanned and bought
    sl_from_drawdown = False  # True: each position's stop loss % = the member's drawdown limit
    use_gtt = False           # True: in LIVE mode each buy gets a Zerodha GTT (OCO: target + stop loss)
    manual_scan = False       # True: the scanner runs ONLY when the member presses "Scan now"; the algo
                              # trades from today's latest scan (exits are still checked automatically)
    warning = ""              # shown in a red box above the settings (optional)

    # ---- when the engine runs it (IST, Mon–Fri)
    window = (dt.time(9, 20), dt.time(15, 10))
    once_per_day = True       # daily-candle algos run once a day
    run_every = 10            # minutes between runs when once_per_day is False
    entry_until = None        # no new entries after this time (intraday)
    reentry_days = 1          # a stock bought from a signal is not bought again by it for this many days
    exits_note = ""           # plain-language exit rules shown on the website (optional)
    candle_label = ""         # e.g. "weekly" when candles are built from daily data

    # ---- exits (None = not used)
    stop_loss_pct = None
    target_pct = None
    max_hold_days = None
    max_hold_minutes = None
    square_off = None         # time to close everything (intraday)

    # ================================================================ fill these in
    def symbols(self, universe: str, kite=None) -> list[str]:
        """Symbols the scanner looks at (scan algos). `kite` lets a list be built live."""
        return []

    def indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add indicator columns to completed candles (open, high, low, close, volume)."""
        return df

    def signal(self, df: pd.DataFrame) -> str:
        """'BUY', 'SELL' or 'HOLD' for the latest completed candle (df.iloc[-1])."""
        return "HOLD"

    def order_symbol(self, signal_symbol: str) -> str:
        """Where the order goes. Override for index -> ETF or F&O contract selection."""
        return signal_symbol

    def quantity(self, price: float, money: float) -> int:
        """Units to buy for the money in one slot. F&O algos override this for lot sizes."""
        return int(money // price) if price > 0 else 0

    # ================================================================ engine helpers
    def signal_symbol(self, order_symbol: str) -> str:
        return order_symbol

    def is_due(self, sub, now: dt.datetime) -> bool:
        if now.weekday() >= 5 or not self.window[0] <= now.time() <= self.window[1]:
            return False
        if self.once_per_day:
            return sub.last_run_date != now.date()
        if not sub.last_run_at:
            return True
        last = sub.last_run_at.replace(tzinfo=config.IST)
        return (now - last) >= dt.timedelta(minutes=self.run_every) - dt.timedelta(seconds=20)

    def can_enter(self, now: dt.datetime) -> bool:
        if self.square_off and now.time() >= self.square_off:
            return False
        return not (self.entry_until and now.time() > self.entry_until)

    def exit_reason(self, pos, ltp, now: dt.datetime, row: dict | None) -> str | None:
        """Why a held position should be sold now, or None to keep it."""
        if self.square_off and now.time() >= self.square_off:
            return "intraday square-off"
        if ltp:
            avg = pos.avg
            if self.stop_loss_pct and ltp <= avg * (1 - self.stop_loss_pct / 100):
                return f"stop loss {self.stop_loss_pct}%"
            if self.target_pct and ltp >= avg * (1 + self.target_pct / 100):
                return f"target {self.target_pct}%"
        held_for = now - pos.entry_at
        if self.max_hold_minutes and held_for >= dt.timedelta(minutes=self.max_hold_minutes):
            return f"time exit after {self.max_hold_minutes} min"
        if self.max_hold_days and held_for >= dt.timedelta(days=self.max_hold_days):
            return f"time exit after {self.max_hold_days} days"
        if row and row.get("signal") == "SELL":
            return "SELL signal"
        return None

    def meta(self) -> dict:
        return {"id": self.id, "name": self.name, "group": self.group, "stars": self.stars,
                "holding": self.holding, "blurb": self.blurb, "risk_note": self.risk_note,
                "ready": self.ready, "source": self.source, "interval": self.interval,
                "universes": self.universes, "default_universe": self.default_universe,
                "columns": self.columns, "product": self.product,
                "max_positions": self.max_positions, "min_amount": self.min_amount,
                "max_drawdown": self.max_drawdown, "warning": self.warning,
                "default_drawdown": self.default_drawdown, "max_price": self.max_price,
                "sl_from_drawdown": self.sl_from_drawdown, "use_gtt": self.use_gtt, "manual_scan": self.manual_scan,
                "once_per_day": self.once_per_day, "require_tradingview": self.require_tradingview, "suggest": self.suggest,
                "auto_trade": self.auto_trade, "match_minutes": self.match_minutes, "run_every": self.run_every,
                "window": [self.window[0].strftime("%H:%M"), self.window[1].strftime("%H:%M")],
                "exits_note": self.exits_note, "candle_label": self.candle_label,
                "exits": {"stop_loss_pct": self.stop_loss_pct, "target_pct": self.target_pct,
                          "max_hold_days": self.max_hold_days,
                          "max_hold_minutes": self.max_hold_minutes,
                          "square_off": self.square_off.strftime("%H:%M") if self.square_off else None}}
