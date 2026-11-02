---
name: in-trader-budget
description: >-
  Budget Manager for Indian intraday trades. Sizes every position to your capital
  and your max loss per trade in rupees, with the real Indian costs inside the max
  loss (brokerage, STT, exchange charges, SEBI fee, stamp duty, GST). Reads the plan
  from in-trader-exit, finds the whole shares that fit four limits (max loss,
  position cap, max order, cash after your buffer), says which limit decided it, and
  writes two Kite-shaped orders to trader/orders.json: an MIS BUY and, for after the
  fill, an SL-M protective stop. A stop too far away is a plain refusal. Nothing is
  placed. Use when the user says "how many shares", "size this trade", "how much
  should I buy", "I have 1 lakh", "I only want to risk 500 a trade", "set my
  rules", "what are the charges", or after in-trader-exit writes a plan.
argument-hint: "[capital in rupees]"
---

# in-trader-budget

Turns a plan ("buy RELIANCE at 1234.50, stop 1223.10") into an exact order ("buy
39 shares"), inside rules the user sets once. The stop decides the size: the
further the stop, the fewer shares. Charges are real money on every round trip in
India, so the max loss includes them. It writes a proposal only.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                       # trader/plan.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write               # write trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit --write       # LIMIT entry at the plan's entry
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 1234.00 --json
```

## Step 1: set the rules once

If `trader/config.json` does not exist, copy `config.example.json` from this
folder to `trader/config.json` and ask the user, in plain words:

- **capital_inr**: the money this is for. Only money they can afford to lose.
- **cash_buffer_pct** (10), **max_loss_per_trade_inr** (500), **max_position_pct**
  (50), **max_order_inr** (50,000), **min_order_inr** (500).
- Day limits in-trader-risk enforces: **max_daily_loss_inr** (1,500),
  **max_trades_per_day** (3), **min_reward_risk** (1.0), **require_stop**,
  **no_entries_before/after** ("09:30" / "14:45") and **flat_by** ("15:05"), IST.
- **product** "MIS" (intraday, squared off by the broker at 15:25) and
  **leverage** 1. MIS offers up to 5x at Zerodha; this pack uses only your cash
  unless `allow_margin` is true and the user says so.
- **charges**: Zerodha's intraday rates are built in (brokerage 0.03 % or ₹20 an
  order, whichever is lower; STT 0.025 % on the sell; NSE 0.00307 % / BSE
  0.00375 %; SEBI ₹10 a crore; stamp 0.003 % on the buy; GST 18 % on brokerage +
  exchange + SEBI). Another broker: override any key, for example
  `"charges": {"brokerage_cap": 0}` for a zero-brokerage plan.
- **blocked**: symbols they never want to trade. Keep **paper** true for now.

## Step 2: size the trade

| limit | shares |
| --- | --- |
| max loss | the most shares where shares x (entry − stop) + charges at the stop ≤ max loss |
| position cap | capital x max_position_pct / entry |
| max order | max_order_inr / entry |
| cash | (capital − buffer) x leverage / entry, never more than `trader/portfolio.json` cash |

The entry it sizes at: the limit price, or for a market order the plan's entry or
a fresher, higher quote from `trader/prices.json` (under 15 minutes old). A price
that ran up means a bigger loss at the same stop, so fewer shares.

It refuses and writes nothing when: zero shares, under the minimum order,
reward:risk under the minimum, the stop not below the entry, the target not above
it (the move already happened), a plan for another day, a blocked symbol, a short.

## The orders it writes

`trader/orders.json` holds two orders in the shape of Kite's `place_order`:

1. `BUY`, `product: MIS`, `order_type: MARKET` (or `LIMIT`), `validity: DAY`.
2. `SELL`, `order_type: SL-M`, `trigger_price` = the stop, marked `"after": 1`:
   placed only once the buy has filled, for the shares that filled.

The target is NOT a resting order. Zerodha has no bracket orders for equity, and
two open sells for the same shares (a stop and a target) can both fill and leave
you short. in-trader-alerts watches the target; selling there is a new ticket and
a new yes. `why` and `plan` are notes, never sent to the broker.

## Example: RELIANCE, Monday 2 November 2026, ₹1,00,000 capital, ₹500 max loss

```
Sizing RELIANCE at ₹1,234.50 (the plan's entry): stop 1223.10, target 1245.90, risk 11.40 a share, reward:risk 1.00.
  max loss      ₹500.00 / 11.40 risk a share, charges included                39  <- decides it
  position cap  50% of ₹1,00,000 = ₹50,000 / 1234.50                          40
  max order     ₹50,000 / 1234.50                                             40
  cash          (₹1,00,000 minus the ₹10,000 buffer) / 1234.50                72
39 shares = ₹48,145.50. If the stop fills at 1223.10: ₹444.60 on the shares + ₹50.88 charges = ₹495.48.
```

Note what the charges do at 1R: about ₹51 of a ₹445 move. Small targets on big
positions can be eaten by costs; say so when the target is under about 0.5 %.

## Rules

- Proposals only: this skill never calls a broker tool.
- Never size money the user has not said is for this. Every number comes from the config, the plan or a price.
- No projections: never say what a trade will make.

## What it never does

It never places, approves or schedules an order, never raises a limit on its own,
never shrinks a stop to fit more shares, and never sizes F&O, MTF or short positions.

<!-- safety:start -->
## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a rules check, not a recommendation. SEBI's study of FY2023 found about 7 in 10 individual intraday equity traders made a loss.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode never calls Kite at all: fills are simulated in `trader/`. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except in-trader-broker, and only when all three hold: in-trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the Kite order tools are set to "Needs approval". Never set an order tool to "Always allow".
- No F&O, options, MTF or leverage, and no short selling, unless the config allows it and the user confirms.
- The Kite login happens on Zerodha's own page. API keys, passwords, PINs and TOTP codes never go in the chat.
<!-- safety:end -->
