#!/usr/bin/env python3
"""in-trader-scanner: scan NSE charts for setups.

  scan.py universe                    F&O stocks (the liquid ~218): trader/universe.txt
  scan.py universe --index nifty500   Nifty 500 constituents (niftyindices.com)
  scan.py universe --all              every NSE EQ-series stock (EQUITY_L.csv, ~2,000+)
  scan.py surveillance                NSE ASM/GSM lists -> trader/surveillance.json
  scan.py daily                       before 9:15: 20-day breakout, bull flag, MA20 reclaim, oversold
  scan.py daily --symbols RELIANCE,TCS,INFY
  scan.py orb                         after 9:35: opening-range breakouts so far
  scan.py orb --at 10:00              cut the clock at 10:00 IST

Yahoo Finance's spark and chart endpoints (SYMBOL.NS), free and unofficial: 20
symbols a spark request, 5-minute bars, bar by bar, never tick by tick.
"""

import argparse
import csv
import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inmarket as M  # noqa: E402

SPARK_MAX = 20
INDEX_CSV = {
    "nifty50": "ind_nifty50list.csv", "nifty100": "ind_nifty100list.csv", "nifty200": "ind_nifty200list.csv",
    "nifty500": "ind_nifty500list.csv", "midcap150": "ind_niftymidcap150list.csv",
    "smallcap250": "ind_niftysmallcap250list.csv", "bank": "ind_niftybanklist.csv",
}


def progress(a, msg):
    if not getattr(a, "json", False):
        print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- universe

def parse_equity_l(text):
    """NSE EQUITY_L.csv -> [(SYMBOL, name, series)] keeping series EQ and BE."""
    out = []
    rd = csv.reader(io.StringIO(text))
    head = [h.strip().upper() for h in next(rd)]
    i_sym, i_name, i_ser = head.index("SYMBOL"), head.index("NAME OF COMPANY"), head.index("SERIES")
    for row in rd:
        if len(row) <= i_ser:
            continue
        ser = row[i_ser].strip().upper()
        if ser in ("EQ", "BE"):
            out.append((row[i_sym].strip().upper(), row[i_name].strip(), ser))
    return out


def parse_index_csv(text):
    out = []
    rd = csv.DictReader(io.StringIO(text))
    for r in rd:
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        if r.get("Symbol"):
            out.append((r["Symbol"].upper(), r.get("Company Name", ""), r.get("Series", "EQ") or "EQ"))
    return out


def cmd_universe(a, cfg):
    rows, src = [], ""
    try:
        if a.all:
            txt = M.http_get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
                             headers={"User-Agent": M.BROWSER_UA})
            rows, src = parse_equity_l(txt), "NSE EQUITY_L.csv (series EQ and BE)"
        elif a.index:
            name = INDEX_CSV.get(a.index.lower().replace(" ", "").replace("_", ""))
            if not name:
                raise SystemExit("--index: one of %s" % ", ".join(sorted(INDEX_CSV)))
            txt = M.http_get("https://niftyindices.com/IndexConstituent/" + name, headers={"User-Agent": M.BROWSER_UA})
            rows, src = parse_index_csv(txt), "niftyindices.com %s" % name
        else:
            try:
                lst = M.NSE().get_json("/api/master-quote")
                rows, src = [(s, "", "EQ") for s in lst], "nseindia.com F&O underlyings"
            except M.DataError as e:
                progress(a, "NSE did not answer (%s); using the built-in F&O list of 2026-11-02." % e)
                rows, src = [(s, "", "EQ") for s in M.FNO_2026_11], "built-in F&O list (2026-11-02)"
    except Exception as e:  # network blocked, site changed
        print("Could not fetch the list: %s" % e)
        return 1
    be = [r for r in rows if r[2] == "BE"]
    path = M.tpath("universe.txt")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for s, n, ser in rows:
            fh.write("%s|%s|%s\n" % (s, n, ser))
    print("%d symbols from %s -> trader/universe.txt%s" % (
        len(rows), src, (" (%d in series BE, trade-to-trade: no intraday)" % len(be)) if be else ""))
    return 0


def read_universe(a):
    if a.symbols:
        return [M.norm_symbol(s) for s in a.symbols.split(",") if s.strip()]
    if a.watchlist:
        doc = M.read_json(a.watchlist, {}) or {}
        return [h["symbol"] for h in doc.get("hits", [])]
    path = M.tpath("universe.txt")
    if os.path.exists(path):
        out = []
        for line in open(path, encoding="utf-8"):
            parts = line.strip().split("|")
            if parts and parts[0] and (len(parts) < 3 or parts[2] != "BE"):
                out.append(parts[0])
        return out
    return list(M.FNO_2026_11)


# ---------------------------------------------------------------- surveillance

def cmd_surveillance(a, cfg):
    nse = M.NSE()
    syms = {}
    try:
        asm = nse.get_json("/api/reportASM")
        for part in ("longterm", "shortterm"):
            for r in ((asm.get(part) or {}).get("data") or []):
                syms[r["symbol"].upper()] = "under %s" % (r.get("survDesc") or "ASM")
        gsm = nse.get_json("/api/reportGSM")
        for r in gsm if isinstance(gsm, list) else (gsm.get("data") or []):
            syms.setdefault(r["symbol"].upper(), "under GSM (%s)" % (r.get("survDesc") or r.get("gsmStage") or ""))
    except M.DataError as e:
        print("NSE did not answer: %s. Add symbols to \"surveillance\" in trader/config.json by hand." % e)
        return 1
    now = M.now_ist(a.now)
    M.write_json(M.tpath("surveillance.json"), {"as_of": now.strftime("%Y-%m-%d %H:%M"), "source": "nseindia.com ASM/GSM",
                                                "symbols": syms})
    print("%d symbols under NSE surveillance (ASM/GSM) -> trader/surveillance.json. in-trader-risk blocks entries in them." % len(syms))
    return 0


# ---------------------------------------------------------------- fetching

def fetch_spark(symbols, rng, interval, a):
    data, failed = {}, {}
    batches = [symbols[i:i + SPARK_MAX] for i in range(0, len(symbols), SPARK_MAX)]
    for k, batch in enumerate(batches):
        if k:
            M.SLEEP(a.pause)
        ys = {M.to_yahoo(s): s for s in batch}
        try:
            got = M.parse_spark(M.yahoo_get(M.spark_path(list(ys), rng, interval)))
        except (M.DataError, ValueError) as e:
            for s in batch:
                failed[s] = str(e)
            continue
        for y, s in ys.items():
            if y.upper() in got:
                data[s] = got[y.upper()]
            else:
                failed[s] = "no data from Yahoo"
        if len(batches) > 10 and (k + 1) % 10 == 0:
            progress(a, "  spark %d of %d requests" % (k + 1, len(batches)))
    return data, failed


def load_offline(path, symbols):
    data, failed = {}, {}
    for s in symbols:
        try:
            data[s] = M.load_chart_offline(path, s)
        except M.DataError as e:
            failed[s] = str(e)
    return data, failed


# ---------------------------------------------------------------- daily

def daily_closes(series, now):
    today = now.date()
    s = M.session(today)
    done = s is None or now.time() >= s[1]
    out = {}
    for ts, c in zip(series["t"], series["c"]):
        if c is None:
            continue
        d = M.ts_to_ist(ts).date()
        if d > today or (d == today and not done):
            continue
        out[d] = float(c)
    return sorted(out.items())


def scan_daily(data, now, min_price, min_volume):
    hits, counts = [], {"fetched": len(data), "illiquid": 0, "short": 0, "scanned": 0}
    last_dates = []
    for sym, ser in data.items():
        dc = daily_closes(ser, now)
        if len(dc) < 30:
            counts["short"] += 1
            continue
        meta = ser.get("meta") or {}
        price = dc[-1][1]
        vol = meta.get("regularMarketVolume") or 0
        if (ser.get("v") or [None])[-1]:
            vol = vol or ser["v"][-1]
        if price < min_price or (min_volume and vol < min_volume):
            counts["illiquid"] += 1
            continue
        counts["scanned"] += 1
        tags, num = M.daily_setups([c for _, c in dc])
        last_dates.append(dc[-1][0])
        if tags:
            hits.append({"symbol": sym, "setups": tags, "close": round(price, 2), "date": dc[-1][0].isoformat(),
                         "turnover": round(price * vol), "rsi": round(num["rsi"], 1) if num["rsi"] else None,
                         "high20": round(num["high20"], 2), "ma20": round(num["ma20"], 2)})
    hits.sort(key=lambda h: -h["turnover"])
    return hits, counts, (max(last_dates).isoformat() if last_dates else None)


def cmd_daily(a, cfg):
    now = M.now_ist(a.now)
    syms = read_universe(a)
    if a.limit:
        syms = syms[:a.limit]
    if a.offline:
        data, failed = load_offline(a.offline, syms)
    else:
        progress(a, "Fetching daily closes for %d symbols (%d spark requests)..." % (len(syms), -(-len(syms) // SPARK_MAX)))
        data, failed = fetch_spark(syms, "3mo", "1d", a)
    mv = a.min_volume if a.min_volume is not None else 200000
    hits, counts, last = scan_daily(data, now, a.min_price, mv)
    doc = {"mode": "daily", "as_of": now.strftime("%Y-%m-%d %H:%M"), "closes_through": last, "universe": len(syms),
           "fetched": len(data), "failed": len(failed), "scanned": counts["scanned"], "hits": hits}
    if a.json:
        print(json.dumps(doc, indent=2))
    else:
        print("Daily scan, %s IST, closes through %s (Yahoo spark, daily closes only)." % (doc["as_of"], last))
        print("Fetched %d of %d charts (%d failed or had no data); %d liquid and long enough to scan." % (
            len(data), len(syms), len(failed), counts["scanned"]))
        by = {}
        for h in hits:
            for t in h["setups"]:
                by.setdefault(t, []).append(h["symbol"])
        for t in ("breakout_20d", "bull_flag", "reclaim_ma20", "oversold", "oversold_bounce"):
            if t in by:
                print("  %-16s %3d  %s" % (t, len(by[t]), ", ".join(by[t][:a.show]) + (" ..." if len(by[t]) > a.show else "")))
        if not hits:
            print("No chart matched a rule.")
    if hits and not a.no_write:
        M.write_json(M.tpath("watchlist.json"), doc)
    return 0 if hits else 1


# ---------------------------------------------------------------- ORB

def orb_scan(data, d, cutoff, or_minutes, min_price, confirm=None, max_confirm=200, na=None):
    """data {SYM: series (closes at least)}; confirm(sym) -> series with highs/lows.
    Returns (hits, counts)."""
    n_or = or_minutes // 5
    o = M.ist_dt(d, M.session(d)[0])
    counts = {"usable": 0, "candidates": 0, "confirmed": 0, "skipped": 0}
    cands = []
    for sym, ser in data.items():
        bars = [b for b in M.session_bars(M.bars_from_series(ser), d) if b["t"] + dt.timedelta(minutes=5) <= cutoff]
        want = int((cutoff - o).total_seconds() // 300)
        if len(bars) < want or want <= n_or:
            continue
        if bars[-1]["c"] < min_price:
            continue
        counts["usable"] += 1
        rmax = max(b["c"] for b in bars[:n_or])
        if any(b["c"] >= rmax for b in bars[n_or:]):
            turnover = sum(b["c"] * b["v"] for b in bars)
            cands.append((turnover, sym, bars))
    counts["candidates"] = len(cands)
    cands.sort(key=lambda x: -x[0])
    if max_confirm and len(cands) > max_confirm:
        counts["skipped"] = len(cands) - max_confirm
        cands = cands[:max_confirm]
    hits = []
    for turnover, sym, bars in cands:
        if confirm:
            try:
                ser = confirm(sym)
                bars = [b for b in M.session_bars(M.bars_from_series(ser), d) if b["t"] + dt.timedelta(minutes=5) <= cutoff]
            except M.DataError:
                continue
        counts["confirmed"] += 1
        oh, ol, nf, ne, _ = M.opening_range(bars, d, or_minutes)
        if nf < ne:
            continue
        i, b = M.first_close_above(bars, oh, o + dt.timedelta(minutes=or_minutes))
        if b is None:
            continue
        ct = b["t"] + dt.timedelta(minutes=5)
        if na and ct.time() > na:
            continue
        last = bars[-1]["c"]
        hits.append({"symbol": sym, "time": M.hhmm(ct), "close": round(b["c"], 2), "or_high": round(oh, 2),
                     "or_low": round(ol, 2), "over_pct": round((b["c"] / oh - 1) * 100, 2), "last": round(last, 2),
                     "turnover": round(turnover)})
    hits.sort(key=lambda h: (h["time"], -h["turnover"]))
    return hits, counts


def cmd_orb(a, cfg):
    now = M.now_ist(a.now)
    d = now.date()
    s = M.session(d)
    if not s:
        print("The market is closed today (%s): no opening range to scan." % (M.closed_reason(d) or "closed"))
        return 1
    at = M.parse_hhmm(a.at) if a.at else now.time()
    cutoff = M.ist_dt(d, at)
    if cutoff > now:
        cutoff = now
    o = M.ist_dt(d, s[0])
    step5 = (cutoff - o).total_seconds() // 300 * 300
    cutoff = o + dt.timedelta(seconds=step5)
    if cutoff < o + dt.timedelta(minutes=a.or_minutes + 5):
        print("Too early: the %d-minute range ends %s and a bar must close after it (run at %s IST or later)." % (
            a.or_minutes, M.clock(o + dt.timedelta(minutes=a.or_minutes)), M.clock(o + dt.timedelta(minutes=a.or_minutes + 5))))
        return 1
    ce = M.ist_dt(d, M.cont_end(d))
    cutoff = min(cutoff, ce)
    na = M.parse_hhmm(cfg.get("no_entries_after") or "14:45")
    syms = read_universe(a)
    if a.limit:
        syms = syms[:a.limit]
    if a.offline:
        data, failed = load_offline(a.offline, syms)
        confirm = None
    else:
        progress(a, "Stage 1: 5-minute closes for %d symbols (%d spark requests)..." % (len(syms), -(-len(syms) // SPARK_MAX)))
        data, failed = fetch_spark(syms, "1d", "5m", a)

        def confirm(sym):
            M.SLEEP(a.pause)
            return M.fetch_chart(sym, "1d", "5m")
    hits, counts = orb_scan(data, d, cutoff, a.or_minutes, a.min_price, confirm, a.max_confirm, na)
    doc = {"mode": "orb", "as_of": cutoff.strftime("%Y-%m-%d %H:%M"), "universe": len(syms), "fetched": len(data),
           "failed": len(failed), "usable": counts["usable"], "candidates": counts["candidates"],
           "skipped": counts["skipped"], "hits": hits}
    if a.json:
        print(json.dumps(doc, indent=2))
    else:
        print("Fetched %d of %d charts (%d failed or had no data); %d usable; %d candidates, %d confirmed with real highs and lows%s." % (
            len(data), len(syms), len(failed), counts["usable"], counts["candidates"], counts["confirmed"],
            (" (PARTIAL: %d more not checked, --max-confirm 0 checks all)" % counts["skipped"]) if counts["skipped"] else ""))
        print("%d of %d charts closed above their %d-minute opening-range high by %s IST:" % (
            len(hits), counts["usable"], a.or_minutes, M.clock(cutoff)))
        for h in hits[:a.show]:
            print("  %8s  %-12s %10s  range %s to %s  %+.2f%% over" % (
                M.clock(M.parse_hhmm(h["time"])), h["symbol"], M.inr(h["close"]), M.px(h["or_low"]), M.px(h["or_high"]),
                h["over_pct"]))
        if len(hits) > a.show:
            print("  ... %d more in trader/watchlist.json" % (len(hits) - a.show))
        print("A hit matched a rule; it is not a buy. A later hit is closer to the price now.")
    if hits and not a.no_write:
        M.write_json(M.tpath("watchlist.json"), doc)
    return 0 if hits else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("universe", "surveillance", "daily", "orb"):
        q = sub.add_parser(name)
        q.add_argument("--now")
        q.add_argument("--config")
        q.add_argument("--json", action="store_true")
        if name == "universe":
            q.add_argument("--all", action="store_true")
            q.add_argument("--index")
            q.add_argument("--fno", action="store_true")
        if name in ("daily", "orb"):
            q.add_argument("--symbols")
            q.add_argument("--watchlist")
            q.add_argument("--limit", type=int)
            q.add_argument("--offline")
            q.add_argument("--min-price", type=float, default=20.0)
            q.add_argument("--min-volume", type=int)
            q.add_argument("--show", type=int, default=15)
            q.add_argument("--pause", type=float, default=0.4)
            q.add_argument("--no-write", action="store_true")
        if name == "orb":
            q.add_argument("--at")
            q.add_argument("--or-minutes", type=int, default=15)
            q.add_argument("--max-confirm", type=int, default=200)
    a = ap.parse_args(argv)
    cfg = M.load_config(a.config)
    return {"universe": cmd_universe, "surveillance": cmd_surveillance, "daily": cmd_daily, "orb": cmd_orb}[a.cmd](a, cfg)


if __name__ == "__main__":
    sys.exit(main())
