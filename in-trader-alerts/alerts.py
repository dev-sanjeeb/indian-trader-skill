#!/usr/bin/env python3
"""in-trader-alerts: price and clock alerts for NSE/BSE, each ringing once.

  alerts.py clock                                NSE open or closed, next session
  alerts.py add --from-plan                      stop, target, flat-by from trader/plan.json
  alerts.py add --opening-bell
  alerts.py add --symbol RELIANCE --stop 1223.10
  alerts.py add --symbol RELIANCE --target 1245.90
  alerts.py add --symbol TCS --above 2550 | --below 2400 | --pct 3
  alerts.py add --at 15:05 --label "flat by" [--symbol RELIANCE]
  alerts.py check                                exit 0 = something rang
  alerts.py quote RELIANCE --write               -> trader/prices.json
  alerts.py quote --holdings --write             portfolio + plan symbols
  alerts.py list | reset ID | remove ID

Quotes are Yahoo Finance's free chart endpoint (SYMBOL.NS / .BO): unofficial and
delayed. Fine for alerts and sizing checks, never for timing an order.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inmarket as M  # noqa: E402


def rules_path():
    return M.tpath("alerts.json")


def load_rules():
    return M.read_json(rules_path(), {"rules": []}) or {"rules": []}


def quote(sym, offline=None, exchange="NSE"):
    """-> {price, prev_close, as_of (ISO, IST), source}"""
    if offline:
        s = M.load_chart_offline(offline, sym)
    else:
        s = M.parse_chart(M.yahoo_get(M.chart_path(M.to_yahoo(sym, exchange), "1d", "5m")), sym)
    meta = s.get("meta") or {}
    price = meta.get("regularMarketPrice")
    t = meta.get("regularMarketTime")
    if price is None:
        cl = [c for c in s["c"] if c is not None]
        if not cl:
            raise M.DataError("no price for %s" % sym)
        price, t = cl[-1], s["t"][-1]
    return {"price": round(float(price), 2), "prev_close": meta.get("previousClose") or meta.get("chartPreviousClose"),
            "as_of": M.ts_to_ist(t).isoformat(timespec="seconds"), "source": "yahoo"}


def add_rule(doc, rule):
    rid = rule["id"]
    doc["rules"] = [r for r in doc["rules"] if r["id"] != rid] + [rule]
    return rule


def describe(r):
    t = r["type"]
    if t in ("above", "target"):
        s = "%s at or above %s" % (r["symbol"], M.px(r["price"]))
    elif t in ("below", "stop"):
        s = "%s at or below %s" % (r["symbol"], M.px(r["price"]))
    elif t == "pct_move":
        s = "%s moves %g%% %sfrom the previous close" % (r["symbol"], r["pct"], (r.get("direction", "") + " ") if r.get("direction") else "")
    elif t == "time":
        s = "%s IST: %s%s" % (r["at"], r.get("label", "time"), (" (" + r["symbol"] + ")") if r.get("symbol") else "")
    else:
        s = "the NSE opening bell (9:15 IST)"
    return "%-22s %-7s %s%s" % (r["id"], t, s, (" on " + r["date"]) if r.get("date") else "")


def evaluate(doc, state, now, quotes):
    """Pure. -> (rang [(rule, message)], state)."""
    d = now.date()
    dkey = d.isoformat()
    s = M.session(d)
    rang = []
    fired = state.setdefault("fired", {})
    for r in doc["rules"]:
        if r.get("date") and r["date"] != dkey:
            continue
        rid = r["id"]
        last = fired.get(rid)
        t = r["type"]
        if t == "opening_bell":
            if s and now >= M.ist_dt(d, s[0]) and now < M.ist_dt(d, s[1]) and last != dkey:
                fired[rid] = dkey
                rang.append((r, "OPENING BELL: NSE is open (%s, %s IST)." % (s[2], M.clock(s[0]))))
            continue
        if t == "time":
            if not s:
                continue
            at = M.parse_hhmm(r["at"])
            if M.is_special(d):
                at = min(at, (dt.datetime.combine(d, M.cont_end(d)) - dt.timedelta(minutes=15)).time())
            if now.time() >= at and last != dkey:
                fired[rid] = dkey
                msg = "ALERT %s: it is %s IST (set for %s)." % (r.get("label", "time").capitalize(), M.hhmm(now), M.hhmm(at))
                if "flat" in r.get("label", ""):
                    msg += (" If %s is still open, close it now, before the 3:15 PM closing auction (no stop-loss orders "
                            "there): ticket.py flatten --symbol %s, then in-trader-risk and your yes. Your broker squares "
                            "off MIS at 3:25 PM anyway, with a fee." % (r.get("symbol") or "a position", r.get("symbol") or "SYMBOL"))
                rang.append((r, msg))
            continue
        q = quotes.get(r.get("symbol"))
        if not q:
            continue
        p = q["price"]
        if t in ("above", "target", "below", "stop"):
            up = t in ("above", "target")
            hit = p >= r["price"] if up else p <= r["price"]
            if hit and not last:
                fired[rid] = now.isoformat(timespec="minutes")
                word = {"target": "TARGET", "stop": "STOP", "above": "ABOVE", "below": "BELOW"}[t]
                msg = "ALERT %s %s: %s is %s (quote %s IST), %s %s." % (
                    r["symbol"], word, r["symbol"], M.px(p), q["as_of"][11:16], "at or above" if up else "at or below", M.px(r["price"]))
                if t == "stop":
                    msg += " The SL-M at Zerodha has probably triggered: check Kite get_positions, then ticket.py fill."
                if t == "target":
                    msg += " Take it? Cancel the SL-M first, then a MARKET sell: ticket.py flatten, in-trader-risk, your yes."
                rang.append((r, msg))
            elif not hit and last and r.get("rearm"):
                fired.pop(rid, None)
        elif t == "pct_move":
            ref = r.get("ref") or q.get("prev_close")
            if not ref:
                continue
            ch = (p / ref - 1) * 100
            dirn = r.get("direction")
            hit = abs(ch) >= r["pct"] and (not dirn or (dirn == "up" and ch > 0) or (dirn == "down" and ch < 0))
            if hit and last != dkey:
                fired[rid] = dkey
                rang.append((r, "ALERT %s MOVE: %s is %s, %+.2f%% from %s." % (r["symbol"], r["symbol"], M.px(p), ch, M.px(ref))))
    return rang, state


def merge_prices(qs):
    doc = M.read_json(M.tpath("prices.json"), {"prices": {}}) or {"prices": {}}
    doc.setdefault("prices", {})
    for s, q in qs.items():
        doc["prices"][s] = {"price": q["price"], "as_of": q["as_of"], "prev_close": q.get("prev_close"), "source": q["source"]}
    doc["as_of"] = max(q["as_of"] for q in qs.values()) if qs else doc.get("as_of")
    M.write_json(M.tpath("prices.json"), doc)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--now")
    ap.add_argument("--offline")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("clock")
    q = sub.add_parser("add")
    q.add_argument("--from-plan", action="store_true")
    q.add_argument("--opening-bell", action="store_true")
    q.add_argument("--symbol")
    for f in ("--stop", "--target", "--above", "--below", "--pct"):
        q.add_argument(f, type=float)
    q.add_argument("--direction", choices=["up", "down"])
    q.add_argument("--at")
    q.add_argument("--label")
    q.add_argument("--date")
    q.add_argument("--rearm", action="store_true")
    sub.add_parser("check")
    q = sub.add_parser("quote")
    q.add_argument("symbols", nargs="*")
    q.add_argument("--holdings", action="store_true")
    q.add_argument("--write", action="store_true")
    sub.add_parser("list")
    for name in ("reset", "remove"):
        q = sub.add_parser(name)
        q.add_argument("id")
    a = ap.parse_args(argv)
    cfg = M.load_config(a.config)
    now = M.now_ist(a.now)
    if a.cmd == "clock":
        st, line = M.market_status(now)
        print(line)
        w = M.year_warning(now.date())
        if w:
            print(w)
        return 0 if st == "open" else 1
    if a.cmd == "add":
        doc = load_rules()
        added = []
        if a.from_plan:
            p = M.read_json(M.tpath("plan.json"))
            if not p:
                print("No trader/plan.json. Run /in-trader-exit first.")
                return 1
            sl = p["symbol"].lower()
            added.append(add_rule(doc, {"id": sl + "-plan-stop", "symbol": p["symbol"], "type": "stop", "price": p["stop"],
                                        "note": "plan stop: " + p.get("stop_rule", ""), "date": p["date"]}))
            added.append(add_rule(doc, {"id": sl + "-plan-target", "symbol": p["symbol"], "type": "target",
                                        "price": p["target"], "note": "plan target", "date": p["date"]}))
            added.append(add_rule(doc, {"id": sl + "-flat-by", "symbol": p["symbol"], "type": "time",
                                        "at": p.get("flat_by", cfg.get("flat_by", "15:05")), "label": "flat by", "date": p["date"]}))
        if a.opening_bell:
            added.append(add_rule(doc, {"id": "opening-bell", "type": "opening_bell"}))
        sym = M.norm_symbol(a.symbol) if a.symbol else None
        for f, t in (("stop", "stop"), ("target", "target"), ("above", "above"), ("below", "below")):
            v = getattr(a, f)
            if v is not None:
                if not sym:
                    raise SystemExit("--%s needs --symbol" % f)
                added.append(add_rule(doc, {"id": "%s-%s-%s" % (sym.lower(), t, M.px(v)), "symbol": sym, "type": t,
                                            "price": v, "date": a.date, "rearm": a.rearm}))
        if a.pct is not None:
            added.append(add_rule(doc, {"id": "%s-move-%g" % (sym.lower(), a.pct), "symbol": sym, "type": "pct_move",
                                        "pct": a.pct, "direction": a.direction, "date": a.date}))
        if a.at:
            label = a.label or "time"
            added.append(add_rule(doc, {"id": "%s%s" % ((sym.lower() + "-") if sym else "", label.replace(" ", "-")),
                                        "symbol": sym, "type": "time", "at": a.at, "label": label, "date": a.date}))
        for r in added:
            for k in [k for k, v in r.items() if v in (None, False)]:
                r.pop(k)
        M.write_json(rules_path(), doc)
        for r in added:
            print("Added  " + describe(r))
        return 0 if added else 1
    if a.cmd == "list":
        doc = load_rules()
        st = M.read_json(M.tpath("state", "alerts.json"), {}) or {}
        for r in doc["rules"]:
            print(describe(r) + ("   (rang %s)" % st.get("fired", {})[r["id"]] if r["id"] in st.get("fired", {}) else ""))
        return 0
    if a.cmd in ("reset", "remove"):
        st = M.read_json(M.tpath("state", "alerts.json"), {}) or {}
        st.get("fired", {}).pop(a.id, None)
        M.write_json(M.tpath("state", "alerts.json"), st)
        if a.cmd == "remove":
            doc = load_rules()
            doc["rules"] = [r for r in doc["rules"] if r["id"] != a.id]
            M.write_json(rules_path(), doc)
        print("%s %s." % ("Removed" if a.cmd == "remove" else "Re-armed", a.id))
        return 0
    if a.cmd == "quote":
        syms = [M.norm_symbol(s) for s in a.symbols]
        if a.holdings:
            p = M.read_json(M.tpath("portfolio.json"), {}) or {}
            syms += list((p.get("positions") or {}).keys())
            pl = M.read_json(M.tpath("plan.json"), {}) or {}
            if pl.get("symbol"):
                syms.append(pl["symbol"])
        syms = sorted(set(syms))
        qs = {}
        for s in syms:
            try:
                qs[s] = quote(s, a.offline, M.exchange_of(s, cfg.get("exchange", "NSE")))
                M.SLEEP(0.5) if not a.offline else None
            except M.DataError as e:
                print("%-12s no quote: %s" % (s, e))
        for s, q in qs.items():
            ch = (" %+.2f%% vs previous close %s" % ((q["price"] / q["prev_close"] - 1) * 100, M.px(q["prev_close"]))) if q.get("prev_close") else ""
            print("%-12s %s at %s IST (Yahoo, delayed)%s" % (s, M.inr(q["price"]), q["as_of"][11:16], ch))
        if a.write and qs:
            merge_prices(qs)
            print("Merged into trader/prices.json.")
        return 0 if qs else 1
    if a.cmd == "check":
        doc = load_rules()
        state = M.read_json(M.tpath("state", "alerts.json"), {}) or {}
        dkey = now.date().isoformat()
        todays = [r for r in doc["rules"] if not r.get("date") or r["date"] == dkey]
        syms = sorted({r["symbol"] for r in todays if r.get("symbol") and r["type"] not in ("time",)})
        qs = {}
        stt, line = M.market_status(now)
        for s in syms:
            try:
                qs[s] = quote(s, a.offline, M.exchange_of(s, cfg.get("exchange", "NSE")))
            except M.DataError as e:
                print("no quote for %s: %s" % (s, e))
        rang, state = evaluate(doc, state, now, qs)
        M.write_json(M.tpath("state", "alerts.json"), state)
        if qs:
            merge_prices(qs)
        print(line)
        for r, msg in rang:
            print(msg)
        if not rang:
            print("Nothing hit. %d rule(s) watched today%s." % (len(todays), (", " + ", ".join(
                "%s %s" % (s, M.inr(q["price"])) for s, q in qs.items())) if qs else ""))
        return 0 if rang else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
