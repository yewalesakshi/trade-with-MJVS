"""
PENNY STOCK — READY. Same rule as Swing, on WEEKLY candles. (Rule: mjvs/algos/rules.py)

BUY on the weekly candle where all three first become true together:
  1. close crosses above the 50 SMA        2. RSI(8) above 60        3. Bollinger %b(50, SD 1) above 51
EXIT: target 8% above the buy price, stop loss 5% below it (checked every 15 minutes).
Weekly candles are built from Kite's daily candles (weeks end Friday); the running week is
ignored until it is complete. A BUY stays valid for that week; each stock is bought once.
Scans ALL NSE stocks (shares the daily data Swing downloads). Small stocks can be illiquid.
"""
from . import rules
from .base import Algo, read_watchlist
from .universe import all_stocks
from .. import config

WEEKS_NEEDED = 65                      # about 15 months of weekly candles


class Penny(Algo):
    id = "penny"
    name = "Penny stock"
    stars = 1
    holding = "Weeks to months"
    blurb = "Lowest rating. Prices can swing sharply and be hard to sell."
    risk_note = "Penny stocks can be hard to sell and can fall sharply."
    ready = True
    source = "scan"
    suggest = True
    interval = "day"                      # fetched daily, turned into weekly candles below
    candle_label = "weekly"
    candles = WEEKS_NEEDED * 5 + 10
    universes = {"all": "All NSE stocks"}
    default_universe = "all"
    columns = rules.COLUMNS
    product = "CNC"
    max_positions = 5
    once_per_day = False
    run_every = 15
    reentry_days = 7                      # a weekly BUY is acted on once
    target_pct = 8
    stop_loss_pct = 5

    def symbols(self, universe, kite=None):
        listed = read_watchlist(universe) if universe != "all" else []
        if listed:
            return listed
        return all_stocks(kite) if kite else []

    def indicators(self, df):
        weekly = rules.to_weekly(df, config.ist_today())
        if len(weekly) < rules.MA_LENGTH + 2:
            raise ValueError(f"Only {len(weekly)} weeks of history (needs about {rules.MA_LENGTH + 2})")
        return rules.add_indicators(weekly)

    def signal(self, df):
        return "BUY" if bool(df["buy_signal"].iloc[-1]) else "HOLD"
