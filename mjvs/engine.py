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
    rows = []
    for n, sym in enumerate(symbols):
        if progress:
            progress(n, len(symbols))
        base = {"symbol": sym, "trade_symbol": algo.order_symbol(sym)}
        q = quotes.get(sym)
        if not q:
            rows.append({**base, "signal": "ERROR", "error": "Symbol not found on Kite"})
            continue
        try:
            df = broker.history(k, q["instrument_token"], algo.interval, algo.candles, now)
            if len(df) < algo.candles - 30:
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
            rows.append(row)
        except (broker.TokenError, broker.PermissionError_):
            raise                # a login or plan problem: stop instead of failing every stock
        except Exception as e:   # one bad symbol must not stop the scan
            rows.append({**base, "signal": "ERROR", "error": str(e)[:120]})
        time.sleep(broker.HISTORY_PAUSE)
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


def sell(s, k, sub, algo, symbol, ours: int, reason: str, notes: list):
    q = ours
    if not sub.paper:
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
        reason = algo.exit_reason(p, prices.get(sym), now, by_trade.get(sym))
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
        slot_cash = sub.amount / sub.max_positions
        picks, seen = [], set(held) | bought_recently(s, sub, algo.reentry_days, now)
        for sym, note in cands:
            if sym not in seen:
                seen.add(sym)
                picks.append((sym, note))
        picks = picks[:max(slots, 0)]
        buy_prices = broker.ltp_many(k, [sym for sym, _ in picks])
        for sym, note in picks:
            price = buy_prices.get(sym)
            units = algo.quantity(price, min(slot_cash, cash)) if price else 0
            name = sym.split(":")[1]
            if units < 1:
                notes.append(f"{name}: not enough cash for 1 unit" if price else f"{name}: no price on Kite")
                continue
            res = place(s, k, sub, algo, sym, "BUY", units, note)
            if res:
                cash -= res[0] * res[1]
                notes.append(f"BOUGHT {res[0]} {name} @ {res[1]:.2f}")
            else:
                notes.append(f"BUY {name} rejected by Kite")

    head = "Manual paper run" if manual else "Run"
    if algo.source == "scan":
        c = {sig: sum(1 for r in rows or [] if r["signal"] == sig) for sig in ("BUY", "SELL", "ERROR")}
        head += f": scanned {len(rows or [])} ({c['BUY']} BUY, {c['SELL']} SELL" + (f", {c['ERROR']} errors" if c["ERROR"] else "") + ")"
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
        if not (algo.ready and algo.suggest and algo.source == "scan"):
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
    sched.add_job(backup_sqlite, "cron", hour=18, minute=5)    # daily database backup
    try:
        backup_sqlite()                                         # and one at every start
    except Exception as e:
        print(f"backup failed: {e!r}")
    sched.start()
    return sched
