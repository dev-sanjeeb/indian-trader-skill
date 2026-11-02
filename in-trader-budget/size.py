#!/usr/bin/env python3
"""in-trader-budget: size a day trade to your capital and your max loss per trade.

  size.py                          trader/plan.json + trader/config.json, print only
  size.py --write                  write trader/orders.json (entry + protective stop)
  size.py --limit --write          a LIMIT entry at the plan's entry price
  size.py --limit 1234.00 --json   a LIMIT entry at 1234.00

The size is the smallest of four limits: max loss (including Indian charges at
the stop), position cap, max order and cash after your buffer. Whole shares only.
It writes two Kite-shaped orders: a BUY (product MIS) and, to place only AFTER
the buy fills, a SELL SL-M at the stop. The target is watched by in-trader-alerts,
not left as a resting order: two open sells for the same shares can both fill
and leave you short. Nothing is placed here.
"""

import argparse
import datetime as dt
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inmarket as M  # noqa: E402

FRESH_MIN = 15


class Refused(Exception):
    pass


def fresh_price(sym, now, prices):
    if not prices:
        return None, None
    p = (prices.get("prices") or {}).get(sym)
    asof = prices.get("as_of")
    if isinstance(p, dict):
        asof = p.get("as_of", asof)
        p = p.get("price")
    if p is None or not asof:
        return None, None
    try:
        t = dt.datetime.fromisoformat(asof.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=M.IST)
    except ValueError:
        return None, None
    age = (now - t).total_seconds() / 60.0
    return (float(p), age) if 0 <= age <= FRESH_MIN else (None, age)


def size(plan, cfg, now, prices=None, portfolio=None, limit=None):
    """Pure. -> result dict with qty and the limits, or raises Refused."""
    sym = plan["symbol"]
    if plan.get("side", "buy") != "buy":
        raise Refused("long plans only: no short selling unless you turn it on and in-trader-risk allows it")
    if plan["date"] != now.date().isoformat():
        raise Refused("the plan is for %s, not today (%s): make a new one with in-trader-exit" % (plan["date"], now.date()))
    if sym in [M.norm_symbol(b) for b in cfg.get("blocked") or []]:
        raise Refused("%s is on your blocked list" % sym)
    stop, target = float(plan["stop"]), float(plan["target"])
    price_note = "the plan's entry"
    if limit is not None:
        entry = float(limit)
        price_note = "your limit price"
    else:
        entry = float(plan["entry"])
        fp, age = fresh_price(sym, now, prices)
        if fp is not None and fp > entry:
            entry, price_note = fp, "the fresh quote (%.0f min old), above the plan's entry" % age
    if stop >= entry:
        raise Refused("the stop %s is not below the entry %s" % (M.px(stop), M.px(entry)))
    if target <= entry:
        raise Refused("the target %s is not above the entry %s: the move already happened" % (M.px(target), M.px(entry)))
    risk = entry - stop
    rr = (target - entry) / risk
    if rr < cfg.get("min_reward_risk", 1.0) - 1e-9:
        raise Refused("reward:risk %.2f is under your minimum %g (entry %s, stop %s, target %s)"
                      % (rr, cfg.get("min_reward_risk", 1.0), M.px(entry), M.px(stop), M.px(target)))
    cap = float(cfg["capital_inr"])
    lev = float(cfg.get("leverage", 1)) if cfg.get("allow_margin") else 1.0
    buffer_ = cap * cfg.get("cash_buffer_pct", 10) / 100.0
    cash_avail = cap - buffer_
    if portfolio and portfolio.get("cash_inr") is not None:
        cash_avail = min(cash_avail, float(portfolio["cash_inr"]) - buffer_)
    ex = plan.get("exchange", cfg.get("exchange", "NSE"))
    ch_tab = cfg.get("charges") or {}
    max_loss = float(cfg["max_loss_per_trade_inr"])
    with_ch = cfg.get("include_charges_in_risk", True)

    def loss_at_stop(q):
        c = M.charges(q * entry, q * stop, ex, ch_tab)["total"] if with_ch else 0.0
        return q * risk + c
    q_loss = int(math.floor(max_loss / risk + 1e-9))
    while q_loss > 0 and loss_at_stop(q_loss) > max_loss + 1e-9:
        q_loss -= 1
    limits = [
        ("max loss", q_loss, "%s / %s risk a share%s" % (M.inr(max_loss), M.px(risk), ", charges included" if with_ch else "")),
        ("position cap", int(math.floor(cap * cfg.get("max_position_pct", 50) / 100.0 / entry + 1e-9)),
         "%g%% of %s = %s / %s" % (cfg.get("max_position_pct", 50), M.inr(cap, False),
                                   M.inr(cap * cfg.get("max_position_pct", 50) / 100.0, False), M.px(entry))),
        ("max order", int(math.floor(float(cfg.get("max_order_inr", 1e12)) / entry + 1e-9)),
         "%s / %s" % (M.inr(float(cfg.get("max_order_inr", 0)), False), M.px(entry))),
        ("cash", int(math.floor(max(0.0, cash_avail) * lev / entry + 1e-9)),
         "(%s minus the %s buffer)%s / %s" % (M.inr(cap, False), M.inr(buffer_, False),
                                               " x %gx" % lev if lev != 1 else "", M.px(entry))),
    ]
    qty = min(l[1] for l in limits)
    decider = [l for l in limits if l[1] == qty][0][0]
    if qty <= 0:
        if decider == "max loss":
            raise Refused("one share risks %s at the stop (with charges), more than your %s max loss per trade"
                          % (M.inr(loss_at_stop(1)), M.inr(max_loss, False)))
        raise Refused("zero shares fit the %s limit" % decider)
    value = qty * entry
    if value < float(cfg.get("min_order_inr", 0)):
        raise Refused("the order is %s, under your %s minimum" % (M.inr(value), M.inr(float(cfg["min_order_inr"]), False)))
    ch_stop = M.charges(qty * entry, qty * stop, ex, ch_tab)
    ch_tgt = M.charges(qty * entry, qty * target, ex, ch_tab)
    return {"symbol": sym, "exchange": ex, "qty": qty, "entry": round(entry, 2), "entry_from": price_note,
            "stop": stop, "target": target, "risk_per_share": round(risk, 2), "reward_risk": round(rr, 2),
            "value": round(value, 2), "limits": limits, "decided_by": decider,
            "loss_at_stop": round(qty * risk + ch_stop["total"], 2), "charges_at_stop": ch_stop,
            "gain_at_target_after_charges": None,  # never printed as a forecast; kept for the record
            "charges_at_target": ch_tgt, "leverage": lev, "capital": cap}


def orders_for(res, plan, cfg, limit=None):
    sym, ex, q = res["symbol"], res["exchange"], res["qty"]
    product = cfg.get("product", "MIS")
    entry = {"variety": "regular", "exchange": ex, "tradingsymbol": sym, "transaction_type": "BUY",
             "quantity": q, "product": product, "order_type": "LIMIT" if limit is not None else "MARKET",
             "validity": "DAY", "tag": "intrader"}
    if limit is not None:
        entry["price"] = round(float(limit), 2)
    stop_type = cfg.get("stop_order_type", "SL-M")
    stop = {"variety": "regular", "exchange": ex, "tradingsymbol": sym, "transaction_type": "SELL",
            "quantity": q, "product": product, "order_type": stop_type, "trigger_price": res["stop"],
            "validity": "DAY", "tag": "intrader"}
    if stop_type == "SL":
        tk = M.tick_size(res["stop"])
        stop["price"] = M.round_down_tick(res["stop"] * 0.995, tk)  # limit 0.5 % under the trigger
    why = ("%s on %s: %d shares, bound by your %s (%d x %s = %s at the stop, %s with charges)" % (
        "opening-range breakout" if plan.get("setup") == "orb" else "level setup", sym, q,
        {"max loss": "%s max loss per trade" % M.inr(float(cfg["max_loss_per_trade_inr"]), False),
         "position cap": "%g%% position cap" % cfg.get("max_position_pct", 50),
         "max order": "%s max order" % M.inr(float(cfg.get("max_order_inr", 0)), False),
         "cash": "cash after the buffer"}[res["decided_by"]],
        q, M.px(res["risk_per_share"]), M.inr(q * res["risk_per_share"]), M.inr(res["loss_at_stop"])))
    pl = {"entry": res["entry"], "stop": res["stop"], "target": res["target"], "risk_per_share": res["risk_per_share"],
          "max_loss": res["loss_at_stop"], "reward_risk": res["reward_risk"], "setup": plan.get("setup"),
          "entry_time": plan.get("entry_time"), "flat_by": plan.get("flat_by"), "date": plan.get("date")}
    return [
        {"id": 1, "role": "entry", "kite": entry, "why": why, "plan": pl},
        {"id": 2, "role": "stop", "after": 1, "kite": stop,
         "why": "protective stop for order 1: place it only after the buy fills, for the shares that filled",
         "plan": pl},
    ]


def render(res, plan):
    L = ["Sizing %s at %s (%s): stop %s, target %s, risk %s a share, reward:risk %.2f." % (
        res["symbol"], M.inr(res["entry"]), res["entry_from"], M.px(res["stop"]), M.px(res["target"]),
        M.px(res["risk_per_share"]), res["reward_risk"])]
    for name, q, how in res["limits"]:
        L.append("  %-13s %-58s %5d%s" % (name, how, q, "  <- decides it" if name == res["decided_by"] else ""))
    c = res["charges_at_stop"]
    L.append("%d shares = %s. If the stop fills at %s: %s on the shares + %s charges = %s." % (
        res["qty"], M.inr(res["value"]), M.px(res["stop"]), M.inr(res["qty"] * res["risk_per_share"]),
        M.inr(c["total"]), M.inr(res["loss_at_stop"])))
    L.append("  charges (round trip at the stop): brokerage %s, STT %s, exchange %s, SEBI %s, stamp %s, GST %s." % (
        M.px(c["brokerage"]), M.px(c["stt"]), M.px(c["exchange"]), M.px(c["sebi"]), M.px(c["stamp"]), M.px(c["gst"])))
    L.append("A stop is an order, not a promise: in a fast market, a gap or a circuit it can fill below the stop.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", nargs="?", const="plan")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--now")
    ap.add_argument("--config")
    ap.add_argument("--plan")
    a = ap.parse_args(argv)
    cfg = M.load_config(a.config)
    if not cfg["_from_file"]:
        print("NOTE: no trader/config.json yet, so the example limits are used (capital Rs 1,00,000, "
              "max loss Rs 500 a trade). Copy config.example.json to trader/config.json and set your own.")
    plan = M.read_json(a.plan or M.tpath("plan.json"))
    if not plan:
        print("No trader/plan.json. Run /in-trader-exit first.")
        return 1
    now = M.now_ist(a.now)
    limit = None
    if a.limit is not None:
        limit = float(plan["entry"]) if a.limit == "plan" else float(a.limit)
    try:
        res = size(plan, cfg, now, M.read_json(M.tpath("prices.json")), M.read_json(M.tpath("portfolio.json")), limit)
    except Refused as ex:
        print("REFUSED, no order: %s." % ex)
        return 1
    orders = orders_for(res, plan, cfg, limit)
    doc = {"as_of": now.strftime("%Y-%m-%d %H:%M"), "source": "in-trader-budget", "paper": bool(cfg.get("paper", True)),
           "orders": orders}
    if a.json:
        print(json.dumps({"sizing": res, "orders": doc}, indent=2, default=str))
    else:
        print(render(res, plan))
        print("Order 1 (entry): %s" % json.dumps(orders[0]["kite"]))
        print("Order 2 (stop, after order 1 fills): %s" % json.dumps(orders[1]["kite"]))
        print("Target %s: watched by /in-trader-alerts, sold by your yes (not a resting order)." % M.px(res["target"]))
    if a.write:
        M.write_json(M.tpath("orders.json"), doc)
        if not a.json:
            print("Wrote trader/orders.json. Nothing was placed. Next: /in-trader-risk.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
