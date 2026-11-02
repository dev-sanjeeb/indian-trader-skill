"""inmarket: the shared India-market toolkit for the Indian Day Trader skill pack.

Standard-library Python 3.8+. One copy of this file sits in every skill folder
(tools/sync_common.py copies it from common/), so each skill folder works on
its own when copied into ~/.claude/skills/.

What is in here:
  - the IST clock (UTC+5:30, no daylight saving) and --now parsing
  - the NSE/BSE trading calendar: weekends, 2026 holidays, special sessions
    (Muhurat), the 09:15-15:30 regular session
  - NSE tick sizes by price band and tick rounding
  - Yahoo Finance fetching for NSE (.NS) and BSE (.BO) symbols and index aliases
  - a polite NSE (nseindia.com) session that bootstraps cookies the way a browser does
  - Indian intraday charges (brokerage, STT, exchange, SEBI, stamp duty, GST)
  - the trader/ folder: config with defaults, JSON read/write
"""

import datetime as _dt
import gzip
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.0.0"
UA = "indian-day-trader-skill/%s (+https://github.com/)" % VERSION
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SLEEP = time.sleep  # tests replace this

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30), "IST")
UTC = _dt.timezone.utc

# ------------------------------------------------------------------ calendar
# NSE equity segment trading holidays (weekdays only). Source: NSE circular for
# 2026, as listed on cleartax.in/s/nse-holidays-2026 (read 2026-11-02). BSE
# follows the same list for equities. 2027 is published by NSE in December;
# add it to trader/config.json "extra_holidays" until this file is updated.
HOLIDAYS = {
    2026: {
        "2026-01-15": "Maharashtra municipal elections",
        "2026-01-26": "Republic Day",
        "2026-03-03": "Holi",
        "2026-03-26": "Shri Ram Navami",
        "2026-03-31": "Shri Mahavir Jayanti",
        "2026-04-03": "Good Friday",
        "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
        "2026-05-01": "Maharashtra Day",
        "2026-05-28": "Bakri Id",
        "2026-06-26": "Muharram",
        "2026-09-14": "Ganesh Chaturthi",
        "2026-10-02": "Mahatma Gandhi Jayanti",
        "2026-10-20": "Dussehra",
        "2026-11-10": "Diwali Balipratipada",
        "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
        "2026-12-25": "Christmas",
    },
}

# Special sessions on days that are otherwise closed (or shortened).
# Muhurat trading 2026: Sunday 8 Nov, normal market 14:20-15:30 IST
# (pre-open 14:05-14:20). Source: NSE/BSE announcement, businesstoday.in 2026-10-19.
SPECIAL_SESSIONS = {
    "2026-11-08": ("14:20", "15:30", "Muhurat trading (Diwali)"),
}

OPEN = _dt.time(9, 15)
CLOSE = _dt.time(15, 30)
PRE_OPEN = _dt.time(9, 0)
# Closing Auction Session (CAS), from 2026-08-03, for stocks with F&O contracts:
# continuous trading stops at 15:15 (no fresh orders 15:15-15:20, auction order
# entry 15:20-15:30, matching 15:30-15:35). Stop-loss orders are NOT accepted in
# CAS. Yahoo's 5-minute NSE bars run 09:15 ... 15:15 with null 15:20/15:25 bars,
# so a full session of 5-minute bars is 73 bars and the last tradable bar ends 15:20.
CONT_END = _dt.time(15, 20)
FULL_SESSION_BARS = 73

# Stocks with F&O contracts on NSE (the CAS-eligible, most liquid intraday names),
# from nseindia.com/api/master-quote on 2026-11-02. `scan.py universe --fno` refreshes it.
FNO_2026_11 = (
    "360ONE ABB ABCAPITAL ADANIENSOL ADANIENT ADANIGREEN ADANIPORTS ADANIPOWER ALKEM AMBER "
    "AMBUJACEM ANANDRATHI ANGELONE APLAPOLLO APOLLOHOSP ASHOKLEY ASIANPAINT ASTRAL ATHERENERG "
    "AUBANK AUROPHARMA AXISBANK BAJAJ-AUTO BAJAJFINSV BAJFINANCE BANDHANBNK BANKBARODA BANKINDIA "
    "BDL BEL BHARATFORG BHARTIARTL BHEL BIOCON BLUESTARCO BOSCHLTD BPCL BRITANNIA BSE CAMS CANBK "
    "CDSL CGPOWER CHOLAFIN CIPLA COALINDIA COCHINSHIP COFORGE COLPAL CONCOR COROMANDEL CROMPTON "
    "CUB CUMMINSIND DABUR DATAPATTNS DELHIVERY DIVISLAB DIXON DLF DMART DRREDDY EICHERMOT ENRIN "
    "ETERNAL FEDERALBNK FORCEMOT FORTIS GAIL GLENMARK GMRAIRPORT GODFRYPHLP GODREJCP GODREJPROP "
    "GRASIM GVT&D HAL HAVELLS HCLTECH HDFCAMC HDFCBANK HDFCLIFE HEROMOTOCO HINDALCO HINDPETRO "
    "HINDUNILVR HINDZINC HYUNDAI ICICIBANK ICICIGI ICICILIFE IDEA IDFCFIRSTB IEX INDHOTEL INDIANB "
    "INDIGO INDUSINDBK INDUSTOWER INFY INOXWIND IOC IREDA IRFC ITC JINDALSTEL JIOFIN JSWENERGY "
    "JSWSTEEL JUBLFOOD KALYANKJIL KARURVYSYA KAYNES KEI KFINTECH KOTAKBANK KPITTECH LAURUSLABS "
    "LICHSGFIN LICI LODHA LT LTF LTM LUPIN M&M MAHABANK MANAPPURAM MANKIND MARICO MARUTI MAXHEALTH "
    "MAZDOCK MCX MFSL MOTHERSON MOTILALOFS MPHASIS MUTHOOTFIN NAM-INDIA NATIONALUM NAUKRI NAVINFLUOR "
    "NBCC NESTLEIND NHPC NMDC NTPC NYKAA OBEROIRLTY OFSS OIL ONGC PAGEIND PATANJALI PAYTM PERSISTENT "
    "PETRONET PFC PGEL PHOENIXLTD PIDILITIND PIIND PNB PNBHOUSING POLICYBZR POLYCAB POWERGRID "
    "POWERINDIA PREMIERENE PRESTIGE RADICO RBLBANK RECLTD RELIANCE RVNL SAGILITY SAIL SBICARD SBILIFE "
    "SBIN SHREECEM SHRIRAMFIN SIEMENS SOLARINDS SONACOMS SRF SUNPHARMA SUPREMEIND SUZLON SWIGGY SYRMA "
    "TATACONSUM TATAELXSI TATAPOWER TATASTEEL TCS TECHM TIINDIA TITAN TMPV TORNTPHARM TRENT TVSMOTOR "
    "UJJIVANSFB ULTRACEMCO UNIONBANK UNITDSPR UNOMINDA UPL VBL VEDL VMM VOLTAS WAAREEENER WIPRO "
    "YESBANK ZYDUSLIFE").split()

_EXTRA = {}  # filled from config "extra_holidays": {"2027-01-26": "Republic Day"}


def load_extra_holidays(cfg):
    _EXTRA.clear()
    for k, v in (cfg.get("extra_holidays") or {}).items():
        _EXTRA[k] = v


def known_year(year):
    return year in HOLIDAYS or any(k.startswith("%d-" % year) for k in _EXTRA)


def holiday_name(d):
    key = d.isoformat()
    return HOLIDAYS.get(d.year, {}).get(key) or _EXTRA.get(key)


def session(d):
    """(open, close, label) as datetime.time for a trading day, or None if closed."""
    key = d.isoformat()
    if key in SPECIAL_SESSIONS:
        o, c, label = SPECIAL_SESSIONS[key]
        return parse_hhmm(o), parse_hhmm(c), label
    if d.weekday() >= 5 or holiday_name(d):
        return None
    return OPEN, CLOSE, "regular session"


def trading_day(d):
    return session(d) is not None


def is_special(d):
    return d.isoformat() in SPECIAL_SESSIONS


def prev_trading_day(d):
    d = d - _dt.timedelta(days=1)
    while not trading_day(d) or is_special(d):
        d -= _dt.timedelta(days=1)
    return d


def next_trading_day(d):
    d = d + _dt.timedelta(days=1)
    while not trading_day(d):
        d += _dt.timedelta(days=1)
    return d


def closed_reason(d):
    if d.weekday() >= 5:
        return "the weekend"
    h = holiday_name(d)
    return ("an exchange holiday (%s)" % h) if h else None


def year_warning(d):
    if not known_year(d.year):
        return ("NOTE: the NSE holiday list for %d is not in this tool yet. Add it to "
                "trader/config.json \"extra_holidays\" or check nseindia.com." % d.year)
    return None

# ------------------------------------------------------------------ clock

def now_ist(override=None):
    """Aware datetime in IST. override: 'YYYY-MM-DD HH:MM' (IST) or None."""
    if override:
        return parse_now(override)
    return _dt.datetime.now(UTC).astimezone(IST)


def parse_now(text):
    text = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(text, fmt).replace(tzinfo=IST)
        except ValueError:
            pass
    raise ValueError("--now wants 'YYYY-MM-DD HH:MM' in India time (IST), got %r" % text)


def parse_hhmm(text):
    if isinstance(text, _dt.time):
        return text
    s = str(text).strip().upper().replace(".", "")
    ampm = None
    if s.endswith("AM") or s.endswith("PM"):
        ampm, s = s[-2:], s[:-2].strip()
    h, _, m = s.partition(":")
    h, m = int(h), int(m or 0)
    if ampm == "PM" and h < 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return _dt.time(h, m)


def ts_to_ist(ts):
    return _dt.datetime.fromtimestamp(int(ts), UTC).astimezone(IST)


def ist_dt(d, t):
    return _dt.datetime.combine(d, t).replace(tzinfo=IST)


def clock(t):
    """'10:15 AM' style label for a time or datetime."""
    if isinstance(t, _dt.datetime):
        t = t.time()
    h = t.hour % 12 or 12
    return "%d:%02d %s" % (h, t.minute, "AM" if t.hour < 12 else "PM")


def hhmm(t):
    if isinstance(t, _dt.datetime):
        t = t.time()
    return "%02d:%02d" % (t.hour, t.minute)


def day_label(d):
    return d.strftime("%a %Y-%m-%d")


def market_status(now):
    """('open'|'pre-open'|'closed', sentence)."""
    d = now.date()
    s = session(d)
    if s is None:
        nxt = next_trading_day(d)
        return "closed", "NSE CLOSED (%s, %s). Next session %s, opens %s IST." % (
            day_label(d), closed_reason(d) or "closed", day_label(nxt), clock(session(nxt)[0]))
    o, c, label = s
    t = now.time()
    if t < o:
        state = "pre-open" if (not is_special(d) and t >= PRE_OPEN) else "closed"
        return state, "NSE %s (%s %s IST). The %s opens at %s IST." % (
            "PRE-OPEN" if state == "pre-open" else "NOT OPEN YET", day_label(d), hhmm(t), label, clock(o))
    if t >= c:
        nxt = next_trading_day(d)
        return "closed", "NSE CLOSED for the day (%s %s IST, closed at %s). Next session %s." % (
            day_label(d), hhmm(t), clock(c), day_label(nxt))
    if is_special(d):
        return "open", "NSE OPEN (%s %s IST, %s, closes %s)." % (day_label(d), hhmm(t), label, clock(c))
    return "open", ("NSE OPEN (%s %s IST, %s; F&O stocks go into the closing auction at 3:15 PM, "
                    "no stop-loss orders there; the market closes %s)." % (day_label(d), hhmm(t), label, clock(c)))

# ------------------------------------------------------------------ ticks

# NSE capital-market tick sizes by price band, effective 2025-04-15 (NSE circular
# CMTR67133). NSE reviews each stock's tick from its closing price periodically,
# so this table is the rule, not a per-stock lookup: check your broker's tick
# when an order is rejected for "tick size".
TICK_BANDS = [
    (250.0, 0.01),
    (1000.0, 0.05),
    (5000.0, 0.10),
    (10000.0, 0.50),
    (20000.0, 1.00),
    (float("inf"), 5.00),
]


def tick_size(price, override=None):
    if override:
        return float(override)
    for top, tick in TICK_BANDS:
        if price < top:
            return tick
    return 5.0


def _q(x, tick):
    return round(x / tick, 6)


def round_down_tick(x, tick):
    import math
    return round(math.floor(_q(x, tick) + 1e-9) * tick, 2)


def round_up_tick(x, tick):
    import math
    return round(math.ceil(_q(x, tick) - 1e-9) * tick, 2)


def round_half_tick(x, tick):
    import math
    return round(math.floor(_q(x, tick) + 0.5 + 1e-9) * tick, 2)


def on_tick(x, tick):
    return abs(_q(x, tick) - round(_q(x, tick))) < 1e-6

# ------------------------------------------------------------------ money

def inr(x, paise=True):
    """Indian digit grouping: 1234567.5 -> '₹12,34,567.50'."""
    neg = x < 0
    txt = ("%.2f" % abs(x)) if paise else ("%d" % round(abs(x)))
    s, _, frac = txt.partition(".")
    frac = ("." + frac) if frac else ""
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if neg else "") + "₹" + s + frac


def px(x):
    return "%.2f" % x

# ------------------------------------------------------------------ charges

DEFAULT_CHARGES = {
    # Zerodha equity intraday, zerodha.com/charges (read 2026-11-02).
    "brokerage_pct": 0.03,          # % of order value ...
    "brokerage_cap": 20.0,          # ... or Rs 20 per executed order, whichever is lower
    "stt_sell_pct": 0.025,          # STT, intraday: sell side only
    "exchange_txn_pct": {"NSE": 0.00307, "BSE": 0.00375},
    "sebi_per_crore": 10.0,
    "stamp_buy_pct": 0.003,         # intraday: buy side only
    "gst_pct": 18.0,                # on brokerage + exchange + SEBI
}


def charges(buy_value, sell_value, exchange="NSE", table=None, orders=(1, 1)):
    """Round-trip intraday equity charges in rupees. orders = (buy orders, sell orders)."""
    t = dict(DEFAULT_CHARGES)
    t.update(table or {})
    ex = t["exchange_txn_pct"]
    ex_pct = ex.get(exchange, ex.get("NSE")) if isinstance(ex, dict) else float(ex)

    def brk(v, n):
        if v <= 0:
            return 0.0
        return min(v * t["brokerage_pct"] / 100.0, t["brokerage_cap"] * max(1, n))
    b = brk(buy_value, orders[0]) + brk(sell_value, orders[1])
    stt = sell_value * t["stt_sell_pct"] / 100.0
    exc = (buy_value + sell_value) * ex_pct / 100.0
    sebi = (buy_value + sell_value) * t["sebi_per_crore"] / 1e7
    stamp = buy_value * t["stamp_buy_pct"] / 100.0
    gst = (b + exc + sebi) * t["gst_pct"] / 100.0
    parts = {"brokerage": b, "stt": stt, "exchange": exc, "sebi": sebi, "stamp": stamp, "gst": gst}
    parts = {k: round(v, 2) for k, v in parts.items()}
    parts["total"] = round(b + stt + exc + sebi + stamp + gst, 2)
    return parts

# ------------------------------------------------------------------ symbols

INDEX_ALIASES = {
    "NIFTY": "^NSEI", "NIFTY50": "^NSEI", "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK", "NIFTYBANK": "^NSEBANK",
    "SENSEX": "^BSESN", "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "NIFTYIT": "^CNXIT", "NIFTYMIDCAP": "^NSEMDCP50", "INDIAVIX": "^INDIAVIX",
}


def norm_symbol(sym):
    """'reliance' -> 'RELIANCE'; 'RELIANCE.NS' -> 'RELIANCE'; keeps '.BO' info out."""
    s = sym.strip().upper()
    for suf in (".NS", ".BO"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    if s.startswith("NSE:") or s.startswith("BSE:"):
        s = s[4:]
    return s


def exchange_of(sym, default="NSE"):
    s = sym.strip().upper()
    if s.endswith(".BO") or s.startswith("BSE:"):
        return "BSE"
    if s.endswith(".NS") or s.startswith("NSE:"):
        return "NSE"
    return default


def to_yahoo(sym, exchange="NSE"):
    s = sym.strip().upper()
    if s in INDEX_ALIASES:
        return INDEX_ALIASES[s]
    if s.startswith("^") or s.endswith(".NS") or s.endswith(".BO"):
        return s
    if s.startswith("NSE:"):
        return s[4:] + ".NS"
    if s.startswith("BSE:"):
        return s[4:] + ".BO"
    # Yahoo spells M&M as M&M.NS and BAJAJ-AUTO as BAJAJ-AUTO.NS: pass through.
    return s + (".BO" if exchange == "BSE" else ".NS")


def from_yahoo(ysym):
    s = ysym.upper()
    for k, v in INDEX_ALIASES.items():
        if v == s:
            return k
    return norm_symbol(s)

# ------------------------------------------------------------------ http

class DataError(Exception):
    pass


YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
BACKOFF = 5.0


def http_get(url, timeout=20, headers=None, opener=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    op = opener.open if opener else urllib.request.urlopen
    with op(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data.decode("utf-8", "replace")


def yahoo_get(path):
    """GET a Yahoo Finance path: query2 first, query1 on a 429 or 5xx, one more
    round after BACKOFF seconds if a 429 was seen. Returns text."""
    last = "no answer"
    for attempt in (0, 1):
        saw_429 = False
        for host in YAHOO_HOSTS:
            try:
                return http_get(host + path, headers={"User-Agent": BROWSER_UA})
            except urllib.error.HTTPError as e:
                last = "HTTP %d" % e.code
                body = ""
                try:
                    if 400 <= e.code < 500 and e.code != 429:
                        body = e.read().decode("utf-8", "replace")
                except Exception:
                    pass
                if e.code == 429:
                    saw_429 = True
                    continue
                if e.code >= 500:
                    continue
                if body.strip().startswith("{"):
                    return body
                raise DataError("Yahoo answered %s for %s" % (last, path.split("?")[0]))
            except (urllib.error.URLError, OSError) as e:
                last = str(getattr(e, "reason", e))
                continue
        if attempt == 0 and saw_429:
            SLEEP(BACKOFF)
            continue
        break
    raise DataError("Yahoo answered %s for %s" % (last, path.split("?")[0]))


def chart_path(ysym, rng, interval, extra=""):
    return "/v8/finance/chart/%s?range=%s&interval=%s%s" % (
        urllib.parse.quote(ysym, safe="^.-_&"), rng, interval, extra)


def spark_path(ysyms, rng, interval):
    return "/v7/finance/spark?symbols=%s&range=%s&interval=%s" % (
        urllib.parse.quote(",".join(ysyms), safe=",^.-_&"), rng, interval)


def series_from_result(res):
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
    t = res.get("timestamp") or []
    n = len(t)

    def col(k):
        v = q.get(k)
        return list(v) + [None] * (n - len(v)) if isinstance(v, list) else None
    return {"t": list(t), "c": col("close") or [None] * n, "o": col("open"), "h": col("high"),
            "l": col("low"), "v": col("volume"), "meta": res.get("meta") or {}}


def parse_chart(text_or_doc, sym=""):
    try:
        doc = json.loads(text_or_doc) if isinstance(text_or_doc, str) else text_or_doc
        chart = doc["chart"]
    except (ValueError, KeyError, TypeError):
        raise DataError("Yahoo returned something unexpected for %s" % sym)
    res = chart.get("result")
    if not res:
        err = chart.get("error") or {}
        raise DataError("no data for %s: %s" % (sym, err.get("description", "unknown ticker")))
    return series_from_result(res[0])


def parse_spark(text_or_doc):
    """Spark JSON -> {YAHOO_SYMBOL: series}."""
    doc = json.loads(text_or_doc) if isinstance(text_or_doc, str) else text_or_doc
    sp = (doc or {}).get("spark") if isinstance(doc, dict) else None
    if not isinstance(sp, dict):
        raise DataError("Yahoo's spark answer is not the shape this tool knows")
    out = {}
    for item in sp.get("result") or []:
        resp = item.get("response") or []
        if not resp:
            continue
        ysym = (item.get("symbol") or (resp[0].get("meta") or {}).get("symbol") or "").upper()
        out[ysym] = series_from_result(resp[0])
    if sp.get("error") and not out:
        e = sp["error"]
        raise DataError("Yahoo spark: %s" % (e.get("description") or e.get("code") or e))
    return out


def read_maybe_gz(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def load_chart_offline(path, sym):
    """A saved v8 chart: a file, or a folder holding <SYM>.json(.gz) / <SYM>.NS.json."""
    if os.path.isdir(path):
        for name in (sym, sym + ".NS", sym + ".BO", to_yahoo(sym)):
            for ext in (".json", ".json.gz"):
                p = os.path.join(path, name + ext)
                if os.path.exists(p):
                    return parse_chart(read_maybe_gz(p), sym)
        raise DataError("no saved chart for %s in %s" % (sym, path))
    doc = json.loads(read_maybe_gz(path))
    if isinstance(doc, dict) and "chart" not in doc:
        for key in (sym, to_yahoo(sym)):
            if key in doc:
                return parse_chart(doc[key], sym)
        raise DataError("no chart for %s in %s" % (sym, path))
    return parse_chart(doc, sym)


def fetch_chart(sym, rng="1d", interval="5m", offline=None, exchange="NSE"):
    if offline:
        return load_chart_offline(offline, sym)
    return parse_chart(yahoo_get(chart_path(to_yahoo(sym, exchange), rng, interval)), sym)


def bars_from_series(series, interval_min=5):
    """[{t: aware IST datetime (bar start), o,h,l,c,v}] dropping nulls and the live
    tick (anything off the interval grid)."""
    out = []
    n = len(series["t"])
    for i in range(n):
        c = series["c"][i]
        if c is None:
            continue
        dt = ts_to_ist(series["t"][i])
        if dt.second or dt.minute % interval_min:
            continue
        g = lambda k: (series.get(k) or [None] * n)[i]
        o, h, l, v = g("o"), g("h"), g("l"), g("v")
        out.append({"t": dt, "o": float(o if o is not None else c), "h": float(h if h is not None else c),
                    "l": float(l if l is not None else c), "c": float(c), "v": int(v or 0)})
    # one bar per start time: the last one wins
    seen = {}
    for b in out:
        seen[b["t"]] = b
    return [seen[k] for k in sorted(seen)]


def session_bars(bars, d):
    return [b for b in bars if b["t"].date() == d]


def bar_slot(d, k, interval_min=5):
    """Start time of the k-th bar (0-based) of the session on day d."""
    s = session(d)
    o = s[0] if s else OPEN
    return ist_dt(d, o) + _dt.timedelta(minutes=interval_min * k)


def cont_end(d):
    """End of continuous trading (the last bar's close) on day d."""
    s = session(d)
    if not s:
        return None
    return min(s[1], CONT_END)


def bars_in_session(d, interval_min=5):
    """Tradable bars, open to the end of continuous trading (73 on a normal day)."""
    s = session(d)
    if not s:
        return 0
    o, e = s[0], cont_end(d)
    return int(((e.hour * 60 + e.minute) - (o.hour * 60 + o.minute)) / interval_min)

# ------------------------------------------------------------------ NSE session

class NSE:
    """A polite nseindia.com session: visits a page first to collect the cookies
    the API wants, sends browser headers, pauses between calls."""

    BASE = "https://www.nseindia.com"

    def __init__(self, pause=0.6, timeout=20):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.pause = pause
        self.timeout = timeout
        self.warm = False
        self.last = 0.0

    def _headers(self, referer=None):
        return {"User-Agent": BROWSER_UA, "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-IN,en;q=0.9", "Accept-Encoding": "gzip",
                "Referer": referer or self.BASE + "/", "Connection": "keep-alive"}

    def _wait(self):
        dt = time.time() - self.last
        if dt < self.pause:
            SLEEP(self.pause - dt)
        self.last = time.time()

    def warmup(self, page="/market-data/live-equity-market"):
        if self.warm:
            return
        for p in ("/", page):
            try:
                self._wait()
                http_get(self.BASE + p, timeout=self.timeout, opener=self.opener,
                         headers=dict(self._headers(), Accept="text/html,*/*"))
            except Exception:
                pass
        self.warm = True

    def get_text(self, path_or_url, referer=None):
        url = path_or_url if path_or_url.startswith("http") else self.BASE + path_or_url
        self.warmup()
        last = None
        for attempt in (0, 1):
            try:
                self._wait()
                return http_get(url, timeout=self.timeout, opener=self.opener,
                                headers=self._headers(referer))
            except urllib.error.HTTPError as e:
                last = "HTTP %d" % e.code
                if e.code in (401, 403) and attempt == 0:
                    self.warm = False
                    self.warmup()
                    continue
                if e.code >= 500 and attempt == 0:
                    SLEEP(2)
                    continue
                break
            except (urllib.error.URLError, OSError) as e:
                last = str(getattr(e, "reason", e))
                if attempt == 0:
                    SLEEP(2)
                    continue
        raise DataError("NSE answered %s for %s" % (last, url.split("?")[0]))

    def get_json(self, path_or_url, referer=None):
        txt = self.get_text(path_or_url, referer)
        try:
            return json.loads(txt)
        except ValueError:
            raise DataError("NSE sent something that is not JSON for %s (blocked or changed)"
                            % path_or_url.split("?")[0])

# ------------------------------------------------------------------ trader/ folder

DEFAULT_CONFIG = {
    "capital_inr": 100000,
    "cash_buffer_pct": 10,
    "max_position_pct": 50,
    "max_order_inr": 50000,
    "min_order_inr": 500,
    "max_loss_per_trade_inr": 500,
    "max_daily_loss_inr": 1500,
    "max_trades_per_day": 3,
    "max_orders_per_day": 10,
    "min_reward_risk": 1.0,
    "require_stop": True,
    "include_charges_in_risk": True,
    "no_entries_before": "09:30",
    "no_entries_after": "14:45",
    "flat_by": "15:05",
    "broker_square_off": "15:25",
    "exchange": "NSE",
    "product": "MIS",
    "leverage": 1,
    "stop_order_type": "SL-M",
    "broker": "zerodha",
    "paper": True,
    "blocked": [],
    "surveillance": [],
    "allow_options": False,
    "allow_futures": False,
    "allow_margin": False,
    "allow_short": False,
    "allow_sme": False,
    "charges": {},
    "extra_holidays": {},
    "watch_investors": ["Rakesh Jhunjhunwala", "Rekha Jhunjhunwala", "Ashish Kacholia",
                        "Vijay Kedia", "Dolly Khanna", "Radhakishan Damani", "Mukul Agrawal",
                        "Sunil Singhania", "Abakkus", "Porinju"],
}


def trader_dir(base=None):
    return base or os.environ.get("TRADER_DIR") or "trader"


def tpath(*parts, base=None):
    return os.path.join(trader_dir(base), *parts)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except ValueError as e:
        raise DataError("%s is not valid JSON: %s" % (path, e))


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False, default=str)
        fh.write("\n")
    os.replace(tmp, path)


def load_config(path=None):
    cfg = dict(DEFAULT_CONFIG)
    user = read_json(path or tpath("config.json"), {}) or {}
    cfg.update(user)
    cfg["_from_file"] = bool(user)
    load_extra_holidays(cfg)
    return cfg


SAFETY = """\
Education and tooling, not financial advice. Most intraday traders in India lose
money (SEBI's FY2023 study: 7 in 10 individual intraday equity traders made a loss).
Nothing places an order except in-trader-broker, after in-trader-risk passes that
exact order and you type an explicit yes for it."""

# ------------------------------------------------------------------ setups (shared math)

def closed_bars(bars, now, interval_min=5):
    """Bars whose end (start + interval) is at or before `now`."""
    step = _dt.timedelta(minutes=interval_min)
    return [b for b in bars if b["t"] + step <= now]


def opening_range(day_bars, d, or_minutes=15, interval_min=5):
    """(high, low, n_bars_found, n_bars_expected, range_bars) for the first
    or_minutes of the session, from day_bars (one day's bars, oldest first)."""
    s = session(d)
    o = ist_dt(d, s[0] if s else OPEN)
    end = o + _dt.timedelta(minutes=or_minutes)
    rb = [b for b in day_bars if o <= b["t"] < end]
    n_exp = or_minutes // interval_min
    if not rb:
        return None, None, 0, n_exp, []
    return max(b["h"] for b in rb), min(b["l"] for b in rb), len(rb), n_exp, rb


def first_close_above(day_bars, level, start, min_volume=None):
    """First bar starting at/after `start` that CLOSES above level (and has at
    least min_volume shares, when given). Returns (index, bar) or (None, None)."""
    for i, b in enumerate(day_bars):
        if b["t"] < start:
            continue
        if b["c"] > level + 1e-9 and (min_volume is None or b["v"] >= min_volume):
            return i, b
    return None, None


def rsi(closes, n=14):
    """Wilder's RSI on closes."""
    if len(closes) < n + 1:
        return None
    g = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    lo = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = sum(g[:n]) / n, sum(lo[:n]) / n
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + lo[i]) / n
    return 100 - 100 / (1 + ag / al) if al else 100.0


def atr(bars, n=14):
    """Average true range over the last n bars (fewer if that is all there is)."""
    if not bars:
        return None, 0
    trs = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b["h"] - b["l"])
        else:
            pc = bars[i - 1]["c"]
            trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
    use = trs[-n:]
    return sum(use) / len(use), len(use)


def daily_setups(c):
    """closes (oldest first, >= 30) -> (setup tags, numbers)."""
    last = c[-1]
    hi20 = max(c[-21:-1])
    ma20 = sum(c[-20:]) / 20.0
    ma20_prev = sum(c[-21:-1]) / 20.0
    run = c[-6] / c[-16] - 1
    rng5 = (max(c[-5:]) - min(c[-5:])) / last
    r = rsi(c)
    r_prev = rsi(c[:-1])
    tags = []
    if last > hi20:
        tags.append("breakout_20d")
    if run > 0.10 and rng5 < 0.05:
        tags.append("bull_flag")
    if c[-2] < ma20_prev and last > ma20:
        tags.append("reclaim_ma20")
    if r is not None and r < 30:
        tags.append("oversold")
    if r_prev is not None and r_prev < 30 and last > c[-2]:
        tags.append("oversold_bounce")
    return tags, {"rsi": r, "rsi_prev": r_prev, "high20": hi20, "ma20": ma20,
                  "run_pct": run * 100, "range5_pct": rng5 * 100}
