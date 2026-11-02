#!/usr/bin/env python3
"""in-trader-entry: the Entry Timer for NSE/BSE stocks.

Watches a setup bar by bar and says the moment to get in: the first COMPLETED
bar that closes above the opening-range high (or a level you give). Long only.
It never places an order.

  entry.py check RELIANCE                     15-minute opening range, 5-minute bars
  entry.py check RELIANCE --write             also save trader/entry.json
  entry.py check TCS --setup level --level 2512.50
  entry.py check SBIN --interval 1m --min-volume-x 1.5
  entry.py watch RELIANCE --until 14:45       one line per closed bar, stops on the trigger
  entry.py watchlist                          every hit in trader/watchlist.json

Times are India time (IST). --now "2026-11-02 10:15" replays a moment;
--offline FILE reads a saved Yahoo chart instead of the network.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inmarket as M  # noqa: E402

YAHOO_LAG = dt.timedelta(seconds=60)


def evaluate(bars, sym, now, cfg, setup="orb", level=None, or_minutes=15, interval=5,
             min_volume_x=None, exchange="NSE"):
    """Pure. bars = all bars (any days). Returns a result dict with status one of
    closed, not_open, forming, waiting, triggered, expired, no_data."""
    d = now.date()
    res = {"symbol": sym, "exchange": exchange, "date": d.isoformat(), "setup": setup,
           "interval": "%dm" % interval, "or_minutes": or_minutes, "as_of": now.strftime("%Y-%m-%d %H:%M")}
    s = M.session(d)
    if s is None:
        res.update(status="closed", line="The market is closed today (%s)." % (M.closed_reason(d) or "closed"))
        return res
    o = M.ist_dt(d, s[0])
    end = M.ist_dt(d, M.cont_end(d))
    nb = M.parse_hhmm(cfg.get("no_entries_before") or "00:00")
    na = M.parse_hhmm(cfg.get("no_entries_after") or "23:59")
    if M.is_special(d):  # Muhurat: the window is the session itself
        nb, na = s[0], M.cont_end(d)
    na = min(na, M.cont_end(d))
    if now < o:
        res.update(status="not_open", line="Not open yet: the %s starts at %s IST." % (s[2], M.clock(s[0])))
        return res
    day = [b for b in M.session_bars(bars, d) if b["t"] <= now]  # nothing from the future
    step = dt.timedelta(minutes=interval)
    closed = M.closed_bars(day, now, interval)
    res["bars_closed"] = len(closed)
    or_end = o + dt.timedelta(minutes=or_minutes)
    oh = ol = None
    if setup == "orb":
        if now < or_end:
            res.update(status="forming", line="The opening range is still forming (until %s IST)." % M.clock(or_end))
            return res
        oh, ol, nf, ne, rb = M.opening_range(closed, d, or_minutes, interval)
        if oh is None:
            res.update(status="no_data", line="No bars for the opening range from Yahoo (%s)." % sym)
            return res
        res.update(or_high=oh, or_low=ol, or_bars=nf, or_bars_expected=ne)
        level = oh
        avg_v = sum(b["v"] for b in rb) / float(len(rb)) if rb else 0
    else:
        if level is None:
            raise SystemExit("--setup level needs --level PRICE")
        avg_v = None
        if closed:
            k = max(1, or_minutes // interval)
            first = closed[:k]
            avg_v = sum(b["v"] for b in first) / float(len(first))
    res["level"] = round(level, 2)
    minv = (avg_v * min_volume_x) if (min_volume_x and avg_v) else None
    start = or_end if setup == "orb" else o
    start = max(start, M.ist_dt(d, nb) - step)  # the bar must CLOSE at/after no_entries_before
    i, b = M.first_close_above(closed, level, start, minv)
    if b is not None:
        close_t = b["t"] + step
        res.update(trigger_bar_start=M.hhmm(b["t"]), trigger_time=M.hhmm(close_t),
                   entry=round(b["c"], 2), bar_index=i + 1,
                   over_pct=round((b["c"] / level - 1) * 100, 2),
                   volume_x=round(b["v"] / avg_v, 2) if avg_v else None)
        if close_t.time() > na:
            res.update(status="expired", line="The first close above came at %s, after your %s cutoff: expired."
                       % (M.clock(close_t), M.clock(na)))
            return res
        age = (now - close_t).total_seconds() / 60.0
        res.update(status="triggered", minutes_since=round(age, 1))
        return res
    # not triggered
    if now.time() > na or now >= end:
        res.update(status="expired", line="No close above %s by your %s cutoff: the setup expired today."
                   % (M.px(level), M.clock(na)))
        return res
    last = closed[-1] if closed else None
    forming = None
    if day:
        lb = day[-1]
        if lb["t"] + step > now:
            forming = lb
    if last:
        res.update(last_close=round(last["c"], 2), last_bar=M.hhmm(last["t"]),
                   gap=round(level - last["c"], 2), gap_pct=round((last["c"] / level - 1) * 100, 2))
    if forming:
        res.update(forming_bar=M.hhmm(forming["t"]), forming_price=round(forming["c"], 2),
                   forming_closes=M.hhmm(forming["t"] + step))
    res["status"] = "waiting"
    return res


def render(r):
    sym = r["symbol"]
    st = r["status"]
    out = []
    if st in ("closed", "not_open", "forming", "no_data") and "line" in r:
        return r["line"]
    head = "%s  %s %s IST  %s on %s bars (Yahoo, free, can lag)" % (
        sym, M.day_label(dt.date.fromisoformat(r["date"])), r["as_of"][11:],
        "opening-range breakout (%d-minute range)" % r["or_minutes"] if r["setup"] == "orb" else "level %s" % M.px(r["level"]),
        r["interval"].replace("m", "-minute"))
    out.append(head)
    if r.get("or_high") is not None:
        out.append("Opening range %s-%s: high %s, low %s (%d of %d bars)." % (
            "9:15", M.clock((dt.datetime(2000, 1, 1, 9, 15) + dt.timedelta(minutes=r["or_minutes"])).time())[:-3],
            M.inr(r["or_high"]), M.inr(r["or_low"]), r["or_bars"], r["or_bars_expected"]))
    if st == "triggered":
        t = dt.datetime.strptime(r["trigger_time"], "%H:%M").time()
        vx = (" Volume %.2fx the range's average." % r["volume_x"]) if r.get("volume_x") else ""
        out.append("TRIGGERED %s at %s: the %s bar (bar %d) closed above %s (+%.2f%%).%s" % (
            M.clock(t), M.inr(r["entry"]), M.clock(dt.datetime.strptime(r["trigger_bar_start"], "%H:%M").time())[:-3],
            r["bar_index"], M.inr(r["level"]), r["over_pct"], vx))
        if r.get("minutes_since", 0) > 6:
            out.append("That close is %.0f minutes old: the price has moved on, and a late entry is a different trade."
                       % r["minutes_since"])
        out.append("This is the moment to get in, if you take the trade. Nothing was placed.")
        out.append("Next: set the stop and target BEFORE you buy: /in-trader-exit (exit.py plan).")
    elif st == "waiting":
        if "last_close" in r and r["gap"] < 0:
            out.append("WAITING  last close %s (%s bar) is above %s, but no close above it has met your volume rule yet." % (
                M.inr(r["last_close"]), r["last_bar"], M.inr(r["level"])))
        elif "last_close" in r:
            out.append("WAITING  last close %s (%s bar), %s under %s (%.2f%%)." % (
                M.inr(r["last_close"]), r["last_bar"], M.inr(r["gap"]), M.inr(r["level"]), r["gap_pct"]))
        else:
            out.append("WAITING  no bar has closed after the range yet.")
        if "forming_bar" in r:
            out.append("The %s bar is still forming (%s so far, closes %s); it does not count until it closes." % (
                r["forming_bar"], M.inr(r["forming_price"]), r["forming_closes"]))
    else:
        out.append(r.get("line", st.upper()))
    return "\n".join(out)


def load_bars(sym, a, interval, exchange):
    rng = "1d" if not a.offline else None
    s = M.fetch_chart(sym, rng or "1d", "%dm" % interval, offline=a.offline, exchange=exchange)
    return M.bars_from_series(s, interval)


def run_check(sym, a, cfg, now):
    interval = int(a.interval.rstrip("m"))
    exchange = a.exchange or M.exchange_of(sym, cfg.get("exchange", "NSE"))
    symn = M.norm_symbol(sym)
    try:
        bars = load_bars(sym, a, interval, exchange)
    except M.DataError as e:
        return {"symbol": symn, "status": "no_data", "line": "No data: %s" % e}
    return evaluate(bars, symn, now, cfg, a.setup, a.level, a.or_minutes, interval, a.min_volume_x, exchange)


def write_entry(r):
    M.write_json(M.tpath("entry.json"), r)


def cmd_check(a, cfg):
    now = M.now_ist(a.now)
    r = run_check(a.symbol, a, cfg, now)
    print(json.dumps(r, indent=2) if a.json else render(r))
    if a.write and r.get("status") in ("triggered", "waiting"):
        write_entry(r)
        if not a.json:
            print("Saved trader/entry.json (%s)." % r["status"])
    return 0 if r.get("status") == "triggered" else 1


def cmd_watch(a, cfg):
    sim = bool(a.now or a.offline)
    now = M.now_ist(a.now) if a.now else M.now_ist()
    interval = int(a.interval.rstrip("m"))
    until = M.parse_hhmm(a.until or cfg.get("no_entries_after") or "14:45")
    last_line = None
    while True:
        r = run_check(a.symbol, a, cfg, now)
        st = r.get("status")
        line = "%s  %s" % (now.strftime("%H:%M"), {
            "waiting": "waiting, last close %s, %s under" % (M.px(r.get("last_close", 0)), M.px(max(0, r.get("gap", 0))))
            if "last_close" in r else "waiting",
            "triggered": "TRIGGERED at %s, %s" % (r.get("trigger_time"), M.px(r.get("entry", 0))),
        }.get(st, r.get("line", st)))
        if line != last_line:
            print(line, flush=True)
            last_line = line
        if st == "triggered":
            write_entry(r)
            print(render(r))
            return 0
        if st in ("expired", "closed", "no_data") or now.time() >= until:
            print("Stopped: %s." % ("expired" if st != "closed" else "market closed"))
            return 1
        # next wake: just after the next bar closes
        step = dt.timedelta(minutes=interval)
        o = M.ist_dt(now.date(), (M.session(now.date()) or (M.OPEN,))[0])
        k = int((now - o).total_seconds() // step.total_seconds()) + 1
        nxt = o + step * k + dt.timedelta(seconds=20)
        if sim:
            now = nxt
        else:
            time.sleep(max(5, min(a.every or 1e9, (nxt - M.now_ist()).total_seconds())))
            now = M.now_ist()


def cmd_watchlist(a, cfg):
    wl = M.read_json(M.tpath("watchlist.json"), {}) or {}
    syms = [h["symbol"] for h in wl.get("hits", [])]
    if not syms:
        print("No hits in trader/watchlist.json. Run /in-trader-scanner first.")
        return 1
    now = M.now_ist(a.now)
    any_t = False
    for s in syms:
        r = run_check(s, a, cfg, now)
        st = r.get("status")
        any_t |= st == "triggered"
        extra = ""
        if st == "triggered":
            extra = "at %s, %s" % (r["trigger_time"], M.inr(r["entry"]))
        elif st == "waiting" and "last_close" in r:
            extra = "%s, %.2f%% from %s" % (M.inr(r["last_close"]), r["gap_pct"], M.inr(r["level"]))
        print("%-12s %-10s %s" % (s, st.upper(), extra))
    return 0 if any_t else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "watch", "watchlist"):
        q = sub.add_parser(name)
        if name != "watchlist":
            q.add_argument("symbol")
        q.add_argument("--setup", choices=["orb", "level"], default="orb")
        q.add_argument("--level", type=float)
        q.add_argument("--interval", default="5m", choices=["5m", "1m"])
        q.add_argument("--or-minutes", type=int, default=15)
        q.add_argument("--min-volume-x", type=float)
        q.add_argument("--exchange", choices=["NSE", "BSE"])
        q.add_argument("--offline")
        q.add_argument("--now")
        q.add_argument("--json", action="store_true")
        q.add_argument("--write", action="store_true")
        q.add_argument("--until")
        q.add_argument("--every", type=float)
        q.add_argument("--config")
    a = p.parse_args(argv)
    cfg = M.load_config(a.config)
    return {"check": cmd_check, "watch": cmd_watch, "watchlist": cmd_watchlist}[a.cmd](a, cfg)


if __name__ == "__main__":
    sys.exit(main())
