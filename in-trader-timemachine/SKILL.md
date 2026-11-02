---
name: in-trader-timemachine
description: >-
  Time Machine for NSE intraday plans. Replays every possible outcome of a trade
  before you risk a rupee: takes the plan from in-trader-exit (entry, stop, target),
  rebuilds the rest of the session 10,000 times from the stock's own 5-minute bars
  over the last 60 days, and re-runs the same rule on every past session. Prints the
  odds of target first, stop first or neither by your flat-by time, where the price
  sits then, the average R, the real history, and one honest verdict. Use when the
  user says "run the time machine", "replay this trade", "what are the odds",
  "simulate this trade", "monte carlo", "backtest this setup", "how often does this
  hit the target", "is this a coin flip", or after in-trader-exit writes a plan.
argument-hint: "[path to plan.json, or SYMBOL]"
---

# in-trader-timemachine

Before anything is sized or sent, one question: if today plays out like the
stock's own last 60 days, how often does this plan hit the target first, the stop
first, or neither? It answers with 10,000 replays and with the real record of the
same rule. It is a simulation from the stock's own recent bars, not a prediction.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until 15:05          # trader/plan.json, seed 19
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until 15:05 --write  # also trader/timemachine.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol RELIANCE --date 2026-11-02 \
    --entry 1234.50 --stop 1223.10 --target 1245.90 --entry-time 09:35 --or-high 1231.60 --or-low 1214.60
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart                      # ASCII fan chart of the saved run
```

Other flags: `--replays N`, `--seed N` (19), `--window N` (2 bars),
`--min-sessions N` (20), `--offline FILE`, `--json`.

## How it works

1. **The pool.** One Yahoo request: `range=60d&interval=5m` for SYMBOL.NS. Only
   FULL sessions before the plan's date go in: all 73 bars from 9:15 to the 15:15
   bar (the end of continuous trading before the closing auction). Holidays,
   Muhurat sessions, days with a missing bar and today are left out.
2. **One replay.** Start at the entry price. For each bar left until `--until`
   (default 15:20; use your flat-by, 15:05), pick a past bar from the same time of
   day (plus or minus 2 bars) at random and scale its open/high/low/close ratios
   to the current price. Check the stop first, then the target: a bar that
   touches both counts as the stop.
3. **10,000 replays** give target first, stop first, neither (still open at the
   end) and green (target, or above the entry at the end). R is +target R or −1;
   otherwise the distance from the entry divided by the risk. A gap or a circuit
   through the stop still counts as −1R here; a real fill can be worse.
4. **The history.** The plan's own rule (same opening range, stop rule, target R,
   entry window) on each of those real sessions: what really happened.
5. **The verdict.** Among replays that hit a side, how often the target came
   first, against break-even for that R: 1 in (1 + R), so 50 % at 1R, 33 % at 2R.
   Within 5 points: "Close to a coin flip" (1R) or "Close to break-even". 5 to 15:
   "Leans toward". 15+: "Strongly toward".

Same plan, same data, same seed: the same numbers on any machine. Say the seed.

## Steps

1. Make sure `trader/plan.json` is today's plan from `/in-trader-exit`.
2. `timemachine.py run --until 15:05 --write`.
3. Tell the user in this order: the four odds, the median and 5-95 % range at the
   end, the average R, the history line, then the verdict line(s) exactly as printed, and the seed.
4. A coin flip is a coin flip: say so plainly. If the history and the replays disagree, say that too.
5. Say once that this is built from the last 60 days and is not a prediction:
   results, a block deal, an ASM listing or a circuit can do what those days never did.
6. If the user still wants the trade, hand off to `/in-trader-budget`.

## Example: RELIANCE, Monday 2 November 2026 (the 19 full sessions in the test fixture)

```
10,000 replays of the rest of the session, 9:35 AM to 3:05 PM (66 five-minute bars), seed 19.
  Plan: entry 1234.50, stop 1223.10, target 1245.90 (1R), risk 11.40 a share.
  target first   33.8 %
  stop first     47.1 %
  neither        19.1 %   still open at 3:05 PM
  green          43.1 %   target first, or above the entry at 3:05 PM
  Price at 3:05 PM: median 1228.60, 90 % of replays between 1223.10 and 1245.90.
  Average R: -0.136
History: the same rule on each of those 19 real sessions fired 12 times: 5 target, 5 stop, 2 neither. Average R -0.101.
Leans toward the stop: target first 33.8 % vs stop first 47.1 %.
```

The real day hit the target at 10:25 AM. One day is one draw; the replays said
the odds leaned the other way. Both statements are true, and the user should hear both.

## Rules

- Every number comes from the run. Never round a coin flip up into an edge.
- Repeat the verdict lines, do not rewrite them; they already weigh the target's R.
- 5-minute bars only, closed bars only, never today's bars in the pool.

## What it never does

It never places an order, sizes a position, changes the plan, prints a P&L, or
calls a result a sure thing.

<!-- safety:start -->
## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a rules check, not a recommendation. SEBI's study of FY2023 found about 7 in 10 individual intraday equity traders made a loss.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode never calls Kite at all: fills are simulated in `trader/`. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except in-trader-broker, and only when all three hold: in-trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the Kite order tools are set to "Needs approval". Never set an order tool to "Always allow".
- No F&O, options, MTF or leverage, and no short selling, unless the config allows it and the user confirms.
- The Kite login happens on Zerodha's own page. API keys, passwords, PINs and TOTP codes never go in the chat.
<!-- safety:end -->
