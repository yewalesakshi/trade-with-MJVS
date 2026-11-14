"""
The MJVS buy/exit rule shared by Swing (daily), Penny stock (weekly) and NIFTY Future (1 hour).

BUY when, on a completed candle:
  1. close crosses above the 50 moving average   (MA_TYPE "SMA" or "EMA")
  2. RSI(8) on close is above 60
  3. Bollinger %b(50, SD 1, SMA) is above 51      (%b shown on a 0-100 scale)
"Cross above" = the candle where all three first become true together (they were not all true on
the candle before), so a stock that has been strong for weeks is not a new BUY.

INDICATOR EXIT (used by NIFTY Future long trades) when ANY one turns weak:
  close below the 50 MA, or RSI(8) below 40, or %b below 50
Indicators follow TradingView's formulas (ta.sma / ta.ema / ta.rsi / ta.stdev).
"""
import numpy as np
import pandas as pd

MA_TYPE = "SMA"        # "SMA" or "EMA" for condition 1
MA_LENGTH = 50
RSI_LENGTH = 8
RSI_BUY = 60
RSI_EXIT = 40
BB_LENGTH = 50
BB_SD = 1.0
PCTB_BUY = 51          # %b on a 0-100 scale
PCTB_EXIT = 50
WARMUP = max(MA_LENGTH, BB_LENGTH) + 60     # candles needed before the first reliable value


def rma(x: pd.Series, n: int) -> pd.Series:
    """TradingView ta.rma: seeded with the SMA of the first n values."""
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


def rsi(close: pd.Series, n: int) -> pd.Series:
    ch = close.diff()
    up, down = rma(ch.clip(lower=0), n), rma((-ch).clip(lower=0), n)
    out = 100 - 100 / (1 + up / down)
    out = out.where(down != 0, 100.0).where(up != 0, 0.0)
    return out.where(up.notna() & down.notna())


def moving_average(close: pd.Series, n: int, kind: str) -> pd.Series:
    if kind.upper() == "EMA":       # ta.ema: seeded with the SMA, alpha 2/(n+1)
        v = close.to_numpy(dtype=float)
        out = np.full(len(v), np.nan)
        if len(v) >= n:
            out[n - 1] = v[:n].mean()
            a = 2 / (n + 1)
            for i in range(n, len(v)):
                out[i] = a * v[i] + (1 - a) * out[i - 1]
        return pd.Series(out, index=close.index)
    return close.rolling(n).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["close"].astype(float)
    df["ma"] = moving_average(c, MA_LENGTH, MA_TYPE)
    df["rsi"] = rsi(c, RSI_LENGTH)
    basis = c.rolling(BB_LENGTH).mean()
    dev = BB_SD * c.rolling(BB_LENGTH).std(ddof=0)
    df["pctb"] = (c - (basis - dev)) / (2 * dev) * 100
    ok = df["ma"].notna() & df["rsi"].notna() & df["pctb"].notna()
    df["buy_ok"] = ok & (c > df["ma"]) & (df["rsi"] > RSI_BUY) & (df["pctb"] > PCTB_BUY)
    df["exit_ok"] = ok & ((c < df["ma"]) | (df["rsi"] < RSI_EXIT) | (df["pctb"] < PCTB_EXIT))
    df["buy_signal"] = df["buy_ok"] & ~df["buy_ok"].shift(1, fill_value=False).astype(bool)
    df["trend"] = np.where(df["buy_ok"], "Bull", np.where(df["exit_ok"], "Weak", "Mixed"))
    return df


def to_weekly(df: pd.DataFrame, today) -> pd.DataFrame:
    """Daily candles -> weekly candles (weeks end Friday). The running week is dropped."""
    d = df.copy()
    d.index = pd.to_datetime(d.index)
    if d.index.tz is not None:
        d.index = d.index.tz_localize(None)
    w = d.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    w = w.dropna(subset=["close"])
    return w[w.index.date < today]      # a week ending today or later is not complete yet


COLUMNS = [("rsi", f"RSI {RSI_LENGTH}"), ("pctb", f"%b {BB_LENGTH}"), ("ma", f"{MA_TYPE} {MA_LENGTH}"), ("trend", "Trend")]
