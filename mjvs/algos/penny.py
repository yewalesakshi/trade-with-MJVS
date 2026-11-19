"""
PENNY STOCK — READY. Same rule as Swing, on WEEKLY candles. (Rule: mjvs/algos/rules.py)

BUY on the weekly candle where all three first become true together:
  1. close crosses above the 50 SMA        2. RSI(8) above 60        3. Bollinger %b(50, SD 1) above 51
ONLY stocks under Rs 100 (checked on the live price before scanning and again before buying).
WEEKS: Monday to Friday. Each weekly candle is built from Kite's daily candles:
  open = first trading day's open, high/low = the week's high/low, close = last trading day's close.
  This week's candle is INCLUDED, built from Monday up to the last completed trading day,
  so a signal can appear mid-week (the candle can still change until Friday's close).
MONEY: up to 'Stocks to buy per day' NEW BUY stocks each day (strongest RSI first; stocks already held do not
  count), money split equally (e.g. Rs 1,000 / 5 -> Rs 200 each), or No limit with a fixed amount per stock.
EXIT: target 8% above the buy price; stop loss = the member's drawdown limit (default 5%) below it.
  The whole algo also stops if it falls that % from its peak. Checked every 15 minutes.
Each stock is bought once a week. Scans ALL NSE stocks under Rs 100. Small stocks can be illiquid.
LIVE MODE: right after each buy fills, a GTT OCO is created in the member's Zerodha account with
  both exits (target +8%, stop loss -drawdown%). Zerodha then sells by itself, even if MJVS is off.
  MJVS checks the GTT every run and records the sell when it triggers (see engine.sync_gtts).
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
    min_history = (rules.MA_LENGTH + 2) * 5   # 52 weeks of trading days is enough for the weekly rule
    universes = {"all": "All NSE stocks"}
    default_universe = "all"
    columns = rules.COLUMNS
    product = "CNC"
    max_positions = 5
    once_per_day = False
    run_every = 15
    reentry_days = 7                      # a weekly BUY is acted on once
    target_pct = 8
    stop_loss_pct = None                  # the stop loss is the member's drawdown limit (below)
    sl_from_drawdown = True               # stop loss % = drawdown slider (default 5%)
    default_drawdown = 5
    max_price = 100                       # only stocks under Rs 100
    max_positions = 5                     # new stocks to buy per scan (held stocks do not count)
    scan_buys = True                      # buys only from each NEW scan (once), Money = amount per scan
    manual_scan = True                    # scans only when "Scan now" is pressed; then trades at once
    use_gtt = True                        # Live: target + stop loss also placed as a Zerodha GTT (OCO)
    exits_note = ("Target 8% above the buy price. Stop loss = your drawdown limit (default 5%) below the buy price. "
                  "The whole algo also stops if it falls that % from its peak. "
                  "LIVE: both exits are also placed in your Zerodha account as a GTT (OCO), so Zerodha sells "
                  "even if MJVS is off.")

    def symbols(self, universe, kite=None):
        listed = read_watchlist(universe) if universe != "all" else []
        if listed:
            return listed
        return all_stocks(kite) if kite else []

    def indicators(self, df):
        weekly = rules.to_weekly(df, config.ist_today(), include_running=True)   # up to the last complete day
        if len(weekly) < rules.MA_LENGTH + 2:
            raise ValueError(f"Only {len(weekly)} weeks of history (needs about {rules.MA_LENGTH + 2})")
        return rules.add_indicators(weekly)

    def signal(self, df):
        return "BUY" if bool(df["buy_signal"].iloc[-1]) else "HOLD"
