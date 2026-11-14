"""Shows what is saved in mjvs.db (read-only). No extra app needed."""
import os, sqlite3, sys

db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mjvs.db")
if not os.path.exists(db):
    print("mjvs.db is not here yet.")
    print("Start START_MJVS.bat once, wait until it says 'Uvicorn running', then try again.")
    sys.exit()

con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def show(title, sql):
    try:
        cur = con.execute(sql)
    except sqlite3.Error as e:
        print(f"\n=== {title} ===\n(not available yet: {e})")
        return
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    print(f"\n=== {title} ({len(rows)} rows) ===")
    if not rows:
        print("(empty)")
        return
    w = [max(len(str(c)), *(len(str(r[i])) for r in rows)) for i, c in enumerate(cols)]
    print(" | ".join(str(c).ljust(w[i]) for i, c in enumerate(cols)))
    print("-+-".join("-" * x for x in w))
    for r in rows:
        print(" | ".join(str(v).ljust(w[i]) for i, v in enumerate(r)))


show("MEMBERS", "SELECT id, full_name, email, mobile, created_at, last_login, "
                "(kite_token IS NOT NULL) AS kite_connected, kite_token_date, "
                "substr(password_hash,1,15)||'...' AS password_scrambled FROM members")
show("ALGO SUBSCRIPTIONS", "SELECT id, member_id, algo_id, amount, drawdown_pct, max_positions, universe, "
                           "CASE paper WHEN 1 THEN 'paper' ELSE 'LIVE' END AS mode, running, last_run_at, last_message FROM subscriptions")
show("TRADES", "SELECT id, member_id, algo_id, symbol, side, qty, price, mode, status, at FROM trades")
show("CHARTINK SIGNALS (last 50)", "SELECT id, algo_id, symbol, price, source, note, at FROM signals ORDER BY id DESC LIMIT 50")
show("FEEDBACK", "SELECT id, member_id, rating, message, at FROM feedback")
print("\nAll times are Indian time (IST).")
print("Passwords are saved only in scrambled form, so the real password can never be shown.")
