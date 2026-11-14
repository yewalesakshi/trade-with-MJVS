"""
SCALPING (1 to 30 minutes) — STRATEGY PENDING.
Intraday (MIS), 1-minute candles, checks every minute, closes everything at 15:10.
To finish: set ready = True and either
  - keep source = "chartink" and point a Chartink alert at this algo's webhook, or
  - set source = "scan" and fill in symbols(), indicators() and signal().
Fill in stop_loss_pct / target_pct with your numbers.
"""
import datetime as dt

from .base import Algo


class Scalping(Algo):
    id = "scalping"
    name = "Scalping"
    stars = 2
    holding = "1–30 minutes"
    blurb = "Many short intraday trades. Brokerage and charges add up, so costs matter."
    ready = False
    source = "chartink"
    interval = "minute"
    product = "MIS"
    once_per_day = False
    run_every = 1
    window = (dt.time(9, 20), dt.time(15, 10))
    entry_until = dt.time(14, 45)
    square_off = dt.time(15, 10)
    max_hold_minutes = 30
    stop_loss_pct = None     # e.g. 0.5
    target_pct = None        # e.g. 1.0
