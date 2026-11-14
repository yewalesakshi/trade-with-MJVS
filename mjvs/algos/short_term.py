"""
SHORT TERM (15–60 days) — STRATEGY PENDING.
Delivery (CNC). Entries from a Chartink scanner alert; exits by stop loss / target / 15-day limit.
To finish: set ready = True, set stop_loss_pct and target_pct, and point your Chartink
alert at this algo's webhook (Admin page).
"""
from .base import Algo


class ShortTerm(Algo):
    id = "short"
    name = "Short term"
    stars = 2
    holding = "15–60 days"
    blurb = "A few trades a month, each held for a few weeks."
    ready = False
    source = "chartink"
    product = "CNC"
    once_per_day = False     # Chartink alerts can arrive during the day
    run_every = 10
    max_hold_days = 60
    stop_loss_pct = None
    target_pct = None
    # Confirm the Chartink picks with your TradingView strategy (see ADDING_A_STRATEGY.txt):
    require_tradingview = False   # True: only stocks in BOTH Chartink and TradingView alerts
    auto_trade = True             # False: only show them on the Suggestions page
