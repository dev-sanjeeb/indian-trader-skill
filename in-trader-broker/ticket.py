#!/usr/bin/env python3
"""in-trader-broker: tickets, your yes, and the trade log. It never talks to a broker.

  ticket.py show                                   every ticket, READY or not
  ticket.py approve --index 1 --reply "yes"        records your yes, word for word
  ticket.py paper --index 1 [--price 1234.60]      PAPER mode: simulate the fill locally
  ticket.py result --index 1 --status placed --order-id 2611020001 --filled-qty 39 --filled-price 1234.60
  ticket.py fill --symbol RELIANCE --side sell --qty 39 --price 1245.90
  ticket.py flatten --symbol RELIANCE --qty 39     a MARKET sell ticket to get flat
  ticket.py log

Three gates for every order that reaches Zerodha: in-trader-risk passed this
exact order today, you typed an explicit yes for this one order, and you clicked
Allow once on Claude's own card for the Kite place_order tool. Zerodha has no
paper account, so "paper": true (the default) means Claude does NOT call Kite at
all: `ticket.py paper` records a simulated fill in trader/ instead.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inmarket as M  # noqa: E402

YES = {"yes", "y", "yes place it", "place it", "yes place the order", "yes go ahead", "confirm", "confirmed",
       "haan", "ha", "haan ji", "yes please", "go ahead"}
NOT_YES = ("all", "every", "both", "sure", "ok", "okay", "fine", "whatever", "maybe", "later", "no", "nahi", "don't",
           "dont", "wait", "cancel")


def state_path():
    return M.tpath("state", "broker.json")


def load_state():
    return M.read_json(state_path(), {"log": []}) or {"log": []}


def save_state(st):
    M.write_json(state_path(), st)


def load_portfolio(cfg):
    p = M.read_json(M.tpath("portfolio.json"))
    if not p:
        p = {"cash_inr": float(cfg["capital_inr"]), "positions": {}, "paper": bool(cfg.get("paper", True))}
    return p


def save_portfolio(p):
    M.write_json(M.tpath("portfolio.json"), p)


def log_event(st, now, **kw):
    e = {"date": now.date().isoformat(), "time": now.strftime("%H:%M:%S")}
    e.update(kw)
    st["log"].append(e)
    return e


def verdict_for(o, risk, date):
    import importlib.util
    fp = None
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        spec_path = os.path.join(os.path.dirname(here), "in-trader-risk", "check.py")
        if os.path.exists(spec_path):
            spec = importlib.util.spec_from_file_location("_risk", spec_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fp = mod.fingerprint(o.get("kite") or {}, date)
    except Exception:
        fp = None
    if fp is None:
        import hashlib
        fp = hashlib.sha256((date + json.dumps(o.get("kite") or {}, sort_keys=True)).encode()).hexdigest()[:16]
    if not risk or risk.get("date") != date:
        return None, fp
    for v in risk.get("verdicts", []):
        if v.get("id") == o.get("id") and v.get("fingerprint") == fp:
            return v, fp
    return None, fp


def parent_filled(o, st, date):
    if not o.get("after"):
        return True
    for e in st["log"]:
        if e.get("date") == date and e.get("order") == o["after"] and e.get("event") in ("placed", "paper_fill") \
                and (e.get("filled_qty") or 0) > 0:
            return True
    return False


def status_of(o, risk, st, date):
    v, fp = verdict_for(o, risk, date)
    if v is None:
        return "NOT READY", "not checked by in-trader-risk today in this exact form: run /in-trader-risk", fp
    if v["verdict"] != "PASS":
        return "BLOCKED", "; ".join(v["reasons"]), fp
    if not parent_filled(o, st, date):
        return "WAITING", "place it only after order %s fills" % o["after"], fp
    done = [e for e in st["log"] if e.get("date") == date and e.get("order") == o["id"] and e.get("fingerprint") == fp
            and e.get("event") in ("placed", "paper_fill", "denied")]
    if done:
        return "DONE", "already %s" % done[-1]["event"].replace("_", " "), fp
    yes = [e for e in st["log"] if e.get("date") == date and e.get("order") == o["id"] and e.get("fingerprint") == fp
           and e.get("event") == "yes"]
    if yes:
        return "APPROVED", "your yes is recorded: %r" % yes[-1]["reply"], fp
    return "READY", "in-trader-risk PASS, waiting for your yes", fp


def describe(k):
    t = k.get("order_type")
    s = "%s %d %s on %s, %s, %s" % (k["transaction_type"], k["quantity"], k["tradingsymbol"], k["exchange"],
                                   {"MARKET": "market", "LIMIT": "limit %s" % k.get("price"),
                                    "SL-M": "stop-loss market, trigger %s" % k.get("trigger_price"),
                                    "SL": "stop-loss limit, trigger %s, limit %s" % (k.get("trigger_price"), k.get("price"))}.get(t, t),
                                   {"MIS": "intraday (MIS)", "CNC": "delivery (CNC)"}.get(k.get("product"), k.get("product")))
    return s + ", good for today"


def cmd_show(a, cfg, now):
    doc = M.read_json(M.tpath("orders.json"))
    if not doc or not doc.get("orders"):
        print("No orders in trader/orders.json.")
        return 1
    risk = M.read_json(M.tpath("state", "risk.json"))
    st = load_state()
    date = now.date().isoformat()
    paper = bool(cfg.get("paper", True))
    n = len(doc["orders"])
    ready = 0
    for i, o in enumerate(doc["orders"], 1):
        k = o["kite"]
        stt, why, fp = status_of(o, risk, st, date)
        ready += stt in ("READY", "APPROVED")
        pl = o.get("plan") or {}
        print("ORDER %d of %d, %s, %s" % (i, n, "PAPER (simulated, Kite is not called)" if paper else "LIVE account",
                                          cfg.get("broker", "zerodha").title()))
        print("  " + describe(k))
        if o.get("role") == "entry" and pl:
            print("  then: protective stop %s (order %s), target %s watched by alerts" % (
                M.px(pl["stop"]), int(o["id"]) + 1, M.px(pl["target"])))
            print("  max loss about %s if the stop fills at %s, charges included (it can fill worse in a fast market)"
                  % (M.inr(pl.get("max_loss") or 0), M.px(pl["stop"])))
        if o.get("why"):
            print("  why: " + o["why"])
        print("  %s: %s" % (stt, why))
        if stt in ("READY", "APPROVED"):
            if paper:
                print("  On your yes: ticket.py paper --index %d records a simulated fill. No order goes to Zerodha." % i)
            else:
                print("  On your yes, Claude calls the Kite place_order tool with exactly:")
                print("    " + json.dumps(k))
        print("")
    return 0 if ready else 1


def reply_is_yes(reply, k):
    r = reply.strip().lower()
    r = re.sub(r"[^\w\s&-]", " ", r)
    r = re.sub(r"\s+", " ", r).strip()
    words = r.split()
    if not words:
        return False, "empty reply"
    if any(w in words for w in NOT_YES) or "yes to all" in r:
        return False, "not an explicit yes for this one order"
    nums = [int(x) for x in re.findall(r"\b\d+\b", r)]
    if nums and k["quantity"] not in nums and not all(n == 1 for n in nums):
        return False, "the reply names a different quantity (%s) than the ticket (%d)" % (nums, k["quantity"])
    syms = [w.upper() for w in words if w.isalpha() and len(w) >= 3 and w not in ("yes", "place", "the", "order", "buy",
            "sell", "it", "please", "go", "ahead", "shares", "haan", "ji", "confirm", "confirmed", "of", "and")]
    if syms and k["tradingsymbol"].upper() not in syms and not any(s in k["tradingsymbol"] for s in syms):
        return False, "the reply names %s, but the ticket is %s" % (", ".join(syms), k["tradingsymbol"])
    if r in YES or words[0] in ("yes", "haan", "confirm", "confirmed"):
        return True, "explicit yes"
    return False, "not an explicit yes (reply yes or no)"


def get_order(idx):
    doc = M.read_json(M.tpath("orders.json")) or {}
    os_ = doc.get("orders") or []
    if not 1 <= idx <= len(os_):
        raise SystemExit("No order %d in trader/orders.json." % idx)
    return os_[idx - 1]


def cmd_approve(a, cfg, now):
    o = get_order(a.index)
    st = load_state()
    date = now.date().isoformat()
    stt, why, fp = status_of(o, M.read_json(M.tpath("state", "risk.json")), st, date)
    if stt != "READY":
        print("Not recorded: order %d is %s (%s)." % (a.index, stt, why))
        return 1
    ok, why = reply_is_yes(a.reply, o["kite"])
    if not ok:
        log_event(st, now, event="not_yes", order=o["id"], fingerprint=fp, reply=a.reply)
        save_state(st)
        print("Not recorded: %r (%s). Ask again: \"Place this order? Reply yes or no.\"" % (a.reply, why))
        return 1
    log_event(st, now, event="yes", order=o["id"], fingerprint=fp, reply=a.reply, symbol=o["kite"]["tradingsymbol"])
    save_state(st)
    if cfg.get("paper", True):
        print("Recorded your yes for order %d. PAPER mode: run ticket.py paper --index %d (Kite is not called)."
              % (a.index, a.index))
    else:
        print("Recorded your yes for order %d. Claude may now call Kite place_order with exactly the ticket's JSON;"
              " Claude's Allow once / Deny card asks you once more." % a.index)
    return 0


def apply_fill(p, sym, side, qty, price):
    pos = p.setdefault("positions", {}).get(sym, {"qty": 0, "avg": 0.0})
    if side == "buy":
        newq = pos["qty"] + qty
        pos["avg"] = round((pos["qty"] * pos["avg"] + qty * price) / newq, 4) if newq else 0.0
        pos["qty"] = newq
        p["cash_inr"] = round(p["cash_inr"] - qty * price, 2)
    else:
        pos["qty"] = pos["qty"] - qty
        p["cash_inr"] = round(p["cash_inr"] + qty * price, 2)
    if pos["qty"] == 0:
        p["positions"].pop(sym, None)
    else:
        p["positions"][sym] = pos
    return p


def max_loss_of(o):
    return (o.get("plan") or {}).get("max_loss") if o.get("role") == "entry" else None


def cmd_paper(a, cfg, now):
    if not cfg.get("paper", True):
        print("Your config is LIVE (\"paper\": false). Paper fills are only for paper mode.")
        return 1
    o = get_order(a.index)
    st = load_state()
    date = now.date().isoformat()
    stt, why, fp = status_of(o, M.read_json(M.tpath("state", "risk.json")), st, date)
    if stt != "APPROVED":
        print("Not filled: order %d is %s (%s). It needs a PASS and your recorded yes." % (a.index, stt, why))
        return 1
    k = o["kite"]
    price = a.price
    if price is None:
        if k["order_type"] == "LIMIT":
            price = float(k["price"])
        elif k["order_type"] in ("SL", "SL-M"):
            print("A paper stop rests until the price reaches %s: record it with ticket.py result --status placed, "
                  "then ticket.py fill when the alert rings." % k.get("trigger_price"))
            log_event(st, now, event="paper_fill", order=o["id"], fingerprint=fp, symbol=k["tradingsymbol"],
                      side=k["transaction_type"].lower(), role=o.get("role"), filled_qty=0, resting=True)
            save_state(st)
            return 0
        else:
            pr = (M.read_json(M.tpath("prices.json"), {}) or {}).get("prices", {}).get(k["tradingsymbol"])
            price = float(pr["price"] if isinstance(pr, dict) else pr) if pr else float((o.get("plan") or {}).get("entry"))
    p = apply_fill(load_portfolio(cfg), k["tradingsymbol"], k["transaction_type"].lower(), k["quantity"], price)
    save_portfolio(p)
    log_event(st, now, event="paper_fill", order=o["id"], fingerprint=fp, symbol=k["tradingsymbol"],
              side=k["transaction_type"].lower(), role=o.get("role"), filled_qty=k["quantity"], price=price,
              max_loss=max_loss_of(o))
    log_event(st, now, event="placed", order=o["id"], fingerprint=fp, symbol=k["tradingsymbol"], role=o.get("role"),
              side=k["transaction_type"].lower(), filled_qty=k["quantity"], price=price, max_loss=max_loss_of(o), paper=True)
    save_state(st)
    print("PAPER fill recorded: %s %d %s at %s. Cash now %s." % (k["transaction_type"], k["quantity"],
          k["tradingsymbol"], M.px(price), M.inr(p["cash_inr"])))
    return 0


def cmd_result(a, cfg, now):
    o = get_order(a.index)
    st = load_state()
    date = now.date().isoformat()
    stt, why, fp = status_of(o, M.read_json(M.tpath("state", "risk.json")), st, date)
    if a.status == "placed" and stt != "APPROVED":
        print("Not recorded: order %d is %s (%s). Placing needs a PASS and your recorded yes." % (a.index, stt, why))
        return 1
    k = o["kite"]
    e = log_event(st, now, event=a.status, order=o["id"], fingerprint=fp, symbol=k["tradingsymbol"], role=o.get("role"),
                  side=k["transaction_type"].lower(), order_id=a.order_id, filled_qty=a.filled_qty or 0,
                  price=a.filled_price, note=a.note, max_loss=max_loss_of(o) if a.status == "placed" else None)
    if a.status == "placed" and a.filled_qty and a.filled_price:
        save_portfolio(apply_fill(load_portfolio(cfg), k["tradingsymbol"], e["side"], a.filled_qty, a.filled_price))
    save_state(st)
    print("Recorded: order %d %s%s." % (a.index, a.status, (" (%d filled at %s)" % (a.filled_qty, a.filled_price))
                                         if a.filled_qty and a.filled_price else ""))
    if a.status == "failed":
        print("A failed order is not retried without a new risk check and a new yes.")
    return 0


def cmd_fill(a, cfg, now):
    st = load_state()
    sym = M.norm_symbol(a.symbol)
    p = apply_fill(load_portfolio(cfg), sym, a.side, a.qty, a.price)
    save_portfolio(p)
    log_event(st, now, event="fill", symbol=sym, side=a.side, filled_qty=a.qty, price=a.price, note=a.note)
    save_state(st)
    print("Recorded fill: %s %d %s at %s. Holding %d. Cash %s." % (a.side, a.qty, sym, M.px(a.price),
          (p["positions"].get(sym) or {}).get("qty", 0), M.inr(p["cash_inr"])))
    return 0


def cmd_flatten(a, cfg, now):
    sym = M.norm_symbol(a.symbol)
    p = load_portfolio(cfg)
    held = (p.get("positions", {}).get(sym) or {}).get("qty", 0)
    qty = a.qty if a.qty is not None else held
    if qty <= 0:
        print("Nothing to flatten in %s (holding %d per trader/portfolio.json; check Kite get_positions)." % (sym, held))
        return 1
    k = {"variety": "regular", "exchange": a.exchange or cfg.get("exchange", "NSE"), "tradingsymbol": sym,
         "transaction_type": "SELL", "quantity": int(qty), "product": cfg.get("product", "MIS"),
         "order_type": "MARKET", "validity": "DAY", "tag": "intrader"}
    doc = {"as_of": now.strftime("%Y-%m-%d %H:%M"), "source": "in-trader-broker flatten", "paper": bool(cfg.get("paper", True)),
           "orders": [{"id": 1, "role": "exit", "kite": k,
                       "why": "flat by %s: close %d %s before the closing auction" % (cfg.get("flat_by", "15:05"), qty, sym)}]}
    M.write_json(M.tpath("orders.json"), doc)
    print("Wrote a MARKET sell for %d %s to trader/orders.json. Cancel the open SL-M stop for these shares first "
          "(Kite get_orders, then cancel_order), or both can fill. Next: /in-trader-risk, then your yes." % (qty, sym))
    return 0


def cmd_log(a, cfg, now):
    st = load_state()
    date = a.date or now.date().isoformat()
    rows = [e for e in st["log"] if e.get("date") == date]
    if not rows:
        print("Nothing logged on %s." % date)
        return 1
    for e in rows:
        print("%s %-10s %s" % (e["time"], e["event"], " ".join("%s=%s" % (k, v) for k, v in e.items()
              if k not in ("date", "time", "event", "fingerprint") and v not in (None, ""))))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--now")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    q = sub.add_parser("approve")
    q.add_argument("--index", type=int, required=True)
    q.add_argument("--reply", required=True)
    q = sub.add_parser("paper")
    q.add_argument("--index", type=int, required=True)
    q.add_argument("--price", type=float)
    q = sub.add_parser("result")
    q.add_argument("--index", type=int, required=True)
    q.add_argument("--status", choices=["placed", "denied", "failed"], required=True)
    q.add_argument("--order-id")
    q.add_argument("--filled-qty", type=int)
    q.add_argument("--filled-price", type=float)
    q.add_argument("--note")
    q = sub.add_parser("fill")
    q.add_argument("--symbol", required=True)
    q.add_argument("--side", choices=["buy", "sell"], required=True)
    q.add_argument("--qty", type=int, required=True)
    q.add_argument("--price", type=float, required=True)
    q.add_argument("--note")
    q = sub.add_parser("flatten")
    q.add_argument("--symbol", required=True)
    q.add_argument("--qty", type=int)
    q.add_argument("--exchange")
    q = sub.add_parser("log")
    q.add_argument("--date")
    a = ap.parse_args(argv)
    cfg = M.load_config(a.config)
    now = M.now_ist(a.now)
    return {"show": cmd_show, "approve": cmd_approve, "paper": cmd_paper, "result": cmd_result, "fill": cmd_fill,
            "flatten": cmd_flatten, "log": cmd_log}[a.cmd](a, cfg, now)


if __name__ == "__main__":
    sys.exit(main())
