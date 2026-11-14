"""
============================================================================
  INDEX STRATEGY  —  Zerodha (Kite Connect)
============================================================================
  Indicators (exactly as per your screenshots, all on daily CLOSE):
    - RSI         : period 8   | overbought 60 | oversold 40
    - Bollinger %b: period 50  | 1 std dev | simple MA | OB 51 | OS 50
    - SMA         : period 50
  Timeframe : daily
  Universe  : indices (NIFTY 50, NIFTY BANK, etc.)
  Broker    : Zerodha

  HOW TO USE
    1) pip install kiteconnect pandas numpy
    2) Fill in the CONFIG section.
    3) Run a BACKTEST first (MODE = "backtest") — uses no real money.
    4) Only switch MODE = "live" once the backtest behaves as you expect.

  THE ONE THING YOU MAY NEED TO CHANGE
    Your screenshots define the indicators but not the buy/sell *rule*.
    That rule lives in ONE place: the generate_signal() function below.
    I implemented a long-only trend-confluence rule. If your rule is
    different (e.g. mean reversion / opposite direction), edit only that
    function — nothing else needs to change.
============================================================================
"""

import time
import datetime as dt

import numpy as np
import pandas as pd
from kiteconnect import KiteConnect


# ===========================================================================
#  CONFIG  — fill these in
# ===========================================================================
API_KEY       = "your_api_key"
API_SECRET    = "your_api_secret"
ACCESS_TOKEN  = "your_access_token"   # generated daily via the login flow

MODE          = "backtest"            # "backtest"  or  "live"
CAPITAL       = 100_000               # rupees, used for position sizing
BACKTEST_DAYS = 500                   # how many daily candles to test on

# Indicator parameters (locked to your screenshots) ------------------------
RSI_PERIOD       = 8
RSI_OVERBOUGHT   = 60
RSI_OVERSOLD     = 40

BB_PERIOD        = 50
BB_STD           = 1
BB_OVERBOUGHT    = 51     # %b on a 0-100 scale (51 = just above the middle band)
BB_OVERSOLD      = 50

SMA_PERIOD       = 50

# Universe ------------------------------------------------------------------
# Signals are computed on the INDEX. Zerodha does NOT let you place an order
# on the raw index (NIFTY/BANKNIFTY spot), so each index maps to a tradeable
# symbol used for live orders. ETFs are the simplest tradeable proxy for a
# daily long strategy; swap to FUT contracts if you prefer.
UNIVERSE = {
    # signal instrument (for data)   ->  order instrument (for live orders)
    "NSE:NIFTY 50":   "NSE:NIFTYBEES",
    "NSE:NIFTY BANK": "NSE:BANKBEES",
}

ORDER_PRODUCT = "CNC"     # CNC = delivery (positional). Use "MIS" for intraday.


# ===========================================================================
#  INDICATORS  (match the screenshots exactly)
# ===========================================================================
def rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(period).mean()


def bollinger_pct_b(close: pd.Series, period: int, num_std: float) -> pd.Series:
    """Bollinger %b on a 0-100 scale (50 = price sitting on the middle band)."""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return (close - lower) / (upper - lower) * 100


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rsi"]  = rsi(df["close"], RSI_PERIOD)
    df["sma"]  = sma(df["close"], SMA_PERIOD)
    df["pctb"] = bollinger_pct_b(df["close"], BB_PERIOD, BB_STD)
    return df


# ===========================================================================
#  SIGNAL RULE  <-- EDIT HERE IF YOUR BUY/SELL RULE IS DIFFERENT
# ===========================================================================
def generate_signal(row: pd.Series) -> str:
    """
    Returns "BUY", "SELL", or "HOLD" for one daily candle.

    Current rule = bullish trend confluence (long-only):
      BUY  when ALL are bullish : RSI > 60  AND  %b > 51  AND  close > SMA50
      SELL when ANY  turns bearish: RSI < 40  OR   %b < 50  OR   close < SMA50
    """
    if pd.isna(row["rsi"]) or pd.isna(row["sma"]) or pd.isna(row["pctb"]):
        return "HOLD"

    bullish = (row["rsi"] > RSI_OVERBOUGHT) and \
              (row["pctb"] > BB_OVERBOUGHT) and \
              (row["close"] > row["sma"])

    bearish = (row["rsi"] < RSI_OVERSOLD) or \
              (row["pctb"] < BB_OVERSOLD) or \
              (row["close"] < row["sma"])

    if bullish:
        return "BUY"
    if bearish:
        return "SELL"
    return "HOLD"


# ===========================================================================
#  DATA
# ===========================================================================
def get_kite() -> KiteConnect:
    kite = KiteConnect(api_key=API_KEY)
    kite.set_access_token(ACCESS_TOKEN)
    return kite


def fetch_daily(kite: KiteConnect, symbol: str, days: int) -> pd.DataFrame:
    """Fetch daily OHLC for an instrument symbol like 'NSE:NIFTY 50'."""
    token = kite.ltp(symbol)[symbol]["instrument_token"]
    end = dt.date.today()
    start = end - dt.timedelta(days=int(days * 1.6) + 60)  # pad for weekends/holidays
    candles = kite.historical_data(token, start, end, "day")
    df = pd.DataFrame(candles)
    df = df[["date", "open", "high", "low", "close", "volume"]]
    df.set_index("date", inplace=True)
    return df.tail(days)


# ===========================================================================
#  BACKTEST  (no real money)
# ===========================================================================
def backtest(df: pd.DataFrame, capital: float) -> pd.DataFrame:
    df = add_indicators(df)
    df["signal"] = df.apply(generate_signal, axis=1)

    cash = capital
    qty = 0
    equity_curve = []
    trades = []

    # "Target open": act on the signal at the NEXT day's open.
    opens = df["open"].shift(-1)

    for i, (date, row) in enumerate(df.iterrows()):
        next_open = opens.iloc[i]
        if pd.isna(next_open):
            equity_curve.append(cash + qty * row["close"])
            continue

        if row["signal"] == "BUY" and qty == 0:
            qty = int(cash // next_open)
            cash -= qty * next_open
            trades.append((date, "BUY", next_open, qty))

        elif row["signal"] == "SELL" and qty > 0:
            cash += qty * next_open
            trades.append((date, "SELL", next_open, qty))
            qty = 0

        equity_curve.append(cash + qty * next_open)

    df["equity"] = equity_curve
    final = df["equity"].iloc[-1]
    ret = (final / capital - 1) * 100

    print(f"  Start capital : Rs {capital:,.0f}")
    print(f"  End equity    : Rs {final:,.0f}")
    print(f"  Return        : {ret:+.2f}%")
    print(f"  Trades        : {len(trades)}")
    print(f"  Buy & hold    : {(df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100:+.2f}%")
    return df


# ===========================================================================
#  LIVE TRADING  (places real orders — handle with care)
# ===========================================================================
def run_live(kite: KiteConnect):
    """
    Computes the signal on the latest completed daily candle for each index
    and places a market order on the mapped tradeable symbol.
    NOTE: Under SEBI's 2026 rules every algo order must be tagged/registered
    with your broker before it will be accepted. Confirm your API + algo are
    approved by Zerodha before relying on this in production.
    """
    for signal_sym, order_sym in UNIVERSE.items():
        df = add_indicators(fetch_daily(kite, signal_sym, SMA_PERIOD + 30))
        latest = df.iloc[-1]
        signal = generate_signal(latest)
        print(f"{signal_sym}: signal = {signal} "
              f"(rsi={latest['rsi']:.1f}, %b={latest['pctb']:.1f}, "
              f"close={latest['close']:.1f}, sma={latest['sma']:.1f})")

        if signal == "HOLD":
            continue

        exch, tradingsymbol = order_sym.split(":")
        ltp = kite.ltp(order_sym)[order_sym]["last_price"]
        qty = int(CAPITAL // ltp)
        if qty < 1:
            print(f"  capital too small for one unit of {order_sym}")
            continue

        transaction = kite.TRANSACTION_TYPE_BUY if signal == "BUY" \
            else kite.TRANSACTION_TYPE_SELL

        order_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=exch,
            tradingsymbol=tradingsymbol,
            transaction_type=transaction,
            quantity=qty,
            product=ORDER_PRODUCT,
            order_type=kite.ORDER_TYPE_MARKET,
            tag="index_strategy",
        )
        print(f"  placed {signal} {qty} {order_sym}  order_id={order_id}")


# ===========================================================================
#  MAIN
# ===========================================================================
def main():
    kite = get_kite()

    if MODE == "backtest":
        for signal_sym in UNIVERSE:
            print(f"\n=== Backtest: {signal_sym} ===")
            df = fetch_daily(kite, signal_sym, BACKTEST_DAYS)
            backtest(df, CAPITAL)

    elif MODE == "live":
        print(f"\n=== LIVE run @ {dt.datetime.now():%Y-%m-%d %H:%M} ===")
        run_live(kite)

    else:
        raise ValueError("MODE must be 'backtest' or 'live'")


if __name__ == "__main__":
    main()
