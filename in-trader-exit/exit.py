#!/usr/bin/env python3
"""in-trader-exit: the Exit Planner. Sets the stop and the target BEFORE the entry.

  exit.py plan                                  trader/entry.json: midpoint stop, 2R target
  exit.py plan --stop or-mid --target 1R --write
  exit.py plan --stop atr:1.5                   needs the session's bars (Yahoo or --offline)
  exit.py plan --symbol RELIANCE --entry 1234.50 --or-high 1231.60 --or-low 1214.60
  exit.py show                                  the current trader/plan.json

Stops: or-mid (default for an opening-range breakout), or-low, price:X, pct:X, atr:K.
Targets: 2R (default), 1R, 1.5R..., price:X. Prices round to the NSE tick for that
price band (0.01 under Rs 250, 0.05 to Rs 1,000, 0.10 to Rs 5,000 ...). Long only.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inmarket as M  # noqa: E402

MIN_RISK_PCT = 0.05     # a stop closer than this is inside the spread's wiggle
MIN_RISK_TICKS = 2


class Refused(Exception):
    pass


def make_plan(e, stop_rule="or-mid", target_rule="2R", flat_by="15:05", atr_bars=None, tick=None):
    """Pure. e: dict with symbol, date, entry, (or_high, or_low), entry time. Returns plan dict."""
    entry = float(e["entry"])
    tk = M.tick_size(entry, tick)
    oh, ol = e.get("or_high"), e.get("or_low")
    rule = stop_rule.lower()
    if rule in ("or-mid", "or-low") and (oh is None or ol is None):
        raise Refused("a %s stop needs the opening range; a level setup needs --stop price:X, pct:X or atr:K" % rule)
    if rule == "or-mid":
        raw = (oh + ol) / 2.0
        why = "opening-range midpoint: (%s + %s) / 2 = %s, rounded down to the %s tick" % (
            M.px(oh), M.px(ol), ("%.3f" % raw).rstrip("0").rstrip("."), M.px(tk))
    elif rule == "or-low":
        raw = ol
        why = "opening-range low"
    elif rule.startswith("price:"):
        raw = float(rule.split(":", 1)[1])
        why = "your price"
    elif rule.startswith("pct:"):
        p = float(rule.split(":", 1)[1])
        raw = entry * (1 - p / 100.0)
        why = "%s%% under the entry" % ("%g" % p)
    elif rule.startswith("atr:"):
        k = float(rule.split(":", 1)[1])
        if not atr_bars:
            raise Refused("an ATR stop needs the session's bars (Yahoo, or --offline FILE)")
        a, n = M.atr(atr_bars, 14)
        raw = entry - k * a
        why = "%g x ATR(%d bars%s) %.2f under the entry" % (k, n, "" if n >= 14 else ", all there were", a)
    else:
        raise Refused("unknown stop rule %r (or-mid, or-low, price:X, pct:X, atr:K)" % stop_rule)
    stop = M.round_down_tick(raw, tk)
    if stop >= entry:
        raise Refused("the stop %s is at or above the entry %s: for a long, the stop goes below" % (M.px(stop), M.px(entry)))
    risk = round(entry - stop, 2)
    if risk < entry * MIN_RISK_PCT / 100.0 or risk < MIN_RISK_TICKS * tk - 1e-9:
        raise Refused("risk %s a share is under %.2f%% of the price (or %d ticks): too tight to survive the spread"
                      % (M.px(risk), MIN_RISK_PCT, MIN_RISK_TICKS))
    tr = target_rule.upper()
    if tr.endswith("R"):
        r_mult = float(tr[:-1])
        target = M.round_half_tick(entry + r_mult * risk, tk)
        twhy = "%gR (%s times the risk)" % (r_mult, "one" if r_mult == 1 else "%g" % r_mult)
    elif tr.startswith("PRICE:"):
        target = M.round_half_tick(float(tr.split(":", 1)[1]), tk)
        r_mult = None
        twhy = "your price"
    else:
        raise Refused("unknown target %r (2R, 1R, 1.5R, price:X)" % target_rule)
    if target <= entry:
        raise Refused("the target %s is at or below the entry %s" % (M.px(target), M.px(entry)))
    rr = round((target - entry) / risk, 2)
    d = dt.date.fromisoformat(e["date"])
    fb = M.parse_hhmm(flat_by)
    ce = M.cont_end(d) or M.CONT_END
    special = M.is_special(d)
    if special:
        fb = min(fb, (dt.datetime.combine(d, ce) - dt.timedelta(minutes=10)).time())
    et = e.get("trigger_time") or e.get("entry_time")
    if et and M.parse_hhmm(et) >= fb:
        raise Refused("the entry at %s is at or after the flat-by time %s" % (et, M.hhmm(fb)))
    return {
        "symbol": e["symbol"], "exchange": e.get("exchange", "NSE"), "date": e["date"], "side": "buy",
        "setup": e.get("setup", "orb"), "interval": e.get("interval", "5m"),
        "entry": round(entry, 2), "entry_time": et, "entry_bar": e.get("bar_index"),
        "or_high": oh, "or_low": ol, "or_minutes": e.get("or_minutes", 15),
        "stop": stop, "stop_rule": stop_rule, "stop_why": why,
        "target": target, "target_rule": target_rule, "target_r": r_mult, "target_why": twhy,
        "risk_per_share": risk, "risk_pct": round(risk / entry * 100, 2), "reward_risk": rr,
        "tick": tk, "flat_by": M.hhmm(fb), "special_session": special,
    }


def render(p):
    d = dt.date.fromisoformat(p["date"])
    lines = ["Exit plan: %s long, %s, %s on %s bars" % (
        p["symbol"], M.day_label(d), "opening-range breakout" if p["setup"] == "orb" else "level setup",
        p["interval"].replace("m", "-minute"))]
    et = p.get("entry_time")
    lines.append("  Entry         %s%s" % (M.inr(p["entry"]), (" at %s IST" % M.clock(M.parse_hhmm(et))) +
                                         (" (bar %s)" % p["entry_bar"] if p.get("entry_bar") else "") if et else ""))
    lines.append("  Stop          %s  %s" % (M.inr(p["stop"]), p["stop_why"]))
    lines.append("  Target        %s  %s" % (M.inr(p["target"]), p["target_why"]))
    lines.append("  Risk a share  %s (%.2f%% of the entry)" % (M.inr(p["risk_per_share"]), p["risk_pct"]))
    lines.append("  Reward:risk   %s" % ("%g" % p["reward_risk"]))
    lines.append("  Flat by       %s IST, win or lose: out before the 3:15 PM closing auction, no overnight hold"
                 % p["flat_by"])
    lines.append("A stop is a plan, not a guarantee: a gap, a circuit or a fast market can fill past it.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("plan")
    q.add_argument("--stop", default="or-mid")
    q.add_argument("--target", default="2R")
    q.add_argument("--from", dest="src")
    q.add_argument("--symbol")
    q.add_argument("--entry", type=float)
    q.add_argument("--or-high", type=float)
    q.add_argument("--or-low", type=float)
    q.add_argument("--entry-time")
    q.add_argument("--date")
    q.add_argument("--setup")
    q.add_argument("--flat-by")
    q.add_argument("--tick", type=float, help="override the tick size")
    q.add_argument("--offline")
    q.add_argument("--now")
    q.add_argument("--write", action="store_true")
    q.add_argument("--json", action="store_true")
    q.add_argument("--config")
    s = sub.add_parser("show")
    s.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "show":
        p = M.read_json(M.tpath("plan.json"))
        if not p:
            print("No trader/plan.json yet. Run exit.py plan --write.")
            return 1
        print(json.dumps(p, indent=2) if a.json else render(p))
        return 0
    cfg = M.load_config(a.config)
    now = M.now_ist(a.now)
    e = {}
    if not a.symbol:
        e = M.read_json(a.src or M.tpath("entry.json"), {}) or {}
        if not e:
            print("No trader/entry.json. Run /in-trader-entry first, or pass --symbol and --entry.")
            return 1
        if e.get("status") != "triggered" and a.entry is None:
            print("REFUSED: the entry in trader/entry.json has not triggered (%s). Pass --entry PRICE to plan ahead."
                  % e.get("status"))
            return 1
    else:
        e = {"symbol": M.norm_symbol(a.symbol), "date": a.date or now.date().isoformat(),
             "setup": a.setup or ("orb" if a.or_high else "level"), "interval": "5m",
             "exchange": M.exchange_of(a.symbol, cfg.get("exchange", "NSE"))}
    for k, v in (("entry", a.entry), ("or_high", a.or_high), ("or_low", a.or_low), ("entry_time", a.entry_time)):
        if v is not None:
            e[k] = v
    if "entry" not in e:
        print("REFUSED: no entry price.")
        return 1
    bars = None
    if a.stop.lower().startswith("atr:"):
        try:
            s = M.fetch_chart(e["symbol"], "1d", "5m", offline=a.offline, exchange=e.get("exchange", "NSE"))
            d = dt.date.fromisoformat(e["date"])
            allb = M.session_bars(M.bars_from_series(s), d)
            cut = e.get("trigger_time") or e.get("entry_time")
            if cut:
                ct = M.ist_dt(d, M.parse_hhmm(cut))
                allb = [b for b in allb if b["t"] + dt.timedelta(minutes=5) <= ct]
            bars = allb
        except M.DataError as ex:
            print("REFUSED: %s" % ex)
            return 1
    try:
        p = make_plan(e, a.stop, a.target, a.flat_by or cfg.get("flat_by", "15:05"), bars, a.tick)
    except Refused as ex:
        print("REFUSED: %s." % ex)
        return 1
    if M.parse_hhmm(p["flat_by"]) > M.parse_hhmm("15:10") and not p["special_session"]:
        p["warning"] = "flat-by after 15:10: stop-loss orders are not accepted in the 15:15 closing auction"
    mrr = cfg.get("min_reward_risk", 1.0)
    if p["reward_risk"] < mrr:
        p["note"] = "reward:risk %.2f is under your minimum %g: in-trader-risk will block it" % (p["reward_risk"], mrr)
    print(json.dumps(p, indent=2) if a.json else render(p))
    for k in ("warning", "note"):
        if k in p and not a.json:
            print("NOTE: " + p[k])
    if a.write:
        M.write_json(M.tpath("plan.json"), p)
        if not a.json:
            print("Saved trader/plan.json. Next: /in-trader-timemachine, then /in-trader-budget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
