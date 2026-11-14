"""
INTRADAY (same day, 1 day) — STRATEGY PENDING.
Intraday (MIS): every position is opened and closed on the same trading day.
New entries stop at 14:45 and everything is squared off at 15:10, before Zerodha's own
automatic square-off. Checks every 5 minutes on 15-minute candles.
To finish: set ready = True, then either keep source = "chartink" (Chartink alert) or set
source = "scan" and fill in symbols(), indicators() and signal(). Fill in stop loss / target.
"""
import datetime as dt

from .base import Algo


class Intraday(Algo):
    id = "intraday"
    name = "Intraday"
    stars = 2
    holding = "Same day (1 day)"
    blurb = "Buys and sells within the same trading day. Nothing is carried overnight."
    risk_note = "Intraday positions are closed by 3:10 pm, even at a loss."
    ready = False
    source = "chartink"
    interval = "15minute"
    product = "MIS"
    once_per_day = False
    run_every = 5
    window = (dt.time(9, 20), dt.time(15, 10))
    entry_until = dt.time(14, 45)
    square_off = dt.time(15, 10)
    stop_loss_pct = None     # e.g. 1.0
    target_pct = None        # e.g. 2.0
