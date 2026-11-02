#!/usr/bin/env python3
"""in-trader-risk: the gate between a proposed order and the broker.

  check.py                             trader/orders.json; writes trader/state/risk.json
  check.py --json
  check.py --no-write                  look without recording
  check.py --now "2026-11-02 09:36"    pin the clock (IST)

PASS or BLOCK for every order, with the reason. A BLOCK is final for that exact
order. An exit (a sell that only reduces what you hold, or the protective stop
for an entry in the same file) is never blocked by a day limit or the entry
window: getting out must always be possible.
"""

import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inmarket as M  # noqa: E402

FRESH_MIN = 15
DERIV_RE = re.compile(r"\d+(CE|PE)$|\d{2}[A-Z]{3}FUT$")  # NIFTY26N0524000CE, RELIANCE26NOVFUT
SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")
ORDER_TYPES = {"MARKET", "LIMIT", "SL", "SL-M"}
PRODUCTS = {"MIS", "CNC", "NRML", "MTF"}


def fingerprint(kite, date):
    return hashlib.sha256((date + json.dumps(kite, sort_keys=True)).encode()).hexdigest()[:16]


def load_surveillance(cfg):
    out = {M.norm_symbol(s): "on your surveillance list" for s in cfg.get("surveillance") or []}
    doc = M.read_json(M.tpath("surveillance.json"), {}) or {}
    for s, why in (doc.get("symbols") or {}).items():
        out.setdefault(s, why)
    return out, doc.get("as_of")


def today_log(state, date):
    return [x for x in (state or {}).get("log", []) if x.get("date") == date]


def check(orders_doc, cfg, now, portfolio=None, prices=None, broker_state=None):
    """Pure. -> (results, summary)."""
    date = now.date().isoformat()
    orders = orders_doc.get("orders", [])
    cap = float(cfg["capital_inr"])
    buffer_ = cap * cfg.get("cash_buffer_pct", 10) / 100.0
    port = portfolio or {"cash_inr": cap, "positions": {}}
    cash = float(port.get("cash_inr", cap))
    held = {k: int(v.get("qty", v) if isinstance(v, dict) else v) for k, v in (port.get("positions") or {}).items()}
    log = today_log(broker_state, date)
    placed_entries = [x for x in log if x.get("event") == "placed" and x.get("role") == "entry"]
    trades_today = len(placed_entries)
    risk_today = sum(float(x.get("max_loss") or 0) for x in placed_entries)
    orders_today = len([x for x in log if x.get("event") == "placed"])
    surv, surv_asof = load_surveillance(cfg)
    s = M.session(now.date())
    sess_open = s is not None and M.ist_dt(now.date(), s[0]) <= now < M.ist_dt(now.date(), M.cont_end(now.date()) or s[1])
    nb = M.parse_hhmm(cfg["no_entries_before"]) if cfg.get("no_entries_before") else None
    na = M.parse_hhmm(cfg["no_entries_after"]) if cfg.get("no_entries_after") else None
    if s and M.is_special(now.date()):
        nb, na = s[0], M.cont_end(now.date())
    by_id = {o.get("id"): o for o in orders}
    seen = set()
    results = []
    passed_entries = []
    for o in orders:
        k = o.get("kite") or {}
        reasons, warns = [], []
        sym = str(k.get("tradingsymbol", "")).upper()
        side = str(k.get("transaction_type", "")).upper()
        qty = k.get("quantity")
        ot = str(k.get("order_type", "")).upper()
        role = o.get("role") or ("entry" if side == "BUY" else "exit")
        ex = str(k.get("exchange", "")).upper()
        # ---- format
        if not sym or not SYMBOL_RE.match(sym):
            reasons.append("format: no valid tradingsymbol")
        if side not in ("BUY", "SELL"):
            reasons.append("format: transaction_type must be BUY or SELL")
        if not isinstance(qty, int) or qty <= 0:
            reasons.append("format: quantity must be a whole number of shares above zero")
            qty = 0
        if ot not in ORDER_TYPES:
            reasons.append("format: order_type must be MARKET, LIMIT, SL or SL-M")
        if ot in ("LIMIT", "SL") and not k.get("price"):
            reasons.append("format: a %s order needs a price" % ot)
        if ot in ("SL", "SL-M") and not k.get("trigger_price"):
            reasons.append("format: a %s order needs a trigger_price" % ot)
        if str(k.get("product", "")).upper() not in PRODUCTS:
            reasons.append("format: product must be MIS (intraday) or CNC (delivery)")
        if k.get("validity", "DAY") not in ("DAY", "IOC"):
            reasons.append("format: validity must be DAY or IOC")
        for f in ("price", "trigger_price"):
            v = k.get(f)
            if v and not M.on_tick(float(v), M.tick_size(float(v))):
                reasons.append("format: %s %s is not on the NSE tick (%s) for that price" % (f, v, M.px(M.tick_size(float(v)))))
        # ---- asset
        if ex not in ("NSE", "BSE"):
            reasons.append("asset: %s is not the NSE/BSE cash market (F&O, commodities and currency are off)" % (ex or "no exchange"))
        if DERIV_RE.search(sym) and not (cfg.get("allow_options") or cfg.get("allow_futures")):
            reasons.append("asset: %s looks like a futures or options contract; allow_options/allow_futures are off" % sym)
        if k.get("product") == "NRML" and not cfg.get("allow_futures"):
            reasons.append("asset: NRML is the F&O carry-forward product")
        if k.get("product") == "MTF" and not cfg.get("allow_margin"):
            reasons.append("asset: MTF is margin trading funding; allow_margin is off")
        # ---- role
        is_exit = False
        if side == "SELL":
            parent = by_id.get(o.get("after"))
            if role == "stop" and parent and (parent.get("kite") or {}).get("tradingsymbol") == k.get("tradingsymbol"):
                pq = (parent.get("kite") or {}).get("quantity") or 0
                if qty > pq:
                    reasons.append("stop: protects %d shares but order %s buys only %d" % (qty, parent.get("id"), pq))
                is_exit = True
            elif qty <= held.get(sym, 0):
                is_exit = True
            elif not cfg.get("allow_short"):
                reasons.append("short: selling %d %s but you hold %d; allow_short is off" % (qty, sym, held.get(sym, 0)))
        pl = o.get("plan") or {}
        price_used = None
        info = {}
        if not is_exit and side == "BUY":
            # the price risk is measured from
            if ot in ("LIMIT", "SL") and k.get("price"):
                price_used, pfrom = float(k["price"]), "the limit price"
            else:
                price_used, pfrom = float(pl.get("entry") or 0), "the plan's entry"
                fp = None
                pr = (prices or {}).get("prices", {}).get(sym)
                if pr is not None:
                    asof = (prices or {}).get("as_of")
                    if isinstance(pr, dict):
                        asof, pr = pr.get("as_of", asof), pr.get("price")
                    try:
                        import datetime as _d
                        t = _d.datetime.fromisoformat(str(asof).replace("Z", "+00:00"))
                        t = t if t.tzinfo else t.replace(tzinfo=M.IST)
                        age = (now - t).total_seconds() / 60
                        if 0 <= age <= FRESH_MIN:
                            fp = float(pr)
                        else:
                            warns.append("the quote in trader/prices.json is %.0f minutes old: not used" % age)
                    except (TypeError, ValueError):
                        pass
                if fp and fp > price_used:
                    price_used, pfrom = fp, "a fresh quote, above the plan's entry"
                if not price_used and fp:
                    price_used, pfrom = fp, "a fresh quote"
            if not price_used:
                reasons.append("price: no entry price to measure the risk from (no plan entry, no fresh quote)")
                price_used = 0.0
            info["entry_used"] = round(price_used, 2)
            info["entry_from"] = pfrom
            value = qty * price_used
            if sym in [M.norm_symbol(b) for b in cfg.get("blocked") or []]:
                reasons.append("blocked: %s is on your blocked list" % sym)
            if sym in surv:
                reasons.append("surveillance: %s is %s: intraday is restricted or risky there" % (sym, surv[sym]))
            if value < float(cfg.get("min_order_inr", 0)):
                reasons.append("size: %s is under your %s minimum order" % (M.inr(value), M.inr(cfg["min_order_inr"], False)))
            if value > float(cfg.get("max_order_inr", 1e15)) + 1e-6:
                reasons.append("size: %s is over your %s maximum order" % (M.inr(value), M.inr(cfg["max_order_inr"], False)))
            pos_val = (held.get(sym, 0) + qty) * price_used
            if pos_val > cap * cfg.get("max_position_pct", 50) / 100.0 + 1e-6:
                reasons.append("position: %s would be %s, over %g%% of your %s capital" % (
                    sym, M.inr(pos_val), cfg.get("max_position_pct", 50), M.inr(cap, False)))
            lev = float(cfg.get("leverage", 1)) if cfg.get("allow_margin") else 1.0
            if value / lev > cash - buffer_ + 1e-6:
                reasons.append("cash: %s needs %s of cash, you have %s after the %s buffer%s" % (
                    M.inr(value), M.inr(value / lev), M.inr(cash - buffer_), M.inr(buffer_, False),
                    "" if cfg.get("allow_margin") else " (margin is off)"))
            # stop
            stop_orders = [x for x in orders if x.get("role") == "stop" and x.get("after") == o.get("id")]
            stop = None
            if stop_orders:
                stop = float((stop_orders[0].get("kite") or {}).get("trigger_price") or 0) or None
            if stop is None and pl.get("stop"):
                stop = float(pl["stop"])
                warns.append("the stop lives only in the plan, not as an order: in-trader-broker places it after the fill")
            if stop is None and cfg.get("require_stop", True):
                reasons.append("stop: no stop, and require_stop is on")
            target = float(pl["target"]) if pl.get("target") else None
            if stop is not None and price_used:
                if stop >= price_used:
                    reasons.append("stop: %s is not below the entry %s" % (M.px(stop), M.px(price_used)))
                else:
                    risk = price_used - stop
                    ch = M.charges(qty * price_used, qty * stop, ex or "NSE", cfg.get("charges")) if cfg.get(
                        "include_charges_in_risk", True) else {"total": 0.0}
                    ml = qty * risk + ch["total"]
                    info.update(stop=stop, risk_per_share=round(risk, 2), max_loss=round(ml, 2), charges=ch["total"])
                    if ml > float(cfg["max_loss_per_trade_inr"]) + 1e-6:
                        reasons.append("loss: %d shares x %s risk a share + %s charges = %s at the stop, over your %s max loss per trade"
                                       % (qty, M.px(risk), M.px(ch["total"]), M.inr(ml), M.inr(cfg["max_loss_per_trade_inr"], False)))
                    if target is not None:
                        rr = (target - price_used) / risk
                        info.update(target=target, reward_risk=round(rr, 2))
                        if rr < cfg.get("min_reward_risk", 1.0) - 1e-9:
                            reasons.append("reward:risk: (%s - %s) / %s = %.2f, under your minimum %g" % (
                                M.px(target), M.px(price_used), M.px(risk), rr, cfg.get("min_reward_risk", 1.0)))
                    day_r = risk_today + sum(x["max_loss"] for x in passed_entries) + ml
                    if day_r > float(cfg["max_daily_loss_inr"]) + 1e-6:
                        reasons.append("daily loss: today's max losses at the stops would be %s, over your %s daily limit" % (
                            M.inr(day_r), M.inr(cfg["max_daily_loss_inr"], False)))
            n_tr = trades_today + len(passed_entries)
            if n_tr >= int(cfg.get("max_trades_per_day", 3)):
                reasons.append("trades: %d of %d trades already today" % (n_tr, cfg.get("max_trades_per_day", 3)))
            if not s:
                reasons.append("window: the market is closed today (%s)" % (M.closed_reason(now.date()) or "closed"))
            elif not sess_open:
                reasons.append("window: outside the session's continuous trading (%s to %s IST)" % (
                    M.hhmm(s[0]), M.hhmm(M.cont_end(now.date()))))
            else:
                if nb and now.time() < nb:
                    reasons.append("window: no new entries before %s IST" % M.hhmm(nb))
                if na and now.time() > na:
                    reasons.append("window: no new entries after %s IST" % M.hhmm(na))
            if (sym, side) in seen:
                reasons.append("duplicate: %s %s twice in this batch" % (side, sym))
            if any(x.get("symbol") == sym and x.get("role") == "entry" for x in placed_entries):
                reasons.append("duplicate: an entry in %s was already placed today" % sym)
            if orders_today + len(passed_entries) >= int(cfg.get("max_orders_per_day", 10)):
                reasons.append("daily limit: %d orders already today" % orders_today)
            if str(k.get("product", "")).upper() == "CNC":
                warns.append("product CNC is a delivery buy: it is not squared off by the broker at the close")
            info["today_before"] = {"trades": trades_today + len(passed_entries),
                                    "risk": round(risk_today + sum(x["max_loss"] for x in passed_entries), 2)}
        if is_exit:
            # exits: format, asset and short only. Everything else is a warning.
            if not s or not sess_open:
                warns.append("the market is not in continuous trading now: an exit may wait or be rejected")
            if ot in ("SL", "SL-M") and s and now.time() >= M.parse_hhmm("15:15") and not M.is_special(now.date()):
                warns.append("stop-loss orders are not accepted in the closing auction (from 15:15)")
        if not cfg.get("paper", True):
            warns.append("LIVE account: this is real money")
        verdict = "BLOCK" if reasons else "PASS"
        if verdict == "PASS" and side == "BUY" and not is_exit:
            passed_entries.append({"symbol": sym, "max_loss": info.get("max_loss", 0.0)})
            cash -= qty * (info.get("entry_used") or 0)
            held[sym] = held.get(sym, 0) + qty
        seen.add((sym, side))
        results.append({"id": o.get("id"), "role": "exit" if is_exit and role != "stop" else role,
                        "symbol": sym, "side": side, "qty": qty, "verdict": verdict, "reasons": reasons,
                        "warnings": warns, "fingerprint": fingerprint(k, date), "info": info})
    summ = {"date": date, "time": now.strftime("%H:%M"), "passed": sum(r["verdict"] == "PASS" for r in results),
            "blocked": sum(r["verdict"] == "BLOCK" for r in results), "cash_after": round(cash, 2),
            "paper": bool(cfg.get("paper", True)), "surveillance_as_of": surv_asof}
    return results, summ


def render(results, summ, cfg):
    L = []
    for r in results:
        i = r["info"]
        L.append("%-5s #%s %s %s %d shares, %s" % (r["verdict"], r["id"], r["side"].lower(), r["symbol"], r["qty"], r["role"]))
        if "max_loss" in i:
            L.append("          entry %s (%s), stop %s%s: risk %s a share" % (
                M.px(i["entry_used"]), i["entry_from"], M.px(i["stop"]),
                (", target %s" % M.px(i["target"])) if "target" in i else "", M.px(i["risk_per_share"])))
            L.append("          max loss %s incl. %s charges (limit %s)%s" % (
                M.inr(i["max_loss"]), M.px(i["charges"]), M.inr(cfg["max_loss_per_trade_inr"], False),
                (", reward:risk %.2f (min %g)" % (i["reward_risk"], cfg.get("min_reward_risk", 1))) if "reward_risk" in i else ""))
            tb = i["today_before"]
            L.append("          today before this: %d of %d trades, %s of %s daily loss" % (
                tb["trades"], cfg.get("max_trades_per_day", 3), M.inr(tb["risk"]), M.inr(cfg["max_daily_loss_inr"], False)))
        for x in r["reasons"]:
            L.append("        - " + x)
        for w in r["warnings"]:
            L.append("        ! " + w)
    L.append("")
    L.append("%d passed, %d blocked at %s %s IST. Cash after the passed orders: %s (%s account)." % (
        summ["passed"], summ["blocked"], summ["date"], summ["time"], M.inr(summ["cash_after"]),
        "paper" if summ["paper"] else "LIVE"))
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("orders", nargs="?")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--now")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    cfg = M.load_config(a.config)
    doc = M.read_json(a.orders or M.tpath("orders.json"))
    if not doc or not doc.get("orders"):
        print("No orders in trader/orders.json. Run /in-trader-budget first.")
        return 1
    now = M.now_ist(a.now)
    results, summ = check(doc, cfg, now, M.read_json(M.tpath("portfolio.json")), M.read_json(M.tpath("prices.json")),
                          M.read_json(M.tpath("state", "broker.json")))
    print(json.dumps({"results": results, "summary": summ}, indent=2) if a.json else render(results, summ, cfg))
    if not a.no_write:
        M.write_json(M.tpath("state", "risk.json"), {"date": summ["date"], "time": summ["time"], "verdicts": results})
    return 0 if summ["blocked"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
