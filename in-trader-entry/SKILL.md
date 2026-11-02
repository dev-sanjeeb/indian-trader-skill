---
name: in-trader-entry
description: >-
  Entry Timer for NSE/BSE stocks. Watches a setup bar by bar and tells you the
  moment to get in: builds the 15-minute opening range from 9:15 IST and calls the
  entry on the first completed 1-minute or 5-minute bar that CLOSES above the range
  high, or above a level you give, with an optional volume check. Says waiting and
  how far, triggered with the time and the price, expired, or not open yet, knows
  NSE holidays and Muhurat trading, and writes trader/entry.json for in-trader-exit.
  Long side only. It never places an order. Use when the user says "tell me when to
  get in", "watch RELIANCE", "has it broken out", "did it break the opening range",
  "entry signal", "time my entry", "check my watchlist", or after in-trader-scanner
  and in-trader-news, before in-trader-exit.
argument-hint: "[SYMBOL] [--setup orb|level] [--interval 5m|1m]"
---

# in-trader-entry

The Entry Timer turns a setup into one moment: the bar that confirms it. A price
that pokes above the high in the middle of a bar is not an entry. A bar that
CLOSES above it is. It says the time and the price, writes them down for the
Exit Planner, and stops. It never buys anything.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE                 # 15-minute range, 5-minute bars
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --write         # also save trader/entry.json
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TCS --setup level --level 2512.50
python3 "${CLAUDE_SKILL_DIR}/entry.py" check SBIN --interval 1m --min-volume-x 1.5
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch RELIANCE --until 14:45   # one line per closed bar
python3 "${CLAUDE_SKILL_DIR}/entry.py" watchlist                      # every hit in trader/watchlist.json
```

Other flags: `--or-minutes N`, `--exchange BSE` (or `SYMBOL.BO`), `--json`,
`--offline FILE`, `--now "2026-11-02 09:35"` (IST). With `--now` or `--offline`,
`watch` replays the day bar by bar on a simulated clock.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/watchlist.json` | the scanner's hits, for `watchlist` |
| `trader/config.json` | `no_entries_before` (09:30) and `no_entries_after` (14:45), IST |
| Yahoo chart API | today's bars for SYMBOL.NS: free, unofficial, can lag |
| `trader/entry.json` | symbol, setup, status, trigger time, bar, entry price, level, opening range |

## The rule

- **Opening range.** High and low of the first 15 minutes: the 9:15, 9:20 and
  9:25 five-minute bars (fifteen 1-minute bars with `--interval 1m`). The level to
  beat is the range high. A **level** setup uses a price you give.
- **The trigger** is the first completed bar after the range whose close is above
  the level. A wick is not a trigger; a close exactly at the level is not above it.
  The time is the bar's close time (the 9:30 bar closes at 9:35); the price is its close.
- **Only closed bars count.** Yahoo's live tick (like 13:16:50) is never a bar.
- **Volume, if asked.** `--min-volume-x 1.5` also needs the trigger bar's volume
  at 1.5x the range bars' average. The 9:15 bar holds the pre-open auction's
  volume, so 1.0 is already strict.
- **Time limits.** No entries before 9:30 or after 14:45 IST (config). The cutoff
  leaves room to be flat before the 15:15 closing auction, where stop-loss orders
  are not accepted. On Muhurat day the window is the special session.
- **Statuses.** Not open yet, range forming, waiting (and how far), triggered,
  expired, market closed (weekend, NSE holiday).

## Steps

1. Get the symbol from the user, or run `entry.py watchlist` after the scanner.
   Check `/in-trader-news` first: results, a block deal or an ASM listing change the picture.
2. `entry.py check SYMBOL`. Tell the user the status in one line.
3. To wait, run `entry.py watch SYMBOL --until 14:45` in the background (it wakes
   just after each bar closes and exits 0 on the trigger, writing `trader/entry.json`),
   or `entry.py check SYMBOL --write` on a `/loop` every 5 minutes. Keep the
   computer awake.
4. When it triggers, say the time and the price, and that nothing was placed. If
   the trigger is more than a bar old, say so: a late entry is a different trade.
5. Hand off to `/in-trader-exit` to set the stop and the target BEFORE anything is bought.

## Example: RELIANCE, Monday 2 November 2026 (real Yahoo bars)

At 9:34 the 9:30 bar is still open:

```
WAITING  last close ₹1,229.90 (09:25 bar), ₹1.70 under ₹1,231.60 (-0.14%).
The 09:30 bar is still forming (₹1,234.50 so far, closes 09:35); it does not count until it closes.
```

At 9:35:

```
Opening range 9:15-9:30: high ₹1,231.60, low ₹1,214.60 (3 of 3 bars).
TRIGGERED 9:35 AM at ₹1,234.50: the 9:30 bar (bar 4) closed above ₹1,231.60 (+0.24%). Volume 0.65x the range's average.
This is the moment to get in, if you take the trade. Nothing was placed.
```

## Rules

- Bar by bar on free Yahoo bars. They are unofficial and can lag; say so when a minute matters.
- A signal is information, not an order and not a promise.
- Long side only. One trigger per setup per day: the first close above.
- Never call an entry early because a bar looks like it will close above.

## What it never does

It never places an order, never sizes a position, never sets the stop, never moves
the level after the fact, never counts a bar that has not closed, and never runs
in-trader-broker from a background watch: nobody is there to say yes.

<!-- safety:start -->
## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a rules check, not a recommendation. SEBI's study of FY2023 found about 7 in 10 individual intraday equity traders made a loss.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode never calls Kite at all: fills are simulated in `trader/`. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except in-trader-broker, and only when all three hold: in-trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the Kite order tools are set to "Needs approval". Never set an order tool to "Always allow".
- No F&O, options, MTF or leverage, and no short selling, unless the config allows it and the user confirms.
- The Kite login happens on Zerodha's own page. API keys, passwords, PINs and TOTP codes never go in the chat.
<!-- safety:end -->
