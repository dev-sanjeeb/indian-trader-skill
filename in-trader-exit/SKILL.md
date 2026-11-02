---
name: in-trader-exit
description: >-
  Exit Planner for NSE/BSE intraday trades. Sets the stop and the target before
  you enter: reads the entry from in-trader-entry (or a price you give), puts the
  stop at the opening-range midpoint by default (or the range low, your price, a
  percent, or a multiple of the ATR), rounds it down to the NSE tick for that price
  band, sets the target at 2R (or 1R, or your price) and a flat-by time of 15:05 IST,
  before the 15:15 closing auction. Refuses a stop at or above the entry, a target at
  or below it, or a stop too tight for the spread, and says why. Writes
  trader/plan.json. Long only. Use when the user says "where's my stop", "set my
  stop loss and target", "plan the exit", "when do I get out", "what's my R",
  "risk reward", or right after in-trader-entry triggers.
argument-hint: "[--stop or-mid|or-low|price:X|pct:X|atr:K] [--target 2R|1R|price:X]"
---

# in-trader-exit

The stop is where the setup has failed. The target is where you take what you came
for. Both are set BEFORE the entry, written down and handed on. A stop is a plan,
not a guarantee: a gap, a circuit limit or a fast market can fill past it.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                          # trader/entry.json: midpoint stop, 2R
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-mid --target 1R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:1.5           # needs the session's bars
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol RELIANCE --entry 1234.50 --or-high 1231.60 --or-low 1214.60 --entry-time 09:35
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

Other flags: `--flat-by 15:05`, `--tick 0.05` (override), `--json`, `--now`,
`--offline FILE`, `--entry PRICE` to plan ahead on a waiting entry.

## Stops, targets and ticks

| stop | where it goes |
| --- | --- |
| `or-mid` | the opening-range midpoint (default for an opening-range breakout) |
| `or-low` | the range low: wider, so fewer shares for the same max loss |
| `price:X` / `pct:X` | your price / X percent under the entry |
| `atr:K` | K x the 14-bar ATR of the session's bars up to the entry bar |

- **NSE ticks** (from 15 April 2025): under ₹250 → ₹0.01; ₹250-1,000 → ₹0.05;
  ₹1,000-5,000 → ₹0.10; ₹5,000-10,000 → ₹0.50; ₹10,000-20,000 → ₹1; above → ₹5.
  NSE reviews each stock's tick from its price, so if Kite rejects a price for
  its tick, pass `--tick`.
- The stop rounds DOWN to the tick (away from the entry). Risk = entry − stop.
  Target = entry + R x risk, rounded to the tick.
- **Refused, with the reason:** stop at or above the entry; target at or below it;
  risk under 0.05 % of the price or under 2 ticks; an entry that has not triggered
  (unless `--entry`); a short.
- **Flat by 15:05 IST** by default: out before the 15:15 closing auction (no
  stop-loss orders there) and well before Zerodha's 15:25 MIS auto square-off,
  which costs extra. A flat-by after 15:10 gets a warning.

## Steps

1. Run it right after `/in-trader-entry` triggers (or with `--entry` to plan ahead).
2. Default stop for an ORB unless the user names another; a level setup needs one: ask.
3. `exit.py plan --write`. Read back entry, stop and its rule, target, risk a
   share, reward:risk, flat by.
4. If it refuses, say why and the fix. Never loosen anything on your own.
5. Hand off to `/in-trader-timemachine`, then `/in-trader-budget`. Offer `/in-trader-alerts`.

## Example: RELIANCE, Monday 2 November 2026

```
Exit plan: RELIANCE long, Mon 2026-11-02, opening-range breakout on 5-minute bars
  Entry         ₹1,234.50 at 9:35 AM IST (bar 4)
  Stop          ₹1,223.10  opening-range midpoint: (1231.60 + 1214.60) / 2 = 1223.1, rounded down to the 0.10 tick
  Target        ₹1,245.90  1R (one times the risk)
  Risk a share  ₹11.40 (0.92% of the entry)
  Reward:risk   1
  Flat by       15:05 IST, win or lose: out before the 3:15 PM closing auction, no overnight hold
```

## Rules

- Stop and target are set before the entry, never after. Never move a stop further away.
- Plain numbers only: never a P&L or a return. A 1R target is not a prediction.

## What it never does

It never places an order, never sizes a position, never widens a stop to make a
plan pass, and never calls a stop a guarantee.

<!-- safety:start -->
## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a rules check, not a recommendation. SEBI's study of FY2023 found about 7 in 10 individual intraday equity traders made a loss.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode never calls Kite at all: fills are simulated in `trader/`. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except in-trader-broker, and only when all three hold: in-trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the Kite order tools are set to "Needs approval". Never set an order tool to "Always allow".
- No F&O, options, MTF or leverage, and no short selling, unless the config allows it and the user confirms.
- The Kite login happens on Zerodha's own page. API keys, passwords, PINs and TOTP codes never go in the chat.
<!-- safety:end -->
