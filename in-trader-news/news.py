#!/usr/bin/env python3
"""in-trader-news: what is new on the stocks you watch, newest first, in IST.

  news.py                               watchlist + plan + portfolio
  news.py --tickers RELIANCE TCS --hours 12
  news.py --no-nse --json               headlines only
  news.py --all                         show items already seen too

Feeds (free, no keys):
  - NSE corporate announcements (the company's own filings to the exchange)
  - NSE event calendar (upcoming board meetings: the next results date)
  - Yahoo Finance headlines RSS (SYMBOL.NS) and Google News India RSS
  - Yahoo chart: the last price against the previous close
"""

import argparse
import datetime as dt
import email.utils
import hashlib
import json
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inmarket as M  # noqa: E402

TAGS = [
    ("results", r"\b(financial results?|quarterly results?|q[1-4]\s?(fy)?\d{0,4}|earnings|profit|net income|revenue|ebitda|pat\b|margin)"),
    ("board", r"board meeting|outcome of board"),
    ("dividend", r"dividend|record date"),
    ("corporate action", r"\bbonus\b|stock split|sub-division|buy-?back|rights issue|demerger"),
    ("capital", r"\bqip\b|preferential|fund ?rais|ncd|debenture|warrants|ofs\b|offer for sale|ipo\b"),
    ("deal", r"acqui|merger|amalgamation|stake|joint venture|\bjv\b|takeover|open offer|scheme of arrangement"),
    ("orders", r"order (win|book|from)|bags .*order|contract|letter of award|\bloa\b|tender"),
    ("people", r"resign|appoint|\bceo\b|\bcfo\b|\bmd\b|managing director|chairman|key managerial|kmp"),
    ("rating", r"credit rating|crisil|icra|care ratings|india ratings|downgrad|upgrad"),
    ("regulatory", r"\bsebi\b|\brbi\b|show cause|penalty|\bgst\b|tax demand|income tax|enforcement directorate|\bed\b raid|cci\b"),
    ("legal", r"\bnclt\b|insolvency|\bibc\b|court|litigation|arbitration|default|fraud|forensic"),
    ("promoter", r"promoter|pledge|encumbrance|insider|sast"),
    ("block deal", r"block deal|bulk deal|large trade"),
    ("surveillance", r"\basm\b|\bgsm\b|surveillance|price band|upper circuit|lower circuit|trade[- ]to[- ]trade"),
    ("analyst", r"target price|price target|\bbuy\b rating|\bsell\b rating|overweight|underweight|brokerage|initiates coverage|motilal|jefferies|morgan stanley|goldman|nomura|clsa|kotak institutional"),
    ("macro", r"\bnifty\b|sensex|\bfii|\bdii|\bfpi|repo rate|inflation|\bcpi\b|\bgdp\b|budget|rupee|crude"),
]
IMPORTANT = re.compile(r"outcome of board|financial result|resignation|insolvency|\bnclt\b|credit rating|fund rais|"
                       r"acquisition|scheme of arrangement|pledge|cyber|fraud|default|forensic|"
                       r"suspension|delist", re.I)
STRONG = re.compile(r"fraud|insolvency|default|resign|raid|search and seizure|forensic|cyber", re.I)


def tag(text):
    t = text.lower()
    return [name for name, rx in TAGS if re.search(rx, t)]


def key_of(*parts):
    return hashlib.sha1("|".join(p or "" for p in parts).encode()).hexdigest()[:16]


def parse_rss(text, source, sym):
    items = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return items
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        try:
            when = email.utils.parsedate_to_datetime(pub).astimezone(M.IST) if pub else None
        except (TypeError, ValueError):
            when = None
        src = it.find("source")
        pubname = (src.text or "").strip() if src is not None else source
        items.append({"symbol": sym, "kind": "headline", "source": pubname or source, "title": title, "link": link,
                      "time": when.isoformat(timespec="minutes") if when else None, "tags": tag(title)})
    return items


def parse_nse_announcements(doc, sym):
    out = []
    for r in doc if isinstance(doc, list) else (doc or {}).get("data", []):
        try:
            when = dt.datetime.strptime(r.get("an_dt") or r.get("sort_date"), "%d-%b-%Y %H:%M:%S").replace(tzinfo=M.IST)
        except (TypeError, ValueError):
            try:
                when = dt.datetime.strptime(r.get("sort_date"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=M.IST)
            except (TypeError, ValueError):
                when = None
        desc = (r.get("desc") or "").strip()
        text = (r.get("attchmntText") or "").strip()
        title = desc + (": " + text if text else "")
        out.append({"symbol": r.get("symbol", sym), "kind": "filing", "source": "NSE filing", "title": title[:400],
                    "link": r.get("attchmntFile"), "time": when.isoformat(timespec="minutes") if when else None,
                    "tags": tag(title), "important": bool(IMPORTANT.search(desc) or STRONG.search(text[:300]))})
    return out


def parse_events(doc, sym, today, days=10):
    out = []
    for r in doc or []:
        try:
            d = dt.datetime.strptime(r["date"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        if today <= d <= today + dt.timedelta(days=days):
            out.append({"symbol": r.get("symbol", sym), "date": d.isoformat(), "purpose": r.get("purpose", ""),
                        "desc": (r.get("bm_desc") or "")[:300]})
    return sorted(out, key=lambda x: x["date"])


def move(sym, offline=None):
    try:
        s = M.fetch_chart(sym, "1d", "5m", offline=offline, exchange=M.exchange_of(sym))
    except M.DataError:
        return None
    m = s.get("meta") or {}
    p, pc = m.get("regularMarketPrice"), m.get("previousClose") or m.get("chartPreviousClose")
    if not p or not pc:
        return None
    return {"price": round(p, 2), "prev_close": round(pc, 2), "pct": round((p / pc - 1) * 100, 2),
            "time": M.ts_to_ist(m.get("regularMarketTime") or s["t"][-1]).strftime("%H:%M")}


def tickers_from_files(a):
    if a.tickers:
        return [M.norm_symbol(t) for t in a.tickers]
    out = []
    wl = M.read_json(M.tpath("watchlist.json"), {}) or {}
    out += [h["symbol"] for h in wl.get("hits", [])][:25]
    pl = M.read_json(M.tpath("plan.json"), {}) or {}
    if pl.get("symbol"):
        out.append(pl["symbol"])
    pf = M.read_json(M.tpath("portfolio.json"), {}) or {}
    out += list((pf.get("positions") or {}).keys())
    seen = []
    for t in out:
        if t not in seen:
            seen.append(t)
    return seen


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--hours", type=float, default=18)
    ap.add_argument("--move-pct", type=float, default=3.0)
    ap.add_argument("--no-nse", action="store_true")
    ap.add_argument("--no-headlines", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--now")
    ap.add_argument("--offline", help="folder with <SYM>-announcements.json, <SYM>-events.json, <SYM>-yahoo.xml, <SYM>.json")
    a = ap.parse_args(argv)
    now = M.now_ist(a.now)
    syms = tickers_from_files(a)
    if not syms:
        print("No tickers: pass --tickers, or run /in-trader-scanner first.")
        return 1
    state = M.read_json(M.tpath("state", "news.json"), {"seen": {}}) or {"seen": {}}
    seen = state.setdefault("seen", {})
    since = now - dt.timedelta(hours=a.hours)
    nse = M.NSE() if not (a.no_nse or a.offline) else None
    items, events, moves, notes = [], {}, {}, []

    def off(name):
        p = os.path.join(a.offline, name)
        return open(p, encoding="utf-8").read() if os.path.exists(p) else None
    for sym in syms:
        if not a.no_nse:
            try:
                if a.offline:
                    t = off(sym + "-announcements.json")
                    ann = json.loads(t) if t else []
                    t = off(sym + "-events.json")
                    ev = json.loads(t) if t else []
                else:
                    ann = nse.get_json("/api/corporate-announcements?index=equities&symbol=" + urllib.parse.quote(sym))
                    ev = nse.get_json("/api/event-calendar?index=equities&symbol=" + urllib.parse.quote(sym))
                items += parse_nse_announcements(ann, sym)
                events[sym] = parse_events(ev, sym, now.date())
            except M.DataError as e:
                notes.append("NSE filings for %s skipped: %s" % (sym, e))
        if not a.no_headlines:
            if a.offline:
                t = off(sym + "-yahoo.xml")
                if t:
                    items += parse_rss(t, "Yahoo Finance", sym)
            else:
                try:
                    url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=IN&lang=en-IN" % urllib.parse.quote(M.to_yahoo(sym))
                    items += parse_rss(M.http_get(url, headers={"User-Agent": M.BROWSER_UA}), "Yahoo Finance", sym)
                except Exception as e:
                    notes.append("Yahoo headlines for %s skipped: %s" % (sym, e))
                try:
                    q = urllib.parse.quote('"%s" share when:2d' % sym)
                    url = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en" % q
                    items += parse_rss(M.http_get(url, headers={"User-Agent": M.BROWSER_UA}), "Google News", sym)
                except Exception as e:
                    notes.append("Google News for %s skipped: %s" % (sym, e))
                M.SLEEP(0.4)
        mv = move(sym, a.offline if a.offline and os.path.isdir(a.offline) else None)
        if mv:
            moves[sym] = mv
    fresh = []
    for it in items:
        if it["time"]:
            t = dt.datetime.fromisoformat(it["time"])
            if t < since or t > now + dt.timedelta(minutes=5):
                continue
        k = key_of(it["symbol"], it["title"], it.get("link"))
        it["key"] = k
        if k in seen and not a.all:
            continue
        fresh.append(it)
    # dedupe identical titles across feeds
    uniq, titles = [], set()
    for it in sorted(fresh, key=lambda x: x["time"] or "", reverse=True):
        tk = (it["symbol"], re.sub(r"\W+", " ", it["title"].lower())[:90])
        if tk in titles:
            continue
        titles.add(tk)
        uniq.append(it)
    if not a.dry_run:
        for it in uniq:
            seen[it["key"]] = now.date().isoformat()
        cutoff = (now.date() - dt.timedelta(days=30)).isoformat()
        state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
        M.write_json(M.tpath("state", "news.json"), state)
    if a.json:
        print(json.dumps({"as_of": now.isoformat(timespec="minutes"), "items": uniq, "events": events,
                          "moves": moves, "notes": notes}, indent=2))
        return 0 if uniq else 1
    print("News check %s IST, last %g hours, %d ticker(s). %d new item(s)." % (
        now.strftime("%Y-%m-%d %H:%M"), a.hours, len(syms), len(uniq)))
    for sym in syms:
        mv = moves.get(sym)
        line = sym
        if mv:
            line += "  %s %+.2f%% vs previous close %s at %s IST%s" % (
                M.px(mv["price"]), mv["pct"], M.px(mv["prev_close"]), mv["time"], "  MOVING" if abs(mv["pct"]) >= a.move_pct else "")
        print("\n" + line)
        for e in events.get(sym, []):
            dd = dt.date.fromisoformat(e["date"])
            print("  UPCOMING %s: board meeting, %s%s" % (M.day_label(dd), e["purpose"],
                  "  <- results inside a few sessions: a gap can jump any stop" if "result" in e["purpose"].lower() else ""))
        mine = [it for it in uniq if it["symbol"] == sym]
        for it in mine[:12]:
            t = it["time"][11:16] if it["time"] else "--:--"
            dd = it["time"][:10] if it["time"] else ""
            print("  %s%s %s %s [%s] %s" % ("!" if it.get("important") else " ", dd[5:], t, it["source"][:18],
                                           ", ".join(it["tags"]) or "-", it["title"][:150]))
            if it.get("link"):
                print("              " + it["link"])
        if not mine:
            print("  no new items")
        if mv and abs(mv["pct"]) >= a.move_pct and not mine:
            print("  A %+.1f%% move with no new headline or filing: say so out loud." % mv["pct"])
    for n in notes:
        print("NOTE: " + n)
    print("\nHeadlines are leads, not facts: open the filing or the story before relying on it.")
    return 0 if uniq else 1


if __name__ == "__main__":
    sys.exit(main())
