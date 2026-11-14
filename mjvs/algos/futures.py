"""
NIFTY FUTURE SWING — READY. Trades only the NIFTY future (never NIFTY options).
Entries and exits use the NIFTY future's own 1-hour candles. Expected trade period 15-20 days.

A) BUY (long) when, on a completed 1-hour candle, all three first become true together:
     1. close crosses above the 50 SMA   2. RSI(8) above 60   3. Bollinger %b(50, SD 1) above 51
   Exit the long:
     Target     8% above the buy price
     Stop loss  ANY of: close below the 50 SMA, RSI(8) below 40, %b below 50 (on a completed
                1-hour candle), or 5% below the buy price
B) SELL (short): the moment the long's stop loss is hit, sell the NIFTY future (go short).
   Exit the short:
     Target     8% below the sell price
     Stop loss  5% above the sell price
     or a new BUY signal (A): cover the short and take the new long.

Price targets / stop losses are checked every 5 minutes; candle conditions once per new candle.
Contract: the near-month NIFTY future (the next month when expiry is 2 days away or less).
A position still open on its expiry day is closed at 15:00. Lots are worked out from the money:
about 15% of one lot's value is kept as margin (Zerodha checks the real margin).

Risk with leverage: one 5% NIFTY move is about a third of the margin money. So for this algo
  - the 5% stop loss above protects each trade (and still flips a long into a short),
  - the member's drawdown limit counts losses on CLOSED trades: once they reach the limit the
    algo stops taking new trades,
  - an emergency guard closes a position whose loss reaches twice the stop (10%), e.g. a gap.

Capital and risk rule: this algo needs at least Rs 2,00,000 and a risk (drawdown limit) of at
most 5%. A new long or short is placed ONLY when it has the 5% stop loss and both of these hold;
otherwise the algo still manages exits but opens nothing new.
"""
import datetime as dt
import json

from . import rules
from .base import Algo
from . import universe as uni

TARGET_PCT = 8
STOP_PCT = 5
MARGIN_PCT = 0.15
EXPIRY_EXIT = dt.time(15, 0)
EMERGENCY_PCT = 2 * STOP_PCT
MIN_CAPITAL = 200_000      # Rs 2 lakh
MAX_RISK_PCT = 5           # highest drawdown limit allowed


class NiftyFutureSwing(Algo):
    id = "futures"
    name = "NIFTY Future swing"
    group = "fno"
    stars = 2
    holding = "15–20 days"
    blurb = "Trades the NIFTY future on 1-hour candles: long on a BUY signal, short when the long's stop loss hits."
    risk_note = "Futures use leverage: losses can be larger than the margin you put in."
    warning = ("WARNING: this algo needs at least Rs 2,00,000 capital, and you trade it only if you can take "
               "a maximum 5% risk. A trade is executed only with its 5% stop loss.")
    min_amount = MIN_CAPITAL
    max_drawdown = MAX_RISK_PCT
    exits_note = ("Long: target 8%, stop loss 5% or close below 50 SMA / RSI below 40 / %b below 50, then it goes "
                  "SHORT. Short: target 8%, stop loss 5%, or a new BUY signal (covers and buys).")
    ready = True
    source = "scan"
    suggest = False
    interval = "60minute"
    candles = rules.WARMUP
    universes = {"niftyfut": "NIFTY future (near month)"}
    default_universe = "niftyfut"
    columns = rules.COLUMNS
    product = "NRML"
    max_positions = 1
    once_per_day = False
    run_every = 5
    window = (dt.time(9, 20), dt.time(15, 25))

    # ---------------------------------------------------------------- contract and scanner
    def contract(self, k, today: dt.date) -> dict | None:
        futs = sorted((r for r in uni.tradable_instruments(k)
                       if r["exchange"] == "NFO" and r["type"] == "FUT" and r["name"] == "NIFTY"),
                      key=lambda r: r["expiry"])
        for r in futs:
            if (dt.date.fromisoformat(r["expiry"]) - today).days > 2:
                return r
        return futs[-1] if futs else None

    def symbols(self, universe, kite=None):
        from .. import config
        c = self.contract(kite, config.ist_today()) if kite else None
        return [f"NFO:{c['symbol']}"] if c else []

    def indicators(self, df):
        return rules.add_indicators(df)

    def signal(self, df):
        last = df.iloc[-1]
        return "BUY" if bool(last["buy_signal"]) else "SELL" if bool(last["exit_ok"]) else "HOLD"

    # ---------------------------------------------------------------- trading
    def custom_run(self, s, k, sub, now: dt.datetime, manual: bool = False):
        from .. import broker, engine as eng
        st = json.loads(sub.state or "{}")
        today, notes = now.date(), []

        cash, held = eng.positions(s, sub)
        held = {sym: p for sym, p in held.items() if sym.startswith("NFO:")}
        if held:
            sym = next(iter(held))
            con = uni.find_instrument(k, sym)
        else:
            con = self.contract(k, today)
        if not con:
            sub.last_message = "NIFTY future contract not found in Kite's instrument list. Will retry."
            return
        full = f"NFO:{con['symbol']}"
        quote = k.ltp([full]).get(full)
        if not quote:
            sub.last_message = f"No price for {con['symbol']} right now. Will retry."
            return
        ltp, token = float(quote["last_price"]), quote["instrument_token"]
        pos = held.get(full)
        q = pos.qty if pos else 0

        def trade(side, qty, reason):
            res = eng.place(s, k, sub, self, full, side, qty, reason)
            notes.append(f"{'BOUGHT' if side == 'BUY' else 'SOLD'} {res[0]} {con['symbol']} @ {res[1]:.2f} ({reason})"
                         if res else f"{side} {con['symbol']} rejected by Kite")
            return res

        # Emergency guard: a gap far beyond the stop loss closes the position and stops the algo
        if q and pos.avg and abs(ltp - pos.avg) / pos.avg * 100 >= EMERGENCY_PCT and \
                ((q > 0 and ltp < pos.avg) or (q < 0 and ltp > pos.avg)):
            trade("SELL" if q > 0 else "BUY", abs(q), f"emergency: loss beyond {EMERGENCY_PCT}%")
            sub.running = False
            sub.last_message = "Emergency stop: the price gapped far past the stop loss. Position closed, algo stopped. " + "; ".join(notes)
            return

        df = rules.add_indicators(broker.history(k, token, self.interval, self.candles, now))
        if len(df) < rules.MA_LENGTH + 5:
            sub.last_message = "Not enough 1-hour candles yet for the NIFTY future. Will retry."
            return
        last = df.iloc[-1]
        candle = str(df.index[-1])
        new_candle = candle != st.get("candle")
        buy_signal = new_candle and bool(last["buy_signal"])
        weak = new_candle and bool(last["exit_ok"])

        lot = int(con.get("lot") or 1)
        lots = int(sub.amount // (ltp * lot * MARGIN_PCT)) if ltp else 0
        new_qty = lots * lot
        # New trades only with the 5% stop loss, Rs 2 lakh capital and at most 5% risk
        blocked = ("stop loss is not 5%" if STOP_PCT != 5 else
                   f"capital is below Rs {MIN_CAPITAL:,}" if sub.amount < MIN_CAPITAL else
                   f"risk (drawdown limit) is above {MAX_RISK_PCT}%" if sub.drawdown_pct > MAX_RISK_PCT else "")
        if blocked:
            new_qty = 0
        expiry = dt.date.fromisoformat(con["expiry"]) if con.get("expiry") else None
        expiry_close = bool(expiry and expiry == today and now.time() >= EXPIRY_EXIT)

        if q and expiry_close:
            trade("SELL" if q > 0 else "BUY", abs(q), "contract expiry today")
        elif q > 0:                                                    # A) long open
            avg = pos.avg
            stop_reason = (f"stop loss {STOP_PCT}%" if ltp <= avg * (1 - STOP_PCT / 100) else
                           "stop loss: " + ", ".join(x for x, ok in (
                               (f"close below {rules.MA_TYPE} {rules.MA_LENGTH}", last["close"] < last["ma"]),
                               (f"RSI below {rules.RSI_EXIT}", last["rsi"] < rules.RSI_EXIT),
                               (f"%b below {rules.PCTB_EXIT}", last["pctb"] < rules.PCTB_EXIT)) if ok) if weak else "")
            if ltp >= avg * (1 + TARGET_PCT / 100):
                trade("SELL", q, f"long target {TARGET_PCT}%")
            elif stop_reason:
                if trade("SELL", q, "long " + stop_reason):
                    if new_qty:                                        # B) go short at that moment
                        trade("SELL", new_qty, "short after the long's stop loss")
        elif q < 0:                                                    # B) short open
            avg = pos.avg
            if ltp <= avg * (1 - TARGET_PCT / 100):
                trade("BUY", -q, f"short target {TARGET_PCT}%")
            elif ltp >= avg * (1 + STOP_PCT / 100):
                trade("BUY", -q, f"short stop loss {STOP_PCT}%")
            elif buy_signal:
                if trade("BUY", -q, "new BUY signal: cover the short") and new_qty:
                    trade("BUY", new_qty, "BUY signal (RSI {:.1f}, %b {:.1f})".format(last["rsi"], last["pctb"]))
        elif buy_signal and not (expiry and expiry == today):           # flat: new long
            if blocked:
                notes.append(f"BUY signal, but no new trade: {blocked}. Press Start again with the right settings")
            elif new_qty:
                trade("BUY", new_qty, "BUY signal (RSI {:.1f}, %b {:.1f})".format(last["rsi"], last["pctb"]))
            else:
                need = ltp * lot * MARGIN_PCT
                notes.append(f"BUY signal, but the money is less than one lot needs (about Rs {need:,.0f})")

        st["candle"] = candle
        sub.state = json.dumps(st)
        cash_now, held_now = eng.positions(s, sub)
        p_now = held_now.get(full)
        if not held_now:                       # flat: drawdown limit on closed trades
            realized = cash_now                # with no position, cash = money + profit/loss of closed trades
            sub.peak_value = max(sub.peak_value or sub.amount, realized)
            down = (sub.peak_value - realized) / sub.peak_value * 100 if sub.peak_value > 0 else 0
            if down >= sub.drawdown_pct:
                sub.running = False
                sub.last_message = (f"Drawdown limit reached on closed trades: down {down:.1f}% from the peak "
                                    f"(Rs {sub.peak_value:,.0f}). Algo stopped. " + "; ".join(notes))
                return
        side = "LONG" if p_now and p_now.qty > 0 else "SHORT" if p_now and p_now.qty < 0 else "no position"
        head = ("Manual paper run" if manual else "Run") + f": {con['symbol']} {ltp:,.2f} · {side}" + \
               (f" {abs(p_now.qty)} @ {p_now.avg:,.2f}" if p_now else "") + \
               f" · last 1h candle: RSI {last['rsi']:.1f}, %b {last['pctb']:.1f}, {rules.MA_TYPE}50 {last['ma']:,.1f}"
        sub.last_message = head + (". " + "; ".join(notes) if notes else ". No trade needed.")
