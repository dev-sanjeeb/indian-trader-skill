---
name: in-trader-scanner
description: >-
  Chart Scanner for the Indian market. Scans NSE charts for setups: opening-range
  breakouts after 9:15 IST, 20-day breakouts, bull flags, a reclaim of the 20-day
  average, oversold and oversold bounces. Builds the universe from NSE's F&O stock
  list (default, the ~218 liquid names), a Nifty index (50/100/200/500) or every
  EQ-series stock, keeps NSE's ASM/GSM surveillance list for the risk check, and
  writes trader/watchlist.json for in-trader-news and in-trader-entry. Free Yahoo
  data (SYMBOL.NS), bar by bar. Use when the user says "scan the market", "scan
  Nifty", "find me setups", "what is breaking out", "opening range breakout", "ORB
  scan", "bull flags", "oversold stocks", "pre-market scan", "build my watchlist",
  "what should I look at today", or at the start of a trading day.
argument-hint: "[universe | surveillance | daily | orb] [--at HH:MM]"
---

# in-trader-scanner

The first step of an intraday trade on NSE. It reads hundreds of free charts and
lists the ones that match a rule. A scan is a list of charts that match a rule,
not a list of stocks to buy. Most intraday traders in India lose money; the
scanner does not change that. It only saves you flipping through charts by hand.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                      # F&O stocks -> trader/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe --index nifty500     # or nifty50/100/200, midcap150, smallcap250, bank
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe --all                # every EQ/BE stock on NSE (EQUITY_L.csv)
python3 "${CLAUDE_SKILL_DIR}/scan.py" surveillance                  # ASM/GSM -> trader/surveillance.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                         # before 9:15 IST -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols RELIANCE,TCS,INFY
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                           # after 9:35 IST
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:00 --json
```

Flags: `--min-price 20`, `--min-volume` (daily, default 2,00,000 shares),
`--or-minutes 15`, `--max-confirm 200`, `--limit N`, `--watchlist FILE`,
`--now "2026-11-02 10:00"` (IST), `--offline PATH`, `--no-write`, `--show N`.
Exit code 0 when something matched, 1 otherwise.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/universe.txt` | `SYMBOL\|Name\|Series`. BE-series stocks (trade-to-trade, no intraday) are skipped by the scans |
| `trader/surveillance.json` | NSE ASM (long and short term) and GSM symbols; in-trader-risk blocks entries in them |
| `trader/watchlist.json` | `mode`, `as_of`, `hits[]`; in-trader-news and in-trader-entry read `hits[].symbol` |
| `trader/config.json` | `no_entries_after` (14:45 IST) for the ORB scan |

## The Indian session, as the tools see it

- Pre-open 9:00-9:08, regular session **9:15 to 15:30 IST**, no daylight saving.
- Since 3 August 2026, stocks with F&O contracts go into a **closing auction
  session (CAS) from 15:15**: no fresh orders 15:15-15:20, auction order entry
  15:20-15:30, **no stop-loss orders accepted**. Yahoo's 5-minute bars run 9:15 to
  the 15:15 bar, so a full day is 73 bars. The tools treat 15:20 as the end of
  continuous trading.
- Weekends and the NSE 2026 holidays are built in. Muhurat trading (Sun 8 Nov
  2026, 14:20-15:30) is a special session. The 2027 list is published by NSE in
  December: add it to `"extra_holidays"` in `trader/config.json` until then.

## The scans

**Universe.** Default: NSE's F&O underlyings (`/api/master-quote`, about 218
names), with a built-in copy from 2026-11-02 if NSE does not answer. They are
the most liquid stocks, which is what an intraday scan needs.

**Daily (before the open).** Yahoo's spark endpoint, 20 symbols a request, three
months of daily closes. Rules on closes: `breakout_20d` (last close above every
close of the 20 sessions before), `bull_flag` (up over 10 % in the 10 sessions
before the last 5, then the last 5 inside a 5 % range), `reclaim_ma20`,
`oversold` (RSI 14 under 30), `oversold_bounce`. Hits are listed by turnover.

**Opening-range breakout (during the session).** The range is the first 15
minutes (the 9:15, 9:20 and 9:25 bars). A hit is the first completed 5-minute bar
that CLOSES above the range high. Stage 1 reads spark closes for everyone; stage 2
confirms the candidates on real highs and lows, most traded first, at most
`--max-confirm` (200). A partial scan is said as partial. A chart counts only if
every bar from 9:15 to the cutoff is there.

## Steps

1. Once a week: `scan.py universe`, and `scan.py surveillance` each morning.
2. Before 9:15: `scan.py daily`. Tell the user the counts and the top few per setup.
3. After 9:35 (10:00 is common): `scan.py orb`. Say how many usable charts broke
   their range and when; a later hit is closer to the price now.
4. The user picks one chart. Hand it on: `/in-trader-news SYMBOL`, then
   `/in-trader-entry SYMBOL`. Never pick for them.

## Example: Monday 2 November 2026, real data

RELIANCE reported results on Friday 30 October after the close and opened Monday
up sharply. `scan.py orb --symbols RELIANCE --now "2026-11-02 10:00"`:

```
1 of 1 charts closed above their 15-minute opening-range high by 10:00 AM IST:
   9:35 AM  RELIANCE      ₹1,234.50  range 1214.60 to 1231.60  +0.24% over
```

## Rules

- Say what was scanned: how many symbols, how many charts came back, how many
  were usable, and the time of the data.
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L or a profit figure. A hit is stale once the price moves: re-run.

## What it never does

It never places, sizes or checks an order, never says which stock to buy, never
calls the data real time, and never promises that a setup works.

<!-- safety:start -->
## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a rules check, not a recommendation. SEBI's study of FY2023 found about 7 in 10 individual intraday equity traders made a loss.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode never calls Kite at all: fills are simulated in `trader/`. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except in-trader-broker, and only when all three hold: in-trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the Kite order tools are set to "Needs approval". Never set an order tool to "Always allow".
- No F&O, options, MTF or leverage, and no short selling, unless the config allows it and the user confirms.
- The Kite login happens on Zerodha's own page. API keys, passwords, PINs and TOTP codes never go in the chat.
<!-- safety:end -->
