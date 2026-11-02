"""Offline tests for the data skills (scanner, news, analyst, insiders) on real NSE
and Yahoo responses saved on 2026-11-02, plus repo checks."""

import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import FIX, REL, ROOT, load  # noqa: E402

M = load("in-trader-scanner", "inmarket.py")
scan = load("in-trader-scanner", "scan.py")
news = load("in-trader-news", "news.py")
facts = load("in-trader-analyst", "facts.py")
ins = load("in-trader-insiders", "insiders.py")


def rd(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def js(*p):
    return json.loads(rd(os.path.join(FIX, *p)))


class Scanner(unittest.TestCase):
    def test_orb_on_real_bars(self):
        data = {"RELIANCE": M.load_chart_offline(REL, "RELIANCE")}
        d = dt.date(2026, 11, 2)
        hits, c = scan.orb_scan(data, d, M.ist_dt(d, dt.time(10, 0)), 15, 20.0)
        self.assertEqual(c["usable"], 1)
        self.assertEqual(hits[0]["time"], "09:35")
        self.assertEqual((hits[0]["or_low"], hits[0]["or_high"], hits[0]["close"]), (1214.6, 1231.6, 1234.5))
        hits, _ = scan.orb_scan(data, d, M.ist_dt(d, dt.time(9, 35)), 15, 20.0)
        self.assertEqual(len(hits), 1)

    def test_daily_setups(self):
        up = [100 + i * 0.1 for i in range(40)] + [110]
        self.assertIn("breakout_20d", M.daily_setups(up)[0])
        down = [200 - i * 2 for i in range(40)]
        self.assertIn("oversold", M.daily_setups(down)[0])
        flag = [100.0] * 20 + [100 + i * 2.5 for i in range(10)] + [125, 124.5, 125.5, 124.8, 125.2]
        self.assertIn("bull_flag", M.daily_setups(flag)[0])

    def test_universe_parsers(self):
        eq = ("SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
              "RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10\n"
              "SMALLCO,Small Co Limited,BE,01-JAN-2020,10,1,INE000X01010,10\n"
              "BONDCO,Bond Co,N1,01-JAN-2020,10,1,INE000Y01010,10\n")
        self.assertEqual([r[0] for r in scan.parse_equity_l(eq)], ["RELIANCE", "SMALLCO"])
        ix = "Company Name,Industry,Symbol,Series,ISIN Code\nReliance Industries Ltd.,Oil Gas,RELIANCE,EQ,INE002A01018\n"
        self.assertEqual(scan.parse_index_csv(ix)[0][0], "RELIANCE")
        self.assertEqual(len(M.FNO_2026_11), 218)


class News(unittest.TestCase):
    def test_announcements(self):
        items = news.parse_nse_announcements(js("news", "RELIANCE-announcements.json"), "RELIANCE")
        self.assertEqual(len(items), 5)
        board = [i for i in items if i["title"].startswith("Outcome of Board Meeting")][0]
        self.assertTrue(board["important"])
        self.assertIn("results", board["tags"])
        self.assertEqual(board["time"], "2026-10-30T19:40+05:30")
        pres = [i for i in items if i["title"].startswith("Investor Presentation")][0]
        self.assertFalse(pres["important"])

    def test_events(self):
        ev = js("news", "RELIANCE-events.json")
        self.assertEqual(news.parse_events(ev, "RELIANCE", dt.date(2026, 10, 28))[0]["date"], "2026-10-30")
        self.assertEqual(news.parse_events(ev, "RELIANCE", dt.date(2026, 11, 2)), [])

    def test_rss_and_tags(self):
        rss = ("<rss><channel><item><title>Reliance Q2 results: net profit rises; Jefferies raises target price"
               "</title><link>https://example.com/a</link><pubDate>Mon, 02 Nov 2026 03:30:00 GMT</pubDate>"
               "<source>Example</source></item></channel></rss>")
        it = news.parse_rss(rss, "Google News", "RELIANCE")[0]
        self.assertEqual(it["time"], "2026-11-02T09:00+05:30")
        self.assertTrue({"results", "analyst"} <= set(it["tags"]))


class Analyst(unittest.TestCase):
    def test_quarters(self):
        rows = facts.parse_timeseries(js("analyst", "RELIANCE-timeseries.json"))
        self.assertEqual(len(rows), 5)
        out, gaps, ttm = facts.analyse(rows)
        last = out[-1]
        self.assertEqual(last["label"], "Q1 FY27")
        self.assertAlmostEqual(last["rev_yoy"], 27.02, places=1)
        self.assertAlmostEqual(last["net_yoy"], -22.4, places=1)
        self.assertEqual(gaps, ["Q1 FY26 to Q3 FY26"])
        self.assertIsNone(ttm)                      # no TTM across a missing quarter
        self.assertEqual(facts.fy_label(dt.date(2026, 9, 30)), "Q2 FY27")
        self.assertEqual(facts.fy_label(dt.date(2027, 3, 31)), "Q4 FY27")

    def test_filing_and_next(self):
        ann = js("analyst", "RELIANCE-announcements.json")
        lf = facts.latest_results_filing(ann, M.parse_now("2026-11-02 08:00"))
        self.assertTrue(lf["link"].endswith("_Results.pdf"))
        self.assertIsNone(facts.latest_results_filing(ann, M.parse_now("2026-10-28 08:00")))
        nr = facts.next_results(js("analyst", "RELIANCE-events.json"), dt.date(2026, 10, 28))
        self.assertEqual(nr[0], dt.date(2026, 10, 30))


class Insiders(unittest.TestCase):
    def test_pit(self):
        rows = ins.parse_pit(js("insiders", "pit-ADANIENT.json"))
        self.assertEqual(rows[0]["filed"], "03-Oct-2022 18:53")
        self.assertIn("PROMOTER MARKET BUY", rows[0]["flags"])
        self.assertEqual(rows[0]["delay_trading_days"], 3)
        self.assertAlmostEqual(rows[0]["price"], 3563.36, places=2)
        rel = ins.parse_pit(js("insiders", "pit-RELIANCE.json"))
        self.assertFalse(any("PROMOTER" in " ".join(r["flags"]) for r in rel))   # off-market, not promoters

    def test_deals(self):
        b = ins.parse_deals(js("insiders", "block.json"), "block")
        self.assertEqual(b[0]["symbol"], "ABCAPITAL")
        self.assertAlmostEqual(b[0]["value"], 3066761 * 366)
        rows = ins.in_range(ins.parse_deals(js("insiders", "bulk.json"), "bulk"), dt.date(2026, 10, 28), dt.date(2026, 11, 2))
        self.assertEqual(rows, [])


class Repo(unittest.TestCase):
    def test_skills(self):
        dirs = sorted(glob.glob(os.path.join(ROOT, "in-trader-*")))
        self.assertEqual(len(dirs), 11)
        for d in dirs:
            sk = rd(os.path.join(d, "SKILL.md"))
            m = re.match(r"---\nname: (\S+)\ndescription: >-\n(.*?)\n---", sk, re.S)
            self.assertIsNotNone(m, d)
            self.assertEqual(m.group(1), os.path.basename(d))
            self.assertLess(len(" ".join(m.group(2).split())), 1024, d)
            self.assertNotIn("{{SAFETY}}", sk)
            self.assertIn("<!-- safety:start -->", sk)
            for py in glob.glob(os.path.join(d, "*.py")):
                compile(rd(py), py, "exec")

    def test_common_in_sync(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "sync_common.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_no_secrets_or_live_default(self):
        cfg = json.loads(rd(os.path.join(ROOT, "in-trader-budget", "config.example.json")))
        self.assertTrue(cfg["paper"])
        self.assertFalse(cfg["allow_margin"] or cfg["allow_short"] or cfg["allow_options"])


if __name__ == "__main__":
    unittest.main()
