/* MJVS website: public pages + member app. No build step: plain JavaScript. */
(function () {
"use strict";
var $ = function (id) { return document.getElementById(id); };
var root = $("root");
var CFG = { algos: [], allow_live: false, turnstile_sitekey: "" }, ALG = {}, DASH = null, PAGE = null;
var money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
var px = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
var calc = { sel: "swing", amount: 10000, risk: 10 };

// ------------------------------------------------------------------ helpers
function esc(t) { return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
function short(sym) { return esc(String(sym || "").split(":").pop()); }
function when(s) { if (!s) return "—"; var d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(s) ? s : s + "Z"); return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }); }
function stars(n) { return n ? '<span class="stars" aria-label="' + n + ' of 2 stars">' + "★".repeat(n) + "☆".repeat(Math.max(0, 2 - n)) + "</span>" : '<span class="muted">Not rated</span>'; }
function signed(v) { if (v == null) return "—"; return '<span class="' + (v >= 0 ? "up" : "dn") + '">' + (v >= 0 ? "+" : "") + px.format(v) + "</span>"; }
function token() { try { return sessionStorage.getItem("mjvs") || ""; } catch (e) { return ""; } }
function setToken(t) { try { t ? sessionStorage.setItem("mjvs", t) : sessionStorage.removeItem("mjvs"); } catch (e) {} }
function go(path) { if (location.hash === "#" + path) route(); else location.hash = path; }
function say(el, ok, t) { if (!el) return; el.className = "msg " + (ok ? "ok" : "err"); el.textContent = t; }
function errText(x, d) { return x && x.d && typeof x.d.detail === "string" ? x.d.detail : (x && x.d && x.d.detail && x.d.detail[0] ? x.d.detail[0].loc.slice(-1) + ": " + x.d.detail[0].msg : d); }
function toast(t) { var el = document.createElement("div"); el.className = "toast"; el.setAttribute("role", "status"); el.textContent = t; document.body.appendChild(el); setTimeout(function () { el.remove(); }, 3200); }
function api(path, opt) {
  opt = opt || {};
  opt.headers = { "Content-Type": "application/json", Authorization: "Bearer " + token() };
  if (opt.json) { opt.body = JSON.stringify(opt.json); delete opt.json; }
  return fetch(path, opt).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (d) {
      if (r.status === 401 && token()) { logout(); }
      return { ok: r.ok, status: r.status, d: d };
    });
  });
}
function logout() { setToken(""); DASH = null; go("/login"); }
function download(path, name) {
  fetch(path, { headers: { Authorization: "Bearer " + token() } }).then(function (r) { if (!r.ok) throw 0; return r.blob(); }).then(function (b) {
    var a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }).catch(function () { toast("Download failed"); });
}
function subOf(id) { return DASH && DASH.subs.filter(function (s) { return s.algo_id === id; })[0]; }
function on(id, ev, fn) { var el = $(id); if (el) el.addEventListener(ev, fn); }
function icon(name) {
  var p = { home: "M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z", algo: "M4 19V9m6 10V5m6 14v-7m4 7H2",
    pos: "M3 7h18v12H3zM8 7V5h8v2", trades: "M4 6h16M4 12h16M4 18h10", learn: "M2 8l10-5 10 5-10 5zM6 10v5c3 2 9 2 12 0v-5",
    user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-8 9a8 8 0 0 1 16 0", admin: "M12 2l8 4v6c0 5-4 9-8 10-4-1-8-5-8-10V6z",
    trade2: "M7 17L17 7M9 7h8v8M4 20h16",
    star: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z",
    web: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-9 10h18M12 2c3 3 3 17 0 20M12 2c-3 3-3 17 0 20" }[name];
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + p + '"/></svg>';
}
function table(head, rows, empty) {
  if (!rows.length) return '<div class="empty">' + esc(empty) + "</div>";
  return '<div class="tblw"><table class="tbl"><thead><tr>' + head.map(function (h) { return "<th" + (h.charAt(0) === "<" ? "" : "") + ">" + h + "</th>"; }).join("") + "</tr></thead><tbody>" + rows.join("") + "</tbody></table></div>";
}
function sourceLabel(a) { return (a.source === "chartink" ? "Chartink scanner" : "Own scanner") + (a.require_tradingview ? " + TradingView" : ""); }
function statusBadge(a) { return a.ready ? '<span class="badge good"><span class="dot"></span>Live algo</span>' : '<span class="badge warn">Strategy pending</span>'; }
function runsText(a) {
  return (a.once_per_day ? "Once a day" : "Every " + a.run_every + " min") + ", " + a.window[0] + "–" + a.window[1] + " on market days";
}
function exitsText(a) {
  if (a.exits_note) return a.exits_note;
  var e = a.exits, out = [];
  if (e.stop_loss_pct) out.push("stop loss " + e.stop_loss_pct + "%");
  if (e.target_pct) out.push("target " + e.target_pct + "%");
  if (e.max_hold_minutes) out.push("max " + e.max_hold_minutes + " min");
  if (e.max_hold_days) out.push("max " + e.max_hold_days + " days");
  if (e.square_off) out.push("square-off " + e.square_off);
  if (a.source === "scan") out.push("SELL signal");
  return out.length ? out.join(", ") : "To be set with the strategy";
}

// ------------------------------------------------------------------ public layout
function pubLayout(active, inner) {
  var nav = [["/", "Home"], ["/products", "Products"], ["/offers", "Offers"], ["/information", "Information"]].map(function (n) {
    return '<a href="#' + n[0] + '"' + (active === n[0] ? ' aria-current="page"' : "") + ">" + n[1] + "</a>";
  }).join("");
  var cta = token() ? '<a class="btn sm" href="#/app">Open dashboard</a>' : '<a href="#/login">Log in</a><a class="btn sm" href="#/register">Get started</a>';
  return '<header class="top"><div class="wrap"><a class="brand" href="#/"><span class="logo">M</span><span>Trade with MJVS</span></a><nav aria-label="Main">' + nav + cta + "</nav></div></header>" +
    "<main>" + inner + "</main>" +
    '<footer class="footer"><div class="wrap">Trading in shares, futures and options carries market risk, and you can lose money. Figures here are planning illustrations, not guaranteed returns or investment advice. Algo services are offered subject to exchange empanelment and broker approval. Orders are placed in your own Zerodha account.</div></footer>';
}

function algoCard(a, cta, noStars) {
  return '<article class="card algo-card"><div class="card-head" style="margin:0"><h3>' + esc(a.name) + "</h3>" + (noStars ? "" : stars(a.stars)) + "</div>" +
    '<div class="meta">' + statusBadge(a) + '<span class="badge">' + sourceLabel(a) + "</span>" + (a.group === "fno" ? '<span class="badge accent">F&amp;O</span>' : '<span class="badge accent">Equity</span>') + "</div>" +
    "<p>" + esc(a.blurb) + "</p>" + (a.risk_note ? '<div class="note">' + esc(a.risk_note) + "</div>" : "") +
    '<div class="foot"><div class="k"><div>Holding<b>' + esc(a.holding) + "</b></div><div>Product<b>" + esc(a.product) + "</b></div></div>" + (cta || "") + "</div></article>";
}

function pageHome() {
  var eq = CFG.algos.filter(function (a) { return a.group === "equity"; }), fo = CFG.algos.filter(function (a) { return a.group === "fno"; });
  function chipRow(list) { return list.map(function (a) { return '<button type="button" class="chip" data-algo="' + a.id + '" aria-pressed="' + (a.id === calc.sel) + '">' + esc(a.name) + "</button>"; }).join(""); }
  var html = '<div class="hero-band"><div class="wrap hero"><div>' +
    '<span class="eyebrow">Algo trading through your own Zerodha account</span>' +
    "<h1>Let the algo trade. You set the limit.</h1>" +
    "<p>Enter your amount, pick a trade style and see the holding period and the most you could be down before the algo stops.</p>" +
    '<div class="hero-stats"><div><b>' + CFG.algos.length + '</b>algo styles</div><div><b>5–15%</b>drawdown limits</div><div><b>Paper</b>test before real money</div></div>' +
    '<div id="home-kite" class="home-kite"></div>' +
    "</div>" +
    '<div class="calc" id="calc"><div class="in">' +
    '<label for="amount">How much do you want to invest?</label><div class="amt"><span>₹</span><input id="amount" inputmode="numeric" autocomplete="off" value="' + calc.amount.toLocaleString("en-IN") + '"></div>' +
    '<div class="lbl" style="margin-top:16px">Shares (equity)</div><div class="chips" id="calc-chips">' + chipRow(eq) + "</div>" +
    '<div class="lbl" style="margin-top:14px">Futures and options</div><div class="chips" id="calc-chips2">' + chipRow(fo) + "</div>" +
    '<div style="margin-top:16px"><label for="risk">Drawdown limit: <span id="riskv">' + calc.risk + '%</span></label><input id="risk" type="range" min="5" max="15" step="1" value="' + calc.risk + '"><div class="ticks"><span>5% lower risk</span><span>15% higher risk</span></div></div>' +
    '</div><div class="out" id="calc-out" aria-live="polite"></div></div></div></div>' +
    '<section class="section"><div class="wrap"><h2>How it works</h2><p class="lead">Three steps from sign-up to a running algo. Start in paper mode: same rules, live prices, no real orders.</p>' +
    '<div class="grid g3 steps"><div class="card"><h3>Connect Kite</h3><p class="muted">Log in on Zerodha’s own page. Your password never reaches us. Kite logins last one day.</p></div>' +
    '<div class="card"><h3>Pick an algo and your limit</h3><p class="muted">Choose a style, the amount and a drawdown limit between 5% and 15%.</p></div>' +
    '<div class="card"><h3>The algo trades for you</h3><p class="muted">Scanner signals become orders in your own account. It stops at your limit, and you can stop it anytime.</p></div></div></div></section>' +
    '<section class="section" style="padding-top:0"><div class="wrap"><div class="banner"><div><b>New to trading or algo trading?</b><p>Seven short topics with the best free videos in English and Hindi, from what a share is to how our algos decide.</p></div><a class="btn" href="#/information">Start learning</a></div></div></section>' +
    '<section class="section" style="padding-top:0"><div class="wrap"><h2>Products</h2><p class="lead">Every trade style runs as its own algo. Higher risk can bring higher profit; lower risk usually brings lower profit.</p>' +
    '<div class="grid auto">' + CFG.algos.map(function (a) { return algoCard(a, '<a class="btn sm ghost" href="#/products">Details</a>', true); }).join("") + "</div></div></section>";
  html += '<section class="section" id="feedback" style="padding-top:0"><div class="wrap"><div class="fb-wrap"><div><h2>Feedback</h2><p class="lead" style="margin-bottom:12px">Tell us what you think, report a problem or ask a question. We read every message.</p>' +
    '<p class="muted small">No account needed. If you want a reply, add your email or mobile.</p></div><div class="card">' + feedbackForm(!token()) + "</div></div></div></section>";
  root.innerHTML = pubLayout("/", html);
  bindFeedback(!token(), token() ? "ff" : "hf");
  function paintHomeKite() { var el = $("home-kite"); if (!el) return; el.innerHTML = kiteCardHtml(false); bindKiteButtons(); }
  paintHomeKite();
  if (token()) loadDash().then(paintHomeKite).catch(function () {});
  function pickAlgo(e) { var b = e.target.closest("button[data-algo]"); if (!b) return; calc.sel = b.getAttribute("data-algo"); document.querySelectorAll("#calc button[data-algo]").forEach(function (x) { x.setAttribute("aria-pressed", x === b); }); drawCalc(); }
  on("calc-chips", "click", pickAlgo); on("calc-chips2", "click", pickAlgo);
  on("amount", "input", function (e) { var v = e.target.value.replace(/[^0-9]/g, ""); e.target.value = v ? Number(v).toLocaleString("en-IN") : ""; calc.amount = +v || 0; drawCalc(); });
  on("risk", "input", function (e) { calc.risk = +e.target.value; $("riskv").textContent = calc.risk + "%"; drawCalc(); });
  drawCalc();
}

function drawCalc() {
  var o = $("calc-out"), a = ALG[calc.sel];
  if (!o || !a) return;
  if (!calc.amount) { o.innerHTML = '<p class="msg err">Enter an amount above ₹0 to see your numbers.</p>'; return; }
  var dd = calc.amount * calc.risk / 100;
  var cta = a.ready ? '<button class="btn block" id="calc-go" type="button" style="margin-top:14px">Start ' + esc(a.name.toLowerCase()) + " algo</button>"
    : '<div class="note" style="margin-top:14px">The ' + esc(a.name.toLowerCase()) + " algo’s strategy is being added. It opens here as soon as it is ready.</div>";
  o.innerHTML = '<div class="lbl">Your ' + esc(a.name.toLowerCase()) + " plan</div>" +
    '<div class="big num">' + money.format(dd) + '</div><div class="muted small">most you could be down at a ' + calc.risk + "% limit</div>" +
    '<div class="bar" role="img" aria-label="Capital split"><i style="width:' + (100 - calc.risk) + '%"></i><u style="width:' + calc.risk + '%"></u></div>' +
    '<div class="row"><span>Algo stops at</span><b class="num">' + money.format(calc.amount - dd) + "</b></div>" +
    '<div class="row"><span>Holding period</span><b>' + esc(a.holding) + "</b></div>" +
    '<div class="row"><span>Signals from</span><b>' + sourceLabel(a) + "</b></div>" +
    (a.risk_note ? '<div class="note" style="margin-top:10px">' + esc(a.risk_note) + "</div>" : "") +
    (a.warning ? '<div class="note" style="margin-top:10px;font-weight:600">⚠ ' + esc(a.warning) + "</div>" : "") + cta;
  on("calc-go", "click", function () {
    try { sessionStorage.setItem("mjvs_prefill", JSON.stringify({ algo: a.id, amount: calc.amount, dd: calc.risk })); } catch (e) {}
    go(token() ? "/app/algo/" + a.id : "/register");
  });
}

function feedbackForm(isPublic) {
  var p = isPublic ? "hf" : "ff";
  return '<form id="' + p + '"><div class="field"><div class="lbl">Topic</div><div class="seg" id="' + p + '-t">' +
    ["Suggestion", "Problem", "Question", "Praise"].map(function (t, i) { return '<button type="button" data-v="' + t + '" aria-pressed="' + (i === 0) + '">' + t + "</button>"; }).join("") + "</div></div>" +
    (isPublic ? '<div class="grid g2" style="gap:12px"><div class="field"><label for="' + p + '-n">Your name (optional)</label><input id="' + p + '-n" maxlength="80" autocomplete="name"></div><div class="field"><label for="' + p + '-c">Email or mobile (optional)</label><input id="' + p + '-c" maxlength="120" autocomplete="email"></div></div>' : "") +
    '<div class="field"><label for="' + p + '-m">Message</label><textarea id="' + p + '-m" rows="4" required minlength="3" maxlength="1000"></textarea></div>' +
    (isPublic ? captchaHtml() : "") + '<button class="btn" type="submit">Send feedback</button><p id="' + p + '-msg" class="msg" role="status"></p></form>';
}
function bindFeedback(isPublic, p) {
  var topic = "Suggestion";
  $(p + "-t").addEventListener("click", function (e) { var b = e.target.closest("button"); if (!b) return; topic = b.getAttribute("data-v"); this.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", x === b); }); });
  if (isPublic && CFG.captcha_mode !== "turnstile") { newCaptcha(); on("capnew", "click", newCaptcha); }
  on(p, "submit", function (e) {
    e.preventDefault(); var m = $(p + "-msg"), body = { topic: topic, message: $(p + "-m").value }, path = "/feedback";
    if (isPublic) {
      path = "/feedback/public"; body.name = $(p + "-n").value; body.contact = $(p + "-c").value;
      body.captcha = $("capin") ? $("capin").value.trim() : ""; body.captcha_id = capId;
      if (!body.captcha) { say(m, false, "Please type the letters in the picture."); return; }
    }
    api(path, { method: "POST", json: body }).then(function (x) {
      if (isPublic) newCaptcha();
      say(m, x.ok, x.ok ? "Thank you! Your feedback was sent." : errText(x, "Please write at least 3 characters"));
      if (x.ok) $(p + "-m").value = "";
    }).catch(function () { say(m, false, "Could not reach the server"); });
  });
}

function pageProducts() {
  function group(g, title, sub) {
    return '<div class="group-title"><h3>' + title + '</h3><span class="muted small">' + sub + "</span></div>" +
      '<div class="grid auto">' + CFG.algos.filter(function (a) { return a.group === g; }).map(function (a) {
        return algoCard(a, a.ready ? '<a class="btn sm" href="#' + (token() ? "/app/algo/" + a.id : "/register") + '">Start</a>' : '<span class="badge">Coming soon</span>');
      }).join("") + "</div>";
  }
  root.innerHTML = pubLayout("/products", '<section class="section"><div class="wrap"><h2>Products</h2><p class="lead">' + CFG.algos.length + ' algos, one for each trade style. Each has its own rating, holding period and rules for when to buy and sell.</p>' +
    group("equity", "Shares (equity)", "Delivery and intraday") + group("fno", "Futures and options", "Margin and lot sizes apply") + "</div></section>");
}

function pageOffers() {
  root.innerHTML = pubLayout("/offers", '<section class="section"><div class="wrap"><h2>Offers</h2><p class="lead">Launch offers for new members will appear here.</p><div class="grid g3"><div class="card"><h3>Free paper trading</h3><p class="muted">Run any live algo in paper mode for free: real prices, no real orders.</p></div><div class="card"><h3>Coming soon</h3><p class="muted">Pricing and free-trial details.</p></div></div></div></section>');
}

var YT = "https://www.youtube.com/";
// ------------------------------------------------------------------ information (shared by public + app)
// Video links were checked in Nov 2026. Videos belong to their creators and open on YouTube.
// v: id = YouTube video id (thumbnail shown); list = playlist id; url = any other link.
var INFO = [
{k:"basics", t:"Stock market basics", lvl:"Start here", mins:"25 min",
 p:["A share is a small piece of ownership in a company. Its price moves as buyers and sellers agree on new prices during market hours (9:15 am to 3:30 pm, Monday to Friday).",
    "An index such as NIFTY 50 tracks a basket of 50 large companies, so you can follow the whole market with one number.",
    "You buy and sell through a broker. MJVS uses your own Zerodha account: your money and shares always stay with Zerodha, never with us.",
    "A market order buys or sells at the best price available now. A limit order lets you set the price you will accept.",
    "Investing means holding for years. Trading means buying and selling over minutes, days or months. Both carry the risk of loss."],
 v:[{id:"GcZW24SkbHM", t:"Why should you invest?", ch:"Zerodha Varsity", lang:"English"},
    {id:"fFZYA9BUQNs", t:"Chai Pe Stock Market, Day 1: basics of the stock market", ch:"CA Rachana Ranade", lang:"Hindi / English"},
    {list:"PLX2SHiKfualGOP9093b6qo11EsgCz8IuQ", t:"Zerodha Varsity full course in Hindi", ch:"Zerodha Varsity", lang:"Hindi · playlist"},
    {id:"8rUc0MaMzik", list:"PLX2SHiKfualFGenPFh2onjzsh8TeprEmU", t:"Fundamental analysis series (long-term investing)", ch:"Zerodha Varsity", lang:"English · playlist"}],
 q:[{q:"Which order lets you choose the exact price you will pay?", o:["Market order","Limit order"], a:1, e:"A limit order only fills at your price or better."},
    {q:"Where does your money stay when you use MJVS?", o:["In your own Zerodha account","With MJVS"], a:0, e:"Orders are placed in your own Zerodha account. MJVS never holds your money."}]},
{k:"charts", t:"Reading charts and candlesticks", lvl:"Beginner", mins:"30 min",
 p:["A candlestick shows four prices for one period (one day, or 5 minutes): open, high, low and close.",
    "A green (or hollow) candle closed higher than it opened. A red candle closed lower.",
    "Support is a price area where falls have often stopped. Resistance is where rises have often stalled.",
    "A trend is the general direction of price. An uptrend makes higher highs and higher lows.",
    "Our algos only look at completed candles, so a half-formed candle never triggers a trade."],
 v:[{id:"AYG2g3O7jKc", t:"Understanding candlestick patterns", ch:"Zerodha Varsity", lang:"English"},
    {id:"yP83rD7DjTg", t:"Multiple candlestick patterns", ch:"Zerodha Varsity", lang:"English"},
    {id:"z0Rwoz6PduM", t:"The right way to use candlestick patterns when trading", ch:"Zerodha Varsity", lang:"English"},
    {id:"yzRP-mA2eiE", list:"PLX2SHiKfualH_xMbGM-3zWC47s9gUjGR_", t:"Technical analysis: full series", ch:"Zerodha Varsity", lang:"English · playlist"}],
 q:[{q:"Which four prices does one candlestick show?", o:["Open, high, low, close","Buy, sell, profit, loss"], a:0, e:"Every candle shows the open, high, low and close of its period."},
    {q:"An uptrend is a series of…", o:["Higher highs and higher lows","Lower highs and lower lows"], a:0, e:"Each rise goes higher and each dip stops higher."}]},
{k:"indicators", t:"Indicators our algos use", lvl:"Beginner", mins:"30 min",
 p:["A Simple Moving Average (SMA 50) is the average of the last 50 closing prices. Price above it usually means an uptrend.",
    "RSI (Relative Strength Index) measures how strong recent moves were, on a 0 to 100 scale. A high reading means strong recent buying, a low one strong selling.",
    "Bollinger Bands draw a band around the moving average. %b shows where the price sits in that band: 50 is the middle, above 50 is the upper half.",
    "Many strategies combine indicators and buy only when they agree, which filters out weak signals.",
    "No indicator is always right. That is why every algo has a drawdown limit."],
 v:[{id:"veWVgyucBqU", t:"Technical indicators", ch:"Zerodha Varsity", lang:"English"},
    {id:"810jmf7drFw", t:"Moving averages", ch:"Zerodha Varsity", lang:"English"},
    {id:"8JTBeh1IbK8", t:"Technical analysis for beginners", ch:"CA Rachana Ranade", lang:"Hindi / English"}],
 q:[{q:"What does a 50-day SMA show?", o:["The highest price in 50 days","The average closing price of the last 50 days"], a:1, e:"It adds up 50 closes and divides by 50."},
    {q:"Why do strategies combine several indicators?", o:["To filter out weak signals","To trade more often"], a:0, e:"Waiting for several indicators to agree avoids many false signals."}]},
{k:"algo", t:"What is algo trading?", lvl:"Beginner", mins:"20 min",
 p:["Algo trading means a computer program follows fixed rules to decide when to buy and sell, and places the orders for you. It never gets scared or greedy, but it also cannot think: it only does what its rules say.",
    "MJVS has 8 algos, one per trade style. Each has its own entry rule (a scanner), exit rules (signal, stop loss, target or time) and a drawdown limit you choose.",
    "Paper mode runs the same rules on live prices without real orders. Always start there and watch it for a few weeks.",
    "Zerodha logs everyone out every morning, so you connect Kite once each trading day. Your Zerodha password is typed only on Zerodha’s own page.",
    "In India, SEBI and the exchanges set rules for algo trading through brokers. These rules change, so MJVS only works through your broker’s official connection."],
 v:[{id:"UuytiT_5ZGU", t:"SEBI’s new algorithmic trading rules: what retail investors need to know", ch:"", lang:"English"},
    {id:"j_OHE_TtCu4", t:"SEBI proposes algorithmic trading for retail investors: experts’ view", ch:"CNBC-TV18", lang:"English · news"}],
 q:[{q:"What is paper mode?", o:["Same rules and live prices, but no real orders","A printed report of trades"], a:0, e:"Paper mode lets you test an algo with no money at risk."},
    {q:"Why do you connect Kite every trading day?", o:["Zerodha logins expire every morning","The algo forgets your settings"], a:0, e:"Kite access lasts one day for safety. Your settings stay saved."}]},
{k:"chartink", t:"Stock scanners (Chartink)", lvl:"Intermediate", mins:"25 min",
 p:["A scanner (screener) checks hundreds of stocks against conditions, for example ‘RSI above 60 and price above the 50-day average’, and lists the ones that match.",
    "Chartink is a popular Indian scanner website. Several MJVS algos take their stock picks from a Chartink scanner alert.",
    "When the scanner finds stocks, Chartink sends them to MJVS. The algo then buys them in each member’s own account, within that member’s money and limits.",
    "A scanner only finds candidates. The exit rules and the drawdown limit protect you when a pick goes wrong."],
 v:[{id:"0nYgU3TWYF0", t:"Chartink screener: beginner’s guide (2025–2026)", ch:"", lang:"English"},
    {id:"TnhRcaUGLiw", t:"RSI scanner: how to create a screener in Chartink", ch:"", lang:"Hindi"}],
 q:[{q:"What does a scanner do?", o:["Lists stocks that match your conditions","Guarantees which stocks will rise"], a:0, e:"It finds candidates. It cannot know the future."}]},
{k:"risk", t:"Risk: stop loss and drawdown", lvl:"Must know", mins:"15 min",
 p:["A stop loss sells a position automatically when it falls a set amount, so one bad trade cannot grow into a big loss.",
    "Drawdown is the fall from your highest value. With ₹10,000 and a 10% limit, the algo sells everything and stops if your value falls to ₹9,000 from its peak.",
    "Position size matters: MJVS splits each algo’s money equally across its positions, so no single stock takes all of it.",
    "A good past result (backtest) does not guarantee future profit. Start small, and never trade with money you cannot afford to lose."],
 v:[{id:"eXMrEMdQWrQ", t:"How to place a stop loss order on Kite", ch:"", lang:"English"}],
 q:[{q:"You invest ₹10,000 with a 10% drawdown limit. When does the algo stop?", o:["When value falls to ₹9,000 from the peak","At ₹10,100"], a:0, e:"10% of ₹10,000 is ₹1,000, so it stops at ₹9,000 (or 10% below a higher peak)."},
    {q:"Does a good backtest guarantee profit?", o:["Yes","No"], a:1, e:"Markets change. Past results are only a guide."}]},
{k:"fo", t:"Futures and options", lvl:"Advanced", mins:"40 min",
 p:["A futures contract is an agreement to buy or sell at a set price on a future date. It uses margin: a small deposit controls a much larger position.",
    "Because of that leverage, futures losses can be larger than the margin you put in.",
    "An option gives the buyer a right, not an obligation. The buyer pays a premium and can lose all of it if the option expires worthless.",
    "SEBI studies have found that most individual F&O traders lose money. Learn the basics well before using the Futures or Options algos."],
 v:[{id:"-mO0YOTcCiQ", list:"PLX2SHiKfualFiusiT9G5uE9jU3vetvW2x", t:"Options trading series", ch:"Zerodha Varsity", lang:"English · playlist"},
    {url:"https://www.youtube.com/@varsitybyzerodha/playlists", t:"All Varsity playlists (including futures)", ch:"Zerodha Varsity", lang:"English and Hindi"}],
 q:[{q:"You buy an option and it expires worthless. What is the most you can lose?", o:["The premium you paid","An unlimited amount"], a:0, e:"A buyer’s loss is limited to the premium paid."},
    {q:"Why can futures losses exceed your margin?", o:["Leverage","Interest rates"], a:0, e:"Margin controls a bigger position, so price moves are magnified."}]}
];
var GLOSSARY = [
["Share / stock","A small piece of ownership in a company."],["Index (NIFTY 50)","A number that tracks a basket of large companies."],
["ETF","A fund you can buy like a share, for example NIFTYBEES tracks NIFTY 50."],
["Candle","Open, high, low and close prices for one period."],["SMA","Simple Moving Average: the average of recent closing prices."],
["RSI","Relative Strength Index, 0–100: how strong recent moves were."],["Bollinger %b","Where the price sits inside the Bollinger Bands; 50 is the middle."],
["Signal","BUY, SELL or HOLD, worked out by an algo’s rule."],["Scanner","A tool that lists stocks matching set conditions."],
["Stop loss","Sells automatically if a position falls a set percent."],["Target","Sells automatically when a position gains a set percent."],
["Drawdown","How far your value has fallen from its highest point."],["Paper mode","Live prices and the same rules, but no real orders."],
["CNC","Delivery: shares are kept in your demat account."],["MIS","Intraday: positions must be closed the same day."],
["NRML","Normal F&O positions that can be carried to expiry."],["Lot size","The fixed quantity in one futures or options contract."],
["Margin","The deposit needed to hold an F&O position."],["Kite","Zerodha’s trading platform; MJVS connects to it."],
["Market order","Buys or sells right away at the best available price."]
];
var lesson = 0, done = {};
try { done = JSON.parse(localStorage.getItem("mjvs_done") || "{}"); } catch (e) {}
function vidUrl(v) { return v.url || (v.list ? YT + (v.id ? "watch?v=" + v.id + "&list=" : "playlist?list=") + v.list : YT + "watch?v=" + v.id); }
function infoHtml() {
  return '<div class="info-top"><div><div class="bar" role="img" aria-label="Topics done"><i id="tr-fill" style="width:0"></i></div><p id="tr-prog" class="small muted" style="margin:6px 0 0"></p></div></div>' +
    '<div class="info-grid"><nav class="topics" id="tr-tabs" aria-label="Topics"></nav><div class="card lesson" id="tr-panel"></div></div>' +
    '<div class="grid g2" style="margin-top:22px"><div class="card"><div class="card-head"><div><h3>Glossary</h3><p class="muted small">Every word used on this site, in plain language.</p></div></div><input id="gl-q" type="search" placeholder="Search a word, e.g. RSI" aria-label="Search the glossary" style="margin-bottom:10px"><div id="gl"></div></div>' +
    '<div class="card"><h3>Trusted free channels</h3><p class="muted small" style="margin:4px 0 12px">Good places to keep learning after these topics.</p>' +
    '<a class="yt" href="https://www.youtube.com/@varsitybyzerodha" target="_blank" rel="noopener noreferrer">▶ Zerodha Varsity<small>English and Hindi · from basics to options</small></a>' +
    '<a class="yt" href="https://www.youtube.com/channel/UCe3qdG0A_gr-sEdat5y2twQ" target="_blank" rel="noopener noreferrer">▶ CA Rachana Ranade<small>Hindi / English · beginner friendly</small></a>' +
    '<a class="yt" href="https://zerodha.com/varsity/" target="_blank" rel="noopener noreferrer">📖 Zerodha Varsity (read online)<small>Free written modules</small></a>' +
    '<p class="small muted" style="margin-top:12px">Videos belong to their creators and open on YouTube in a new tab. They are for learning only, not investment advice, and not paid for or endorsed by MJVS.</p></div></div>';
}
function drawGlossary() {
  var q = ($("gl-q") ? $("gl-q").value : "").toLowerCase();
  var rows = GLOSSARY.filter(function (g) { return !q || (g[0] + " " + g[1]).toLowerCase().indexOf(q) >= 0; });
  $("gl").innerHTML = rows.length ? '<dl class="gloss">' + rows.map(function (g) { return "<dt>" + esc(g[0]) + "</dt><dd>" + esc(g[1]) + "</dd>"; }).join("") + "</dl>" : '<div class="empty">No match. Try another word.</div>';
}
function drawInfo() {
  var m = INFO[lesson], T = $("tr-tabs"); if (!T) return;
  T.innerHTML = INFO.map(function (x, i) {
    return '<button type="button" class="topic" data-i="' + i + '" aria-pressed="' + (i === lesson) + '"><span class="tnum">' + (done[x.k] ? "✓" : i + 1) + '</span><span><b>' + esc(x.t) + '</b><small>' + esc(x.lvl) + " · " + esc(x.mins) + "</small></span></button>";
  }).join("");
  T.querySelectorAll(".topic").forEach(function (b) { b.onclick = function () { lesson = +b.getAttribute("data-i"); drawInfo(); var p = $("tr-panel"); if (p && window.innerWidth < 980) p.scrollIntoView({ block: "start" }); }; });
  var n = INFO.filter(function (x) { return done[x.k]; }).length;
  $("tr-prog").textContent = n + " of " + INFO.length + " topics done";
  $("tr-fill").style.width = (n / INFO.length * 100) + "%";
  $("tr-panel").innerHTML = '<div class="card-head" style="margin-bottom:6px"><div><span class="badge accent">Topic ' + (lesson + 1) + " · " + esc(m.lvl) + "</span><h3 style=\"font-size:22px;margin-top:8px\">" + esc(m.t) + "</h3></div></div>" +
    "<ul>" + m.p.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") + "</ul>" +
    '<div class="lbl" style="margin-top:18px">Watch</div><div class="vids">' + m.v.map(function (v) {
      var thumb = v.id ? '<img src="https://i.ytimg.com/vi/' + esc(v.id) + '/mqdefault.jpg" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">' : '<span class="vph">▶</span>';
      return '<a class="vid" href="' + esc(vidUrl(v)) + '" target="_blank" rel="noopener noreferrer"><span class="thumb">' + thumb + '<span class="play" aria-hidden="true">▶</span></span><b>' + esc(v.t) + '</b><small>' + esc([v.ch, v.lang].filter(Boolean).join(" · ")) + "</small></a>";
    }).join("") + "</div>" +
    '<div class="lbl" style="margin-top:18px">Quick check</div>' +
    m.q.map(function (q, qi) { return '<div class="qz" data-q="' + qi + '"><p><b>' + esc(q.q) + '</b></p><div class="chips">' + q.o.map(function (o, oi) { return '<button type="button" class="chip" data-o="' + oi + '">' + esc(o) + "</button>"; }).join("") + '</div><p class="small muted fb" role="status" style="margin:8px 0 0"></p></div>'; }).join("") +
    '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px"><button type="button" class="btn ghost" id="tr-done">' + (done[m.k] ? "Mark as not done" : "Mark topic as done") + "</button>" +
    (lesson < INFO.length - 1 ? '<button type="button" class="btn quiet" id="tr-next">Next topic →</button>' : "") + "</div>";
  $("tr-panel").querySelectorAll(".qz").forEach(function (z) {
    var q = m.q[+z.getAttribute("data-q")], bs = z.querySelectorAll("button");
    bs.forEach(function (b) { b.onclick = function () { var oi = +b.getAttribute("data-o"); bs.forEach(function (x) { x.disabled = true; }); b.classList.add(oi === q.a ? "good" : "bad"); if (oi !== q.a) bs[q.a].classList.add("good"); z.querySelector(".fb").textContent = (oi === q.a ? "Correct. " : "Not quite. ") + q.e; }; });
  });
  $("tr-done").onclick = function () { done[m.k] = !done[m.k]; try { localStorage.setItem("mjvs_done", JSON.stringify(done)); } catch (e) {} drawInfo(); };
  on("tr-next", "click", function () { lesson++; drawInfo(); });
}
function setupInfo() { drawInfo(); drawGlossary(); on("gl-q", "input", drawGlossary); }
function pageInformation() {
  root.innerHTML = pubLayout("/information", '<section class="section"><div class="wrap"><h2>Information</h2><p class="lead">New to trading? Start here. Seven short topics take you from “what is a share” to how our algos decide when to buy and sell. Each one has a plain explanation, the best free videos we could find, and a quick check.</p>' + infoHtml() + "</div></section>");
  setupInfo();
}

// ------------------------------------------------------------------ login / register
var capTok = {}, capWid = {};
function loadCaptcha(ids) {
  var key = CFG.turnstile_sitekey;
  ids.forEach(function (id) { capTok[id] = ""; });
  if (!key) { ids.forEach(function (id) { var el = $(id); if (el) el.innerHTML = '<div class="note">Captcha is not configured (TURNSTILE_SITEKEY).</div>'; }); return; }
  if (!key) { ids.forEach(function (id) { var el = $(id); if (el) el.innerHTML = '<div class="empty small">Captcha appears here on your hosted site</div>'; }); return; }
  function render() { ids.forEach(function (id) { var el = $(id); if (el && window.turnstile) capWid[id] = window.turnstile.render(el, { sitekey: key, callback: function (t) { capTok[id] = t; } }); }); }
  if (window.turnstile) { render(); return; }
  var s = document.createElement("script"); s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"; s.onload = render; document.head.appendChild(s);
}
var capId = "";
function captchaHtml() {
  if (CFG.captcha_mode === "turnstile") return "";
  return '<div class="field"><label for="capin">Security check: type the letters in the picture</label><div class="capbox"><img id="capimg" alt="Security picture. If you cannot read it, press New picture." width="200" height="64"><button type="button" class="btn sm quiet" id="capnew">New picture</button></div>' +
    '<input id="capin" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="8" required><small>Not case-sensitive. A new picture appears after each try.</small></div>';
}
function newCaptcha() {
  var img = $("capimg"); if (!img) return;
  fetch("/auth/captcha", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) { capId = d.id; img.src = d.image; if ($("capin")) $("capin").value = ""; }).catch(function () {});
}
function pageAuth(mode) {
  var reg = mode === "register";
  root.innerHTML = pubLayout("", '<div class="auth"><div class="card"><h1>' + (reg ? "Create your account" : "Welcome back") + '</h1><p class="muted" style="margin:0 0 18px">' + (reg ? "Free to join. Test any algo in paper mode first." : "Log in to see your algos.") + "</p>" +
    '<div class="seg" style="margin-bottom:18px"><button type="button" aria-pressed="' + !reg + '" onclick="location.hash=\'/login\'">Log in</button><button type="button" aria-pressed="' + reg + '" onclick="location.hash=\'/register\'">Register</button></div>' +
    (reg ? '<form id="af"><div class="field"><label for="rn">Full name</label><input id="rn" autocomplete="name" required minlength="2"></div>' +
      '<div class="field"><label for="rmob">Mobile number</label><input id="rmob" inputmode="numeric" autocomplete="tel" pattern="[6-9][0-9]{9}" required><small>10 digits, starting 6–9</small></div>' +
      '<div class="field"><label for="re">Email</label><input id="re" type="email" autocomplete="email" required></div>' +
      '<div class="field"><label for="rp">Password</label><input id="rp" type="password" autocomplete="new-password" minlength="8" required><small>At least 8 characters</small></div>' +
      '<div class="field"><label for="rp2">Confirm password</label><input id="rp2" type="password" autocomplete="new-password" required></div>'
      : '<form id="af"><div class="field"><label for="u">Email</label><input id="u" type="email" autocomplete="username" required></div><div class="field"><label for="p">Password</label><input id="p" type="password" autocomplete="current-password" required></div>') +
    '<div id="cap" style="margin-bottom:14px"></div>' + captchaHtml() + '<button class="btn block" type="submit">' + (reg ? "Create account" : "Log in") + '</button><p id="am" class="msg" role="status"></p></form></div></div>');
  if (CFG.captcha_mode === "turnstile") loadCaptcha(["cap"]); else { newCaptcha(); on("capnew", "click", newCaptcha); }
  on("af", "submit", function (e) {
    e.preventDefault(); var m = $("am");
    var builtin = CFG.captcha_mode !== "turnstile", capAns = builtin ? $("capin").value.trim() : capTok.cap;
    if (!capAns) { say(m, false, builtin ? "Please type the letters in the picture." : "Please complete the captcha."); return; }
    var body, path;
    if (reg) {
      if ($("rp").value !== $("rp2").value) { say(m, false, "Passwords do not match"); return; }
      path = "/auth/register"; body = { full_name: $("rn").value, mobile: $("rmob").value, email: $("re").value, password: $("rp").value, captcha: capAns, captcha_id: capId };
    } else { path = "/auth/login"; body = { email: $("u").value, password: $("p").value, captcha: capAns, captcha_id: capId }; }
    api(path, { method: "POST", json: body }).then(function (x) {
      if (builtin) { if (!x.ok) newCaptcha(); } else if (capWid.cap !== undefined) { capTok.cap = ""; try { window.turnstile.reset(capWid.cap); } catch (er) {} }
      if (!x.ok) { say(m, false, errText(x, "Please check your details")); return; }
      setToken(x.d.token); var pf = null; try { pf = JSON.parse(sessionStorage.getItem("mjvs_prefill") || "null"); } catch (er) {}
      go(reg ? "/app/connect" : (pf ? "/app/algo/" + pf.algo : "/app"));
    }).catch(function () { if (builtin) newCaptcha(); say(m, false, "Could not reach the server. Check that the black window is still open."); });
  });
}

// ------------------------------------------------------------------ member app
function loadDash() { return api("/dashboard").then(function (x) { if (x.ok) { DASH = x.d; CFG.allow_live = DASH.allow_live; CFG.kite_ready = DASH.kite_ready; } return DASH; }); }
function disconnectKite() {
  if (!confirm("Disconnect Zerodha now? Running algos pause until you connect again.")) return;
  api("/kite/disconnect", { method: "POST" }).then(function (x) { toast(x.ok ? "Zerodha disconnected" : errText(x, "Could not disconnect")); refresh(); if (PAGE && PAGE.paint) PAGE.paint(); });
}
function connectKite() {
  if (!token()) { try { sessionStorage.setItem("mjvs_connect", "1"); } catch (e) {} go("/register"); return; }
  api("/kite/link", { method: "POST" }).then(function (x) { if (x.d.url) location.href = x.d.url; else toast(errText(x, "Could not start the Zerodha login")); }).catch(function () { toast("Could not reach the server"); });
}

// One card used on the home page and the Connect page: shows the right next step.
function kiteCardHtml(big) {
  var k = DASH ? DASH.kite : null, ready = DASH ? DASH.kite_ready : CFG.kite_ready, admin = DASH && DASH.is_admin;
  var steps = '<ol class="ksteps"><li><b>' + (token() ? "✓ " : "") + 'Create your free MJVS account</b><span>Name, mobile and email. Takes a minute.</span></li>' +
    '<li><b>' + (k && k.fresh ? "✓ " : "") + 'Press “Connect Zerodha”</b><span>Zerodha’s own login page opens.</span></li>' +
    '<li><b>Log in with your Zerodha ID, password and app code</b><span>You come straight back here. Your Zerodha password is never seen by MJVS.</span></li></ol>';
  if (!ready) {
    return '<div class="kcard"><div class="khead"><span class="zlogo">Z</span><div><b>Connect Zerodha</b><span>' + (admin ? "One-time setup needed first" : "Coming soon") + "</span></div></div>" +
      (admin ? '<p>Before members can connect, add the MJVS Kite app keys once. It takes about 10 minutes.</p><a class="btn block" href="#/app/admin">Open Kite setup</a>'
        : '<p>Zerodha connection is being switched on. You can already create your account, read Information and look around.</p>' + (token() ? "" : '<a class="btn block" href="#/register">Create free account</a>')) + "</div>";
  }
  if (k && k.fresh) {
    return '<div class="kcard ok"><div class="khead"><span class="zlogo">Z</span><div><b>Zerodha connected ✓</b><span>Connected for today</span></div></div>' +
      "<p>Your algos can scan and trade until the market closes. Zerodha logs everyone out every morning, so tomorrow just press Connect again.</p>" +
      '<a class="btn block" href="#/app">Open my dashboard</a>' + (big ? '<button class="btn quiet block" type="button" data-kdisc="1" style="margin-top:8px">Disconnect Zerodha</button>' : "") + "</div>";
  }
  var title = !token() ? "Connect your Zerodha account" : (k && k.connected ? "Reconnect Zerodha for today" : "Connect your Zerodha account");
  var sub = !token() ? "3 easy steps · free" : (k && k.connected ? "Zerodha logs everyone out each morning" : "Last step: about 30 seconds");
  return '<div class="kcard"><div class="khead"><span class="zlogo">Z</span><div><b>' + title + "</b><span>" + sub + "</span></div></div>" +
    (big || !token() ? steps : "") +
    '<button class="btn block kgo" type="button" data-kite="1">' + (token() ? "Connect Zerodha" : "Get started: connect Zerodha") + "</button>" +
    '<p class="small muted" style="margin:10px 0 0">Orders are placed only in your own Zerodha account. You can disconnect any time by logging out of Kite.</p></div>';
}
function bindKiteButtons() { document.querySelectorAll("[data-kite]").forEach(function (b) { b.onclick = connectKite; }); document.querySelectorAll("[data-kdisc]").forEach(function (b) { b.onclick = disconnectKite; }); }

function appConnect() {
  var r = QUERY.kite, msg = QUERY.msg;
  var top = r === "ok" ? '<div class="banner ok"><div><b>Zerodha is connected 🎉</b><p>You are ready. Start an algo in paper mode, or check today’s Suggestions.</p></div><a class="btn" href="#/app/algos">Choose an algo</a></div>'
    : r === "cancelled" ? '<div class="banner need"><div><b>The Zerodha login was cancelled</b><p>No problem. Press Connect Zerodha when you are ready.</p></div></div>'
    : r === "error" ? '<div class="banner need"><div><b>Could not connect</b><p>' + esc(msg || "Please try again.") + "</p></div></div>" : "";
  appLayout("", "Connect Zerodha", '<div class="stack" style="max-width:760px">' + top + '<div id="kc-card"></div>' +
    '<div class="card"><h3>Good to know</h3><div style="margin-top:8px">' +
    '<div class="row"><span>Is it safe?</span><b>You log in on Zerodha’s own website. MJVS never sees your Zerodha password or app code.</b></div>' +
    '<div class="row"><span>How long does it last?</span><b>Until about 6 am next day. Zerodha asks everyone to log in once a day.</b></div>' +
    '<div class="row"><span>What can MJVS do?</span><b>Read prices and place the orders of the algos you start. Paper mode places no orders at all.</b></div>' +
    '<div class="row"><span>Do I need a Zerodha account?</span><b>Yes. <a href="https://zerodha.com/open-account" target="_blank" rel="noopener noreferrer">Open one on zerodha.com</a> if you do not have one.</b></div>' +
    "</div></div></div>");
  PAGE.paint = function () { $("kc-card").innerHTML = kiteCardHtml(true); bindKiteButtons(); };
}

function appLayout(active, title, inner) {
  var items = [["", "home", "Overview"], ["algos", "algo", "Algo trading"], ["trade", "trade2", "Manual trading"], ["positions", "pos", "Positions"], ["trades", "trades", "Trades"], ["suggestions", "star", "Suggestions"], ["learn", "learn", "Information"], ["profile", "user", "Profile"]];
  if (DASH && DASH.is_admin) items.push(["admin", "admin", "Admin"]);
  root.innerHTML = '<div class="shell"><aside class="side" aria-label="App menu"><a class="brand" href="#/"><span class="logo">M</span><span>MJVS</span></a>' +
    items.map(function (i) { return '<a class="nav" href="#/app' + (i[0] ? "/" + i[0] : "") + '"' + (active === i[0] ? ' aria-current="page"' : "") + ">" + icon(i[1]) + i[2] + "</a>"; }).join("") +
    '<a class="nav" href="#/">' + icon("web") + 'Website</a><div class="sp"></div><div class="who"><b>' + esc(DASH ? DASH.full_name : "") + '</b><span>Member</span><br><button type="button" id="lo">Log out</button></div></aside>' +
    '<div class="main"><div class="appbar"><h1>' + esc(title) + '</h1><span id="barx" style="display:contents"></span></div><div class="page" id="page">' + inner + "</div></div></div>";
  on("lo", "click", logout); paintBar();
}
function paintBar() {
  var el = $("barx"); if (!el || !DASH) return;
  var k = DASH.kite, running = DASH.subs.filter(function (s) { return s.running; }), live = running.filter(function (s) { return !s.paper; }).length;
  el.innerHTML = (live ? '<span class="badge bad"><span class="dot"></span>' + live + " live</span>" : "") +
    (running.length - live ? '<span class="badge accent">' + (running.length - live) + " paper</span>" : "") +
    (k.fresh ? '<span class="badge good"><span class="dot"></span>Kite connected today</span><button class="btn sm quiet" id="kd" type="button">Disconnect</button>'
      : '<span class="badge warn"><span class="dot"></span>' + (k.connected ? "Kite login expired" : "Kite not connected") + '</span><button class="btn sm" id="kc" type="button">Connect Kite</button>');
  on("kc", "click", connectKite); on("kd", "click", disconnectKite);
}

function kiteBanner() {
  var k = DASH.kite;
  if (!DASH.kite_ready) return DASH.is_admin ? '<div class="banner need"><div><b>Finish the one-time Kite setup</b><p>Members can connect Zerodha after you add the MJVS Kite app keys. About 10 minutes.</p></div><a class="btn" href="#/app/admin">Open Kite setup</a></div>'
    : '<div class="banner need"><div><b>Zerodha connection is coming soon</b><p>MJVS is switching on Zerodha connections. You can look around and read Information meanwhile.</p></div></div>';
  if (k.fresh) return '<div class="banner ok"><div><b>Kite is connected for today</b><p>Your running algos can place orders until the market closes. Kite logs everyone out every morning.</p></div></div>';
  return '<div class="banner need"><div><b>' + (k.connected ? "Your Kite login has expired" : "Connect your Zerodha Kite account") + "</b><p>Kite logins last one day. Connect once each trading day, before your algos’ run time, so they can trade.</p></div>" +
    '<button class="btn" type="button" id="kc2">Connect Kite</button></div>';
}

function subRows(list) {
  return list.map(function (s) {
    var a = ALG[s.algo_id] || { name: s.algo_id };
    return '<tr class="click" data-go="/app/algo/' + esc(s.algo_id) + '"><td><b>' + esc(a.name) + "</b></td><td>" + (s.paper ? '<span class="badge accent">Paper</span>' : '<span class="badge bad">Live</span>') +
      "</td><td>" + (s.running ? '<span class="badge good"><span class="dot"></span>Running</span>' : '<span class="badge">Stopped</span>') + "</td><td>" + money.format(s.amount) + "</td><td>" + money.format(s.value) + "</td><td>" + signed(s.pnl) +
      '</td><td class="wrap">' + esc(s.last_message || "") + "</td></tr>";
  });
}
function tradeRows(list, withAlgo) {
  return list.map(function (t) {
    return "<tr><td>" + when(t.at) + "</td>" + (withAlgo ? "<td>" + esc((ALG[t.algo_id] || {}).name || t.algo_id) + "</td>" : "") + '<td><span class="sig ' + (t.side === "BUY" ? "BUY" : "SELL") + '">' + t.side + "</span></td><td><b>" + short(t.symbol) + "</b></td><td>" + t.qty + "</td><td>" + px.format(t.price) +
      "</td><td>" + (t.mode === "paper" ? '<span class="badge accent">Paper</span>' : (t.status === "REJECTED" ? '<span class="badge bad">Rejected</span>' : '<span class="badge">' + esc(t.status) + "</span>")) + '</td><td class="wrap">' + esc(t.reason) + "</td></tr>";
  });
}
function posRows(list, withAlgo, withGtt) {
  return list.map(function (p) {
    return "<tr>" + (withAlgo ? "<td>" + esc(p.algo) + "</td>" : "") + "<td><b>" + short(p.symbol) + "</b></td><td>" + p.qty + "</td><td>" + px.format(p.avg) + "</td><td>" + (p.ltp == null ? "—" : px.format(p.ltp)) + "</td><td>" + signed(p.pnl) + "</td><td>" + when(p.since) + "</td>" + (withGtt ? "<td>" + gttCell(p.gtt) + "</td>" : "") + "</tr>";
  });
}
function gttCell(g) {
  if (!g) return '<span class="muted small">—</span>';
  var lbl = { active: "GTT active", triggered: "GTT triggered", done: "GTT done", error: "GTT error", deleted: "GTT deleted", cancelled: "GTT cancelled", expired: "GTT expired" }[g.status] || ("GTT " + g.status);
  var cls = g.status === "active" ? "good" : g.status === "triggered" ? "" : "bad";
  return '<span class="badge ' + cls + '" title="Zerodha GTT ' + esc(g.id) + '">' + esc(lbl) + "</span>" +
    (g.sl ? '<div class="small muted num">SL ' + px.format(g.sl) + " · Target " + px.format(g.target) + "</div>" : "");
}
function bindRowLinks() { document.querySelectorAll("tr[data-go]").forEach(function (tr) { tr.onclick = function () { go(tr.getAttribute("data-go")); }; }); }

function appOverview() {
  appLayout("", "Overview", '<div class="stack"><div id="kb"></div><div class="grid g4" id="kpis"></div>' +
    '<div class="card"><div class="card-head"><div><h3>My algos</h3><p class="muted small">Each algo has its own money, limit and mode.</p></div><a class="btn sm ghost" href="#/app/algos">Browse all ' + CFG.algos.length + ' algos</a></div><div id="my"></div></div>' +
    '<div class="card"><div class="card-head"><h3>Recent trades</h3><a class="btn sm quiet" href="#/app/trades">All trades</a></div><div id="rt"></div></div></div>');
  PAGE.paint = function () {
    $("kb").innerHTML = kiteBanner(); on("kc2", "click", connectKite);
    var run = DASH.subs.filter(function (s) { return s.running; });
    var act = DASH.subs.filter(function (s) { return s.running || s.positions.length; });
    var cap = run.reduce(function (t, s) { return t + s.amount; }, 0), val = act.reduce(function (t, s) { return t + s.value; }, 0), pnl = act.reduce(function (t, s) { return t + s.pnl; }, 0);
    $("kpis").innerHTML = '<div class="card kpi"><div class="lbl">Algos running</div><b>' + run.length + ' <span class="muted">/ ' + CFG.algos.length + "</span></b></div>" +
      '<div class="card kpi"><div class="lbl">Money in running algos</div><b class="num">' + money.format(cap) + "</b></div>" +
      '<div class="card kpi"><div class="lbl">Value now</div><b class="num">' + money.format(val) + "</b></div>" +
      '<div class="card kpi"><div class="lbl">Profit / loss</div><b class="num ' + (pnl >= 0 ? "up" : "dn") + '">' + (pnl >= 0 ? "+" : "") + money.format(pnl) + "</b></div>";
    $("my").innerHTML = DASH.subs.length ? table(["Algo", "Mode", "Status", "Money", "Value", "P&amp;L", '<span class="l">Latest</span>'], subRows(DASH.subs)) :
      '<div class="empty">No algos yet. <a href="#/app/algos">See the algos</a>: each one opens as soon as its strategy is added.</div>';
    $("rt").innerHTML = table(["Time", "Algo", "Side", "Symbol", "Qty", "Price", "Type", '<span class="l">Note</span>'], tradeRows(DASH.trades.slice(0, 8), true), "Trades appear here after an algo runs.");
    bindRowLinks();
  };
}

function modeSwitch(active) {
  var run = DASH ? DASH.subs.filter(function (s) { return s.running; }) : [];
  return '<div class="modesw" role="tablist" aria-label="Trading mode"><a role="tab" href="#/app/algos" aria-selected="' + (active === "algo") + '"><b>Algo trading</b><span>' +
    (run.length ? run.length + " algo" + (run.length > 1 ? "s" : "") + " running" : "Algos trade for you by rules") + '</span></a><a role="tab" href="#/app/trade" aria-selected="' + (active === "manual") + '"><b>Manual trading</b><span>Search and place orders yourself</span></a></div>';
}
function appAlgos() {
  appLayout("algos", "Algo trading", modeSwitch("algo") + '<p class="muted" style="margin-top:0">Pick an algo to set it up. Live algos can run in paper mode or with real orders. The others will open as soon as their strategies are added.</p><div class="grid auto" id="ag"></div>');
  PAGE.paint = function () {
    $("ag").innerHTML = CFG.algos.map(function (a) {
      var s = subOf(a.id), st = s ? (s.running ? '<span class="badge good"><span class="dot"></span>Running · ' + (s.paper ? "paper" : "live") + "</span>" : '<span class="badge">Stopped</span>') : "";
      return algoCard(a, '<div style="display:flex;gap:8px;align-items:center">' + st + '<a class="btn sm' + (a.ready ? "" : " quiet") + '" href="#/app/algo/' + a.id + '">' + (a.ready ? "Open" : "View") + "</a></div>");
    }).join("");
  };
}

// ---------------- NIFTY Future swing chart (TradingView Lightweight Charts, saved in web/)
function futChartCard() {
  return '<div class="card"><div class="card-head"><div><h3>Chart · NIFTY future, 1-hour candles</h3><p class="muted small" id="fc-sub">Candles with the 50 SMA and Bollinger band (50, SD 1). ' +
    '<b style="color:var(--good)">▲ BUY</b> = all three buy conditions first true (opens a long, or covers a short and buys). <b style="color:var(--bad)">▼ SELL</b> = while long, an exit condition turned true (long closed, short opened). ' +
    'Circles = your trades (B = bought, S = sold, with quantity; they also include the 8% target and 5% stop-loss exits). Completed candles only, like the algo.</p></div><button class="btn ghost sm" type="button" id="fc-go">Refresh chart</button></div>' +
    '<div class="fc-now" id="fc-now"></div>' +
    '<div id="fc-main" class="fc-box" style="height:420px"></div>' +
    '<div class="lbl" style="margin:10px 0 4px">RSI(8) and %b(50, SD 1)</div><div id="fc-ind" class="fc-box" style="height:160px"></div>' +
    '<div class="fc-legend small muted"><span><i style="background:#f59e0b"></i>SMA 50</span><span><i style="background:#8b8bd8"></i>Bollinger band</span><span><i style="background:#2f80ed"></i>RSI(8)</span><span><i style="background:#c2410c"></i>%b</span><span>Dotted: RSI 60 / 40, %b 51 / 50</span></div>' +
    '<p id="fc-msg" class="msg small" role="status"></p><div id="fc-sig"></div></div>';
}
var LWC_PROMISE = null;
function loadLWC() {
  if (window.LightweightCharts) return Promise.resolve();
  if (!LWC_PROMISE) LWC_PROMISE = new Promise(function (ok, bad) {
    var sc = document.createElement("script"); sc.src = "/static/lightweight-charts.js"; sc.onload = ok;
    sc.onerror = function () { LWC_PROMISE = null; bad(); }; document.head.appendChild(sc);
  });
  return LWC_PROMISE;
}
var FC = { charts: [] };
function futChartLoad() {
  var m = $("fc-msg"), b = $("fc-go"); if (!m) return;
  if (b && !b.dataset.on) { b.dataset.on = 1; b.addEventListener("click", futChartLoad); }
  say(m, true, "Loading the chart from Kite…"); if (b) b.disabled = true;
  Promise.all([loadLWC(), api("/algos/futures/chart")]).then(function (r) {
    if (b) b.disabled = false;
    var x = r[1];
    if (!x.ok) { say(m, false, errText(x, "Could not load the chart")); return; }
    say(m, true, ""); futChartDraw(x.d);
  }).catch(function () { if (b) b.disabled = false; say(m, false, "Could not load the chart. Check the connection and press Refresh chart."); });
}
function futChartDraw(d) {
  FC.charts.forEach(function (c) { c.remove(); }); FC.charts = [];
  var cs = getComputedStyle(document.documentElement), v = function (n) { return cs.getPropertyValue(n).trim(); };
  var L = window.LightweightCharts, ink = v("--muted"), line = v("--line"), good = v("--good"), bad = v("--bad");
  var base = { layout: { background: { type: "solid", color: "transparent" }, textColor: ink, fontFamily: "Instrument Sans, system-ui, sans-serif" },
    grid: { vertLines: { color: line }, horzLines: { color: line } }, rightPriceScale: { borderColor: line },
    timeScale: { borderColor: line, timeVisible: true, secondsVisible: false }, crosshair: { mode: 0 },
    localization: { locale: "en-IN", priceFormatter: function (p) { return p.toLocaleString("en-IN", { maximumFractionDigits: 2 }); } } };
  var main = L.createChart($("fc-main"), Object.assign({ autoSize: true }, base));
  var ind = L.createChart($("fc-ind"), Object.assign({ autoSize: true }, base));
  FC.charts = [main, ind];
  var cnd = main.addCandlestickSeries({ upColor: good, downColor: bad, borderUpColor: good, borderDownColor: bad, wickUpColor: good, wickDownColor: bad });
  cnd.setData(d.candles);
  var opt = function (c, w, style) { return { color: c, lineWidth: w || 2, lineStyle: style || 0, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }; };
  main.addLineSeries(opt("#8b8bd8", 1)).setData(d.bbu);
  main.addLineSeries(opt("#8b8bd8", 1)).setData(d.bbl);
  main.addLineSeries(opt("#f59e0b", 2)).setData(d.ma);
  var marks = d.signals.map(function (s) {
    return s.type === "BUY" ? { time: s.time, position: "belowBar", color: good, shape: "arrowUp", text: "BUY" }
                            : { time: s.time, position: "aboveBar", color: bad, shape: "arrowDown", text: "SELL" };
  }).concat(d.trades.map(function (t) {
    return { time: t.time, position: t.side === "BUY" ? "belowBar" : "aboveBar", color: t.side === "BUY" ? good : bad, shape: "circle",
             text: (t.side === "BUY" ? "B " : "S ") + t.qty };
  })).sort(function (p, q) { return p.time - q.time; });
  cnd.setMarkers(marks);
  var rsi = ind.addLineSeries(opt("#2f80ed", 2)), pb = ind.addLineSeries(opt("#c2410c", 2));
  rsi.setData(d.rsi); pb.setData(d.pctb);
  [[d.levels.rsi_buy, "#2f80ed"], [d.levels.rsi_exit, "#2f80ed"]].forEach(function (l) { rsi.createPriceLine({ price: l[0], color: l[1], lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "" }); });
  [[d.levels.pctb_buy, "#c2410c"], [d.levels.pctb_exit, "#c2410c"]].forEach(function (l) { pb.createPriceLine({ price: l[0], color: l[1], lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" }); });
  // keep both charts on the same time window
  var busy = false;
  [[main, ind], [ind, main]].forEach(function (p) {
    p[0].timeScale().subscribeVisibleLogicalRangeChange(function (r) { if (busy || !r) return; busy = true; p[1].timeScale().setVisibleLogicalRange(r); busy = false; });
  });
  var n = d.candles.length; main.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 120), to: n + 3 });
  var l = d.last, state = l.buy_ok ? '<span class="sig BUY">All BUY conditions true</span>' : l.exit_ok ? '<span class="sig SELL">Exit condition true</span>' : '<span class="sig HOLD">Mixed</span>';
  $("fc-now").innerHTML = '<div><span class="muted small">Contract</span><b>' + esc(d.symbol) + "</b></div>" +
    '<div><span class="muted small">Price now</span><b class="num">' + (d.ltp == null ? "—" : px.format(d.ltp)) + "</b></div>" +
    '<div><span class="muted small">Last 1h close</span><b class="num">' + px.format(l.close) + "</b></div>" +
    '<div><span class="muted small">SMA 50</span><b class="num">' + (l.ma == null ? "—" : px.format(l.ma)) + "</b></div>" +
    '<div><span class="muted small">RSI(8)</span><b class="num">' + (l.rsi == null ? "—" : l.rsi.toFixed(1)) + "</b></div>" +
    '<div><span class="muted small">%b</span><b class="num">' + (l.pctb == null ? "—" : l.pctb.toFixed(1)) + "</b></div>" +
    '<div><span class="muted small">Now</span>' + state + "</div>";
  var recent = d.signals.slice(-8).reverse();
  $("fc-sig").innerHTML = '<div class="lbl" style="margin-top:12px">Latest signals on this chart</div>' + table(["Candle (IST)", "Signal", "Close"], recent.map(function (s) {
    return "<tr><td>" + chartTime(s.time) + '</td><td><span class="sig ' + s.type + '">' + s.type + "</span></td><td>" + px.format(s.price) + "</td></tr>";
  }), "No BUY or SELL signal in the last " + n + " one-hour candles.");
}
function chartTime(t) { // chart times are IST clock times stored as UTC
  return new Date(t * 1000).toLocaleString("en-IN", { timeZone: "UTC", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

function appAlgo(id) {
  var a = ALG[id]; if (!a) { go("/app/algos"); return; }
  var s0 = subOf(id), pf = null;
  try { pf = JSON.parse(sessionStorage.getItem("mjvs_prefill") || "null"); if (pf && pf.algo === id) sessionStorage.removeItem("mjvs_prefill"); else pf = null; } catch (e) {}
  var amount = s0 ? s0.amount : (pf ? pf.amount : Math.max(1000, a.min_amount)), dd = Math.min(s0 ? s0.drawdown_pct : (pf ? pf.dd : (a.default_drawdown || 10)), a.max_drawdown || 15);
  var uni = (s0 && s0.universe) || a.default_universe, paper = s0 ? s0.paper : true;
  var uniKeys = Object.keys(a.universes || {});
  var settings = '<div class="card" id="setcard"><div class="card-head"><h3>Settings</h3><span id="runbadge"></span></div>' +
    (a.ready ? "" : '<div class="note" style="margin-bottom:14px">This algo’s strategy is still being added, so it cannot be started yet.</div>') +
    (a.warning ? '<div class="note" role="alert" style="margin-bottom:14px;font-weight:600">⚠ ' + esc(a.warning) + "</div>" : "") +
    (a.ready && !a.auto_trade ? '<div class="info" style="margin-bottom:14px">This algo only <b>suggests</b> stocks that pass both the scanner and the TradingView strategy. See them below and on the <a href="#/app/suggestions">Suggestions</a> page.</div>' : "") +
    '<div class="field"><label for="s-amt">Money for this algo</label><div class="amt"><span>₹</span><input id="s-amt" inputmode="numeric" value="' + Number(amount).toLocaleString("en-IN") + '"></div><small>' + (a.group === "fno" ? "Lots are worked out from this money: about 15% of one lot’s value is kept as margin (NIFTY: roughly ₹2.5–3 lakh per lot). Zerodha checks the real margin." : (a.max_price ? "" : "Any amount you choose. Split equally across positions, so each position gets this amount ÷ most positions.")) + '</small><small id="s-each"></small><div id="s-cash" class="small" style="margin-top:6px"></div></div>' +
    '<div class="field"><label for="s-dd">Drawdown limit: <span id="s-ddv">' + dd + '%</span></label><input id="s-dd" type="range" min="5" max="' + (a.max_drawdown || 15) + '" step="1" value="' + dd + '"><small id="s-ddh"></small></div>' +
    (uniKeys.length > 1 ? '<div class="field"><label for="s-uni">What to trade</label><select id="s-uni">' + uniKeys.map(function (k) { return '<option value="' + esc(k) + '"' + (k === uni ? " selected" : "") + ">" + esc(a.universes[k]) + "</option>"; }).join("") + "</select></div>" : "") +
    '<div class="field" id="s-maxw"><label for="s-max">Most positions at once</label><input id="s-max" type="number" min="1" max="20" value="' + ((s0 && s0.max_positions) || a.max_positions) + '"></div>' +
    '<div class="field"><div class="lbl">Mode</div><div class="seg" id="s-mode"><button type="button" data-v="paper">Paper (no real orders)</button><button type="button" data-v="live">Live</button></div>' +
    (CFG.allow_live ? "" : '<small>Live trading is switched off. ' + (DASH && DASH.is_admin ? '<a href="#/app/admin">Switch it on in Admin</a>.' : "The admin can switch it on.") + '</small>') + "</div>" +
    '<button class="btn block" type="button" id="s-go"' + (a.ready && a.auto_trade ? "" : " disabled") + '>Start algo</button>' +
    '<div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap"><button class="btn ghost sm" type="button" id="s-run" hidden>Run once now (paper test)</button><button class="btn quiet sm" type="button" id="s-reset">Clear paper trades</button></div>' +
    '<p id="s-msg" class="msg" role="status"></p></div>';
  var status = '<div class="card"><div class="card-head"><h3>Account</h3></div><div id="acct"></div><div class="lbl" style="margin-top:14px">Latest from the algo</div><div class="logbox" id="lastmsg">Not started yet.</div>' +
    '<div class="lbl" style="margin-top:16px">How this algo runs</div><div class="row"><span>Signals</span><b>' + sourceLabel(a) + (a.source === "scan" ? " · " + esc(a.candle_label || ({ day: "daily", "60minute": "1-hour", "30minute": "30-minute", "15minute": "15-minute", "5minute": "5-minute", minute: "1-minute" }[a.interval] || a.interval)) + " candles" : "") + '</b></div><div class="row"><span>Runs</span><b>' + esc(runsText(a)) + '</b></div><div class="row"><span>Exits</span><b>' + esc(exitsText(a)) + '</b></div><div class="row"><span>Order type</span><b>Market · ' + esc(a.product) + "</b></div></div>";
  var sig = '<div class="card"><div class="card-head"><div><h3>' + (a.source === "scan" ? "Scanner" : "Chartink alerts") + '</h3><p class="muted small">' +
    (a.source === "scan" ? (uniKeys.length === 1 ? esc(a.universes[uniKeys[0]]) + " · " : "") + "Your rule on completed candles. BUY rows are bought into free slots, strongest first. Press Buy to buy one yourself." + (a.universes && a.universes.all ? " A full scan of about 2,000 stocks takes 10–15 minutes." : "") : "Stocks sent by this algo’s Chartink scanner. New alerts are bought at the next run.") + "</p></div>" +
    (a.source === "scan" && a.ready ? '<div style="display:flex;gap:8px;flex-wrap:wrap">' + (uniKeys.length > 1 ? '<select id="sc-uni" style="width:auto">' + uniKeys.map(function (k) { return '<option value="' + esc(k) + '"' + (k === uni ? " selected" : "") + ">" + esc(a.universes[k]) + "</option>"; }).join("") + "</select>" : "") + '<button class="btn sm" type="button" id="sc-go">Scan now</button></div>' : "") +
    '</div><p id="sc-msg" class="msg small" role="status"></p><div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:8px"><p class="small muted" id="sc-at" style="margin:0"></p>' +
    (a.source === "scan" ? '<div class="seg" id="sc-f"><button type="button" data-v="">All</button><button type="button" data-v="BUY">BUY</button><button type="button" data-v="SELL">SELL</button><button type="button" data-v="HOLD">HOLD</button></div>' : "") + '</div><div id="sc"></div></div>';
  appLayout("algos", a.name, '<div class="crumb"><a href="#/app/algos">Algos</a> / ' + esc(a.name) + "</div>" +
    '<div class="algo-head"><div><h2>' + esc(a.name) + " " + stars(a.stars) + '</h2><div class="meta">' + statusBadge(a) + '<span class="badge">' + esc(a.holding) + '</span><span class="badge">' + sourceLabel(a) + "</span></div>" +
    '<p class="muted" style="margin:10px 0 0;max-width:60ch">' + esc(a.blurb) + "</p></div></div>" +
    '<div class="stack"><div id="kb"></div><div class="grid g2">' + settings + status + "</div>" +
    (a.require_tradingview || a.suggest ? '<div class="card"><div class="card-head"><div><h3>Suggestions' + (a.require_tradingview ? ": scanner + TradingView" : "") + '</h3><p class="muted small">' +
      (a.require_tradingview ? "Stocks that passed both checks" + (a.match_minutes ? " within " + a.match_minutes + " minutes" : " on the same day") + "." : "Fresh BUY signals from this algo’s scanner. The scanner runs by itself every trading morning.") +
      (a.auto_trade ? " Running members buy them at the next check." : " This algo only suggests; it places no orders.") + '</p></div></div><div id="sg"></div></div>' : "") +
    (id === "futures" ? futChartCard() : "") + sig +
    '<div class="card"><div class="card-head"><h3>Open positions</h3></div><div id="ps"></div></div>' +
    '<div class="card"><div class="card-head"><h3>Trades</h3></div><div id="ts"></div></div></div>');

  if ((a.max_drawdown || 15) <= 5) $("s-dd").disabled = true;
  function amt() { return parseFloat(($("s-amt").value || "").replace(/[^0-9.]/g, "")) || 0; }
  function ddHint() { var v = +$("s-dd").value; $("s-ddv").textContent = v + "%"; $("s-ddh").textContent = a.group === "fno" ? "Stops taking new trades when losses on closed trades reach " + money.format(amt() * v / 100) + ". Each trade also has its own 5% stop loss." : a.sl_from_drawdown ? "Stop loss for each stock: sold if it falls " + v + "% below its buy price. The whole algo also stops if it is down " + money.format(amt() * v / 100) + " from its peak." : "Stops and sells everything if this algo is down " + money.format(amt() * v / 100) + " from its peak."; }
  function maxVis() { $("s-maxw").hidden = a.group === "fno"; }
  function setMode(v) { paper = v === "paper"; $("s-mode").querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-v") === v); }); goLabel(); cashHint(); }
  function goLabel() {
    var g = $("s-go"), s = subOf(id), run = !!(s && s.running); if (!g) return;
    g.textContent = !a.auto_trade && a.ready ? "Suggestions only" : run ? "Stop algo" : (paper ? "Start in paper mode" : "Start with LIVE orders");
    g.className = "btn block" + (run ? " danger" : "");
  }
  var kiteCash = null;
  function cashHint() {
    var el = $("s-cash"); if (!el) return;
    var n = $("s-max") ? (+$("s-max").value || a.max_positions) : a.max_positions;
    if ($("s-each")) $("s-each").textContent = a.group === "fno" || a.max_price || !amt() ? "" : " Each stock gets about " + money.format(amt() / n) + " (" + money.format(amt()) + " ÷ " + n + ").";
    if (kiteCash == null) { el.innerHTML = ""; return; }
    el.innerHTML = amt() > kiteCash
      ? '<div class="note" role="alert" style="background:var(--bad-soft);color:var(--bad)"><b>Amount is less in your Zerodha account.</b> Available: ' + money.format(kiteCash) + ", you entered " + money.format(amt()) + ". " + (paper ? "Paper mode can still start; Live needs the full amount." : "Live cannot start: lower the amount or add money in Kite.") + "</div>"
      : '<span class="muted">Zerodha cash available: <b class="num">' + money.format(kiteCash) + "</b></span>";
  }
  api("/kite/funds").then(function (x) { if (x.ok && x.d.cash != null) { kiteCash = x.d.cash; cashHint(); } });
  on("s-amt", "input", function (e) { var v = e.target.value.replace(/[^0-9]/g, ""); e.target.value = v ? Number(v).toLocaleString("en-IN") : ""; ddHint(); cashHint(); });
  on("s-dd", "input", ddHint); on("s-max", "input", cashHint); on("s-uni", "change", maxVis);
  $("s-mode").addEventListener("click", function (e) { var b = e.target.closest("button"); if (b && !b.disabled) setMode(b.getAttribute("data-v")); });
  setMode(paper ? "paper" : "live"); ddHint(); maxVis();

  on("s-go", "click", function () {
    var m = $("s-msg"), s = subOf(id);
    if (s && s.running) { api("/algos/" + id + "/stop", { method: "POST" }).then(function (x) { say(m, x.ok, x.ok ? "Algo stopped. Open positions are kept." : errText(x, "Could not stop")); refresh(); }); return; }
    if (!paper && !confirm("LIVE mode places REAL orders in your Zerodha account with real money, up to " + money.format(amt()) + ". Continue?")) return;
    var body = { amount: amt(), drawdown_pct: +$("s-dd").value, max_positions: +$("s-max").value || a.max_positions, universe: $("s-uni") ? $("s-uni").value : "", paper: paper };
    api("/algos/" + id + "/start", { method: "POST", json: body }).then(function (x) { say(m, x.ok, x.ok ? "Algo started." + (x.d.warning ? " ⚠ " + x.d.warning : "") : errText(x, "Please check your settings")); refresh(); }).catch(function () { say(m, false, "Could not reach the server"); });
  });
  on("s-run", "click", function () {
    var m = $("s-msg"), b = this; b.disabled = true; say(m, true, "Running… a full scan can take about 20 seconds.");
    api("/algos/" + id + "/run-now", { method: "POST" }).then(function (x) { b.disabled = false; say(m, x.ok, x.ok ? "Done." : errText(x, "Run failed")); refresh(); }).catch(function () { b.disabled = false; say(m, false, "Could not reach the server"); });
  });
  on("s-reset", "click", function () {
    if (!confirm("Delete this algo’s paper trades and start its paper account fresh?")) return;
    api("/algos/" + id + "/paper-reset", { method: "POST" }).then(function (x) { say($("s-msg"), x.ok, x.ok ? "Paper trades cleared." : errText(x, "Could not clear")); refresh(); });
  });
  on("sc-go", "click", function () {
    var m = $("sc-msg"), b = this; b.disabled = true; say(m, true, "Starting the scan…");
    var u = $("sc-uni") ? $("sc-uni").value : uni;
    api("/algos/" + id + "/scan", { method: "POST", json: { universe: u } }).then(function (x) {
      if (!x.ok) { b.disabled = false; say(m, false, errText(x, "Scan failed")); return; }
      watchScan(u);
    }).catch(function () { b.disabled = false; say(m, false, "Could not reach the server"); });
  });
  on("sc-uni", "change", function () { loadSignals(this.value); });
  function jobText(j) {
    if (!j.total) return j.step + "…";
    var left = Math.max(0, Math.ceil((j.total - j.done) * 0.4 / 60));
    return j.step + ": " + j.done + " of " + j.total + " stocks" + (left > 0 ? " · about " + left + " min left" : "");
  }
  function watchScan(u) {
    var m = $("sc-msg"), b = $("sc-go");
    api("/algos/" + id + "/signals?universe=" + encodeURIComponent(u)).then(function (x) {
      if (!$("sc-msg")) return;            // page changed
      var j = x.ok && x.d.job;
      if (j && j.running) { if (b) b.disabled = true; say(m, true, jobText(j) + ". You can leave this page; the scan keeps going."); setTimeout(function () { watchScan(u); }, 2000); return; }
      if (b) b.disabled = false;
      if (j && j.error) say(m, false, j.error); else { m.textContent = ""; toast("Scan finished"); }
      loadSignals(u);
    }).catch(function () { setTimeout(function () { watchScan(u); }, 4000); });
  }

  var scanRows = [], scanF = "BUY";
  on("sc-f", "click", function (e) { var b = e.target.closest("button"); if (!b) return; scanF = b.getAttribute("data-v"); drawScan(scanRows, null, true); });
  function drawScan(rows, at, keepAt) {
    scanRows = rows || [];
    if (!keepAt) $("sc-at").textContent = at ? "Last scan: " + when(at) + " · " + scanRows.filter(function (r) { return r.signal === "BUY"; }).length + " BUY of " + scanRows.length : "";
    if ($("sc-f")) $("sc-f").querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-v") === scanF); });
    var cols = a.columns || [];
    var buyCol = a.group !== "fno";
    $("sc").innerHTML = table(["Symbol", "Signal", "Close"].concat(cols.map(function (c) { return esc(c[1]); })).concat(buyCol ? [""] : []), scanRows.filter(function (r) { return !scanF || r.signal === scanF; }).map(function (r) {
      if (r.signal === "ERROR") return "<tr><td><b>" + short(r.symbol) + '</b></td><td><span class="sig ERROR">ERROR</span></td><td class="wrap" colspan="' + (1 + cols.length) + '" style="text-align:left">' + esc(r.error) + "</td></tr>";
      return "<tr><td><b>" + short(r.symbol) + "</b>" + (r.trade_symbol !== r.symbol ? ' <span class="muted small">→ ' + short(r.trade_symbol) + "</span>" : "") + '</td><td><span class="sig ' + esc(r.signal) + '">' + esc(r.signal) + "</span></td><td>" + px.format(r.close) + "</td>" +
        cols.map(function (c) { return "<td>" + (r[c[0]] == null ? "—" : esc(r[c[0]])) + "</td>"; }).join("") +
        (buyCol ? "<td>" + (r.signal === "BUY" ? buyBtn(r.trade_symbol, r.ltp || r.close) : "") + "</td>" : "") + "</tr>";
    }), !a.ready ? "The scanner opens when the strategy is added." : scanRows.length ? "No stock has a " + scanF + " signal in the last scan (" + scanRows.length + " checked). Choose All to see every stock." : "No scan yet. Connect Kite and press Scan now.");
  }
  function drawAlerts(list) {
    $("sc").innerHTML = table(["Time", "Symbol", "Trigger price", "From", '<span class="l">Scan</span>'], list.map(function (x) {
      return "<tr><td>" + when(x.at) + "</td><td><b>" + short(x.symbol) + "</b></td><td>" + (x.price == null ? "—" : px.format(x.price)) + "</td><td>" + ({ chartink: "Chartink", tradingview: "TradingView", test: "Test" }[x.source] || esc(x.source)) + (x.action === "SELL" ? ' <span class="sig SELL">SELL</span>' : "") + '</td><td class="wrap">' + esc(x.note) + "</td></tr>";
    }), "No alerts yet. Alerts arrive here from this algo’s Chartink scanner" + (a.require_tradingview ? " and TradingView strategy." : "."));
  }
  function loadSignals(u) {
    api("/algos/" + id + "/signals?universe=" + encodeURIComponent(u || uni || "")).then(function (x) { if (!x.ok) return; if (a.source === "scan") drawScan(x.d.scan, x.d.scan_at); else drawAlerts(x.d.alerts);
      if (x.d.job && x.d.job.running && $("sc-go") && !$("sc-go").disabled) watchScan(u || uni || "");
      if ($("sg")) $("sg").innerHTML = table(["Date", "Stock", "Price at match", "LTP now", "Scanner", "TradingView", ""], sugRows(x.d.suggestions, false), "No matches yet."); });
  }
  loadSignals(uni);
  if (id === "futures") futChartLoad();

  PAGE.paint = function () {
    $("kb").innerHTML = DASH.kite.fresh ? "" : kiteBanner(); on("kc2", "click", connectKite);
    var s = subOf(id), run = !!(s && s.running);
    $("runbadge").innerHTML = s ? (run ? '<span class="badge good"><span class="dot"></span>Running · ' + (s.paper ? "paper" : "LIVE") + "</span>" : '<span class="badge">Stopped</span>') : "";
    ["s-amt", "s-dd", "s-uni", "s-max"].forEach(function (f) { if ($(f)) $(f).disabled = run || !a.ready || !a.auto_trade || (f === "s-dd" && (a.max_drawdown || 15) <= 5); });
    $("s-mode").querySelectorAll("button").forEach(function (b) { b.disabled = run || !a.ready; });
    if (run) setMode(s.paper ? "paper" : "live");
    goLabel();
    $("s-run").hidden = !(run && s.paper);
    $("acct").innerHTML = s ? '<div class="row"><span>Value now</span><b class="num">' + money.format(s.value) + '</b></div><div class="row"><span>Profit / loss</span><b>' + signed(s.pnl) + '</b></div><div class="row"><span>Cash with algo</span><b class="num">' + money.format(s.cash) +
      '</b></div><div class="row"><span>Peak value</span><b class="num">' + money.format(s.peak) + '</b></div><div class="row"><span>Stops below</span><b class="num">' + money.format(s.peak * (1 - s.drawdown_pct / 100)) + " (" + s.drawdown_pct + "%)</b></div>"
      : '<div class="empty">Set the money and limit, then start in paper mode.</div>';
    $("lastmsg").textContent = s && s.last_message ? (s.last_run_at ? when(s.last_run_at) + " · " : "") + s.last_message : "Not started yet.";
    var gt = !!(a.use_gtt && s && !s.paper);
    $("ps").innerHTML = table(["Symbol", "Qty", "Avg", "LTP", "P&amp;L", "Since"].concat(gt ? ["Zerodha GTT"] : []), posRows(s ? s.positions : [], false, gt), "No open positions.");
    $("ts").innerHTML = table(["Time", "Side", "Symbol", "Qty", "Price", "Type", '<span class="l">Note</span>'], tradeRows(DASH.trades.filter(function (t) { return t.algo_id === id; })), "No trades yet.");
  };
  PAGE.reload = function () { loadSignals($("sc-uni") ? $("sc-uni").value : uni); };
}

function allPositions() {
  var out = [];
  DASH.subs.forEach(function (s) { s.positions.forEach(function (p) { out.push(Object.assign({ algo: (ALG[s.algo_id] || {}).name || s.algo_id }, p)); }); });
  return out;
}
function appPositions() {
  appLayout("positions", "Positions", '<div class="card"><div class="card-head"><div><h3>Open positions</h3><p class="muted small">From each algo’s own trades. Prices update while Kite is connected.</p></div></div><div id="ps"></div></div>');
  PAGE.paint = function () { $("ps").innerHTML = table(["Algo", "Symbol", "Qty", "Avg", "LTP", "P&amp;L", "Since", "Zerodha GTT"], posRows(allPositions(), true, true), "No open positions."); };
}
function appTrades() {
  appLayout("trades", "Trades", '<div class="card"><div class="card-head"><div><h3>All trades</h3><p class="muted small">Every trade is saved permanently, paper and live.</p></div><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn sm quiet" type="button" id="tcsv">Download CSV</button><select id="tf" style="width:auto"><option value="">All algos</option>' + CFG.algos.map(function (a) { return '<option value="' + a.id + '">' + esc(a.name) + "</option>"; }).join("") + '</select></div></div><div id="ts"></div></div>');
  on("tf", "change", function () { PAGE.paint(); }); on("tcsv", "click", function () { download("/trades.csv", "mjvs-trades.csv"); });
  PAGE.paint = function () { var f = $("tf").value; $("ts").innerHTML = table(["Time", "Algo", "Side", "Symbol", "Qty", "Price", "Type", '<span class="l">Note</span>'], tradeRows(DASH.trades.filter(function (t) { return !f || t.algo_id === f; }), true), "No trades yet."); };
}
// ---- Kite-style order window (Buy from scanner / suggestions)
function buyBtn(sym, price) { return '<button type="button" class="btn sm buybtn" data-buy="' + esc(sym) + '" data-px="' + esc(price || "") + '">Buy</button>'; }
document.addEventListener("click", function (e) { var b = e.target.closest && e.target.closest("[data-buy]"); if (b) openOrderPad(b.getAttribute("data-buy"), +b.getAttribute("data-px") || null); });
function openOrderPad(sym, px0) {
  var old = $("opad"); if (old) old.remove();
  var live = false; try { live = CFG.allow_live && localStorage.getItem("mjvs_trade_mode") === "live"; } catch (e) {}
  var otype = "MARKET", name = String(sym).split(":").pop(), exch = String(sym).split(":")[0];
  var el = document.createElement("div"); el.id = "opad"; el.className = "opad-bg";
  el.innerHTML = '<div class="opad" role="dialog" aria-modal="true" aria-labelledby="opad-t"><div class="opad-h"><div><b id="opad-t">Buy ' + esc(name) + '</b><span>' + esc(exch) + ' · <span id="opad-ltp">' + (px0 ? "₹" + px.format(px0) : "") + "</span></span></div>" +
    '<div class="seg" id="opad-mode"><button type="button" data-v="paper" aria-pressed="' + !live + '">Paper</button><button type="button" data-v="live" aria-pressed="' + live + '"' + (CFG.allow_live ? "" : " disabled") + ">Live</button></div></div>" +
    '<div class="opad-b"><div class="grid g2" style="gap:12px"><div class="field"><label for="opad-q">Qty.</label><input id="opad-q" type="number" min="1" step="1" value="1"></div>' +
    '<div class="field"><label for="opad-p">Price</label><input id="opad-p" type="number" min="0" step="0.05" value="' + (px0 || "") + '" disabled></div></div>' +
    '<div class="field"><div class="seg" id="opad-type"><button type="button" data-v="MARKET" aria-pressed="true">Market</button><button type="button" data-v="LIMIT" aria-pressed="false">Limit</button></div>' +
    '<span class="badge" style="margin-left:8px">CNC · Delivery</span></div><p class="small muted" id="opad-est"></p><p id="opad-msg" class="msg" role="status"></p></div>' +
    '<div class="opad-f"><button type="button" class="btn opad-go" id="opad-go">Buy</button><button type="button" class="btn quiet" id="opad-x">Cancel</button></div></div>';
  document.body.appendChild(el);
  function est() { var q = +$("opad-q").value || 0, p = otype === "LIMIT" ? +$("opad-p").value : px0; $("opad-est").textContent = q && p ? "Approx. " + money.format(q * p) + (live ? " · LIVE order in your Zerodha account" : " · paper order (no real money)") : ""; $("opad-go").textContent = live ? "Buy (LIVE)" : "Buy (paper)"; }
  function close() { el.remove(); document.removeEventListener("keydown", esc_); }
  function esc_(e) { if (e.key === "Escape") close(); }
  document.addEventListener("keydown", esc_);
  el.addEventListener("click", function (e) { if (e.target === el) close(); });
  $("opad-x").onclick = close;
  $("opad-q").oninput = est; $("opad-p").oninput = est;
  $("opad-type").onclick = function (e) { var b = e.target.closest("button"); if (!b) return; otype = b.getAttribute("data-v"); this.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", x === b); }); $("opad-p").disabled = otype !== "LIMIT"; est(); };
  $("opad-mode").onclick = function (e) { var b = e.target.closest("button"); if (!b || b.disabled) return; live = b.getAttribute("data-v") === "live"; try { localStorage.setItem("mjvs_trade_mode", live ? "live" : "paper"); } catch (er) {} this.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", x === b); }); est(); };
  $("opad-go").onclick = function () {
    var m = $("opad-msg"), btn = this, q = +$("opad-q").value;
    if (!(q >= 1)) { say(m, false, "Enter a quantity of 1 or more"); return; }
    var body = { symbol: sym, side: "BUY", lots: q, order_type: otype, product: "CNC", paper: !live };
    if (otype === "LIMIT") body.price = +$("opad-p").value;
    if (live && !confirm("Place a LIVE BUY order for " + q + " " + name + " in your Zerodha account?")) return;
    btn.disabled = true; say(m, true, "Sending…");
    api("/orders/manual", { method: "POST", json: body }).then(function (x) { btn.disabled = false; say(m, x.ok, x.ok ? x.d.message : errText(x, "Order failed")); if (x.ok) { toast(x.d.message); setTimeout(close, 1500); } }).catch(function () { btn.disabled = false; say(m, false, "Could not reach the server"); });
  };
  est(); $("opad-q").focus();
}
function sugRows(list, withAlgo) {
  return list.map(function (x) {
    var tv = "https://www.tradingview.com/chart/?symbol=" + encodeURIComponent(String(x.symbol).replace("&", "_").replace("-", "_"));
    var chg = x.ltp != null && x.price ? (x.ltp - x.price) / x.price * 100 : null;
    return "<tr><td>" + esc(x.day) + "</td>" + (withAlgo ? "<td>" + esc((ALG[x.algo_id] || {}).name || x.algo_id) + "</td>" : "") +
      "<td><b>" + short(x.symbol) + "</b></td><td>" + (x.price == null ? "—" : px.format(x.price)) + "</td><td>" + (x.ltp == null ? "—" : px.format(x.ltp) + (chg == null ? "" : ' <span class="' + (chg >= 0 ? "up" : "dn") + ' small">' + (chg >= 0 ? "+" : "") + chg.toFixed(2) + "%</span>")) +
      "</td><td>" + when(x.scanner_at) + "</td><td>" + (x.tradingview_at ? when(x.tradingview_at) : '<span class="muted small">not needed</span>') + '</td><td style="white-space:nowrap">' + buyBtn(x.symbol, x.ltp || x.price) + ' <a class="btn sm quiet" href="' + esc(tv) + '" target="_blank" rel="noopener noreferrer">Chart</a></td></tr>';
  });
}
var SUG_HEAD = ["Date", "Algo", "Stock", "Price at match", "LTP now", "Scanner", "TradingView", ""];
function appSuggestions() {
  appLayout("suggestions", "Suggestions", '<div class="stack"><div class="info"><b>How a stock is suggested.</b> Every trading morning each algo’s scanner checks its stocks with the algo’s strategy on the last completed candle. A stock appears here on the day its BUY signal is fresh. For algos with TradingView confirmation, the stock must also get an alert from your TradingView strategy that day. Suggestions are not advice: check the chart before you act.</div>' +
    '<div class="grid g3" id="sg-k"></div><div class="card"><div class="card-head"><div><h3>Today</h3><p class="muted small">Fresh BUY signals today.</p></div><button class="btn sm quiet" type="button" id="sg-r">Refresh</button></div><div id="sg-t"></div></div>' +
    '<div class="card"><div class="card-head"><h3>Last 7 days</h3></div><div id="sg-h"></div></div></div>');
  function load() {
    api("/suggestions?days=7").then(function (x) {
      if (!x.ok) return; var d = x.d, today = d.rows.filter(function (r) { return r.day === d.today; }), old = d.rows.filter(function (r) { return r.day !== d.today; });
      var names = d.algos.map(function (id) { return (ALG[id] || {}).name || id; });
      $("sg-k").innerHTML = '<div class="card kpi"><div class="lbl">Suggested today</div><b>' + today.length + '</b></div><div class="card kpi"><div class="lbl">Last 7 days</div><b>' + d.rows.length + '</b></div>' +
        '<div class="card kpi"><div class="lbl">Algos suggesting</div><b style="font-size:18px">' + (names.length ? esc(names.join(", ")) : "None yet") + '</b><span class="muted">' + (d.tradingview.length ? "TradingView confirmation: " + esc(d.tradingview.map(function (id) { return (ALG[id] || {}).name || id; }).join(", ")) : "TradingView confirmation: off") + "</span></div>";
      $("sg-t").innerHTML = table(SUG_HEAD, sugRows(today, true), "No stock has passed both checks today yet. This page updates as alerts arrive.");
      $("sg-h").innerHTML = table(SUG_HEAD, sugRows(old, true), "Nothing in the last 7 days.");
    });
  }
  on("sg-r", "click", load); load();
  PAGE.paint = load;
}
var TR = { paper: true, ins: null, side: "BUY", otype: "MARKET", tab: "orders", timer: null };
try { TR.paper = localStorage.getItem("mjvs_trade_mode") !== "live"; } catch (e) {}
function typeBadge(r) {
  var t = r.type === "EQ" ? "Share" : r.type === "FUT" ? "Future" : r.type === "CE" ? "Call (CE)" : "Put (PE)";
  return '<span class="badge ' + (r.type === "EQ" ? "" : r.type === "FUT" ? "accent" : r.type === "CE" ? "good" : "bad") + '">' + t + "</span>";
}
function insLine(r) {
  return (r.expiry ? "Expiry " + esc(new Date(r.expiry).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })) + " · " : "") + (r.type !== "EQ" ? "Lot " + r.lot + " · " : "") + esc(r.name);
}
function appTrade() {
  appLayout("trade", "Manual trading", modeSwitch("manual") + '<div class="stack">' +
    '<div class="banner' + (TR.paper ? "" : " need") + '" id="tr-mode"></div>' +
    '<div class="grid g2"><div class="card"><div class="card-head"><div><h3>Search</h3><p class="muted small">Shares, futures and options. Try <b>SBIN</b>, <b>NIFTY FUT</b> or <b>NIFTY 24500 CE</b>.</p></div></div>' +
    '<input id="tq" type="search" placeholder="Search a stock, future or option" autocomplete="off" aria-label="Search instruments"><p id="tq-msg" class="msg small" role="status"></p><div id="tq-res" class="ires"></div></div>' +
    '<div class="card" id="ticket"><h3>Order</h3><div class="empty" style="margin-top:12px">Search and pick an instrument to see its price and place an order.</div></div></div>' +
    '<div class="card"><div class="card-head"><div><h3>Your Zerodha account today</h3><p class="muted small">Every order, position and holding in your Zerodha account, from any app: MJVS, the Kite app, Streak and others.</p></div>' +
    '<div style="display:flex;gap:8px;flex-wrap:wrap"><div class="seg" id="acc-tab"><button type="button" data-v="orders">Orders</button><button type="button" data-v="positions">Positions</button><button type="button" data-v="holdings">Holdings</button></div><button class="btn sm quiet" type="button" id="acc-r">Refresh</button></div></div><p id="acc-msg" class="msg small" role="status"></p><div id="acc"></div></div>' +
    '<div class="card"><div class="card-head"><div><h3>My manual trades</h3><p class="muted small">Orders placed on this page. Paper positions are worked out from your paper trades.</p></div></div><div id="mt-pos"></div><div id="mt"></div></div>' +
    '<div class="card streak"><div class="card-head"><div><h3>Zerodha Streak</h3><p class="muted small">Streak is Zerodha’s partner app for no-code strategies. It logs in with the same Zerodha account.</p></div><a class="btn" href="https://www.streak.tech/" target="_blank" rel="noopener noreferrer">Open Streak ↗</a></div>' +
    '<ul class="muted" style="margin:0;padding-left:20px;font-size:14px"><li>Orders that Streak places go into your same Zerodha account, so they appear above in <b>Your Zerodha account today</b>, marked “Kite / Streak / other app”.</li>' +
    '<li>Streak does not let other apps read its strategies or receive its alerts, so a Streak strategy cannot run inside MJVS directly.</li>' +
    '<li>To run a Streak strategy here as one of the MJVS algos, copy its conditions (or a Chartink scanner for it) and it can be added.</li></ul></div>' +
    "</div>");
  if (!CFG.allow_live) TR.paper = true;
  function paintMode() {
    $("tr-mode").className = "banner" + (TR.paper ? "" : " need");
    $("tr-mode").innerHTML = '<div><b>' + (TR.paper ? "Paper mode: practice, no real orders" : "LIVE mode: orders go straight to your Zerodha account (you will see them in Kite)") + "</b><p>" + (CFG.allow_live ? (TR.paper ? "Switch to Live to trade for real." : "Real money. Each order asks you to confirm.") : "Live orders are switched off. " + (DASH.is_admin ? '<a href="#/app/admin">Switch them on in Admin</a>.' : "The admin can switch them on.")) + '</p></div><div class="seg" id="tm"><button type="button" data-v="paper" aria-pressed="' + TR.paper + '">Paper</button><button type="button" data-v="live" aria-pressed="' + !TR.paper + '"' + (CFG.allow_live ? "" : " disabled") + ">Live</button></div>";
    $("tm").addEventListener("click", function (e) { var b = e.target.closest("button"); if (!b || b.disabled) return; TR.paper = b.getAttribute("data-v") === "paper"; try { localStorage.setItem("mjvs_trade_mode", TR.paper ? "paper" : "live"); } catch (er) {} paintMode(); drawTicket(); });
  }
  paintMode();
  on("tq", "input", function () {
    var q = this.value.trim(); clearTimeout(TR.timer);
    if (q.length < 2) { $("tq-res").innerHTML = ""; $("tq-msg").textContent = ""; return; }
    TR.timer = setTimeout(function () {
      say($("tq-msg"), true, "Searching…");
      api("/market/search?q=" + encodeURIComponent(q)).then(function (x) {
        if (!x.ok) { say($("tq-msg"), false, errText(x, "Search failed")); $("tq-res").innerHTML = ""; return; }
        $("tq-msg").textContent = x.d.results.length ? "" : "Nothing found. Check the spelling.";
        $("tq-res").innerHTML = x.d.results.map(function (r, i) { return '<button type="button" class="ires-row" data-i="' + i + '"><span><b>' + esc(r.symbol) + "</b><small>" + insLine(r) + "</small></span>" + typeBadge(r) + "</button>"; }).join("");
        $("tq-res").querySelectorAll("button").forEach(function (b) { b.onclick = function () { pickIns(x.d.results[+b.getAttribute("data-i")]); }; });
      });
    }, 300);
  });
  function pickIns(r) {
    TR.ins = r; TR.q = null; TR.qerr = ""; TR.side = "BUY"; TR.otype = r.type === "EQ" ? "MARKET" : "LIMIT";
    drawTicket(); loadQuote();
  }
  function loadQuote() {
    var r = TR.ins; if (!r) return;
    api("/market/quote?symbol=" + encodeURIComponent(r.exchange + ":" + r.symbol)).then(function (x) {
      if (TR.ins !== r) return;
      if (x.ok) { TR.q = x.d; TR.qerr = ""; if ($("tk-price") && !$("tk-price").value && x.d.ltp) $("tk-price").value = x.d.ltp; drawQuote(); est(); return; }
      TR.qerr = /market data/.test(errText(x, "")) ? "No price shown: your Kite plan has no market data. You can still place a LIVE order: Market (Zerodha fills it at the current price) or Limit (at your price)." : errText(x, "Price not available right now.");
      drawQuote();
    });
  }
  function drawQuote() {
    var q = TR.q, el = $("tk-q"); if (!el) return;
    if (!q) { el.innerHTML = TR.qerr ? '<div class="note small">' + esc(TR.qerr) + "</div>" : '<span class="muted small">Loading price…</span>'; return; }
    el.innerHTML = '<div class="qbig num">' + (q.ltp == null ? "—" : px.format(q.ltp)) + (q.change_pct == null ? "" : ' <span class="' + (q.change_pct >= 0 ? "up" : "dn") + '">' + (q.change_pct >= 0 ? "+" : "") + q.change_pct + "%</span>") + "</div>" +
      '<div class="qgrid small"><span>Open <b>' + (q.open == null ? "—" : px.format(q.open)) + "</b></span><span>High <b>" + (q.high == null ? "—" : px.format(q.high)) + "</b></span><span>Low <b>" + (q.low == null ? "—" : px.format(q.low)) + "</b></span><span>Bid <b>" + (q.bid == null ? "—" : px.format(q.bid)) + "</b></span><span>Ask <b>" + (q.ask == null ? "—" : px.format(q.ask)) + "</b></span>" + (q.oi ? "<span>OI <b>" + Number(q.oi).toLocaleString("en-IN") + "</b></span>" : "<span>Volume <b>" + (q.volume == null ? "—" : Number(q.volume).toLocaleString("en-IN")) + "</b></span>") + "</div>";
  }
  function est() {
    var r = TR.ins, el = $("tk-est"); if (!r || !el) return;
    var lots = +$("tk-lots").value || 0, qty = lots * r.lot, pr = TR.otype === "LIMIT" ? +$("tk-price").value : (TR.q && TR.q.ltp);
    el.textContent = qty ? (r.type === "EQ" ? qty + " shares" : lots + " lot" + (lots > 1 ? "s" : "") + " = " + qty + " qty") + (pr ? " · about " + money.format(qty * pr) + (r.type === "EQ" || r.type === "FUT" ? "" : " premium") : "") : "";
  }
  function drawTicket() {
    var r = TR.ins, el = $("ticket"); if (!el) return;
    if (!r) return;
    var fo = r.type !== "EQ", prods = fo ? [["NRML", "NRML (carry forward)"], ["MIS", "MIS (intraday)"]] : [["CNC", "CNC (delivery)"], ["MIS", "MIS (intraday)"]];
    el.innerHTML = '<div class="card-head" style="margin-bottom:6px"><div><h3>' + esc(r.symbol) + ' <span class="muted small">' + esc(r.exchange) + "</span></h3><p class=\"muted small\">" + insLine(r) + "</p></div>" + typeBadge(r) + "</div>" +
      '<div id="tk-q"></div><button class="btn sm quiet" type="button" id="tk-r" style="margin:6px 0 12px">Refresh price</button>' +
      '<div class="seg sidebs" id="tk-side"><button type="button" data-v="BUY" class="buy" aria-pressed="' + (TR.side === "BUY") + '">Buy</button><button type="button" data-v="SELL" class="sell" aria-pressed="' + (TR.side === "SELL") + '">Sell</button></div>' +
      '<div class="grid g2" style="gap:12px;margin-top:12px"><div class="field"><label for="tk-lots">' + (fo ? "Lots (1 lot = " + r.lot + ")" : "Quantity (shares)") + '</label><input id="tk-lots" type="number" min="1" step="1" value="1"></div>' +
      '<div class="field"><label for="tk-prod">Product</label><select id="tk-prod">' + prods.map(function (p) { return '<option value="' + p[0] + '">' + p[1] + "</option>"; }).join("") + "</select></div></div>" +
      '<div class="field"><div class="lbl">Order type</div><div class="seg" id="tk-type"><button type="button" data-v="MARKET" aria-pressed="' + (TR.otype === "MARKET") + '">Market</button><button type="button" data-v="LIMIT" aria-pressed="' + (TR.otype === "LIMIT") + '">Limit</button></div>' +
      (fo ? '<small>Limit orders are safer for options: prices can jump between bid and ask.</small>' : "") + "</div>" +
      '<div class="field" id="tk-pw"' + (TR.otype === "LIMIT" ? "" : " hidden") + '><label for="tk-price">Limit price</label><input id="tk-price" type="number" min="0" step="' + r.tick + '"></div>' +
      '<p class="small muted" id="tk-est"></p>' +
      '<button class="btn block" type="button" id="tk-go">' + (TR.paper ? "Place paper order" : "Place LIVE order") + '</button><p id="tk-msg" class="msg" role="status"></p>';
    drawQuote(); est();
    if (TR.q && TR.q.ltp && $("tk-price")) $("tk-price").value = TR.q.ltp;
    on("tk-r", "click", loadQuote);
    on("tk-lots", "input", est); on("tk-price", "input", est);
    $("tk-side").addEventListener("click", function (e) { var b = e.target.closest("button"); if (!b) return; TR.side = b.getAttribute("data-v"); this.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", x === b); }); });
    $("tk-type").addEventListener("click", function (e) { var b = e.target.closest("button"); if (!b) return; TR.otype = b.getAttribute("data-v"); this.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", x === b); }); $("tk-pw").hidden = TR.otype !== "LIMIT"; if (TR.otype === "LIMIT" && !$("tk-price").value && TR.q) $("tk-price").value = TR.q.ltp; est(); });
    on("tk-go", "click", function () {
      var m = $("tk-msg"), btn = this, lots = +$("tk-lots").value;
      if (!(lots >= 1)) { say(m, false, "Enter a quantity of 1 or more"); return; }
      var body = { symbol: r.exchange + ":" + r.symbol, side: TR.side, lots: lots, order_type: TR.otype, product: $("tk-prod").value, paper: TR.paper };
      if (TR.otype === "LIMIT") body.price = +$("tk-price").value;
      if (!TR.paper && !confirm("Place a LIVE " + TR.side + " order for " + (lots * r.lot) + " " + r.symbol + " in your Zerodha account with real money?")) return;
      btn.disabled = true; say(m, true, "Sending…");
      api("/orders/manual", { method: "POST", json: body }).then(function (x) { btn.disabled = false; say(m, x.ok, x.ok ? x.d.message : errText(x, "Order failed")); if (x.ok) { loadAcc(); loadManual(); } }).catch(function () { btn.disabled = false; say(m, false, "Could not reach the server"); });
    });
    if (TR.q) { drawQuote(); est(); }
  }
  function loadAcc() {
    $("acc-tab").querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-v") === TR.tab); });
    if (!DASH.kite.fresh) { $("acc").innerHTML = '<div class="empty">Connect Zerodha to see your account.</div>'; return; }
    api("/kite/account").then(function (x) {
      if (!x.ok) { say($("acc-msg"), false, errText(x, "Could not load your account")); return; }
      $("acc-msg").textContent = ""; var d = x.d;
      if (TR.tab === "orders") $("acc").innerHTML = table(["Time", "Symbol", "Side", "Qty", "Price", "Status", "From", ""], d.orders.map(function (o) {
        var open = /OPEN|TRIGGER PENDING|AMO REQ/.test(o.status || "");
        return "<tr><td>" + esc(String(o.time).slice(11, 16) || "—") + "</td><td><b>" + short(o.symbol) + '</b></td><td><span class="sig ' + (o.side === "BUY" ? "BUY" : "SELL") + '">' + esc(o.side) + "</span></td><td>" + esc(o.filled) + "/" + esc(o.qty) + "</td><td>" + (o.avg ? px.format(o.avg) : o.price ? px.format(o.price) : "MKT") +
          '</td><td><span class="badge' + (o.status === "COMPLETE" ? " good" : o.status === "REJECTED" ? " bad" : "") + '" title="' + esc(o.message || "") + '">' + esc(o.status) + "</span></td><td>" + esc(o.source) + "</td><td>" + (open ? '<button class="btn sm quiet" type="button" data-cancel="' + esc(o.id) + '" data-var="' + esc(o.variety || "regular") + '">Cancel</button>' : "") + "</td></tr>";
      }), "No orders in your Zerodha account today.");
      if (TR.tab === "positions") $("acc").innerHTML = table(["Symbol", "Product", "Qty", "Avg", "LTP", "P&amp;L"], d.positions.map(function (p) { return "<tr><td><b>" + short(p.symbol) + "</b></td><td>" + esc(p.product) + "</td><td>" + p.qty + "</td><td>" + px.format(p.avg || 0) + "</td><td>" + px.format(p.ltp || 0) + "</td><td>" + signed(p.pnl) + "</td></tr>"; }), "No open positions today.");
      if (TR.tab === "holdings") $("acc").innerHTML = table(["Symbol", "Qty", "Avg", "LTP", "P&amp;L"], d.holdings.map(function (h) { return "<tr><td><b>" + short(h.symbol) + "</b></td><td>" + h.qty + "</td><td>" + px.format(h.avg || 0) + "</td><td>" + px.format(h.ltp || 0) + "</td><td>" + signed(h.pnl) + "</td></tr>"; }), "No holdings.");
      $("acc").querySelectorAll("[data-cancel]").forEach(function (b) { b.onclick = function () {
        if (!confirm("Cancel this order in Zerodha?")) return;
        api("/kite/orders/" + encodeURIComponent(b.getAttribute("data-cancel")) + "/cancel?variety=" + encodeURIComponent(b.getAttribute("data-var")), { method: "POST" }).then(function (r) { toast(r.ok ? "Order cancelled" : errText(r, "Could not cancel")); loadAcc(); });
      }; });
    });
  }
  function loadManual() {
    api("/manual/trades").then(function (x) {
      if (!x.ok) return;
      $("mt-pos").innerHTML = x.d.paper_positions.length ? '<div class="lbl">Paper positions</div>' + table(["Symbol", "Qty", "Avg"], x.d.paper_positions.map(function (p) { return "<tr><td><b>" + short(p.symbol) + "</b></td><td>" + p.qty + "</td><td>" + px.format(p.avg) + "</td></tr>"; }), "") + '<div class="lbl" style="margin-top:14px">Trades</div>' : "";
      $("mt").innerHTML = table(["Time", "Side", "Symbol", "Qty", "Price", "Type", '<span class="l">Note</span>'], x.d.trades.map(function (t) {
        return "<tr><td>" + when(t.at) + '</td><td><span class="sig ' + (t.side === "BUY" ? "BUY" : "SELL") + '">' + t.side + "</span></td><td><b>" + short(t.symbol) + "</b></td><td>" + t.qty + "</td><td>" + px.format(t.price) + "</td><td>" + (t.mode === "paper" ? '<span class="badge accent">Paper</span>' : '<span class="badge' + (t.status === "REJECTED" ? " bad" : "") + '">' + esc(t.status) + "</span>") + '</td><td class="wrap">' + esc(t.note) + "</td></tr>";
      }), "No manual trades yet.");
    });
  }
  $("acc-tab").addEventListener("click", function (e) { var b = e.target.closest("button"); if (!b) return; TR.tab = b.getAttribute("data-v"); loadAcc(); });
  on("acc-r", "click", loadAcc);
  if (TR.ins) { drawTicket(); loadQuote(); }
  loadManual();
  PAGE.paint = function () {
    loadAcc();
    if (!DASH.kite.fresh) { $("tq").disabled = true; say($("tq-msg"), false, "Connect Zerodha to search and trade."); } else if ($("tq").disabled) { $("tq").disabled = false; $("tq-msg").textContent = ""; }
  };
}
function appLearn() { appLayout("learn", "Information", '<p class="muted" style="margin-top:0">New to trading? Seven short topics with the best free videos, from basics to how our algos work.</p>' + infoHtml()); setupInfo(); }

function appProfile() {
  appLayout("profile", "Profile", '<div class="grid g3"><div class="card"><h3>Your details</h3><form id="pf" style="margin-top:12px"><div class="field"><label for="pfn">Full name</label><input id="pfn" required minlength="2" maxlength="80"></div><div class="field"><label for="pmob">Mobile number</label><input id="pmob" inputmode="numeric" pattern="[6-9][0-9]{9}" required></div><div class="field"><label for="pem">Email</label><input id="pem" disabled></div><button class="btn block" type="submit">Save changes</button><p id="pm" class="msg" role="status"></p></form></div>' +
    '<div class="card"><h3>Account</h3><div style="margin-top:8px"><div class="row"><span>Zerodha Kite</span><b id="pk">—</b></div><button class="btn sm quiet" type="button" id="pkd" hidden style="margin:4px 0 8px">Disconnect Zerodha</button><div class="row"><span>Member since</span><b id="ps">—</b></div><div class="row"><span>Last login</span><b id="pl">—</b></div></div><p class="small muted">Your password is stored in scrambled form and cannot be shown to anyone, including us.</p><button class="btn quiet block" id="out" type="button">Log out</button></div>' +
    '<div class="card"><h3>Send feedback</h3><div style="margin-top:12px">' + feedbackForm(false) + "</div></div></div>");
  api("/me").then(function (x) { if (!x.ok) return; var d = x.d; $("pfn").value = d.full_name; $("pmob").value = d.mobile; $("pem").value = d.email; $("pk").textContent = d.kite_fresh ? "Connected today" : d.connected ? "Login expired" : "Not connected"; $("pkd").hidden = !d.connected; $("pkd").onclick = function () { disconnectKite(); setTimeout(appProfile, 800); }; $("ps").textContent = when(d.member_since); $("pl").textContent = when(d.last_login); });
  on("pf", "submit", function (e) { e.preventDefault(); api("/me", { method: "PUT", json: { full_name: $("pfn").value, mobile: $("pmob").value } }).then(function (x) { say($("pm"), x.ok, x.ok ? "Saved." : errText(x, "Please check your details")); }); });
  bindFeedback(false, "ff");
  on("out", "click", logout);
}

function appAdmin() {
  if (!DASH.is_admin) { go("/app"); return; }
  appLayout("admin", "Admin", '<div class="stack"><div class="card" id="ks"></div><div class="grid g3" id="ad-k"></div><div class="card"><div class="card-head"><div><h3>Algos and webhooks</h3><p class="muted small">Paste the Chartink URL into the algo’s Chartink alert, and the TradingView URL into its TradingView strategy alert. A stock in both becomes a Suggestion.</p></div></div><div id="ad-a"></div></div>' +
    '<div class="grid g2"><div class="card"><h3>Connect a Chartink scanner</h3><ol class="muted" style="padding-left:20px;margin:10px 0 0;font-size:14px"><li>Open your scanner on chartink.com and press <b>Create Alert</b> (needs a Chartink plan with webhooks).</li><li>Paste the webhook URL of the algo it belongs to.</li><li>Chartink must reach this server over the internet. For a home PC, run a tunnel (for example Cloudflare Tunnel) and set <code>PUBLIC_URL</code> in START_MJVS.bat to the tunnel address.</li><li>Test with the form here first, in paper mode.</li></ol></div>' +
    '<div class="card"><h3>Send a test signal</h3><p class="muted small">Acts like a real alert. Only members running that algo are affected.</p><form id="tsf" style="margin-top:12px"><div class="field"><label for="ts-a">Algo</label><select id="ts-a">' + CFG.algos.filter(function (a) { return a.source === "chartink" || a.require_tradingview; }).map(function (a) { return '<option value="' + a.id + '">' + esc(a.name) + "</option>"; }).join("") + '</select></div>' +
    '<div class="grid g2" style="gap:12px"><div class="field"><label for="ts-src">Comes from</label><select id="ts-src"><option value="chartink">Scanner (Chartink)</option><option value="tradingview">TradingView strategy</option></select></div><div class="field"><label for="ts-act">Action</label><select id="ts-act"><option>BUY</option><option>SELL</option></select></div></div><div class="field"><label for="ts-s">Stocks</label><input id="ts-s" placeholder="SBIN, ITC" required><small>NSE symbols, comma separated</small></div><button class="btn" type="submit">Send test signal</button><p id="ts-m" class="msg" role="status"></p></form></div></div>' +
    '<div class="card"><h3>Connect a TradingView strategy</h3><ol class="muted" style="padding-left:20px;margin:10px 0 0;font-size:14px"><li>Add your strategy (Pine Script) to a chart on TradingView. For many stocks, use an alert on a <b>watchlist</b> (TradingView paid plans support webhooks and watchlist alerts).</li><li>Create Alert → Notifications → <b>Webhook URL</b>: paste the algo’s TradingView URL above.</li><li>Message: <code>{"symbol": "{{ticker}}", "exchange": "{{exchange}}", "price": {{close}}, "action": "BUY"}</code> (use "SELL" in a second alert to exit).</li><li>When the same stock is also picked by the scanner that day, it appears on the Suggestions page.</li></ol></div>' +
    '<div class="card"><div class="card-head"><h3>Recent alerts</h3></div><div id="ad-al"></div></div>' +
    '<div class="card"><div class="card-head"><h3>Feedback</h3></div><div id="ad-fb"></div></div>' +
    '<div class="card"><div class="card-head"><div><h3>Members</h3><p class="muted small">Passwords are stored only as scrambled hashes and are never shown or exported.</p></div></div><div id="ad-m"></div></div>' +
    '<div class="grid g2"><div class="card"><h3>Database</h3><div id="ad-db" style="margin-top:8px"></div><div class="lbl" style="margin-top:14px">Download data (CSV, opens in Excel)</div><div class="chips" id="ad-exp">' +
    [["members", "Members"], ["trades", "All trades"], ["subscriptions", "Algo settings"], ["signals", "Signals"], ["suggestions", "Suggestions"], ["logins", "Login history"], ["feedback", "Feedback"]].map(function (t) { return '<button type="button" class="chip" data-t="' + t[0] + '">' + t[1] + "</button>"; }).join("") + "</div></div>" +
    '<div class="card"><div class="card-head"><h3>Recent logins</h3></div><div id="ad-l"></div></div></div></div>');
  $("ad-exp").addEventListener("click", function (e) { var b = e.target.closest("button[data-t]"); if (b) download("/admin/export/" + b.getAttribute("data-t") + ".csv", "mjvs-" + b.getAttribute("data-t") + ".csv"); });
  api("/admin/members").then(function (x) {
    if (!x.ok) return; var d = x.d;
    $("ad-m").innerHTML = table(["Name", '<span class="l">Email</span>', "Mobile", "Joined", "Last login", "Kite", '<span class="l">Running algos</span>', "Trades"], d.members.map(function (m) {
      return "<tr><td><b>" + esc(m.full_name) + '</b></td><td class="l">' + esc(m.email) + "</td><td>" + esc(m.mobile) + "</td><td>" + when(m.created_at) + "</td><td>" + when(m.last_login) + "</td><td>" + (m.kite === "today" ? '<span class="badge good">Today</span>' : m.kite === "expired" ? '<span class="badge warn">Expired</span>' : '<span class="badge">No</span>') + '</td><td class="l">' + (m.running.length ? esc(m.running.join(", ")) : '<span class="muted">—</span>') + "</td><td>" + m.trades + "</td></tr>";
    }), "No members yet.");
    $("ad-db").innerHTML = '<div class="row"><span>Database</span><b>' + esc(d.database) + '</b></div><div class="row"><span>Latest backups</span><b>' + (d.backups.length ? esc(d.backups.slice().reverse().join(", ")) : "None yet") + "</b></div>";
    $("ad-l").innerHTML = table(["Time", '<span class="l">Email</span>', "Result", "Address"], d.logins.slice(0, 15).map(function (e) {
      return "<tr><td>" + when(e.at) + '</td><td class="l">' + esc(e.email) + "</td><td>" + (e.success ? '<span class="badge good">' + esc(e.kind === "register" ? "Registered" : "Logged in") + "</span>" : '<span class="badge bad">' + esc(e.note || "Failed") + "</span>") + "</td><td>" + esc(e.ip) + "</td></tr>";
    }), "No logins yet.");
  });
  function loadKite() {
    api("/admin/kite").then(function (x) {
      if (!x.ok) return; var d = x.d;
      $("ks").className = "card" + (d.ready ? "" : " setup-need");
      $("ks").innerHTML = '<div class="card-head"><div><h3>Kite setup ' + (d.ready ? '<span class="badge good"><span class="dot"></span>Done</span>' : '<span class="badge warn">One-time, about 10 minutes</span>') + '</h3><p class="muted small">You do this once for the whole site. Members never see these steps: they only press Connect Zerodha.</p></div>' +
        (d.ready ? '<div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn sm" type="button" data-kite="1">Test: connect my Zerodha</button><button class="btn sm quiet" type="button" id="kchk">Check market data</button></div>' : "") + "</div>" +
        '<div id="kchk-out"></div>' +
        '<ol class="wizard">' +
        '<li><b>Open the Kite developer site</b><span>Sign in with your Zerodha ID. </span><a class="btn sm quiet" href="https://developers.kite.trade/" target="_blank" rel="noopener noreferrer">Open developers.kite.trade ↗</a></li>' +
        '<li><b>Create a new app of type “Connect” (not “Personal”)</b><span>App name: MJVS. Leave Postback URL empty. “Connect” is Zerodha’s paid monthly plan and includes live prices and charts, which scanning needs. The free “Personal” plan only places orders. After setup, press “Check market data”.</span></li>' +
        '<li><b>Paste this as the Redirect URL</b><span><code>' + esc(d.redirect_url) + '</code> <button class="btn sm quiet" type="button" data-copy="' + esc(d.redirect_url) + '">Copy</button></span></li>' +
        '<li><b>Copy the API key and API secret here</b><form id="kf" class="kform"><div class="field"><label for="kk">API key</label><input id="kk" autocomplete="off" spellcheck="false" placeholder="' + (d.api_key ? "Saved: " + esc(d.api_key) : "e.g. abcd1234efgh5678") + '"></div>' +
        '<div class="field"><label for="ksec">API secret</label><input id="ksec" type="password" autocomplete="off" placeholder="' + (d.has_secret ? "Saved (hidden). Leave empty to keep it" : "Paste the secret") + '"></div><button class="btn" type="submit">Save keys</button><p id="km" class="msg" role="status"></p></form></li>' +
        '<li><b>Test it</b><span>Press “Test: connect my Zerodha” above. When it says connected, every member can connect.</span></li>' +
        '<li><b>Allow live orders from this PC: IP Whitelist</b><span>Since 1 April 2026 Zerodha accepts orders from apps only from a registered <b>static IP</b>. On developers.kite.trade open your <b>Profile → IP Whitelist</b> and add this PC’s internet IP: ' +
        (d.public_ip ? '<code>' + esc(d.public_ip) + '</code> <button class="btn sm quiet" type="button" data-copy="' + esc(d.public_ip) + '">Copy</button>' : '<i>(could not detect: search “what is my IP” in your browser)</i>') +
        '. Home internet IPs usually change; ask your internet provider for a static IP, or run MJVS on a server that has one.</span></li></ol>' +
        (d.source === "START_MJVS.bat" ? '<p class="small muted">Currently using the keys from START_MJVS.bat. Saving here replaces them.</p>' : "");
      bindKiteButtons();
      on("kchk", "click", function () {
        var o = $("kchk-out"); o.innerHTML = '<p class="muted small">Checking with Zerodha…</p>';
        api("/admin/kite/check", { method: "POST" }).then(function (r) {
          if (!r.ok) { o.innerHTML = '<p class="msg err">' + esc(errText(r, "Check failed")) + "</p>"; return; }
          var d2 = r.d, row = function (lbl, v) { return '<div class="row"><span>' + lbl + '</span><b class="' + (v === "ok" ? "up" : "dn") + '">' + (v === "ok" ? "✓ Works" : esc(v)) + "</b></div>"; };
          o.innerHTML = '<div class="' + (d2.market_data ? "banner ok" : "banner need") + '" style="margin:10px 0"><div><b>' + (d2.market_data ? "Market data works: scanning and prices are ready" : "Market data is not in your Kite plan") + "</b><p>" +
            (d2.market_data ? "Algos can scan and members can see live prices." : "Orders work, but scanning, live prices and the morning run need the paid “Connect” plan. Follow steps 1–5 below with a “Connect” app, then check again.") +
            '</p></div></div>' + row("Zerodha login", d2.login) + row("Live prices", d2.prices) + row("Charts (historical data)", d2.charts);
        });
      });
      $("ks").querySelectorAll("[data-copy]").forEach(function (b) { b.onclick = function () { (navigator.clipboard ? navigator.clipboard.writeText(b.getAttribute("data-copy")) : Promise.reject()).then(function () { toast("Copied"); }).catch(function () { toast("Select the text and copy it"); }); }; });
      on("kf", "submit", function (e) {
        e.preventDefault(); var m = $("km");
        api("/admin/kite", { method: "PUT", json: { api_key: $("kk").value.trim() || "", api_secret: $("ksec").value.trim() } }).then(function (r) {
          if (!r.ok) { say(m, false, errText(r, "Please check the key and secret")); return; }
          CFG.kite_ready = r.d.ready; toast("Kite keys saved"); refresh(); loadKite();
        });
      });
    });
  }
  loadKite();
  function load() {
    api("/admin/overview").then(function (x) {
      if (!x.ok) return; var d = x.d;
      $("ad-k").innerHTML = '<div class="card kpi"><div class="lbl">Members</div><b>' + d.members + "</b></div>" +
        '<div class="card kpi"><div class="lbl">Chartink webhooks</div><b style="font-size:18px">' + (d.chartink_ready ? '<span class="up">Ready</span>' : '<span class="dn">Not set up</span>') + '</b><span class="muted">' + (d.chartink_ready ? (d.public_url ? "Public: " + esc(d.public_url) : "Set PUBLIC_URL for Chartink to reach you") : "Set CHARTINK_KEY in START_MJVS.bat") + "</span></div>" +
        '<div class="card kpi"><div class="lbl">Live trading (real orders)</div><b style="font-size:18px">' + (d.allow_live ? '<span class="dn">On</span>' : "Off (paper only)") + '</b><button class="btn sm ' + (d.allow_live ? "quiet" : "danger") + '" type="button" id="live-tg" style="margin-top:8px">' + (d.allow_live ? "Switch off" : "Switch on live trading") + "</button></div>";
      on("live-tg", "click", function () {
        var turnOn = !d.allow_live;
        if (turnOn && !confirm("Switch on LIVE trading? Manual orders and running algos in Live mode will place REAL orders with real money in Zerodha accounts.")) return;
        api("/admin/live", { method: "PUT", json: { on: turnOn } }).then(function (x) { if (x.ok) { CFG.allow_live = x.d.allow_live; toast(x.d.allow_live ? "Live trading is ON" : "Live trading is OFF"); load(); refresh(); } else toast(errText(x, "Could not change")); });
      });
      function urlCell(label, u) { return '<div class="small muted">' + label + '</div><code>' + esc(u) + '</code> <button class="btn sm quiet" type="button" data-copy="' + esc(u) + '">Copy</button>'; }
      $("ad-a").innerHTML = table(["Algo", "Status", "Signals", "Running", '<span class="l">Webhook URLs</span>'], d.algos.map(function (a) {
        var cells = !a.webhook ? '<span class="muted small">Set CHARTINK_KEY first</span>' :
          (a.source === "chartink" ? urlCell("Chartink", a.webhook) : '<span class="muted small">Own scanner (no Chartink URL)</span>') +
          (a.require_tradingview ? '<div style="margin-top:6px">' + urlCell("TradingView", a.tv_webhook) + "</div>" : '<div class="small muted" style="margin-top:4px">TradingView: off for this algo</div>');
        return "<tr><td><b>" + esc(a.name) + "</b></td><td>" + statusBadge(a) + (a.ready && !a.auto_trade ? ' <span class="badge accent">Suggest only</span>' : "") + "</td><td>" + sourceLabel(a) + "</td><td>" + a.running + ' <span class="muted small">(' + a.paper + " paper, " + a.live + ' live)</span></td><td class="l">' + cells + "</td></tr>";
      }));
      $("ad-fb").innerHTML = table(["Time", "Topic", '<span class="l">From</span>', '<span class="l">Message</span>'], d.feedback.map(function (f) {
        return "<tr><td>" + when(f.at) + '</td><td><span class="badge' + (f.topic === "Problem" ? " bad" : f.topic === "Praise" ? " good" : "") + '">' + esc(f.topic || "—") + '</span></td><td class="l">' + esc(f.name || "Visitor") + (f.contact ? '<div class="small muted">' + esc(f.contact) + "</div>" : "") + (f.member_id ? ' <span class="badge accent">Member</span>' : "") + '</td><td class="wrap">' + esc(f.message) + "</td></tr>";
      }), "No feedback yet.");
      document.querySelectorAll("[data-copy]").forEach(function (b) { b.onclick = function () { (navigator.clipboard ? navigator.clipboard.writeText(b.getAttribute("data-copy")) : Promise.reject()).then(function () { toast("Webhook URL copied"); }).catch(function () { toast("Select the URL and copy it"); }); }; });
      $("ad-al").innerHTML = table(["Time", "Algo", "Symbol", "Price", "From", '<span class="l">Scan</span>'], d.alerts.map(function (x) { return "<tr><td>" + when(x.at) + "</td><td>" + esc((ALG[x.algo_id] || {}).name || x.algo_id) + "</td><td><b>" + short(x.symbol) + "</b></td><td>" + (x.price == null ? "—" : px.format(x.price)) + "</td><td>" + esc(x.source) + (x.action === "SELL" ? ' <span class="sig SELL">SELL</span>' : "") + '</td><td class="wrap">' + esc(x.note) + "</td></tr>"; }), "No alerts received yet.");
    });
  }
  on("tsf", "submit", function (e) { e.preventDefault(); api("/admin/algos/" + $("ts-a").value + "/test-signal", { method: "POST", json: { stocks: $("ts-s").value, source: $("ts-src").value, action: $("ts-act").value } }).then(function (x) { say($("ts-m"), x.ok, x.ok ? x.d.added + " signal(s) added. Suggestions today for this algo: " + x.d.suggestions_today + "." : errText(x, "Could not send")); if (x.ok) load(); }); });
  load();
  PAGE.paint = function () {};
}

// ------------------------------------------------------------------ router
var QUERY = {};
function refresh() { return loadDash().then(function () { if (PAGE && PAGE.paint && DASH) { paintBar(); PAGE.paint(); } }); }
function route() {
  var h = location.hash.replace(/^#/, "");
  if (h === "dashboard" || h === "profile") h = "/app" + (h === "profile" ? "/profile" : "");
  if (h === "login") h = "/login";
  if (h.charAt(0) !== "/") h = "/";
  QUERY = {};
  if (h.indexOf("?") >= 0) { h.split("?")[1].split("&").forEach(function (kv) { var i = kv.indexOf("="); if (i > 0) QUERY[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1).replace(/\+/g, " ")); }); h = h.split("?")[0]; }
  var parts = h.split("/").filter(Boolean);
  PAGE = { paint: null };
  window.scrollTo(0, 0);
  if (parts[0] === "app") {
    if (!token()) { go("/login"); return; }
    var view = parts[1] || "", page = PAGE;
    var draw = function () {
      if (PAGE !== page) return;
      if (!DASH) { root.innerHTML = '<div class="auth"><div class="card">Loading…</div></div>'; return; }
      ({ "": appOverview, algos: appAlgos, algo: function () { appAlgo(parts[2]); }, positions: appPositions, trades: appTrades, suggestions: appSuggestions, learn: appLearn, profile: appProfile, admin: appAdmin, connect: appConnect, trade: appTrade }[view] || appOverview)();
      if (PAGE.paint) PAGE.paint();
    };
    if (DASH) { draw(); refresh(); } else { draw(); loadDash().then(draw); }
    return;
  }
  ({ "": pageHome, products: pageProducts, offers: pageOffers, information: pageInformation, training: pageInformation, login: function () { pageAuth("login"); }, register: function () { pageAuth("register"); } }[parts[0] || ""] || pageHome)();
}

function checkServer() {
  var b = $("srv");
  fetch("/health").then(function (r) { if (!r.ok) throw 0; b.hidden = true; }).catch(function () {
    b.textContent = location.protocol === "file:" ? "Open http://localhost:8000/ in your browser instead of this file, while START_MJVS.bat is running." : "The server is not running. Double-click START_MJVS.bat and keep the black window open, then reload this page.";
    b.hidden = false;
  });
}

setInterval(function () { if (token() && /^#\/app/.test(location.hash) && !document.hidden && PAGE && PAGE.paint) { var ae = document.activeElement; if (!ae || !/INPUT|SELECT|TEXTAREA/.test(ae.tagName)) refresh(); } }, 30000);
window.addEventListener("hashchange", route);
checkServer();
fetch("/config").then(function (r) { return r.json(); }).then(function (c) {
  CFG = c; CFG.algos.forEach(function (a) { ALG[a.id] = a; }); route();
}).catch(function () { root.innerHTML = '<div class="auth"><div class="card"><h1>Cannot reach the server</h1><p class="muted">Double-click START_MJVS.bat and keep the black window open, then reload this page.</p></div></div>'; });
})();
