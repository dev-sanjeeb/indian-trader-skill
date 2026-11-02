#!/usr/bin/env python3
"""in-trader-insiders: who with inside knowledge or big money traded a stock.

  insiders.py pit RELIANCE [--days 365]          SEBI insider-trading (PIT) disclosures for a company
  insiders.py deals [--days 5] [--type bulk|block|both] [--symbol X] [--client "kacholia"]
  insiders.py watch                              only what is NEW since the last check: deals by the
                                                 investors you follow (config "watch_investors") and in
                                                 your symbols, plus PIT filings in your symbols

Sources (public, free, NSE):
  - SEBI (Prohibition of Insider Trading) Regulations, 2015, Reg. 7(2): promoters,
    directors, KMP and their relatives disclose trades over Rs 10 lakh in a quarter
    within 2 trading days; the company tells the exchange within 2 more.
  - Bulk deals (one client trading over 0.5% of a company's shares in a day) and
    block deals (single trades of Rs 10 crore or more in the block window), reported
    by the exchange the same evening.
This is fast, not early: it is public information, read quickly, never inside information.
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inmarket as M  # noqa: E402


def num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def pdate(s, fmts=("%d-%b-%Y %H:%M", "%d-%b-%Y", "%d-%b-%Y %H:%M:%S")):
    for f in fmts:
        try:
            return dt.datetime.strptime(s.strip().title() if f.startswith("%d-%b") else s, f)
        except (AttributeError, ValueError):
            pass
    return None


def trading_days_between(a, b):
    n, d = 0, a
    while d < b:
        d += dt.timedelta(days=1)
        if M.trading_day(d):
            n += 1
    return n


def parse_pit(doc):
    rows = []
    for r in (doc or {}).get("data") or []:
        td = pdate(r.get("acqtoDt") or "")
        fd = pdate(r.get("date") or "")
        qty = num(r.get("secAcq"))
        val = num(r.get("secVal"))
        cat = r.get("personCategory") or ""
        typ = (r.get("tdpTransactionType") or "").title()
        mode = r.get("acqMode") or ""
        delay = trading_days_between(td.date(), fd.date()) if td and fd else None
        flag = []
        if "promoter" in cat.lower() and mode.lower().startswith("market") and typ == "Buy":
            flag.append("PROMOTER MARKET BUY")
        if "promoter" in cat.lower() and typ == "Sell":
            flag.append("PROMOTER SELL")
        if "pledge" in (typ + mode).lower():
            flag.append("PLEDGE")
        if delay is not None and delay > 4:
            flag.append("LATE (%d trading days)" % delay)
        rows.append({"symbol": r.get("symbol"), "company": r.get("company"), "person": r.get("acqName"),
                     "category": cat, "type": typ, "mode": mode, "qty": int(qty), "value": val,
                     "price": round(val / qty, 2) if qty else None,
                     "from": r.get("acqfromDt"), "to": r.get("acqtoDt"), "filed": r.get("date"),
                     "before_pct": r.get("befAcqSharesPer"), "after_pct": r.get("afterAcqSharesPer"),
                     "security": r.get("secType"), "delay_trading_days": delay, "flags": flag,
                     "link": r.get("xbrl"), "key": "pit-%s-%s" % (r.get("did"), r.get("pid"))})
    rows.sort(key=lambda x: pdate(x["filed"] or "") or dt.datetime.min, reverse=True)
    return rows


def parse_deals(doc, kind):
    out = []
    for r in (doc or {}).get("data") or []:
        q, p = num(r.get("BD_QTY_TRD")), num(r.get("BD_TP_WATP"))
        out.append({"kind": kind, "date": r.get("BD_DT_DATE"), "symbol": r.get("BD_SYMBOL"),
                    "company": r.get("BD_SCRIP_NAME"), "client": r.get("BD_CLIENT_NAME"),
                    "side": (r.get("BD_BUY_SELL") or "").upper(), "qty": int(q), "price": p, "value": q * p,
                    "key": "%s-%s-%s-%s-%s-%s" % (kind, r.get("BD_DT_DATE"), r.get("BD_SYMBOL"), r.get("BD_CLIENT_NAME"),
                                                  r.get("BD_BUY_SELL"), r.get("BD_QTY_TRD"))})
    return out


def crores(v):
    return "Rs %s cr" % format(round(v / 1e7, 2), ",") if v >= 1e7 else M.inr(v, False)


def fetch_pit(sym, a, nse):
    if a.offline:
        p = os.path.join(a.offline, "pit-%s.json" % sym)
        return json.loads(M.read_maybe_gz(p)) if os.path.exists(p) else {"data": []}
    return nse.get_json("/api/corporates-pit?index=equities&symbol=" + urllib.parse.quote(sym))


def in_range(rows, start, end):
    out = []
    for r in rows:
        d = pdate(r.get("date") or "")
        if d is None or start <= d.date() <= end:
            out.append(r)
    return out


def fetch_deals(kind, start, end, a, nse):
    if a.offline:
        p = os.path.join(a.offline, "%s.json" % kind)
        return json.loads(M.read_maybe_gz(p)) if os.path.exists(p) else {"data": []}
    return nse.get_json("/api/historicalOR/bulk-block-short-deals?optionType=%s_deals&from=%s&to=%s" % (
        kind, start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y")))


def show_pit(rows):
    for r in rows:
        print("  filed %s  %-28s %-18s %-4s %10s sh  %-14s at ~%s  (%s to %s%%)%s" % (
            r["filed"], (r["person"] or "")[:28], r["category"][:18], r["type"][:4], format(r["qty"], ","),
            crores(r["value"]), M.px(r["price"]) if r["price"] else "-", r["before_pct"], r["after_pct"],
            ("  " + ", ".join(r["flags"])) if r["flags"] else ""))
        print("        %s, traded %s%s. %s" % (r["mode"], r["to"], (", filed %s trading days later" % r["delay_trading_days"])
                                             if r["delay_trading_days"] is not None else "", r["link"] or ""))


def show_deals(rows):
    for r in rows:
        print("  %s %-5s %-12s %-4s %12s sh at %9s = %-14s %s" % (
            r["date"], r["kind"], r["symbol"], r["side"], format(r["qty"], ","), M.px(r["price"]), crores(r["value"]),
            r["client"]))


def my_symbols(a):
    s = set(M.norm_symbol(x) for x in (a.symbols or []))
    wl = M.read_json(M.tpath("watchlist.json"), {}) or {}
    s |= {h["symbol"] for h in wl.get("hits", [])[:20]}
    pl = M.read_json(M.tpath("plan.json"), {}) or {}
    if pl.get("symbol"):
        s.add(pl["symbol"])
    s |= set(((M.read_json(M.tpath("portfolio.json"), {}) or {}).get("positions") or {}).keys())
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["pit", "deals", "watch"])
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--days", type=int)
    ap.add_argument("--type", choices=["bulk", "block", "both"], default="both")
    ap.add_argument("--symbol")
    ap.add_argument("--client", action="append")
    ap.add_argument("--offline")
    ap.add_argument("--now")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    cfg = M.load_config(a.config)
    now = M.now_ist(a.now)
    nse = None if a.offline else M.NSE()
    try:
        if a.cmd == "pit":
            if not a.symbols:
                print("pit needs a symbol: insiders.py pit RELIANCE")
                return 1
            out = []
            for sym in [M.norm_symbol(s) for s in a.symbols]:
                rows = parse_pit(fetch_pit(sym, a, nse))
                days = a.days or 365
                cut = now.replace(tzinfo=None) - dt.timedelta(days=days)
                recent = [r for r in rows if (pdate(r["filed"] or "") or dt.datetime.min) >= cut]
                out += recent
                if a.json:
                    continue
                print("\n%s: %d insider disclosures filed in the last %d days (SEBI PIT Reg. 7(2), via NSE)." % (sym, len(recent), days))
                if not recent and rows:
                    print("  None that recent. The latest NSE has: filed %s." % rows[0]["filed"])
                    show_pit(rows[:3])
                show_pit(recent[:25])
            if a.json:
                print(json.dumps(out, indent=2))
            return 0 if out else 1
        if a.cmd == "deals":
            days = a.days or 5
            start = now.date() - dt.timedelta(days=days)
            kinds = ["bulk", "block"] if a.type == "both" else [a.type]
            rows = []
            for k in kinds:
                rows += in_range(parse_deals(fetch_deals(k, start, now.date(), a, nse), k), start, now.date())
            if a.symbol:
                rows = [r for r in rows if r["symbol"] == M.norm_symbol(a.symbol)]
            if a.client:
                rows = [r for r in rows if any(c.lower() in (r["client"] or "").lower() for c in a.client)]
            rows.sort(key=lambda r: -r["value"])
            if a.json:
                print(json.dumps(rows, indent=2))
            else:
                print("%s deals %s to %s on NSE%s: %d, biggest first." % (
                    " and ".join(kinds).capitalize(), start, now.date(),
                    (" matching " + ", ".join(a.client)) if a.client else "", len(rows)))
                show_deals(rows[:40])
                print("A bulk deal is a fact about who traded, not a signal: brokers, arbitrage desks and HFT firms show "
                      "up on both sides the same day.")
            return 0 if rows else 1
        # watch
        state = M.read_json(M.tpath("state", "insiders.json"), {"seen": []}) or {"seen": []}
        seen = set(state.get("seen", []))
        first = not seen
        names = [n.lower() for n in cfg.get("watch_investors") or []]
        syms = my_symbols(a)
        start = now.date() - dt.timedelta(days=a.days or 7)
        new_deals = []
        for k in ("bulk", "block"):
            for r in in_range(parse_deals(fetch_deals(k, start, now.date(), a, nse), k), start, now.date()):
                hit_name = any(all(tok in (r["client"] or "").lower() for tok in n.split()) for n in names)
                if (hit_name or r["symbol"] in syms) and r["key"] not in seen:
                    r["why"] = "an investor you follow" if hit_name else "a symbol you watch"
                    new_deals.append(r)
        new_pit = []
        for sym in sorted(syms):
            try:
                for r in parse_pit(fetch_pit(sym, a, nse)):
                    fd = pdate(r["filed"] or "")
                    if r["key"] not in seen and fd and fd >= now.replace(tzinfo=None) - dt.timedelta(days=a.days or 30):
                        new_pit.append(r)
            except M.DataError as e:
                print("NOTE: PIT for %s skipped: %s" % (sym, e))
        if not a.dry_run:
            seen |= {r["key"] for r in new_deals + new_pit}
            state["seen"] = sorted(seen)[-5000:]
            state["checked"] = now.isoformat(timespec="minutes")
            M.write_json(M.tpath("state", "insiders.json"), state)
        print("Insider and big-money check %s IST%s: %d new deal(s), %d new insider filing(s). Watching %d investor names, %d symbols." % (
            now.strftime("%Y-%m-%d %H:%M"), " (first run: the last %d days)" % (a.days or 7) if first else "",
            len(new_deals), len(new_pit), len(names), len(syms)))
        if new_deals:
            show_deals(new_deals)
        if new_pit:
            show_pit(new_pit)
        print("Public filings, read fast. Never inside information, and never a reason on its own to trade.")
        return 0 if (new_deals or new_pit) else 1
    except M.DataError as e:
        print("NSE did not answer: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
