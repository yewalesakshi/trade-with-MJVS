"""
LONG TERM (5–10 years) — STRATEGY PENDING.
Delivery (CNC), daily candles, once a day. Exits only by your rule (or a wide stop).
"""
from .base import Algo


class LongTerm(Algo):
    id = "long"
    name = "Long term"
    stars = 2
    holding = "5–10 years"
    blurb = "Needs patience. Suits pension-style goals."
    ready = False
    source = "chartink"
    product = "CNC"
    max_positions = 10
