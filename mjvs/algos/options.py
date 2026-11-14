"""
OPTIONS — STRATEGY PENDING.
High risk can mean high profit; low risk means low profit. Patience matters for pension goals.
NFO, product NRML. Strike/expiry selection (order_symbol) and lots (quantity) come with your strategy.
"""
from .base import Algo


class Options(Algo):
    id = "options"
    name = "Options"
    group = "fno"
    stars = 2
    holding = "To be added"
    blurb = "High risk can mean high profit. Low risk means low profit."
    risk_note = "Options can expire worthless."
    ready = False
    source = "chartink"
    product = "NRML"
    min_amount = 10000
