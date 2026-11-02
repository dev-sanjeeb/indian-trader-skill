---
name: in-trader-risk
description: >-
  Risk Manager for Indian intraday orders. Checks every order against your limits
  and stops anything over them before it can reach Zerodha: a stop is required, the
  loss at the stop including Indian charges must fit your max loss per trade,
  reward:risk must meet your minimum, the day's total risk must fit your daily loss
  limit, trades per day, no new entries outside your IST window or when NSE is
  closed, no entries in stocks under NSE ASM/GSM surveillance, prices on the NSE
  tick, no F&O, MTF or short sales unless allowed, position size and cash. Getting
  out is never blocked by a day limit. Prints PASS or BLOCK with the reason and
  records verdicts so in-trader-broker only shows an order that passed. Use when the
  user says "check my order", "is this safe", "risk check", "can I take this trade",
  "how much have I risked today", or before in-trader-broker, always.
argument-hint: "[path to orders.json]"
---

# in-trader-risk

The gate between a proposal and the broker. A BLOCK is final for that order: it
does not go to the user for a yes, and it does not go to Zerodha. These limits
keep each loss and each day's losses small. They do not make a trade win.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                            # writes trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-11-02 09:36"   # IST
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | proposed orders (in-trader-budget, or in-trader-broker's flatten) |
| `trader/config.json` | the limits |
| `trader/portfolio.json` | cash and positions; if missing, a fresh account with your capital |
| `trader/prices.json` | a fresh quote raises the entry the risk is measured from |
| `trader/surveillance.json` | NSE ASM/GSM symbols (in-trader-scanner `surveillance`), plus `"surveillance"` in the config |
| `trader/state/broker.json` | what was placed today: trades, daily risk, duplicates |
| `trader/state/risk.json` | the verdicts, each with a fingerprint of the exact order |

## Entries and exits

An **entry** opens a position (a BUY). An **exit** only reduces what you hold: a
SELL within your holdings, or the protective SL-M stop for an entry in the same
file. Exits are checked for format, asset and short sales only; every other rule
becomes a warning, never a BLOCK. Getting out must always be possible.

## The checks

| check | blocks when |
| --- | --- |
| format | no symbol, side not BUY/SELL, quantity not whole and positive, order type not MARKET/LIMIT/SL/SL-M, a LIMIT/SL without price, an SL/SL-M without trigger, a price off the NSE tick |
| asset | exchange not NSE/BSE cash; an option or future (`...26NOV1300CE`, `...FUT`) unless allowed; NRML or MTF products unless allowed |
| short | a SELL beyond your holdings (`allow_short` false) |
| blocked / surveillance | the symbol is on your blocked list, or under NSE ASM/GSM |
| size / position / cash | under the minimum or over the maximum order; over `max_position_pct`; more than your cash after the buffer (no margin) |
| stop | no stop while `require_stop` is true; a stop at or above the entry |
| loss | qty x (entry − stop) + charges at the stop over `max_loss_per_trade_inr` |
| reward:risk | (target − entry) / (entry − stop) under `min_reward_risk` |
| daily loss | today's max losses at the stops plus this one over `max_daily_loss_inr` |
| trades / daily limit | `max_trades_per_day` entries or `max_orders_per_day` orders already today |
| window | NSE closed (weekend, holiday), outside continuous trading, before `no_entries_before` or after `no_entries_after` IST |
| duplicate | the same symbol and side twice in a batch, or an entry already placed today |

- **The entry it measures from:** the limit price; for a market order the HIGHER
  of the plan's entry and a fresh quote (under 15 minutes old).
- **Daily loss** counts the full max loss of every entry placed today, win or lose.
- **Warnings** (said, not blocking): a LIVE account, a stop that lives only in the
  plan, a quote too old to use, CNC (delivery) instead of MIS, a stop-loss order
  sent after 15:15 (not accepted in the closing auction).
- India has no pattern-day-trader rule; the daily limits are yours.

## Steps

1. If the price may have moved, refresh it: `alerts.py quote SYMBOL --write`.
2. `check.py`. Exit 0 = every order passed.
3. Tell the user order by order: max loss at the stop with charges, reward:risk,
   and how much of today's limits it uses. For a BLOCK, the reason and the fix
   (fewer shares, a closer stop, wait for the window, skip it). Never change a limit yourself.
4. Any change to an order means a new check: in-trader-broker matches verdicts by fingerprint.

## Example: RELIANCE, 2 November 2026, 9:36 IST

```
PASS  #1 buy RELIANCE 39 shares, entry
          entry 1234.50 (the plan's entry), stop 1223.10, target 1245.90: risk 11.40 a share
          max loss ₹495.48 incl. 50.88 charges (limit ₹500), reward:risk 1.00 (min 1)
          today before this: 0 of 3 trades, ₹0.00 of ₹1,500 daily loss
PASS  #2 sell RELIANCE 39 shares, stop
```

At 9:20 the same order is blocked: "window: no new entries before 09:30 IST".
With 40 shares it is blocked: ₹508.19 at the stop, over the ₹500 limit.

## What it never does

It never places an order, edits an order to make it pass, loosens a limit,
blocks a sell that only gets the user out, or treats a PASS as the user's yes.

<!-- safety:start -->
## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a rules check, not a recommendation. SEBI's study of FY2023 found about 7 in 10 individual intraday equity traders made a loss.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode never calls Kite at all: fills are simulated in `trader/`. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except in-trader-broker, and only when all three hold: in-trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the Kite order tools are set to "Needs approval". Never set an order tool to "Always allow".
- No F&O, options, MTF or leverage, and no short selling, unless the config allows it and the user confirms.
- The Kite login happens on Zerodha's own page. API keys, passwords, PINs and TOTP codes never go in the chat.
<!-- safety:end -->
