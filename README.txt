MJVS - START HERE

1. Install Python from python.org (tick "Add python.exe to PATH"). Only once.
2. Right-click the zip file and choose "Extract All". Do NOT run files from inside the zip.
3. Double-click START_MJVS.bat. Keep the black window open: the algos run inside it.
4. Your browser opens http://localhost:8000/ by itself.
5. Create your account. The FIRST account created is the owner (admin).
6. One-time owner step: Admin page -> "Kite setup". Follow the 5 steps on screen
   (create the MJVS app on developers.kite.trade, paste the redirect URL shown,
   paste the API key and secret, press Test). No file editing needed.

MARKET DATA (live prices and charts) comes from Zerodha Kite
  It needs the paid "Connect" plan on developers.kite.trade (about Rs 500/month). The free
  "Personal" plan only places orders, so scans fail with "Insufficient permission".
  Create a "Connect" app, paste its API key and secret in Admin -> Kite setup, then Disconnect
  and Connect Zerodha again. "Check market data" must show three ticks.

CONNECTING ZERODHA (for every member, about 30 seconds)
  Home page or dashboard -> "Connect Zerodha" -> log in on Zerodha's own page -> back to MJVS.
  New members are taken to this step right after creating their account.
  Zerodha logs everyone out every morning, so members press Connect once each trading day.

THE 8 ALGOS
  Scalping (1-30 min), Intraday (same day), Short term (15-60 days), Swing, Long term (5-10 years),
  Penny stock, NIFTY Future swing, Options. Each one is its own file in mjvs\algos\ .
  Ready now (rule in mjvs\algos\rules.py):
    BUY when all three first become true together: close crosses above the 50 SMA,
    RSI(8) above 60, Bollinger %b(50, SD 1) above 51.
  - Swing: daily candles, scans ALL NSE stocks. Target 8%, stop loss 5%.
  - Penny stock: same rule on WEEKLY candles, scans ALL NSE stocks. Target 8%, stop loss 5%.
  A full scan of about 2,000 stocks takes 10-15 minutes (Kite allows ~3 chart downloads a
  second); Swing and Penny share the downloaded data. Every BUY row has a Buy button that opens
  a Kite-style order window (Paper or Live, Market or Limit, CNC).
  - NIFTY Future swing: 1-hour candles of the NIFTY future (never options), 15-20 day trades.
    Long: target 8%; stop loss 5% or close < 50 SMA / RSI < 40 / %b < 50 -> then goes SHORT.
    Short: target 8%, stop loss 5%, or a new BUY signal (covers and buys).
    Drawdown limit counts closed-trade losses; emergency close if a gap passes 10%.
    WARNING: needs at least Rs 2,00,000 capital and a risk (drawdown limit) of at most 5%.
    A trade is executed only with its 5% stop loss; with less money or more risk it opens nothing new.
    CHART: the NIFTY Future swing page shows the 1-hour chart of the NIFTY future with the 50 SMA,
    Bollinger band, RSI(8) and %b, the BUY / SELL signals and your trades (press "Refresh chart").
    Chart drawing: TradingView Lightweight Charts (web/lightweight-charts.js, Apache 2.0 licence).
  Target and stop loss are checked every 15 min (futures every 5 min) in market hours.
  All times in the database and on the site are Indian time (IST).

  Every member can run several algos at once. Each algo has its own money, drawdown limit
  (5-15%) and Paper/Live mode.

INFORMATION (for beginners)
  The Information page (website menu, and inside the dashboard) has 7 topics from
  "what is a share" to algo trading, Chartink, risk and F&O, with free YouTube videos
  (Zerodha Varsity, CA Rachana Ranade and others), quick checks and a glossary.
  To change the videos, edit the INFO list near the top of web\app.js.

DAILY ROUTINE
  - Kite logs everyone out every morning. Click "Connect Kite" once each trading day.
  - The computer must stay on and the black window open during market hours (9:15-15:30).
  - Holidays are detected automatically.

MANUAL TRADING (next to Algo trading)
  Dashboard -> Manual trading (switch back any time with "Algo trading"). Search any NSE share, future or option (e.g. "SBIN", "NIFTY FUT",
  "NIFTY 24500 CE"), see the live price, and Buy/Sell: Market or Limit, CNC/MIS for shares,
  NRML/MIS for futures and options (quantity in lots). Paper or Live (Live needs the
  Admin switch on). Live orders work even on the free "Personal" Kite plan; prices need "Connect". "Your Zerodha account today" lists every order, position and holding in your
  Zerodha account from ANY app (MJVS, Kite app, Streak ...) and can cancel open orders.

LIVE ORDERS NEED A WHITELISTED STATIC IP (Zerodha rule since 1 April 2026)
  If an order is refused with "IP ... is not allowed" or "Insufficient permission": on
  developers.kite.trade -> your Profile -> IP Whitelist, add this PC's internet IP (shown on the
  Admin page). Home IPs usually change: get a static IP from your internet provider, or run
  MJVS on a server that has one.

DISCONNECT ZERODHA
  "Disconnect" in the top bar (or Profile / Connect page) logs MJVS out of Zerodha at once.
  Running algos pause until you connect again.

ZERODHA STREAK
  Streak logs in with the same Zerodha account, so its orders show on the Trade page.
  Streak does not let other apps read its strategies or receive its alerts, so a Streak
  strategy cannot run inside MJVS directly; send its conditions to add it as an MJVS algo.

YOUR DATA (DATABASE)
  Everything is saved permanently in the database: members, passwords (only as scrambled
  argon2 hashes, which nobody can read back), Kite connections, algo settings, every trade
  (paper and live), Chartink signals, feedback and a login history.
  - Default database: the file mjvs.db in this folder. Do not delete it.
  - A backup copy is made at every start and every evening into the backups folder
    (newest 30 kept). To restore: close the app, copy a backup over mjvs.db.
  - Admin page -> Members, Recent logins, and "Download data" (CSV files for Excel).
    Members can download their own trades on the Trades page.
  - When you host the site, use an online Postgres database instead: set DATABASE_URL in
    START_MJVS.bat (format shown there). The tables are created automatically.

LOGIN SECURITY
  - Login and register need a picture captcha (built in, single use, expires in 5 minutes).
  - 5 wrong passwords for an account lock it for 15 minutes (20 from one address).
  - Sessions expire after 12 hours.

SAFETY
  - Always start in PAPER mode: live prices, no real orders. "Run once now" tests it any time.
  - Real orders are blocked until the admin switches them on: Admin page -> "Live trading" -> Switch on.
  - Drawdown limit: if an algo is down that % from its peak, it sells everything and stops.
  - "Stop algo" does NOT sell positions. Sell them in Kite if you want out.

CHARTINK SCANNERS
  Algos marked "Chartink scanner" buy the stocks a Chartink alert sends them.
  1. Log in with your admin email -> Admin page -> copy that algo's webhook URL.
  2. On chartink.com open your scanner -> Create Alert -> paste the webhook URL
     (webhooks need a paid Chartink plan).
  3. Chartink must reach your PC over the internet: run a tunnel (for example Cloudflare
     Tunnel: cloudflared tunnel --url http://localhost:8000) and put the tunnel address in
     PUBLIC_URL in START_MJVS.bat. Or host the app on a server.
  4. Test with "Send a test signal" on the Admin page first, in paper mode.

FILES
  START_MJVS.bat              settings + start
  backend.py                  entry point
  legacy\                     saved older strategies (not used by the app)
  mjvs\algos\*.py             one file per algo  <- strategies go here
  mjvs\engine.py              automation: schedule, risk, orders, paper mode
  mjvs\broker.py              Zerodha Kite connection
  mjvs\app.py                 website API
  watchlists\*.txt            symbol lists for scanner algos
  web\                        the website
  ADDING_A_STRATEGY.txt       how a new algo is filled in

To see saved data: double-click view_database.bat
To stop: close the black window.

HOSTING ONLINE (fixed IP for Zerodha, free 3 months)
  See deploy/HOSTING_GUIDE.txt (AWS Lightsail Mumbai). deploy/setup_server.sh installs
  everything on the server with one command; deploy/update_app.sh installs a newer version.
