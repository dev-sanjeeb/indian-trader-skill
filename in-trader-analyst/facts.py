#!/usr/bin/env python3
"""in-trader-analyst: what the last results said, and when the next ones are.

  facts.py RELIANCE                       quarters, YoY growth, margins, TTM
  facts.py TCS INFY --metrics trader/metrics.json
  facts.py calendar --days 7              board meetings for results in the next 7 days
                                          (your watchlist, plan and holdings; --all for everyone)

Numbers: Yahoo Finance's fundamentals timeseries (SYMBOL.NS), which lags the
filing by days to weeks and can skip a quarter. Filings: NSE corporate
announcements ("Outcome of Board Meeting", "Financial Results") and the NSE event
calendar. When the company has filed a quarter Yahoo does not have yet, the tool
says so and links the filing: read it before summarising.
Indian fiscal quarters: Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inmarket as M  # noqa: E402

TYPES = ["quarterlyTotalRevenue", "quarterlyGrossProfit", "quarterlyOperatingIncome", "quarterlyEBITDA",
         "quarterlyNetIncome", "quarterlyDilutedEPS"]
SHORT = {"quarterlyTotalRevenue": "revenue", "quarterlyGrossProfit": "gross", "quarterlyOperatingIncome": "operating",
         "quarterlyEBITDA": "ebitda", "quarterlyNetIncome": "net", "quarterlyDilutedEPS": "eps"}


def fy_label(d):
    """2026-09-30 -> 'Q2 FY27'."""
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(d.month)
    fy = d.year + 1 if d.month >= 4 else d.year
    return "Q%s FY%02d" % (q or "?", fy % 100)


def parse_timeseries(doc):
    """-> {date: {revenue, gross, operating, ebitda, net, eps}} quarterly, INR."""
    rows = {}
    for res in ((doc or {}).get("timeseries") or {}).get("result") or []:
        t = (res.get("meta") or {}).get("type", [None])[0]
        for x in res.get(t) or []:
            if not x or x.get("periodType") != "3M":
                continue
            d = dt.date.fromisoformat(x["asOfDate"])
            rows.setdefault(d, {})[SHORT[t]] = x["reportedValue"]["raw"]
    return dict(sorted(rows.items()))


def crore(x):
    if x is None:
        return "-"
    return "%s cr" % format(round(x / 1e7), ",")


def pct(a, b):
    if a is None or b in (None, 0):
        return None
    return (a / b - 1) * 100 * (1 if b > 0 else -1)


def analyse(rows, quarters=6):
    ds = sorted(rows)
    out = []
    for d in ds[-quarters:]:
        r = rows[d]
        ya = [x for x in ds if abs((x - dt.date(d.year - 1, d.month, d.day if d.day <= 28 else 28)).days) < 20]
        prev = rows[ya[0]] if ya else {}
        i = ds.index(d)
        qprev = rows[ds[i - 1]] if i > 0 and 70 < (d - ds[i - 1]).days < 110 else {}
        rev = r.get("revenue")
        row = {"quarter_end": d.isoformat(), "label": fy_label(d), **r,
               "rev_yoy": pct(rev, prev.get("revenue")), "net_yoy": pct(r.get("net"), prev.get("net")),
               "eps_yoy": pct(r.get("eps"), prev.get("eps")), "rev_qoq": pct(rev, qprev.get("revenue")),
               "gross_margin": (r["gross"] / rev * 100) if r.get("gross") and rev else None,
               "op_margin": (r["operating"] / rev * 100) if r.get("operating") is not None and rev else None,
               "ebitda_margin": (r["ebitda"] / rev * 100) if r.get("ebitda") is not None and rev else None,
               "net_margin": (r["net"] / rev * 100) if r.get("net") is not None and rev else None,
               "net_above_operating": bool(r.get("net") and r.get("operating") and r["net"] > r["operating"])}
        out.append(row)
    gaps = []
    for a, b in zip(ds, ds[1:]):
        if (b - a).days > 110:
            gaps.append("%s to %s" % (fy_label(a), fy_label(b)))
    last4 = ds[-4:]
    ttm = None
    if len(last4) == 4 and (last4[-1] - last4[0]).days < 300:
        ttm = {k: sum(rows[d].get(k) or 0 for d in last4) for k in ("revenue", "net", "eps")}
    return out, gaps, ttm


def latest_results_filing(ann, now=None):
    for r in ann or []:
        if now is not None:
            try:
                if dt.datetime.strptime(r.get("an_dt"), "%d-%b-%Y %H:%M:%S").replace(tzinfo=M.IST) > now:
                    continue
            except (TypeError, ValueError):
                pass
        desc = (r.get("desc") or "").lower()
        text = (r.get("attchmntText") or "").lower()
        if "outcome of board meeting" in desc and "result" in text or "financial result" in desc:
            return {"time": r.get("an_dt"), "desc": r.get("desc"), "link": r.get("attchmntFile"),
                    "text": (r.get("attchmntText") or "")[:220]}
    return None


def next_results(events, today):
    best = None
    for e in events or []:
        try:
            d = dt.datetime.strptime(e["date"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        if d >= today and "result" in (e.get("purpose") or "").lower():
            if best is None or d < best[0]:
                best = (d, e)
    return best


def get_sources(sym, a, nse):
    if a.offline:
        def j(name):
            p = os.path.join(a.offline, "%s-%s.json" % (sym, name))
            return json.loads(M.read_maybe_gz(p)) if os.path.exists(p) else None
        return j("timeseries"), j("announcements"), j("events")
    p2 = int(time.time())
    p1 = p2 - 4 * 366 * 86400
    path = "/ws/fundamentals-timeseries/v1/finance/timeseries/%s?symbol=%s&type=%s&period1=%d&period2=%d" % (
        urllib.parse.quote(M.to_yahoo(sym)), urllib.parse.quote(M.to_yahoo(sym)), ",".join(TYPES), p1, p2)
    ts = ann = ev = None
    try:
        ts = json.loads(M.yahoo_get(path))
    except (M.DataError, ValueError) as e:
        print("NOTE: Yahoo fundamentals for %s: %s" % (sym, e))
    if nse:
        try:
            ann = nse.get_json("/api/corporate-announcements?index=equities&symbol=" + urllib.parse.quote(sym))
            ev = nse.get_json("/api/event-calendar?index=equities&symbol=" + urllib.parse.quote(sym))
        except M.DataError as e:
            print("NOTE: NSE filings for %s: %s" % (sym, e))
    return ts, ann, ev


def fmt_pct(x, pts=False):
    return "-" if x is None else ("%+.1f%%" % x)


def cmd_facts(a):
    now = M.now_ist(a.now)
    nse = None if (a.offline or a.no_nse) else M.NSE()
    metrics = []
    for sym in [M.norm_symbol(s) for s in a.symbols]:
        ts, ann, ev = get_sources(sym, a, nse)
        rows = parse_timeseries(ts)
        print("\n%s  (Yahoo fundamentals, INR, crore = 10 million)" % sym)
        if not rows:
            print("  No quarterly numbers from Yahoo. Read the latest results filing on NSE instead.")
        out, gaps, ttm = analyse(rows, a.quarters) if rows else ([], [], None)
        if out:
            print("  %-8s %-10s %14s %8s %8s %13s %8s %8s %8s %8s" % ("quarter", "ended", "revenue", "YoY", "QoQ",
                                                                   "net profit", "YoY", "EPS", "EPS YoY", "op mgn"))
            for r in out:
                print("  %-8s %-10s %14s %8s %8s %13s %8s %8s %8s %8s" % (
                    r["label"], r["quarter_end"], crore(r.get("revenue")), fmt_pct(r["rev_yoy"]), fmt_pct(r["rev_qoq"]),
                    crore(r.get("net")), fmt_pct(r["net_yoy"]), "%.2f" % r["eps"] if r.get("eps") is not None else "-",
                    fmt_pct(r["eps_yoy"]), "%.1f%%" % r["op_margin"] if r.get("op_margin") is not None else "-"))
            last = out[-1]
            if last.get("ebitda_margin") is not None:
                print("  Latest margins: EBITDA %.1f%%, operating %.1f%%, net %.1f%%%s." % (
                    last["ebitda_margin"], last["op_margin"] or 0, last["net_margin"] or 0,
                    (", gross %.1f%%" % last["gross_margin"]) if last.get("gross_margin") else ""))
            if last["net_above_operating"]:
                print("  NOTE: net profit is above operating profit: other income or one-offs are inside it.")
            if gaps:
                print("  NOTE: Yahoo skips %s: growth across a gap is not shown." % "; ".join(gaps))
            if ttm:
                print("  Last four quarters: revenue %s, net profit %s, EPS %.2f." % (crore(ttm["revenue"]), crore(ttm["net"]), ttm["eps"]))
        lf = latest_results_filing(ann, now)
        if lf:
            print("  Latest results filing on NSE: %s, %s" % (lf["time"], lf["link"]))
            try:
                fd = dt.datetime.strptime(lf["time"], "%d-%b-%Y %H:%M:%S").date()
                if out and fd > dt.date.fromisoformat(out[-1]["quarter_end"]) + dt.timedelta(days=95):
                    print("  NOTE: that filing is newer than Yahoo's last quarter (%s): Yahoo lags. Open the filing and "
                          "read the new quarter before summarising." % out[-1]["label"])
            except (TypeError, ValueError):
                pass
        nr = next_results(ev, now.date())
        if nr:
            days = (nr[0] - now.date()).days
            print("  NEXT: board meeting for results on %s (%d day%s away, NSE event calendar)." % (
                M.day_label(nr[0]), days, "" if days == 1 else "s"))
            if days <= 3:
                print("  Results are days away: a day trade that is flat by 3:05 PM is not exposed; anything held overnight is.")
        else:
            print("  No upcoming results meeting on NSE's event calendar (companies announce it about a week ahead).")
        if out:
            l = out[-1]
            metrics.append({"symbol": sym, "quarter": l["label"], "quarter_end": l["quarter_end"],
                            "revenue_cr": round((l.get("revenue") or 0) / 1e7), "rev_yoy": l["rev_yoy"],
                            "net_cr": round((l.get("net") or 0) / 1e7), "net_yoy": l["net_yoy"], "eps": l.get("eps"),
                            "op_margin": l["op_margin"], "ttm_eps": ttm["eps"] if ttm else None,
                            "next_results": nr[0].isoformat() if nr else None})
    if a.metrics:
        M.write_json(a.metrics, {"as_of": now.strftime("%Y-%m-%d"), "source": "Yahoo fundamentals + NSE", "rows": metrics})
        print("\nWrote %s." % a.metrics)
    return 0 if metrics else 1


def cmd_calendar(a):
    now = M.now_ist(a.now)
    if a.offline:
        p = os.path.join(a.offline, "event-calendar.json")
        evs = json.loads(M.read_maybe_gz(p)) if os.path.exists(p) else []
    else:
        try:
            evs = M.NSE().get_json("/api/event-calendar")
        except M.DataError as e:
            print("NSE did not answer: %s" % e)
            return 1
    mine = set()
    if not a.all:
        for f, key in (("watchlist.json", "hits"),):
            mine |= {h["symbol"] for h in (M.read_json(M.tpath(f), {}) or {}).get(key, [])}
        pl = M.read_json(M.tpath("plan.json"), {}) or {}
        if pl.get("symbol"):
            mine.add(pl["symbol"])
        mine |= set(((M.read_json(M.tpath("portfolio.json"), {}) or {}).get("positions") or {}).keys())
        mine |= {M.norm_symbol(s) for s in a.symbols or []}
    rows = []
    for e in evs:
        try:
            d = dt.datetime.strptime(e["date"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        if not (now.date() <= d <= now.date() + dt.timedelta(days=a.days)):
            continue
        if "result" not in (e.get("purpose") or "").lower():
            continue
        if not a.all and e.get("symbol") not in mine:
            continue
        rows.append((d, e.get("symbol"), e.get("company", "")))
    rows.sort()
    print("Results board meetings, %s to %s (NSE event calendar)%s: %d" % (
        now.date(), now.date() + dt.timedelta(days=a.days), "" if a.all else " for your symbols", len(rows)))
    for d, s, c in rows[:a.show]:
        print("  %s  %-12s %s" % (M.day_label(d), s, c))
    if len(rows) > a.show:
        print("  ... %d more" % (len(rows) - a.show))
    return 0 if rows else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--quarters", type=int, default=6)
    ap.add_argument("--metrics")
    ap.add_argument("--offline")
    ap.add_argument("--no-nse", action="store_true")
    ap.add_argument("--now")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--show", type=int, default=40)
    a = ap.parse_args(argv)
    if a.symbols and a.symbols[0] == "calendar":
        a.symbols = a.symbols[1:]
        return cmd_calendar(a)
    if not a.symbols:
        ap.print_help()
        return 1
    return cmd_facts(a)


if __name__ == "__main__":
    sys.exit(main())
