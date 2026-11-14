@echo off
title MJVS - keep this window open
cd /d "%~dp0"
echo.
echo  MJVS is starting. Keep this window open while you use the website.
echo.

set PY=python
%PY% --version >nul 2>&1
if errorlevel 1 set PY=py
%PY% --version >nul 2>&1
if errorlevel 1 (
  echo Python is not installed. Install it from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)

echo Installing needed packages. The first time takes a few minutes...
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo Package install failed. Check your internet and try again.
  pause
  exit /b 1
)

REM Secret keys are made once on this PC and kept in my_secrets.bat (never uploaded to GitHub).
if not exist my_secrets.bat %PY% -c "import secrets; from cryptography.fernet import Fernet; print('set JWT_SECRET=' + secrets.token_hex(32)); print('set FERNET_KEY=' + Fernet.generate_key().decode()); print('set CHARTINK_KEY=' + secrets.token_urlsafe(18))" > my_secrets.bat
call my_secrets.bat

REM Settings for running on this PC (localhost).
set FRONTEND_URL=http://localhost:8000,http://127.0.0.1:8000
set BACKEND_URL=http://localhost:8000
REM Captcha on login/register. builtin = picture captcha from this app (works on a home PC).
REM When the site is on the internet you can switch to Cloudflare: CAPTCHA_MODE=turnstile + your real keys.
set CAPTCHA_MODE=builtin
set TURNSTILE_SECRET=
set TURNSTILE_SITEKEY=
REM Database. Default: the file mjvs.db in this folder, backed up daily into the backups folder.
REM For a hosted database use Postgres, e.g.  set DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DBNAME
set DATABASE_URL=sqlite:///mjvs.db
REM Kite keys: easiest is the Admin page -> Kite setup (no need to edit this file).
REM You can also put them here. Admin-page values win.
set KITE_API_KEY=not-set-yet
set KITE_API_SECRET=not-set-yet
REM Starting value only: the admin switches live trading on/off on the Admin page.
set ALLOW_LIVE=0
REM Admins (comma separated emails). Leave empty: the FIRST account created is the admin.
set ADMIN_EMAILS=
REM Internet address of this PC for Chartink (e.g. a Cloudflare Tunnel URL). Empty = local only.
set PUBLIC_URL=

REM close an older copy that is still using port 8000
for /f "tokens=5" %%A in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /f /pid %%A >nul 2>&1

echo.
echo  When you see "Uvicorn running", the website is ready.
echo  Your browser opens http://localhost:8000/ by itself.
echo.
start "" cmd /c "ping -n 8 127.0.0.1 >nul & start http://localhost:8000/"
%PY% -m uvicorn backend:app --host 127.0.0.1 --port 8000
echo.
echo MJVS stopped. If there is an error above, send a screenshot of this window.
pause
