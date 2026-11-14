"""
SWING — READY. Daily candles. (Rule: mjvs/algos/rules.py)

BUY on the daily candle where all three first become true together:
  1. close crosses above the 50 SMA        2. RSI(8) above 60        3. Bollinger %b(50, SD 1) above 51
EXIT: target 8% above the buy price, stop loss 5% below it.
Signals use completed daily candles (checked from 9:20). Target and stop loss are checked
every 15 minutes during market hours. Scans ALL NSE stocks (about 2,000; 10-15 minutes).
(Earlier strategy versions are kept in the legacy folder.)
"""
from . import rules
from .base import Algo, read_watchlist
from .universe import all_stocks

INDEX_TO_ETF = {"NSE:NIFTY 50": "NSE:NIFTYBEES", "NSE:NIFTY BANK": "NSE:BANKBEES"}


class Swing(Algo):
    id = "swing"
    name = "Swing"
    stars = 2
    holding = "3–6 months"
    blurb = "Fewer trades, held through short market swings."
    ready = True
    source = "scan"
    suggest = True
    interval = "day"
    candles = rules.WARMUP
    universes = {"all": "All NSE stocks"}
    default_universe = "all"
    columns = rules.COLUMNS
    product = "CNC"
    max_positions = 5
    once_per_day = False      # entries from the daily scan; target / stop loss checked through the day
    run_every = 15
    target_pct = 8
    stop_loss_pct = 5

    def symbols(self, universe, kite=None):
        if universe == "index":          # older setting (not offered on the site any more)
            return list(INDEX_TO_ETF)
        listed = read_watchlist(universe) if universe != "all" else []
        if listed:                       # a watchlists/<name>.txt file, if one is chosen
            return listed
        return all_stocks(kite) if kite else []

    def indicators(self, df):
        return rules.add_indicators(df)

    def signal(self, df):
        return "BUY" if bool(df["buy_signal"].iloc[-1]) else "HOLD"

    def order_symbol(self, signal_symbol):
        return INDEX_TO_ETF.get(signal_symbol, signal_symbol)

    def signal_symbol(self, order_symbol):
        for sig, order in INDEX_TO_ETF.items():
            if order == order_symbol:
                return sig
        return order_symbol
