"""
The trading engine. Every minute on market days it finds subscriptions that are due and:
  1. works out the algo's entry signals ONCE (scanner or new Chartink alerts),
  2. then for each member: drawdown guard -> exits -> entries, in that member's own Kite account.
Paper mode records trades at the live price without sending orders.
"""
import json
import time
import threading
import datetime as dt
from dataclasses import dataclass

import pandas as pd
from sqlalchemy.orm import Session

from . import broker, config
from .algos import ALGOS
from .db import engine as db_engine, Member, Subscription, Trade, Signal, Suggestion, AlgoState, now_ist
from . import signals as sigmod

COUNTED = ("COMPLETE", "PENDING", "PAPER")    # rejected orders never count


@dataclass
class Position:
    qty: int = 0
    cost: float = 0.0
    entry_at: dt.datetime | None = None   # IST time of the first buy of the open lot

    @property
    def avg(self):
        return self.cost / self.qty if self.qty else 0.0


def token_fresh(m: Member) -> bool:
    """Kite access tokens expire every morning, so only a login from today counts."""
    return bool(m.kite_token) and m.kite_token_date == config.ist_today()


def mode_of(sub) -> str:
    return "paper" if sub.paper else "live"


def to_ist(t: dt.datetime) -> dt.datetime:
    """Database times are IST without a label; this adds the label."""
    return t.replace(tzinfo=config.IST)


# ---------------------------------------------------------------- ledger
def positions(s: Session, sub: Subscription, mode: str | None = None):
    """Cash left and open positions, from this subscription's own trades."""
    mode = mode or mode_of(sub)
    cash, pos = sub.amount, {}
    trades = (s.query(Trade).filter(Trade.member_id == sub.member_id, Trade.algo_id == sub.algo_id,
                                    Trade.mode == mode, Trade.status.in_(COUNTED))
              .order_by(Trade.id).all())
    for t in trades:
        p = pos.setdefault(t.symbol, Position())
        q = t.qty if t.side == "BUY" else -t.qty          # signed: shorts (futures) are negative
        cash -= q * t.price
        if p.qty == 0 or (p.qty > 0) == (q > 0):          # opening or adding
            if p.qty == 0:
                p.cost, p.entry_at = 0.0, to_ist(t.at)
            p.cost += q * t.price
            p.qty += q
        else:                                             # reducing, closing or flipping
            closing = min(abs(q), abs(p.qty))
            p.cost -= (1 if p.qty > 0 else -1) * closing * (p.cost / p.qty)
            p.qty += q
            if p.qty == 0:
                p.cost = 0.0
            elif abs(q) > closing:                        # flipped to the other side
                p.cost, p.entry_at = p.qty * t.price, to_ist(t.at)
    return cash, {sym: p for sym, p in pos.items() if p.qty != 0}


def account_value(cash, held: dict, prices: dict) -> float:
    return cash + sum(p.qty * prices.get(sym, p.avg) for sym, p in held.items())


# ---------------------------------------------------------------- scanner
def algo_symbols(algo, universe: str, k) -> list[str]:
    """The algo's stock list; lists like 'under100' are built live from Kite."""
    try:
        return list(algo.symbols(universe, kite=k))
    except TypeError:
        return list(algo.symbols(universe))


def scan(algo, k, symbols: list[str], now: dt.datetime, progress=None) -> list[dict]:
    """Runs the algo's rule on every symbol. BUY first, strongest RSI (if any) first."""
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return []
    quotes = {}
    for i in range(0, len(symbols), 500):
        quotes.update(k.ltp(symbols[i:i + 500]))

    def one(sym):
        base = {"symbol": sym, "trade_symbol": algo.order_symbol(sym)}
        q = quotes.get(sym)
        if not q:
            return {**base, "signal": "ERROR", "error": "Symbol not found on Kite"}
        if algo.max_price and float(q.get("last_price") or 0) >= algo.max_price:
            return None              # e.g. Penny stock: only stocks under Rs 100 (no download needed)
        try:
            df = broker.history(k, q["instrument_token"], algo.interval, algo.candles, now)
            if len(df) < getattr(algo, "min_history", algo.candles - 30):
                raise ValueError("Not enough price history")
            df = algo.indicators(df)
            last = df.iloc[-1]
            row = {**base, "ltp": float(q["last_price"]), "close": round(float(last["close"]), 2),
                   "candle": str(pd.Timestamp(df.index[-1]))[:16], "signal": algo.signal(df)}
            for key, _ in algo.columns:
                v = last.get(key)
                if isinstance(v, str):
                    row[key] = v
                else:
                    row[key] = None if v is None or pd.isna(v) else round(float(v), 3 if abs(float(v)) < 10 else 2)
            return row
        except (broker.TokenError, broker.PermissionError_):
            raise                # a login or plan problem: stop instead of failing every stock
        except Exception as e:   # one bad symbol must not stop the scan
            return {**base, "signal": "ERROR", "error": str(e)[:120]}

    # Downloads run in parallel threads; broker keeps them within Kite's ~3 charts a second.
    from concurrent.futures import ThreadPoolExecutor
    rows, done, lock, stop = [None] * len(symbols), [0], threading.Lock(), threading.Event()

    def work(i, sym):
        if stop.is_set():
            return
        try:
            rows[i] = one(sym)
        except Exception:
            stop.set()
            raise
        finally:
            with lock:
                done[0] += 1
                if progress:
                    progress(done[0], len(symbols))

    try:
        with ThreadPoolExecutor(max_workers=broker.SCAN_THREADS) as pool:
            futures = [pool.submit(work, i, sym) for i, sym in enumerate(symbols)]
            for f in futures:
                f.result()           # re-raises a Kite login / plan error from any thread
    finally:
        if algo.interval == "day":
            broker.save_day_cache()
    rows = [r for r in rows if r]
    order = {"BUY": 0, "HOLD": 1, "SELL": 2, "ERROR": 3}
    first_col = algo.columns[0][0] if algo.columns else None
    rows.sort(key=lambda r: (order.get(r["signal"], 9), -((r.get(first_col) or 0) if first_col else 0)))
    return rows


def save_scan(s: Session, algo_id: str, universe: str, rows: list[dict]):
    key = f"{algo_id}:{universe}"
    st = s.get(AlgoState, key) or AlgoState(key=key)
    st.scan, st.scan_at = json.dumps(rows), now_ist()
    s.merge(st)
    s.commit()
    sigmod.refresh_suggestions(s, algo_id)


# ---------------------------------------------------------------- orders
def place(s: Session, k, sub: Subscription, algo, symbol: str, side: str, qty: int, reason: str):
    """Paper: record only. Live: market order + real fill. Returns (qty, price) or None if rejected."""
    mode = mode_of(sub)
    ltp = broker.ltp_many(k, [symbol])[symbol]
    common = dict(member_id=sub.member_id, algo_id=sub.algo_id, symbol=symbol, side=side, mode=mode)
    if sub.paper:
        s.add(Trade(**common, qty=qty, price=ltp, status="PAPER", reason=reason,
                    order_id=f"PAPER-{int(time.time() * 1000)}"))
        s.commit()
        return qty, ltp
    from .settings_store import allow_live
    if not allow_live():
        raise RuntimeError("Live trading is switched off (Admin page -> Live trading)")
    try:
        order_id = broker.send_order(k, symbol, side, qty, algo.product)
    except broker.PermissionError_ as e:        # e.g. static IP not whitelisted: not a market-data problem
        raise broker.OrderRefused(broker.order_refused(e))
    st, avg, filled, msg = broker.wait_for_fill(k, order_id)
    if st == "COMPLETE" or (st in ("REJECTED", "CANCELLED") and filled):
        t = Trade(**common, qty=filled or qty, price=avg or ltp, status="COMPLETE", reason=reason, order_id=order_id)
    elif st in ("REJECTED", "CANCELLED"):
        t = Trade(**common, qty=qty, price=ltp, status="REJECTED", reason=(msg or st)[:200], order_id=order_id)
    else:
        t = Trade(**common, qty=qty, price=ltp, status="PENDING", reason=reason, order_id=order_id)
    s.add(t)
    s.commit()
    return None if t.status == "REJECTED" else (t.qty, t.price)


def reconcile_pending(s: Session, k, sub: Subscription):
    """Fix up live orders that had not filled when they were recorded."""
    for t in s.query(Trade).filter_by(member_id=sub.member_id, algo_id=sub.algo_id,
                                      mode="live", status="PENDING").all():
        try:
            last = k.order_history(t.order_id)[-1]
        except Exception:
            continue
        st, filled = last.get("status"), int(last.get("filled_quantity") or 0)
        if st == "COMPLETE" or (st in ("REJECTED", "CANCELLED") and filled):
            t.status, t.qty = "COMPLETE", filled or t.qty
            t.price = float(last.get("average_price") or t.price)
        elif st in ("REJECTED", "CANCELLED"):
            t.status, t.reason = "REJECTED", (last.get("status_message") or st)[:200]
    s.commit()


# ---------------------------------------------------------------- GTT exits at Zerodha (live only)
GTT_LIVE = ("active", "triggered")      # Zerodha still owns the exit of this position


def opening_buy(s: Session, sub: Subscription, symbol: str):
    """The live BUY that opened the current position in `symbol` (it carries the GTT)."""
    return (s.query(Trade).filter(Trade.member_id == sub.member_id, Trade.algo_id == sub.algo_id,
                                  Trade.mode == "live", Trade.symbol == symbol, Trade.side == "BUY",
                                  Trade.status == "COMPLETE").order_by(Trade.id.desc()).first())


def gtt_managed(s: Session, sub: Subscription, symbol: str) -> bool:
    t = opening_buy(s, sub, symbol)
    return bool(t and t.gtt_id and t.gtt_status in GTT_LIVE)


def ensure_gtts(s: Session, k, sub: Subscription, algo, notes: list):
    """Every live position without a GTT gets one: OCO with the target and the stop loss."""
    _, held = positions(s, sub)
    for sym, p in held.items():
        if p.qty <= 0:
            continue
        t = opening_buy(s, sub, sym)
        if not t or (t.gtt_id and t.gtt_status not in ("cancelled", "deleted", "expired", "disabled", "rejected")):
            continue
        sl_pct = sub.drawdown_pct if algo.sl_from_drawdown else (algo.stop_loss_pct or 5)
        sl, tg = p.avg * (1 - sl_pct / 100), p.avg * (1 + (algo.target_pct or 8) / 100)
        name = sym.split(":")[1]
        try:
            ltp = broker.ltp_many(k, [sym]).get(sym) or p.avg
            if not sl < ltp < tg:          # already past a level: MJVS sells at this run instead
                continue
            t.gtt_id = broker.place_gtt_oco(k, sym, p.qty, sl, tg, ltp, algo.product)
            t.gtt_status, t.gtt_sl, t.gtt_target = "active", broker.tick_round(sl), broker.tick_round(tg)
            notes.append(f"GTT created for {name}: target {t.gtt_target:.2f}, stop loss {t.gtt_sl:.2f}")
        except broker.TokenError:
            raise
        except Exception as e:
            t.gtt_status = "error"
            notes.append(f"GTT for {name} not created ({str(e)[:90]}); MJVS checks target / stop loss itself")
        s.commit()


def sync_gtts(s: Session, k, sub: Subscription, notes: list):
    """Reads each GTT at Zerodha. When one has triggered and its SELL filled, the sell is recorded
    here so the algo's money, positions and trades stay right."""
    _, held = positions(s, sub)
    for sym in held:
        t = opening_buy(s, sub, sym)
        if not t or not t.gtt_id or t.gtt_status not in GTT_LIVE:
            continue
        name = sym.split(":")[1]
        try:
            g = broker.gtt_info(k, t.gtt_id)
        except broker.TokenError:
            raise
        except Exception as e:
            # GTT status unreadable: reconcile_account() checks the account itself right after this
            notes.append(f"GTT {name}: status unreadable in Kite ({str(e)[:40]}); checked against your account instead")
            continue
        status = str(g.get("status") or "").lower()
        if status == "active":
            t.gtt_status = "active"
            continue
        if status != "triggered":                       # cancelled / deleted / expired in Kite
            t.gtt_status = status or "unknown"
            notes.append(f"GTT {name} is {t.gtt_status} in Kite; MJVS checks target / stop loss itself")
            continue
        t.gtt_status = "triggered"
        done = [o for o in g.get("orders", []) if (o.get("result") or {}).get("order_result")]
        if not done:
            continue
        o = done[0]
        oid = str(o["result"]["order_result"].get("order_id") or "")
        try:
            last = k.order_history(oid)[-1] if oid else {}
        except Exception:
            last = {}
        st, filled = last.get("status"), int(last.get("filled_quantity") or 0)
        if st == "COMPLETE" or filled:
            price = float(last.get("average_price") or o.get("price") or 0)
            leg = "target" if price >= t.gtt_target * 0.995 or float(o.get("price") or 0) >= t.gtt_target else "stop loss"
            s.add(Trade(member_id=sub.member_id, algo_id=sub.algo_id, symbol=sym, side="SELL",
                        qty=filled or int(o.get("quantity") or held[sym].qty), price=price, mode="live",
                        status="COMPLETE", reason=f"GTT {leg} (Zerodha)", order_id=oid))
            t.gtt_status = "done"
            notes.append(f"SOLD {name} @ {price:.2f} by GTT {leg}")
        elif st in ("REJECTED", "CANCELLED"):
            t.gtt_status = "error"
            notes.append(f"GTT sell for {name} was {st.lower()} by Zerodha; MJVS checks target / stop loss itself")
        else:
            notes.append(f"GTT sell order for {name} is open in Kite ({st or 'waiting'})")
    s.commit()


def reconcile_account(s: Session, k, sub: Subscription, algo, notes: list) -> bool:
    """LIVE: the Zerodha account is the truth. A position this algo has on record but the account no
    longer holds (sold by a GTT, in the Kite app or anywhere else) is recorded as sold, using the
    real sell order from Zerodha when there is one. Returns False when the account cannot be read
    (then nothing is changed and no new buy is made this run)."""
    try:
        have = broker.account_quantities(k)
        orders = k.orders() or []
    except broker.TokenError:
        raise
    except Exception as e:
        notes.append(f"Could not read your Zerodha account ({str(e)[:60]}); nothing changed, no new buy this run")
        return False
    pending = {t.symbol for t in s.query(Trade).filter_by(member_id=sub.member_id, algo_id=sub.algo_id,
                                                         mode="live", status="PENDING")}
    _, held = positions(s, sub)
    changed = False
    for sym, p in held.items():
        if p.qty <= 0 or sym in pending:          # an order still filling is not a sale
            continue
        name = sym.split(":")[1]
        actual = max(have.get((algo.product, name), 0), 0)
        missing = p.qty - actual
        if missing <= 0:
            continue
        known = {t.order_id for t in s.query(Trade).filter_by(member_id=sub.member_id, symbol=sym, mode="live")}
        sells = [o for o in orders if o.get("tradingsymbol") == name and o.get("transaction_type") == "SELL"
                 and o.get("status") == "COMPLETE" and str(o.get("order_id")) not in known]
        if sells:
            o = sells[-1]
            qty = min(missing, int(o.get("filled_quantity") or missing))
            price, oid = float(o.get("average_price") or 0), str(o.get("order_id"))
            how = "sold in Zerodha (real order " + oid + ")"
        else:
            qty = missing
            price = broker.ltp_many(k, [sym]).get(sym) or p.avg
            oid = f"ACCOUNT-{config.ist_today():%Y%m%d}"
            how = "not in your Zerodha account any more; sell order not found today, price = last price (approximate)"
        s.add(Trade(member_id=sub.member_id, algo_id=sub.algo_id, symbol=sym, side="SELL", qty=qty, price=price,
                    mode="live", status="COMPLETE", order_id=oid, reason=how[:200]))
        t = opening_buy(s, sub, sym)
        if t and t.gtt_id and t.gtt_status in ("active", "triggered", "error"):
            if qty >= p.qty and t.gtt_status == "active":
                broker.delete_gtt(k, t.gtt_id)        # shares are gone: an active GTT would only fail later
            t.gtt_status = "done" if qty >= p.qty else t.gtt_status
        notes.append(f"{name}: {qty} recorded as sold @ {price:.2f} ({'real Zerodha order' if sells else 'approximate price'})")
        changed = True
    if changed:
        s.commit()
    return True


def sell(s, k, sub, algo, symbol, ours: int, reason: str, notes: list):
    q = ours
    if not sub.paper:
        t = opening_buy(s, sub, symbol)
        if t and t.gtt_id and t.gtt_status == "active":
            broker.delete_gtt(k, t.gtt_id)
            t.gtt_status = "deleted"
            s.commit()
        q = min(ours, broker.available_qty(k, symbol, algo.product))
        if q < ours:
            notes.append(f"{symbol}: algo record shows {ours}, Kite shows {q}")
        if q <= 0:
            return None
    res = place(s, k, sub, algo, symbol, "SELL", q, reason)
    name = symbol.split(":")[1]
    notes.append(f"SOLD {res[0]} {name} @ {res[1]:.2f} ({reason})" if res else f"SELL {name} rejected by Kite")
    return res


# ---------------------------------------------------------------- one member, one algo
def entry_candidates(s: Session, algo, sub: Subscription, rows: list[dict] | None, today: dt.date):
    """[(order_symbol, note)] in priority order."""
    if algo.require_tradingview:      # only stocks that passed scanner AND TradingView
        new = (s.query(Suggestion).filter(Suggestion.algo_id == algo.id, Suggestion.id > sub.last_suggestion_id,
                                          Suggestion.day == today).order_by(Suggestion.id).all())
        if new:
            sub.last_suggestion_id = new[-1].id
        return [(algo.order_symbol(x.symbol), "scanner + TradingView match") for x in new]
    if algo.source == "chartink":
        new = (s.query(Signal).filter(Signal.algo_id == algo.id, Signal.id > sub.last_signal_id, Signal.day == today,
                                      Signal.action == "BUY", Signal.source.in_(sigmod.SCANNER_SOURCES))
               .order_by(Signal.id).all())
        latest = s.query(Signal.id).filter(Signal.algo_id == algo.id).order_by(Signal.id.desc()).first()
        if latest:
            sub.last_signal_id = latest[0]
        return [(algo.order_symbol(sig.symbol), f"{sig.source} alert {sig.note}".strip()) for sig in new]
    cols = algo.columns[:2]
    return [(r["trade_symbol"], "BUY signal" + (" (" + ", ".join(f"{lbl} {r.get(key)}" for key, lbl in cols) + ")" if cols else ""))
            for r in rows or [] if r["signal"] == "BUY"]


def bought_recently(s: Session, sub: Subscription, days: int, now: dt.datetime) -> set:
    """Symbols not to buy again now: bought in the last `days` days (a daily/weekly BUY is used once),
    or sold today (no buying back straight after a stop loss or target)."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    since = midnight - dt.timedelta(days=max(days, 1) - 1)
    out = set()
    for t in s.query(Trade).filter(Trade.member_id == sub.member_id, Trade.algo_id == sub.algo_id,
                                   Trade.mode == mode_of(sub), Trade.status.in_(COUNTED), Trade.at >= since):
        if t.side == "BUY" or t.at >= midnight:
            out.add(t.symbol)
    return out


def run_sub(s: Session, algo, sub: Subscription, rows: list[dict] | None, now: dt.datetime, manual=False):
    m = s.get(Member, sub.member_id)
    k = broker.client(m.kite_token)
    today, notes = now.date(), []
    if hasattr(algo, "custom_run"):                       # algos with their own trade logic (NIFTY Future)
        if not sub.paper:
            reconcile_pending(s, k, sub)
        algo.custom_run(s, k, sub, now, manual)
        sub.last_run_at = now_ist()
        return
    if not sub.paper:
        reconcile_pending(s, k, sub)
        if algo.use_gtt:
            sync_gtts(s, k, sub, notes)
    account_ok = True
    if not sub.paper and not hasattr(algo, "custom_run"):
        account_ok = reconcile_account(s, k, sub, algo, notes)

    cash, held = positions(s, sub)
    prices = broker.ltp_many(k, list(held))
    value = account_value(cash, held, prices)
    sub.peak_value = max(sub.peak_value or sub.amount, value)
    down = (sub.peak_value - value) / sub.peak_value * 100 if sub.peak_value > 0 else 0

    # 1. Drawdown guard
    if down >= sub.drawdown_pct:
        for sym, p in held.items():
            sell(s, k, sub, algo, sym, p.qty, "drawdown limit", notes)
        sub.running = False
        sub.last_message = (f"Drawdown limit hit: down {down:.1f}% from the peak of Rs {sub.peak_value:,.0f}. "
                            "Sold everything and stopped. " + "; ".join(notes))
        sub.last_run_date, sub.last_run_at = today, now_ist()
        return

    # 2. Exits
    by_trade = {r["trade_symbol"]: r for r in rows or []}
    for sym, p in list(held.items()):
        if not sub.paper and algo.use_gtt and gtt_managed(s, sub, sym):
            continue                     # Zerodha's GTT sells it at the target or stop loss
        reason = algo.exit_reason(p, prices.get(sym), now, by_trade.get(sym))
        ltp = prices.get(sym)
        if not reason and algo.sl_from_drawdown and ltp and p.avg and p.qty > 0 and \
                ltp <= p.avg * (1 - sub.drawdown_pct / 100):
            reason = f"stop loss {sub.drawdown_pct:g}%"
        if not reason and algo.require_tradingview and p.entry_at:
            since = p.entry_at.replace(tzinfo=None)
            if sigmod.norm(sym) in sigmod.tradingview_sells(s, algo.id, since):
                reason = "TradingView SELL alert"
        if reason:
            res = sell(s, k, sub, algo, sym, p.qty, reason, notes)
            if res:
                cash += res[0] * res[1]
                held.pop(sym)

    # 3. Entries into free slots, equal money per slot
    cands = entry_candidates(s, algo, sub, rows, today)
    if algo.can_enter(now) and algo.auto_trade:
        slots = sub.max_positions - len(held)
        if slots <= 0 and cands:
            notes.append(f"No free slot: {len(held)} of {sub.max_positions} positions are held ("
                         + ", ".join(s.split(":")[1] for s in held) + "), so no new buy. A slot frees when one is sold")
        slot_cash = sub.amount / sub.max_positions
        if not sub.paper:
            kite_cash = broker.available_cash(k) if account_ok else None
            if kite_cash is None:
                slots = 0
                notes.append("Zerodha cash could not be read, so no new buy this run")
            else:
                cash = min(cash, kite_cash)
        picks, seen = [], set(held) | bought_recently(s, sub, algo.reentry_days, now)
        for sym, note in cands:
            if sym not in seen:
                seen.add(sym)
                picks.append((sym, note))
        # Walk down the BUY list (strongest first) until the free slots are filled: a stock that
        # costs more than one slot's money (or is above the price limit) is skipped for the next one.
        buy_prices = broker.ltp_many(k, [sym for sym, _ in picks]) if slots > 0 else {}
        bought, skipped = 0, []
        for sym, note in picks:
            if bought >= slots:
                break
            price = buy_prices.get(sym)
            name = sym.split(":")[1]
            if price and algo.max_price and price >= algo.max_price:
                skipped.append(f"{name} (not under Rs {algo.max_price})")
                continue
            units = algo.quantity(price, min(slot_cash, cash)) if price else 0
            if units < 1:
                skipped.append(f"{name} ({'Rs ' + format(price, ',.2f') + ' is more than one slot' if price else 'no price on Kite'})")
                continue
            res = place(s, k, sub, algo, sym, "BUY", units, note)
            if res:
                cash -= res[0] * res[1]
                bought += 1
                notes.append(f"BOUGHT {res[0]} {name} @ {res[1]:.2f}")
            else:
                notes.append(f"BUY {name} rejected by Kite")
        if skipped:
            notes.append("skipped: " + ", ".join(skipped[:8]) + (f" and {len(skipped) - 8} more" if len(skipped) > 8 else ""))

    if not sub.paper and algo.use_gtt:
        ensure_gtts(s, k, sub, algo, notes)

    head = "Manual paper run" if manual else "Run"
    if algo.manual_scan and not rows:
        notes.append("No scan for the latest candles yet: press Scan now, or wait for the daily scan "
                     "(target / stop loss are still checked)")
    if algo.source == "scan":
        c = {sig: sum(1 for r in rows or [] if r["signal"] == sig) for sig in ("BUY", "SELL", "ERROR")}
        head += f": scanned {len(rows or [])} ({c['BUY']} BUY, {c['SELL']} SELL" + (f", {c['ERROR']} errors" if c["ERROR"] else "") + ")"
        if c["ERROR"]:
            from collections import Counter
            top = Counter((r.get("error") or "unknown")[:60] for r in rows or [] if r["signal"] == "ERROR").most_common(2)
            head += " [errors: " + "; ".join(f"{n} × {e}" for e, n in top) + "]"
        if algo.require_tradingview:
            head += f", {len(cands)} new scanner + TradingView match(es)"
    elif algo.require_tradingview:
        head += f": {len(cands)} new scanner + TradingView match(es)"
    else:
        head += f": {len(cands)} new Chartink alert(s)"
    sub.last_message = head + ". " + ("; ".join(notes) if notes else "No trades needed.")
    if not manual and algo.once_per_day:
        sub.last_run_date = today
    sub.last_run_at = now_ist()


_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def guarded(s: Session, sub: Subscription, fn):
    """Never runs the same subscription twice at once; errors go to the dashboard."""
    with _locks_guard:
        lock = _locks.setdefault(sub.id, threading.Lock())
    if not lock.acquire(blocking=False):
        sub.last_message = "A run is already in progress. Try again in a minute."
        return
    try:
        fn()
    except broker.TokenError:
        m = s.get(Member, sub.member_id)
        m.kite_token = None
        sub.last_message = "Kite login expired. Connect Kite again to let the algo run."
    except broker.OrderRefused as e:
        sub.last_message = str(e)
    except broker.PermissionError_:
        sub.last_message = broker.NO_MARKET_DATA
    except Exception as e:     # retried at the next check
        sub.last_message = f"Error, will retry at the next check: {str(e)[:200]}"
        print(f"subscription {sub.id} error: {e!r}")
    finally:
        s.commit()
        lock.release()


def group_rows(s: Session, algo, universe: str, subs: list, now: dt.datetime, check_market=True):
    """Signals for one algo, worked out once with the first member token that works.
    Returns (rows or None, market_open)."""
    for sub in subs:
        m = s.get(Member, sub.member_id)
        if not token_fresh(m):
            continue
        k = broker.client(m.kite_token)
        try:
            if check_market and not broker.market_open_today(k, now.date()):
                return None, False
            if algo.source != "scan" or hasattr(algo, "custom_run"):
                return None, True
            if algo.manual_scan:          # only "Scan now" or the daily scheduled scan scans
                st = s.get(AlgoState, f"{algo.id}:{universe}")
                fresh = st and st.scan_at and broker.data_day(to_ist(st.scan_at)) == broker.data_day(now)
                return (json.loads(st.scan or "[]") if fresh else []), True
            held_syms = []
            for other in subs:   # held symbols are always re-checked, even if dropped from the list
                _, held = positions(s, other)
                held_syms += [algo.signal_symbol(sym) for sym in held]
            st = s.get(AlgoState, f"{algo.id}:{universe}")
            if algo.interval == "day" and st and st.scan_at and to_ist(st.scan_at).date() == now.date():
                rows = json.loads(st.scan or "[]")       # today's scan already done: reuse it
                have = {r["symbol"] for r in rows}
                extra = [x for x in dict.fromkeys(held_syms) if x not in have]
                if extra:
                    rows = rows + scan(algo, k, extra, now)
                return rows, True
            rows = scan(algo, k, algo_symbols(algo, universe, k) + held_syms, now)
            save_scan(s, algo.id, universe, rows)
            return rows, True
        except broker.TokenError:
            m.kite_token = None
            s.commit()
    raise broker.TokenError("No working Kite login for this algo")


def tick(now: dt.datetime | None = None):
    """Called every minute by the scheduler."""
    now = now or config.ist_now()
    if now.weekday() >= 5:
        return
    with Session(db_engine) as s:
        groups: dict[tuple, list] = {}
        for sub in s.query(Subscription).filter(Subscription.running.is_(True)).all():
            algo = ALGOS.get(sub.algo_id)
            if not algo or not algo.is_due(sub, now):
                continue
            if not algo.ready:
                sub.running, sub.last_message = False, "Stopped: this algo's strategy is not ready yet."
                continue
            if not token_fresh(s.get(Member, sub.member_id)):
                sub.last_message = ("Waiting for today's Kite login. Kite logins expire every morning, "
                                    f"so connect Kite before {algo.window[1].strftime('%H:%M')}.")
                continue
            groups.setdefault((algo.id, sub.universe), []).append(sub)
        s.commit()

        for (algo_id, universe), subs in groups.items():
            algo = ALGOS[algo_id]
            try:
                rows, is_open = group_rows(s, algo, universe, subs, now)
            except broker.PermissionError_:
                for sub in subs:
                    sub.last_message = broker.NO_MARKET_DATA
                s.commit()
                continue
            except Exception as e:
                for sub in subs:
                    sub.last_message = f"Error, will retry at the next check: {str(e)[:200]}"
                s.commit()
                continue
            for sub in subs:
                if not is_open:
                    sub.last_run_date, sub.last_run_at = now.date(), now_ist()
                    sub.last_message = "Market is closed today. Nothing to do."
                    s.commit()
                    continue
                guarded(s, sub, lambda sub=sub: run_sub(s, algo, sub, rows, now))
        daily_scans(s, now)


_closed_days: set = set()


def daily_scans(s: Session, now: dt.datetime):
    """Algos with suggest=True scan every list once a day, even when nobody runs them,
    so their fresh signals reach the Suggestions page. Uses any member's Kite login of today
    (admins first). Lists already scanned today by a running member are skipped."""
    if now.date() in _closed_days:
        return
    for algo in ALGOS.values():
        if not (algo.ready and algo.suggest and algo.source == "scan") or algo.manual_scan:
            continue
        if not algo.window[0] <= now.time() <= algo.window[1]:
            continue
        for uni in (algo.universes or {"": ""}):
            st = s.get(AlgoState, f"{algo.id}:{uni}")
            if st and st.scan_at and to_ist(st.scan_at).date() == now.date():
                continue
            members = [m for m in s.query(Member).filter(Member.kite_token.isnot(None)).all() if token_fresh(m)]
            from .settings_store import is_admin
            members.sort(key=lambda m: not is_admin(s, m))
            for m in members:
                try:
                    k = broker.client(m.kite_token)
                    if not broker.market_open_today(k, now.date()):
                        _closed_days.add(now.date())
                        return
                    save_scan(s, algo.id, uni, scan(algo, k, algo_symbols(algo, uni, k), now))
                    break
                except broker.TokenError:
                    m.kite_token = None
                    s.commit()
                except broker.PermissionError_:
                    _closed_days.add(now.date())     # no market data on this plan: stop trying today
                    print("daily scan: " + broker.NO_MARKET_DATA)
                    return
                except Exception as e:
                    print(f"daily scan {algo.id}:{uni} failed: {e!r}")
                    break


# ---------------------------------------------------------------- daily scheduled scan
_sched_scan = {"day": None, "running": False, "last": ""}


def scheduled_scan(now: dt.datetime | None = None, wait: bool = False):
    """Called every minute. On weekdays at the time set on the Scanner page (default 15:30), scans
    Swing and Penny once in the background with any member's Kite login of today."""
    from .settings_store import scan_time
    now = now or config.ist_now()
    t = scan_time()
    if not t or now.weekday() >= 5:
        return
    hh, mm = (int(x) for x in t.split(":"))
    if now.time() < dt.time(hh, mm) or _sched_scan["day"] == now.date() or _sched_scan["running"]:
        return
    _sched_scan["running"] = True
    th = threading.Thread(target=_scheduled_run, args=(now,), daemon=True)
    th.start()
    if wait:
        th.join()


def _scheduled_run(now: dt.datetime):
    try:
        with Session(db_engine) as s:
            from .settings_store import is_admin
            members = [m for m in s.query(Member).filter(Member.kite_token.isnot(None)).all() if token_fresh(m)]
            if not members:
                _sched_scan["last"] = f"{now:%d %b %H:%M}: skipped, nobody connected Kite today"
                return                       # tried again next minute, until someone connects
            members.sort(key=lambda m: not is_admin(s, m))
            k = broker.client(members[0].kite_token)
            if not broker.market_open_today(k, now.date()):
                _sched_scan.update(day=now.date(), last=f"{now:%d %b}: market closed, no scan")
                return
            algos = [a for a in ALGOS.values() if a.ready and a.manual_scan]
            algos.sort(key=lambda a: a.max_price is not None)      # the full list first (Swing)
            for algo in algos:
                for uni in (algo.universes or {"": ""}):
                    for m in members:
                        try:
                            k = broker.client(m.kite_token)
                            rows = scan(algo, k, algo_symbols(algo, uni, k), now)
                            save_scan(s, algo.id, uni, rows)
                            if algo.auto_trade:
                                run_after_scan(algo, uni, rows, now)
                            break
                        except broker.TokenError:
                            m.kite_token = None
                            s.commit()
            _sched_scan.update(day=now.date(), last=f"{now:%d %b %H:%M}: daily scan done ({config.ist_now():%H:%M})")
    except broker.PermissionError_:
        _sched_scan.update(day=now.date(), last=broker.NO_MARKET_DATA)
    except Exception as e:
        _sched_scan["last"] = f"{now:%d %b %H:%M}: daily scan failed: {str(e)[:120]}"
        print(f"scheduled scan failed: {e!r}")
    finally:
        _sched_scan["running"] = False


def run_after_scan(algo, universe: str, rows: list[dict], now: dt.datetime | None = None) -> str:
    """After a member's "Scan now": every running subscription of this algo trades from the new scan
    at once (inside the algo's hours on a market day). Returns a short note for the page."""
    now = now or config.ist_now()
    if not algo.window[0] <= now.time() <= algo.window[1] or now.weekday() >= 5:
        return (f"Scan done. Outside trading hours ({algo.window[0]:%H:%M}–{algo.window[1]:%H:%M}, Mon–Fri): "
                "no orders now. Scan again during those hours to trade.")
    n = 0
    with Session(db_engine) as s:
        subs = [x for x in s.query(Subscription).filter_by(algo_id=algo.id, running=True).all()
                if (x.universe or algo.default_universe) == universe and token_fresh(s.get(Member, x.member_id))]
        if subs:
            m = s.get(Member, subs[0].member_id)
            if not broker.market_open_today(broker.client(m.kite_token), now.date()):
                return "Scan done. The market is closed today: no orders."
        for sub in subs:
            guarded(s, sub, lambda sub=sub: run_sub(s, algo, sub, rows, now))
            n += 1
    return f"Scan done. {n} running algo(s) traded from it now." if n else "Scan done. Start the algo to trade from it."


def run_now(s: Session, sub: Subscription):
    """Paper test: one full cycle immediately, ignoring the clock and holidays."""
    algo, now = ALGOS[sub.algo_id], config.ist_now()

    def go():
        rows, _ = group_rows(s, algo, sub.universe, [sub], now, check_market=False)
        run_sub(s, algo, sub, rows, now, manual=True)
    guarded(s, sub, go)


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    sched = BackgroundScheduler(timezone="Asia/Kolkata")
    sched.add_job(tick, "cron", day_of_week="mon-fri", hour="9-15", minute="*",
                  max_instances=1, coalesce=True)
    from .db import backup_sqlite
    sched.add_job(scheduled_scan, "cron", day_of_week="mon-fri", hour="*", minute="*",
                  max_instances=1, coalesce=True)                 # daily scan at the time set (default 15:30)
    sched.add_job(backup_sqlite, "cron", hour=18, minute=5)    # daily database backup
    try:
        backup_sqlite()                                         # and one at every start
    except Exception as e:
        print(f"backup failed: {e!r}")
    sched.start()
    return sched
