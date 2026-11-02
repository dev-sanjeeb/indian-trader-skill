---
name: in-trader-alerts
description: >-
  Price Alerts for NSE/BSE. Rings when a price, a stop, a target, the opening bell
  or your flat-by time hits. Turns the trade plan into three alerts in one go (stop,
  target, "flat by" 15:05 IST), plus above/below levels, percent moves from the
  previous close and any time of day, each ringing once. Knows NSE hours, the 2026
  holidays, Muhurat trading and the 15:15 closing auction, works in IST itself,
  fetches free delayed Yahoo quotes (SYMBOL.NS) and writes trader/prices.json for
  sizing and the risk check. Use when the user says "alert me when", "tell me if
  RELIANCE hits", "watch my stop", "watch my trade", "remind me to square off",
  "is the market open", "is today a holiday", "when does NSE open", "get me a
  price", or right after in-trader-exit writes a plan.
argument-hint: "[symbol] [price]"
---

# in-trader-alerts

Watches the numbers so the user does not have to stare at a chart. An alert is
information, never an order: when a stop alert rings, nothing is sold by this skill.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                         # NSE open/closed, holiday, next session
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan               # stop, target, flat by from trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol RELIANCE --stop 1223.10
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol TCS --above 2550
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol SBIN --pct 3 --direction down
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --at 15:05 --label "flat by" --symbol RELIANCE
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                         # exit 0 = something rang
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote RELIANCE --write        # -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list | reset ID | remove ID
```

`--now "2026-11-02 15:05"` pins the clock (IST); `--offline FILE` reads a saved chart.

## Rule types

| type | rings when | rings again |
| --- | --- | --- |
| `above` / `target` | price at or above | after `reset`, or by itself with `--rearm` once it falls back |
| `below` / `stop` | price at or below | same |
| `pct_move` | moved `pct` % from the previous close, optional `direction` | once a day |
| `time` | the IST clock passed `at` on a trading day | once a day |
| `opening_bell` | NSE's session is open (9:15, or the Muhurat start) | once a day |

`--from-plan` rules carry the plan's date, so yesterday's stop never rings today.
On Muhurat day a `time` rule moves up to 15 minutes before the session's end.

## Quotes

Yahoo Finance's chart endpoint for SYMBOL.NS (or .BO), one request per symbol.
Free, unofficial and delayed: fine for alerts and sizing checks, never for timing
an order. Each price in `trader/prices.json` keeps its quote time; in-trader-risk
uses only quotes under 15 minutes old. If Yahoo is down, read the price from
Kite's `get_ltp` (read only) and write it into `trader/prices.json` as
`{"as_of": "2026-11-02T10:52:00+05:30", "prices": {"RELIANCE": 1253.40}}`.

## The NSE clock

Regular session 9:15 to 15:30 IST (pre-open 9:00-9:08); F&O stocks enter the
closing auction at 15:15. Closed on weekends and on the 2026 holidays: 15 Jan, 26
Jan, 3 Mar, 26 Mar, 31 Mar, 3 Apr, 14 Apr, 1 May, 28 May, 26 Jun, 14 Sep, 2 Oct,
20 Oct, 10 Nov, 24 Nov, 25 Dec. Muhurat trading on Sunday 8 November 2026,
14:20-15:30. For 2027, add NSE's list to `"extra_holidays"` in `trader/config.json`
when it is published; until then the clock says the year is unknown.

## Steps

1. Right after in-trader-exit writes the plan: `add --from-plan`. Confirm the three alerts back.
2. While the trade is open, `check` every few minutes from a scheduled task or `/loop 5m`.
   A check reads the latest delayed quote: a price can pass a level between two checks.
3. Say what rang, one line each. A stop alert means the SL-M at Zerodha has
   probably triggered: check `get_positions`, record it with in-trader-broker
   `fill`. A target or "flat by" alert means: cancel the SL-M, then flatten, risk
   check and the user's yes. Never act for them.

## Example: RELIANCE, 2 November 2026

```
Added  reliance-plan-stop     stop    RELIANCE at or below 1223.10 on 2026-11-02
Added  reliance-plan-target   target  RELIANCE at or above 1245.90 on 2026-11-02
Added  reliance-flat-by       time    15:05 IST: flat by (RELIANCE) on 2026-11-02
ALERT RELIANCE TARGET: RELIANCE is 1253.40 (quote 13:20 IST), at or above 1245.90. Take it? Cancel the SL-M first, then a MARKET sell: ticket.py flatten, in-trader-risk, your yes.
```

## What it never does

It never places, cancels or changes an order, never calls a quote live, and never
predicts where a price is going.

<!-- safety:start -->
## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a rules check, not a recommendation. SEBI's study of FY2023 found about 7 in 10 individual intraday equity traders made a loss.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode never calls Kite at all: fills are simulated in `trader/`. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except in-trader-broker, and only when all three hold: in-trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the Kite order tools are set to "Needs approval". Never set an order tool to "Always allow".
- No F&O, options, MTF or leverage, and no short selling, unless the config allows it and the user confirms.
- The Kite login happens on Zerodha's own page. API keys, passwords, PINs and TOTP codes never go in the chat.
<!-- safety:end -->
