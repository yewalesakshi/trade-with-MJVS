"""
SWING — READY. Daily candles. (Rule: mjvs/algos/rules.py)

BUY on the daily candle where all three first become true together:
  1. close crosses above the 50 SMA        2. RSI(8) above 60        3. Bollinger %b(50, SD 1) above 51
Signals use the last completed trading day (checked from 9:20). Scans ALL NSE stocks, no price limit.
MONEY: the top 5 BUY stocks (strongest RSI first), money split equally. A stock that costs more than
  one slot's money is skipped and the next BUY stock is bought instead, so the slots still fill.
EXIT: target 8% above the buy price; stop loss ALWAYS 5% below the buy price (fixed).
  The drawdown limit is separate: it stops the whole algo if it falls that % from its peak.
  Checked every 15 minutes.
LIVE MODE: after each buy fills, a GTT OCO (target + stop loss) is created in Zerodha, which then
  sells by itself even if MJVS is off; MJVS records the sell at its next check (engine.sync_gtts).
(Earlier strategy versions are kept in the legacy folder.)
"""
from . import rules
from .base import Algo, read_watchlist
from .universe import all_stocks


class Swing(Algo):
    id = "swing"
    name = "Swing"
    stars = 2
    holding = "Days to weeks"
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
    stop_loss_pct = 5                     # fixed: always 5% below the buy price
    manual_scan = True                    # scans only when "Scan now" is pressed; then trades at once
    use_gtt = True                        # Live: target + stop loss also placed as a Zerodha GTT (OCO)
    exits_note = ("Target 8% above the buy price. Stop loss always 5% below the buy price. "
                  "The drawdown limit stops the whole algo if it falls that % from its peak. "
                  "LIVE: both exits are also placed in your Zerodha account as a GTT (OCO), so Zerodha sells "
                  "even if MJVS is off.")

    def symbols(self, universe, kite=None):
        listed = read_watchlist(universe) if universe != "all" else []
        if listed:                       # a watchlists/<name>.txt file, if one is chosen
            return listed
        return all_stocks(kite) if kite else []

    def indicators(self, df):
        return rules.add_indicators(df)

    def signal(self, df):
        return "BUY" if bool(df["buy_signal"].iloc[-1]) else "HOLD"
