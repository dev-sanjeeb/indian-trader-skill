"""Offline tests for the shared module and the trade chain (entry -> exit -> time
machine -> budget -> risk -> broker -> alerts) on real RELIANCE 5-minute bars,
29 Sep to 2 Nov 2026 (Yahoo), the day RELIANCE opened after its Q2 FY27 results."""

import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import REL, load  # noqa: E402

M = load("in-trader-entry", "inmarket.py")
entry = load("in-trader-entry", "entry.py")
exitp = load("in-trader-exit", "exit.py")
tm = load("in-trader-timemachine", "timemachine.py")
size = load("in-trader-budget", "size.py")
risk = load("in-trader-risk", "check.py")
ticket = load("in-trader-broker", "ticket.py")
alerts = load("in-trader-alerts", "alerts.py")

BARS = M.bars_from_series(M.load_chart_offline(REL, "RELIANCE"))
D = dt.date(2026, 11, 2)


def now(s):
    return M.parse_now(s)


class Shared(unittest.TestCase):
    def test_ticks(self):
        self.assertEqual(M.tick_size(120.37), 0.01)
        self.assertEqual(M.tick_size(999.95), 0.05)
        self.assertEqual(M.tick_size(1234.5), 0.10)
        self.assertEqual(M.tick_size(7000), 0.50)
        self.assertEqual(M.round_down_tick(1223.125, 0.1), 1223.1)
        self.assertEqual(M.round_down_tick(364.18, 0.05), 364.15)
        self.assertEqual(M.round_up_tick(364.18, 0.05), 364.2)
        self.assertTrue(M.on_tick(1223.1, 0.1))
        self.assertFalse(M.on_tick(1223.13, 0.1))

    def test_inr(self):
        self.assertEqual(M.inr(1234567.5), "₹12,34,567.50")
        self.assertEqual(M.inr(999.999), "₹1,000.00")
        self.assertEqual(M.inr(100000, False), "₹1,00,000")

    def test_charges(self):
        c = M.charges(39 * 1234.5, 39 * 1223.1)
        self.assertEqual(c["total"], 50.88)
        self.assertEqual(c["brokerage"], 28.75)       # 0.03 % each side, under Rs 20
        self.assertEqual(M.charges(1e6, 1e6)["brokerage"], 40.0)  # capped Rs 20 an order

    def test_calendar(self):
        self.assertIsNone(M.session(dt.date(2026, 11, 10)))           # Diwali Balipratipada
        self.assertIsNone(M.session(dt.date(2026, 10, 20)))           # Dussehra
        self.assertIsNone(M.session(dt.date(2026, 11, 7)))            # Saturday
        o, c, label = M.session(dt.date(2026, 11, 8))                 # Muhurat, a Sunday
        self.assertEqual((M.hhmm(o), M.hhmm(c)), ("14:20", "15:30"))
        self.assertEqual(M.bars_in_session(D), 73)
        self.assertEqual(M.prev_trading_day(dt.date(2026, 11, 11)), dt.date(2026, 11, 9))
        self.assertIsNotNone(M.year_warning(dt.date(2027, 1, 4)))
        # the fixture has no bars on the two holidays inside it
        days = {b["t"].date() for b in BARS}
        self.assertNotIn(dt.date(2026, 10, 2), days)
        self.assertNotIn(dt.date(2026, 10, 20), days)

    def test_symbols(self):
        self.assertEqual(M.to_yahoo("reliance"), "RELIANCE.NS")
        self.assertEqual(M.to_yahoo("BSE:500325"), "500325.BO")
        self.assertEqual(M.to_yahoo("NIFTY"), "^NSEI")
        self.assertEqual(M.norm_symbol("M&M.NS"), "M&M")

    def test_bars(self):
        day = M.session_bars(BARS, D)
        self.assertEqual(M.hhmm(day[0]["t"]), "09:15")
        self.assertTrue(all(b["t"].second == 0 for b in BARS))      # the live tick is dropped


class Entry(unittest.TestCase):
    cfg = dict(M.DEFAULT_CONFIG)

    def ev(self, t, **kw):
        return entry.evaluate(BARS, "RELIANCE", now(t), self.cfg, **kw)

    def test_triggered(self):
        r = self.ev("2026-11-02 09:35")
        self.assertEqual(r["status"], "triggered")
        self.assertEqual((r["or_high"], r["or_low"]), (1231.6, 1214.6))
        self.assertEqual((r["trigger_time"], r["entry"], r["bar_index"]), ("09:35", 1234.5, 4))

    def test_waiting_forming_closed(self):
        r = self.ev("2026-11-02 09:34")
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(r["last_close"], 1229.9)
        self.assertEqual(r["forming_bar"], "09:30")
        self.assertEqual(self.ev("2026-11-02 09:25")["status"], "forming")
        self.assertEqual(self.ev("2026-11-02 09:00")["status"], "not_open")
        self.assertEqual(self.ev("2026-11-10 10:00")["status"], "closed")

    def test_volume_rule_delays(self):
        r = self.ev("2026-11-02 11:00", min_volume_x=1.0)
        self.assertEqual(r["status"], "waiting")

    def test_level(self):
        r = self.ev("2026-11-02 12:00", setup="level", level=1250.0)
        self.assertEqual(r["status"], "triggered")
        self.assertGreater(r["entry"], 1250.0)


class Exit(unittest.TestCase):
    E = {"symbol": "RELIANCE", "date": "2026-11-02", "entry": 1234.5, "or_high": 1231.6, "or_low": 1214.6,
         "trigger_time": "09:35", "bar_index": 4, "setup": "orb"}

    def test_plan(self):
        p = exitp.make_plan(self.E, "or-mid", "1R")
        self.assertEqual((p["stop"], p["target"], p["risk_per_share"], p["reward_risk"]), (1223.1, 1245.9, 11.4, 1.0))
        self.assertEqual(exitp.make_plan(self.E, "or-mid", "2R")["target"], 1257.3)
        self.assertEqual(exitp.make_plan(self.E, "or-low", "1R")["stop"], 1214.6)
        self.assertEqual(p["flat_by"], "15:05")

    def test_refusals(self):
        for stop, tgt in (("price:1240", "1R"), ("price:1234.2", "1R"), ("or-mid", "price:1230")):
            with self.assertRaises(exitp.Refused):
                exitp.make_plan(self.E, stop, tgt)
        with self.assertRaises(exitp.Refused):
            exitp.make_plan(dict(self.E, or_high=None, or_low=None), "or-mid", "1R")
        with self.assertRaises(exitp.Refused):
            exitp.make_plan(dict(self.E, trigger_time="15:10"), "or-mid", "1R")


PLAN = exitp.make_plan(Exit.E, "or-mid", "1R")


class TimeMachine(unittest.TestCase):
    def test_reel_numbers(self):
        r = tm.run(PLAN, BARS, M.DEFAULT_CONFIG, "15:05", 10000, 19, 2, min_sessions=15)
        mc, h = r["mc"], r["history"]
        self.assertEqual(r["pool_sessions"], 19)
        self.assertEqual(mc["bars"], 66)
        self.assertEqual((mc["target_pct"], mc["stop_pct"], mc["neither_pct"], mc["green_pct"]), (33.8, 47.1, 19.1, 43.1))
        self.assertEqual(mc["avg_r"], -0.136)
        self.assertEqual((h["fired"], h["target"], h["stop"], h["neither"]), (12, 5, 5, 2))
        self.assertTrue(r["verdict"][0].startswith("Leans toward the stop"))

    def test_deterministic_and_seeded(self):
        a = tm.run(PLAN, BARS, M.DEFAULT_CONFIG, "15:05", 2000, 7, 2, min_sessions=15)["mc"]
        b = tm.run(PLAN, BARS, M.DEFAULT_CONFIG, "15:05", 2000, 7, 2, min_sessions=15)["mc"]
        self.assertEqual(a["target_pct"], b["target_pct"])

    def test_refuses_thin_pool(self):
        with self.assertRaises(tm.Refused):
            tm.run(PLAN, BARS, M.DEFAULT_CONFIG)          # 19 full sessions < 20

    def test_verdict_r(self):
        v = tm.verdict({"target_pct": 24.1, "stop_pct": 50.5, "neither_pct": 25.4, "target_r": 2.0, "avg_r": 0.0})
        self.assertTrue(v[0].startswith("Close to break-even"))


class Budget(unittest.TestCase):
    def test_size(self):
        r = size.size(PLAN, dict(M.DEFAULT_CONFIG), now("2026-11-02 09:36"))
        self.assertEqual((r["qty"], r["decided_by"], r["loss_at_stop"]), (39, "max loss", 495.48))
        o = size.orders_for(r, PLAN, M.DEFAULT_CONFIG)
        self.assertEqual(o[0]["kite"]["product"], "MIS")
        self.assertEqual(o[1]["kite"]["order_type"], "SL-M")
        self.assertEqual(o[1]["kite"]["trigger_price"], 1223.1)
        self.assertEqual(o[1]["after"], 1)

    def test_refusals(self):
        cfg = dict(M.DEFAULT_CONFIG)
        with self.assertRaises(size.Refused):
            size.size(PLAN, cfg, now("2026-11-03 09:36"))                     # another day
        with self.assertRaises(size.Refused):
            size.size(dict(PLAN, stop=600.0), cfg, now("2026-11-02 09:36"))   # one share > max loss
        with self.assertRaises(size.Refused):
            size.size(PLAN, dict(cfg, blocked=["RELIANCE"]), now("2026-11-02 09:36"))

    def test_fresh_price_shrinks(self):
        pr = {"as_of": "2026-11-02T10:50:00+05:30", "prices": {"RELIANCE": 1240.0}}
        with self.assertRaises(size.Refused):   # reward:risk falls under 1
            size.size(PLAN, dict(M.DEFAULT_CONFIG), now("2026-11-02 10:55"), pr)


def orders_doc(qty=39):
    r = size.size(PLAN, dict(M.DEFAULT_CONFIG), now("2026-11-02 09:36"))
    r["qty"] = qty
    r["loss_at_stop"] = round(qty * 11.4 + M.charges(qty * 1234.5, qty * 1223.1)["total"], 2)
    return {"orders": size.orders_for(r, PLAN, M.DEFAULT_CONFIG)}


class Risk(unittest.TestCase):
    cfg = dict(M.DEFAULT_CONFIG)

    def test_pass(self):
        res, s = risk.check(orders_doc(), self.cfg, now("2026-11-02 09:36"))
        self.assertEqual([r["verdict"] for r in res], ["PASS", "PASS"])
        self.assertEqual(res[0]["info"]["max_loss"], 495.48)
        self.assertEqual(s["cash_after"], 51854.5)

    def test_blocks(self):
        res, _ = risk.check(orders_doc(), self.cfg, now("2026-11-02 09:20"))
        self.assertIn("window", " ".join(res[0]["reasons"]))
        self.assertEqual(res[1]["verdict"], "PASS")              # the stop is an exit
        res, _ = risk.check(orders_doc(40), self.cfg, now("2026-11-02 09:36"))
        self.assertIn("508.19", " ".join(res[0]["reasons"]))
        res, _ = risk.check(orders_doc(), dict(self.cfg, surveillance=["RELIANCE"]), now("2026-11-02 09:36"))
        self.assertIn("surveillance", " ".join(res[0]["reasons"]))
        res, _ = risk.check(orders_doc(), self.cfg, now("2026-11-10 10:00"))
        self.assertIn("closed", " ".join(res[0]["reasons"]))

    def test_derivatives_and_shorts(self):
        self.assertFalse(risk.DERIV_RE.search("RELIANCE"))
        self.assertTrue(risk.DERIV_RE.search("NIFTY26N1024000CE"))
        self.assertTrue(risk.DERIV_RE.search("RELIANCE26NOVFUT"))
        k = {"exchange": "NSE", "tradingsymbol": "TCS", "transaction_type": "SELL", "quantity": 5, "product": "MIS",
             "order_type": "MARKET", "validity": "DAY"}
        res, _ = risk.check({"orders": [{"id": 1, "kite": k}]}, self.cfg, now("2026-11-02 10:00"))
        self.assertIn("short", " ".join(res[0]["reasons"]))
        port = {"cash_inr": 50000, "positions": {"TCS": {"qty": 5}}}
        res, _ = risk.check({"orders": [{"id": 1, "kite": k}]}, self.cfg, now("2026-11-02 15:08"), port)
        self.assertEqual(res[0]["verdict"], "PASS")              # an exit after the window

    def test_tick(self):
        d = orders_doc()
        d["orders"][1]["kite"]["trigger_price"] = 1223.13
        res, _ = risk.check(d, self.cfg, now("2026-11-02 09:36"))
        self.assertIn("tick", " ".join(res[1]["reasons"]))


class Broker(unittest.TestCase):
    K = {"tradingsymbol": "RELIANCE", "quantity": 39}

    def test_yes(self):
        for r in ("yes", "Yes, place it", "haan", "YES!", "yes buy 39 reliance"):
            self.assertTrue(ticket.reply_is_yes(r, self.K)[0], r)
        for r in ("sure", "ok", "yes to all", "yes, buy 40", "yes TCS", "no", "", "maybe later"):
            self.assertFalse(ticket.reply_is_yes(r, self.K)[0], r)

    def test_paper_flow(self):
        tmp = tempfile.mkdtemp()
        os.environ["TRADER_DIR"] = tmp
        try:
            M.write_json(os.path.join(tmp, "orders.json"), orders_doc())
            with redirect_stdout(io.StringIO()):
                risk.main(["--now", "2026-11-02 09:36"])
                self.assertEqual(ticket.main(["--now", "2026-11-02 09:37", "paper", "--index", "1"]), 1)  # no yes yet
                self.assertEqual(ticket.main(["--now", "2026-11-02 09:37", "approve", "--index", "1", "--reply", "sure"]), 1)
                self.assertEqual(ticket.main(["--now", "2026-11-02 09:37", "approve", "--index", "1", "--reply", "yes"]), 0)
                self.assertEqual(ticket.main(["--now", "2026-11-02 09:37", "paper", "--index", "1", "--price", "1234.6"]), 0)
            port = M.read_json(os.path.join(tmp, "portfolio.json"))
            self.assertEqual(port["positions"]["RELIANCE"]["qty"], 39)
            self.assertEqual(port["cash_inr"], 51850.6)
            log = M.read_json(os.path.join(tmp, "state", "broker.json"))["log"]
            self.assertEqual([e["event"] for e in log], ["not_yes", "yes", "paper_fill", "placed"])
            # the next entry in the same symbol today is a duplicate for the risk check
            res, _ = risk.check(orders_doc(), dict(M.DEFAULT_CONFIG), now("2026-11-02 09:40"), port, None,
                                M.read_json(os.path.join(tmp, "state", "broker.json")))
            self.assertIn("duplicate", " ".join(res[0]["reasons"]))
        finally:
            os.environ.pop("TRADER_DIR", None)
            shutil.rmtree(tmp)


class Alerts(unittest.TestCase):
    def test_rings_once(self):
        doc = {"rules": [{"id": "s", "symbol": "RELIANCE", "type": "stop", "price": 1223.1, "date": "2026-11-02"},
                         {"id": "t", "symbol": "RELIANCE", "type": "target", "price": 1245.9, "date": "2026-11-02"},
                         {"id": "f", "symbol": "RELIANCE", "type": "time", "at": "15:05", "label": "flat by",
                          "date": "2026-11-02"},
                         {"id": "b", "type": "opening_bell"}]}
        q = {"RELIANCE": {"price": 1253.4, "as_of": "2026-11-02T13:20:00+05:30", "prev_close": 1164.9}}
        rang, st = alerts.evaluate(doc, {}, now("2026-11-02 13:16"), q)
        self.assertEqual(sorted(r["id"] for r, _ in rang), ["b", "t"])
        rang, st = alerts.evaluate(doc, st, now("2026-11-02 13:21"), q)
        self.assertEqual(rang, [])
        rang, st = alerts.evaluate(doc, st, now("2026-11-02 15:05"), q)
        self.assertEqual([r["id"] for r, _ in rang], ["f"])
        rang, _ = alerts.evaluate(doc, {}, now("2026-11-03 10:00"), q)   # yesterday's plan rules are not watched
        self.assertEqual([r["id"] for r, _ in rang], ["b"])


if __name__ == "__main__":
    unittest.main()
