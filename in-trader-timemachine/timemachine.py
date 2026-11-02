#!/usr/bin/env python3
"""in-trader-timemachine: replay a plan 10,000 times before you risk a rupee.

  timemachine.py run                     trader/plan.json, 10,000 replays, seed 19
  timemachine.py run --write             also save trader/timemachine.json
  timemachine.py run --until 15:05       end each replay at your flat-by time
  timemachine.py run --symbol RELIANCE --date 2026-11-02 --entry 1234.50 --stop 1223.10 \
      --target 1245.90 --entry-time 09:35
  timemachine.py chart                   ASCII fan chart of the saved run

How: the stock's own 5-minute bars over the last 60 days (Yahoo, free, can lag).
Only FULL sessions before the plan's date go in the pool (73 bars, 9:15 to the
3:15 PM bar, the end of continuous trading before the closing auction). Each
replay rebuilds the rest of the day bar by bar from past bars at the same time
of day (plus or minus 2 bars), scaled to the current price, checking the stop
first and then the target. Then the plan's own rule is re-run on every one of
those real sessions. A simulation from the past, not a prediction.
"""

import argparse
import datetime as dt
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inmarket as M  # noqa: E402

STEP = dt.timedelta(minutes=5)
MIN_SESSIONS = 20


class Refused(Exception):
    pass


def build_pool(bars, before):
    """{date: [bars]} of full sessions before `before` (73 bars, 9:15..15:15)."""
    days = {}
    for b in bars:
        d = b["t"].date()
        if d >= before or not M.trading_day(d) or M.is_special(d):
            continue
        days.setdefault(d, []).append(b)
    pool = {}
    for d, bs in days.items():
        o = M.ist_dt(d, M.OPEN)
        want = [o + STEP * k for k in range(M.FULL_SESSION_BARS)]
        got = {b["t"]: b for b in bs}
        if all(w in got for w in want):
            pool[d] = [got[w] for w in want]
    return pool


def ratios(pool):
    """{date: [(o,h,l,c) / previous close]} for bars 1..72 (index-aligned; [0] is None)."""
    out = {}
    for d, bs in pool.items():
        r = [None]
        for k in range(1, len(bs)):
            pc = bs[k - 1]["c"]
            b = bs[k]
            r.append((b["o"] / pc, b["h"] / pc, b["l"] / pc, b["c"] / pc))
        out[d] = r
    return out


def slot_of(t, d):
    return int((t - M.ist_dt(d, M.OPEN)).total_seconds() // 300)


def simulate(plan, rat, first_slot, last_slot, n=10000, seed=19, window=2, keep_paths=160):
    """Monte Carlo. first_slot = index of the first bar after the entry bar,
    last_slot = index of the last bar (inclusive) before --until."""
    rng = random.Random(seed)
    days = sorted(rat)
    e, s, t = plan["entry"], plan["stop"], plan["target"]
    risk = e - s
    tgt_r = (t - e) / risk
    hits = {"target": 0, "stop": 0, "neither": 0}
    green = 0
    rs, closes = [], []
    nslots = last_slot - first_slot + 1
    bands = [[] for _ in range(nslots)]
    paths = []
    for i in range(n):
        p = e
        out = None
        path = [e]
        for j, k in enumerate(range(first_slot, last_slot + 1)):
            d = days[rng.randrange(len(days))]
            kk = min(M.FULL_SESSION_BARS - 1, max(1, k + rng.randint(-window, window)))
            o, h, l, c = rat[d][kk]
            lo, hi, cl = p * l, p * h, p * c
            if lo <= s:
                out = "stop"
                p = s
            elif hi >= t:
                out = "target"
                p = t
            else:
                p = cl
            bands[j].append(p)
            path.append(p)
            if out:
                for jj in range(j + 1, nslots):
                    bands[jj].append(p)
                break
        if out is None:
            out = "neither"
        hits[out] += 1
        r = -1.0 if out == "stop" else (tgt_r if out == "target" else (p - e) / risk)
        if out == "target" or (out == "neither" and p > e):
            green += 1
        rs.append(r)
        closes.append(p)
        if i < keep_paths:
            paths.append([round(x, 2) for x in path])
    closes_sorted = sorted(closes)

    def pct(q, arr):
        if not arr:
            return None
        k = (len(arr) - 1) * q
        f = int(math.floor(k))
        c = min(len(arr) - 1, f + 1)
        return arr[f] + (arr[c] - arr[f]) * (k - f)
    band_out = []
    for col in bands:
        cs = sorted(col)
        band_out.append([round(pct(q, cs), 2) for q in (0.05, 0.25, 0.5, 0.75, 0.95)])
    lo, hi = closes_sorted[0], closes_sorted[-1]
    nb = 24
    width = (hi - lo) / nb or 1
    hist = [0] * nb
    for c in closes:
        hist[min(nb - 1, int((c - lo) / width))] += 1
    return {
        "replays": n, "seed": seed, "window": window, "bars": nslots,
        "target_pct": round(100.0 * hits["target"] / n, 1), "stop_pct": round(100.0 * hits["stop"] / n, 1),
        "neither_pct": round(100.0 * hits["neither"] / n, 1), "green_pct": round(100.0 * green / n, 1),
        "avg_r": round(sum(rs) / n, 3), "target_r": round(tgt_r, 3),
        "close_median": round(pct(0.5, closes_sorted), 2), "close_p05": round(pct(0.05, closes_sorted), 2),
        "close_p95": round(pct(0.95, closes_sorted), 2),
        "bands": band_out, "paths": paths, "hist": {"lo": round(lo, 2), "width": round(width, 4), "counts": hist},
    }


def stop_for(rule, entry, oh, ol, plan, day_bars_to_entry):
    rule = (rule or "or-mid").lower()
    tk = M.tick_size(entry)
    if rule == "or-mid":
        raw = (oh + ol) / 2.0
    elif rule == "or-low":
        raw = ol
    elif rule.startswith("pct:"):
        raw = entry * (1 - float(rule[4:]) / 100.0)
    elif rule.startswith("atr:"):
        a, _ = M.atr(day_bars_to_entry, 14)
        raw = entry - float(rule[4:]) * a
    else:  # price:X -> the same percent risk as the plan
        raw = entry * (1 - plan["risk_per_share"] / plan["entry"])
    return M.round_down_tick(raw, tk)


def history(plan, pool, cfg, until_t):
    """Re-run the plan's rule on every pool session. -> dict."""
    orm = int(plan.get("or_minutes") or 15)
    k_or = orm // 5
    tr = plan.get("target_r")
    if tr is None:
        tr = (plan["target"] - plan["entry"]) / plan["risk_per_share"]
    nb = M.parse_hhmm(cfg.get("no_entries_before") or "09:30")
    na = M.parse_hhmm(cfg.get("no_entries_after") or "14:45")
    setup = plan.get("setup", "orb")
    res = {"sessions": len(pool), "fired": 0, "target": 0, "stop": 0, "neither": 0, "rs": [], "days": []}
    for d in sorted(pool):
        bs = pool[d]
        if setup == "orb":
            oh = max(b["h"] for b in bs[:k_or])
            ol = min(b["l"] for b in bs[:k_or])
            level = oh
        else:
            oh = ol = None
            level = plan["entry"] * 0 + plan.get("level", plan["entry"])  # a fixed level rarely repeats
            # scale a level setup to the session: the same distance above the prior close
            continue
        ent = None
        for i in range(k_or, len(bs)):
            close_t = (bs[i]["t"] + STEP).time()
            if close_t < nb:
                continue
            if close_t > na:
                break
            if bs[i]["c"] > level:
                ent = i
                break
        if ent is None:
            continue
        e = bs[ent]["c"]
        s = stop_for(plan.get("stop_rule"), e, oh, ol, plan, bs[:ent + 1])
        if s >= e:
            continue
        risk = e - s
        t = M.round_half_tick(e + tr * risk, M.tick_size(e))
        out, p = "neither", e
        for b in bs[ent + 1:]:
            if (b["t"] + STEP).time() > until_t:
                break
            if b["l"] <= s:
                out, p = "stop", s
                break
            if b["h"] >= t:
                out, p = "target", t
                break
            p = b["c"]
        r = -1.0 if out == "stop" else (tr if out == "target" else (p - e) / risk)
        res["fired"] += 1
        res[out] += 1
        res["rs"].append(r)
        res["days"].append({"date": d.isoformat(), "entry": e, "entry_time": M.hhmm(bs[ent]["t"] + STEP),
                            "stop": s, "target": t, "outcome": out, "r": round(r, 3)})
    res["avg_r"] = round(sum(res["rs"]) / len(res["rs"]), 3) if res["rs"] else None
    del res["rs"]
    return res


def verdict(mc):
    tp, sp, ne = mc["target_pct"], mc["stop_pct"], mc["neither_pct"]
    R = mc["target_r"]
    lines = []
    sided = tp + sp
    if sided <= 0:
        lines.append("Almost every replay hit neither side: the price at the end decides this plan.")
        return lines
    share = 100.0 * tp / sided
    need = 100.0 / (1 + R)
    diff = share - need
    one_r = abs(R - 1) < 1e-6
    if abs(diff) < 5:
        v = ("Close to a coin flip" if one_r else "Close to break-even") + ": target first %.1f %% vs stop first %.1f %%" % (tp, sp)
        if not one_r:
            v += " (a %gR target needs %.0f %% of the replays that hit a side, and got %.0f %%)" % (R, need, share)
    elif abs(diff) < 15:
        v = "Leans toward the %s: target first %.1f %% vs stop first %.1f %%" % ("target" if diff > 0 else "stop", tp, sp)
        if not one_r:
            v += " (needs %.0f %% of the sided replays at %gR, got %.0f %%)" % (need, R, share)
    else:
        v = "Strongly toward the %s: target first %.1f %% vs stop first %.1f %%" % ("target" if diff > 0 else "stop", tp, sp)
        if not one_r:
            v += " (needs %.0f %% of the sided replays at %gR, got %.0f %%)" % (need, R, share)
    lines.append(v + ".")
    if ne > 40:
        lines.append("%.1f %% of the replays hit neither by the end; the price at the end decides those." % ne)
    if (diff >= 5 and mc["avg_r"] < 0) or (diff <= -5 and mc["avg_r"] > 0):
        lines.append("But the average R is %+.3f, the other way: the replays that hit neither pull it." % mc["avg_r"])
    return lines


def run(plan, bars, cfg, until=None, n=10000, seed=19, window=2, min_sessions=MIN_SESSIONS):
    d = dt.date.fromisoformat(plan["date"])
    if plan.get("side", "buy") != "buy":
        raise Refused("long plans only")
    if not (plan["stop"] < plan["entry"] < plan["target"]):
        raise Refused("the plan does not make sense: a buy needs stop < entry < target")
    pool = build_pool(bars, d)
    if len(pool) < min_sessions:
        raise Refused("only %d full sessions before %s in the data (need %d)" % (len(pool), d, min_sessions))
    et = M.parse_hhmm(plan["entry_time"])
    entry_close = M.ist_dt(d, et)
    if (entry_close - M.ist_dt(d, M.OPEN)).total_seconds() % 300:
        raise Refused("the entry time %s is not on the 5-minute grid" % plan["entry_time"])
    first_slot = slot_of(entry_close, d)  # the bar that STARTS at the entry close
    ce = M.cont_end(d) or M.CONT_END
    ut = M.parse_hhmm(until) if until else ce
    ut = min(ut, ce)
    last_slot = slot_of(M.ist_dt(d, ut), d) - 1
    if last_slot < first_slot:
        raise Refused("nothing left to replay between %s and %s" % (plan["entry_time"], M.hhmm(ut)))
    rat = ratios(pool)
    mc = simulate(plan, rat, first_slot, last_slot, n, seed, window)
    hist = history(plan, pool, cfg, ut)
    return {"plan": plan, "until": M.hhmm(ut), "pool_sessions": len(pool),
            "pool_from": min(pool).isoformat(), "pool_to": max(pool).isoformat(),
            "mc": mc, "history": hist, "verdict": verdict(mc)}


def render(r):
    p, mc, h = r["plan"], r["mc"], r["history"]
    ut = M.clock(M.parse_hhmm(r["until"]))
    L = ["%s replays of the rest of the session, %s to %s (%d five-minute bars), seed %d." % (
        format(mc["replays"], ","), M.clock(M.parse_hhmm(p["entry_time"])), ut, mc["bars"], mc["seed"]),
        "  Plan: entry %s, stop %s, target %s (%gR), risk %s a share." % (
            M.px(p["entry"]), M.px(p["stop"]), M.px(p["target"]), mc["target_r"], M.px(p["entry"] - p["stop"])),
        "  target first  %5.1f %%" % mc["target_pct"],
        "  stop first    %5.1f %%" % mc["stop_pct"],
        "  neither       %5.1f %%   still open at %s" % (mc["neither_pct"], ut),
        "  green         %5.1f %%   target first, or above the entry at %s" % (mc["green_pct"], ut),
        "  Price at %s: median %s, 90 %% of replays between %s and %s." % (
            ut, M.px(mc["close_median"]), M.px(mc["close_p05"]), M.px(mc["close_p95"])),
        "  Average R: %+.3f" % mc["avg_r"],
        "Pool: %d full sessions, %s to %s (Yahoo 5-minute bars)." % (r["pool_sessions"], r["pool_from"], r["pool_to"])]
    if h["sessions"] and p.get("setup", "orb") == "orb":
        L.append("History: the same rule on each of those %d real sessions fired %d times: %d target, %d stop, %d neither.%s"
                 % (h["sessions"], h["fired"], h["target"], h["stop"], h["neither"],
                    (" Average R %+.3f." % h["avg_r"]) if h["avg_r"] is not None else ""))
    else:
        L.append("History: a fixed price level does not repeat on other days, so only the replays apply.")
    L.extend(r["verdict"])
    L.append("Built from the last %d sessions. Results, news, a circuit or a block deal can do what those days never did."
             % r["pool_sessions"])
    return "\n".join(L)


def chart(r, width=60, height=16):
    mc = r["mc"]
    b = mc["bands"]
    p = r["plan"]
    lo = min(min(x[0] for x in b), p["stop"])
    hi = max(max(x[4] for x in b), p["target"])
    span = hi - lo or 1
    cols = len(b)
    grid = [[" "] * cols for _ in range(height)]

    def row(v):
        return height - 1 - int(round((v - lo) / span * (height - 1)))
    for j, q in enumerate(b):
        for y in range(row(q[4]), row(q[0]) + 1):
            grid[y][j] = "."
        for y in range(row(q[3]), row(q[1]) + 1):
            grid[y][j] = ":"
        grid[row(q[2])][j] = "*"
    out = []
    for y in range(height):
        v = hi - y * span / (height - 1)
        tag = ""
        if row(p["target"]) == y:
            tag = " target"
        if row(p["entry"]) == y:
            tag = " entry"
        if row(p["stop"]) == y:
            tag = " stop"
        out.append("%9.2f |%s|%s" % (v, "".join(grid[y]), tag))
    out.append("          5-95 %% (.)  25-75 %% (:)  median (*), %s to %s" % (p["entry_time"], r["until"]))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("run")
    q.add_argument("plan_file", nargs="?")
    for f in ("--symbol", "--date", "--entry-time", "--until", "--offline", "--now", "--config", "--stop-rule"):
        q.add_argument(f)
    for f in ("--entry", "--stop", "--target", "--or-high", "--or-low"):
        q.add_argument(f, type=float)
    q.add_argument("--replays", type=int, default=10000)
    q.add_argument("--seed", type=int, default=19)
    q.add_argument("--window", type=int, default=2)
    q.add_argument("--min-sessions", type=int, default=MIN_SESSIONS)
    q.add_argument("--write", action="store_true")
    q.add_argument("--json", action="store_true")
    c = sub.add_parser("chart")
    c.add_argument("--from", dest="src")
    a = ap.parse_args(argv)
    if a.cmd == "chart":
        r = M.read_json(a.src or M.tpath("timemachine.json"))
        if not r:
            print("No trader/timemachine.json. Run timemachine.py run --write first.")
            return 1
        print(chart(r))
        return 0
    cfg = M.load_config(a.config)
    if a.symbol:
        if None in (a.entry, a.stop, a.target) or not a.entry_time:
            print("With --symbol, give --entry, --stop, --target and --entry-time.")
            return 1
        plan = {"symbol": M.norm_symbol(a.symbol), "exchange": M.exchange_of(a.symbol),
                "date": a.date or M.now_ist(a.now).date().isoformat(), "side": "buy",
                "setup": "orb" if a.or_high else "level", "entry": a.entry, "stop": a.stop, "target": a.target,
                "entry_time": a.entry_time, "or_high": a.or_high, "or_low": a.or_low, "or_minutes": 15,
                "stop_rule": a.stop_rule or ("or-mid" if a.or_high else "price"),
                "risk_per_share": round(a.entry - a.stop, 2), "target_r": round((a.target - a.entry) / (a.entry - a.stop), 3)}
    else:
        plan = M.read_json(a.plan_file or M.tpath("plan.json"))
        if not plan:
            print("No trader/plan.json. Run /in-trader-exit first, or pass the plan as flags.")
            return 1
    try:
        s = M.fetch_chart(plan["symbol"], "60d", "5m", offline=a.offline, exchange=plan.get("exchange", "NSE"))
        bars = M.bars_from_series(s)
        r = run(plan, bars, cfg, a.until, a.replays, a.seed, a.window, a.min_sessions)
    except (Refused, M.DataError) as ex:
        print("REFUSED: %s." % ex)
        return 1
    if a.json:
        slim = dict(r)
        slim["mc"] = {k: v for k, v in r["mc"].items() if k not in ("bands", "paths")}
        print(json.dumps(slim, indent=2, default=str))
    else:
        print(render(r))
    if a.write:
        M.write_json(M.tpath("timemachine.json"), r)
        if not a.json:
            print("Saved trader/timemachine.json (timemachine.py chart draws it).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
