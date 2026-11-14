"""
MJVS entry point (START_MJVS.bat runs:  uvicorn backend:app).

Project layout
  backend.py                  this file
  legacy/                     your first strategy file (no longer used)
  mjvs/app.py                 web API (login, Kite connect, dashboard, algo controls, Chartink webhook)
  mjvs/engine.py              automated trading engine (scheduler, risk, orders, paper mode)
  mjvs/broker.py              everything that talks to Zerodha Kite
  mjvs/algos/                 one file per algo (the 8 styles) -> edit these to add strategies
  watchlists/                 symbol lists for scanner algos
  web/                        the website (index.html, app.css, app.js)

Run with ONE worker only: the scheduler lives inside this process.
"""
from mjvs.app import app  # noqa: F401
