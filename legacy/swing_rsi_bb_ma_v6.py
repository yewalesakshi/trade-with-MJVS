"""
SAVED COPY (not used by the app). To bring it back as the Swing algo, copy this file over
mjvs\algos\swing.py and change the import line to:  from .base import Algo, read_watchlist

SWING (3–6 months) — READY.
Strategy: "RSI + BB%B + MA Alignment Strategy v6 [FINAL]" (your TradingView Pine Script),
rebuilt in Python so the scanner runs on Kite data with the same results as TradingView.

  Bull alignment = close > SMA(50) and RSI(8) > 40 and BB %B(50, 1.0) > 0.50
  Bear alignment = close < SMA(50) and RSI(8) < 60 and BB %B(50, 1.0) < 0.50
  BUY  = bull alignment starts on this candle   (bull_alignment and not bull_alignment[1])
  SELL = bear alignment (the strategy reverses long -> short there; delivery cannot short,
         so the algo sells and waits for the next BUY)

Daily candles, completed candles only. Like TradingView's default strategy fills, a signal
on today's close is acted on at the next market open (the algo runs at 9:20).
The session filter in the Pine Script is off by default and has no effect on daily candles.
"""
import numpy as np
import pandas as pd

from mjvs.algos.base import Algo, read_watchlist

# === INPUTS (same names and defaults as the Pine Script) ===
MA_LENGTH = 50
RSI_LENGTH = 8
RSI_OB = 60
RSI_OS = 40
BB_LENGTH = 50
BB_MULT = 1.0
PBB_LONG_LEVEL = 0.5
PBB_SHORT_LEVEL = 0.5
ENTRY_LOOKBACK = 1      # 1 = only a BUY on the latest candle, exactly like the Pine Script.
                        # 2-3 also catches a BUY missed on a holiday or a day without Kite login.

# Indices cannot be bought: signals use the index, orders go to an ETF.
INDEX_TO_ETF = {"NSE:NIFTY 50": "NSE:NIFTYBEES", "NSE:NIFTY BANK": "NSE:BANKBEES"}


# === INDICATORS (match Pine's ta.sma, ta.rsi, ta.stdev) ===
def pine_rma(x: pd.Series, n: int) -> pd.Series:
    """ta.rma: seeded with the SMA of the first n values, then (prev*(n-1) + x) / n."""
    v = x.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    valid = np.flatnonzero(~np.isnan(v))
    if len(valid) < n:
        return pd.Series(out, index=x.index)
    start = valid[0] + n - 1
    out[start] = np.nanmean(v[valid[0]:start + 1])
    for i in range(start + 1, len(v)):
        out[i] = (out[i - 1] * (n - 1) + v[i]) / n
    return pd.Series(out, index=x.index)


def pine_rsi(close: pd.Series, n: int) -> pd.Series:
    ch = close.diff()
    up = pine_rma(ch.clip(lower=0), n)
    down = pine_rma((-ch).clip(lower=0), n)
    rsi = 100 - 100 / (1 + up / down)
    rsi = rsi.where(down != 0, 100.0).where(up != 0, 0.0)
    return rsi.where(up.notna() & down.notna())


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["close"]
    df["sma"] = c.rolling(MA_LENGTH).mean()
    df["rsi"] = pine_rsi(c, RSI_LENGTH)
    basis = c.rolling(BB_LENGTH).mean()
    dev = BB_MULT * c.rolling(BB_LENGTH).std(ddof=0)          # ta.stdev is the population stdev
    df["pctb"] = (c - (basis - dev)) / ((basis + dev) - (basis - dev))
    ready = df["sma"].notna() & df["rsi"].notna() & df["pctb"].notna()
    df["bull"] = ready & (c > df["sma"]) & (df["rsi"] > RSI_OS) & (df["pctb"] > PBB_LONG_LEVEL)
    df["bear"] = ready & (c < df["sma"]) & (df["rsi"] < RSI_OB) & (df["pctb"] < PBB_SHORT_LEVEL)
    prev_bull = df["bull"].shift(1, fill_value=False).astype(bool)
    prev_bear = df["bear"].shift(1, fill_value=False).astype(bool)
    df["long_signal"] = df["bull"] & ~prev_bull
    df["short_signal"] = df["bear"] & ~prev_bear
    df["trend"] = np.where(df["bull"], "Bull", np.where(df["bear"], "Bear", "Mixed"))
    return df


def signal_of(df: pd.DataFrame, lookback: int = ENTRY_LOOKBACK) -> str:
    last = df.iloc[-1]
    if bool(last["bear"]):
        return "SELL"
    recent = df.iloc[-max(1, lookback):]
    if bool(last["bull"]) and bool(recent["long_signal"].any()):
        return "BUY"
    return "HOLD"


class Swing(Algo):
    id = "swing"
    name = "Swing"
    stars = 2
    holding = "3–6 months"
    blurb = "Fewer trades, held through short market swings."
    ready = True
    source = "scan"
    suggest = True                      # fresh BUY signals appear on the Suggestions page
    interval = "day"
    candles = max(MA_LENGTH, BB_LENGTH) + 60
    universes = {"nifty50": "NIFTY 50 stocks", "index": "Index ETFs (NIFTY, BANKNIFTY)"}
    default_universe = "nifty50"
    columns = [("rsi", f"RSI {RSI_LENGTH}"), ("pctb", f"%B {BB_LENGTH}"), ("sma", f"MA {MA_LENGTH}"), ("trend", "Trend")]
    product = "CNC"
    max_positions = 5

    def symbols(self, universe):
        return list(INDEX_TO_ETF) if universe == "index" else read_watchlist(universe)

    def indicators(self, df):
        return add_indicators(df)

    def signal(self, df):
        return signal_of(df)

    def order_symbol(self, signal_symbol):
        return INDEX_TO_ETF.get(signal_symbol, signal_symbol)

    def signal_symbol(self, order_symbol):
        for sig, order in INDEX_TO_ETF.items():
            if order == order_symbol:
                return sig
        return order_symbol
