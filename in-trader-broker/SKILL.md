---
name: in-trader-broker
description: >-
  Order Executor for Zerodha Kite. Sends approved orders to your broker, paper
  trading by default, never without your yes. Shows each order as a plain ticket
  (MIS buy, the SL-M protective stop to place after the fill, the max loss with
  charges) plus the exact JSON for Kite's place_order, records your yes word for
  word, then Claude's own Allow once / Deny card asks again. Zerodha has no paper
  account, so paper mode simulates fills locally and never calls Kite. Builds the
  sell ticket that gets you flat by 15:05 IST, records fills, and logs each trade's
  max loss for the daily limit. Covers connecting Zerodha's official Kite MCP server
  and setting its order tools to "Needs approval". Use when the user says "place the
  order", "buy it", "execute", "send it to Zerodha", "square off", "close my
  position", "get me out", "connect Kite", "set up paper trading", or after
  in-trader-risk passes.
argument-hint: "[order number]"
---

# in-trader-broker

The only skill in this pack that can lead to a real order, so it is the strictest.
An order reaches NSE only after three separate gates, every time:

1. **in-trader-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.
3. **The user clicked Allow once** on Claude's card for Kite's `place_order`,
   because that tool is set to "Needs approval".

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                     # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" paper --index 1          # PAPER: simulated fill, Kite not called
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --order-id ID --filled-qty 39 --filled-price 1234.60
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol RELIANCE --side sell --qty 39 --price 1245.90
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol RELIANCE --qty 39
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to a broker. It renders tickets, checks a reply is a real
yes for that order (it accepts "yes", "haan", "yes, place it"; it refuses "sure",
"ok", "yes to all", or a yes naming another stock or quantity), keeps the log in
`trader/state/broker.json` and the paper portfolio in `trader/portfolio.json`.

## Paper mode (the default)

Zerodha has no paper or sandbox account. With `"paper": true`, Claude never calls
any Kite order tool. After the yes, `ticket.py paper --index N` records a simulated
fill (at the fresh quote in `trader/prices.json`, the limit price, or the plan's
entry; `--price` to set it). The SL-M stop "rests" in paper mode: when
in-trader-alerts rings the stop or the target, record the exit with `ticket.py fill`.
Run paper mode for a few weeks before the user even considers going live.

## Setup: Zerodha's Kite MCP server

Zerodha publishes an official MCP server, github.com/zerodha/kite-mcp-server,
hosted at `https://mcp.kite.trade/mcp`. Its tools include `login`, `get_profile`,
`get_margins`, `get_holdings`, `get_positions`, `get_ltp`, `get_quotes`, `get_ohlc`,
`get_historical_data`, `search_instruments`, `place_order`, `modify_order`,
`cancel_order`, `get_orders`, `get_trades`, `get_order_history` and the GTT tools.

1. In Claude: Customize > Connectors > Add custom connector, URL
   `https://mcp.kite.trade/mcp`. Or in Claude Desktop's config (Settings >
   Developer > Edit Config), the block in `claude_desktop_config.example.json`
   here (`npx mcp-remote https://mcp.kite.trade/mcp`; needs Node.js).
2. Ask Claude to call `login`. It returns a Zerodha link: the user signs in on
   Zerodha's own page. **Passwords, PINs and TOTP codes never go in the chat.**
3. **Tool permissions** (Customize > Connectors > Kite):
   - `place_order`, `modify_order`, `cancel_order`, `place_gtt_order`,
     `modify_gtt_order`, `delete_gtt_order`: **Needs approval**. Never Always allow.
   - read-only tools (`get_*`, `search_instruments`): Always allow is fine.
4. Zerodha's README says the hosted server leaves out some "potentially
   destructive trading operations". If `place_order` is not in the connector's
   tool list, the hosted server will not place orders for you: either self-host
   it (same README), or the user places the order by hand in Kite from the
   ticket. Never work around a missing tool.
5. Check it: `get_profile` and `get_margins` (read only).

In Claude Code, keep order tools on ask in `.claude/settings.json`:
`"permissions": {"ask": ["mcp__kite__place_order", "mcp__kite__modify_order", "mcp__kite__cancel_order"]}`.

Other brokers (Upstox, Angel One, Dhan, Fyers...): the tickets are plain Kite
JSON; map the same fields to that broker's connector, with the same three gates.

## Steps: the entry

1. `ticket.py show`. Only READY tickets go to the user; NOT READY or BLOCKED go back to `/in-trader-risk`.
2. Show ONE ticket and ask: "Place this order? Reply yes or no." One order per question.
3. `ticket.py approve --index N --reply "<the user's words, verbatim>"`. If it says
   "Not recorded", ask again. Never turn a reply into a yes yourself.
4. Paper: `ticket.py paper --index N`. Live: call `place_order` with exactly the
   ticket's JSON; Claude's card appears; then `ticket.py result ...` with the order id
   and the fill from `get_order_history` / `get_positions`.
5. Then the protective stop (order 2, `"after": 1`): it becomes READY only after
   the buy is recorded as filled. Show it, get its own yes, place it the same way,
   for the quantity that actually filled.
6. A failed order is not retried without a new check and a new yes.

## Steps: out by 15:05 IST

- in-trader-alerts rings the stop, the target and "flat by".
- Stop filled: record it with `ticket.py fill`.
- Target hit, or flat-by time: `get_orders` to find the open SL-M, cancel it
  (`cancel_order`, its own yes), then `ticket.py flatten --symbol S --qty Q`, then
  `/in-trader-risk` (an exit is never blocked by day limits), then `ticket.py show`
  and the user's yes. Cancel first, or the stop and the sell can both fill.
- Be flat before 15:15: the closing auction does not accept stop-loss orders, and
  Zerodha's 15:25 auto square-off of MIS positions adds a charge.

## Example: the RELIANCE ticket, 2 November 2026

```
ORDER 1 of 2, PAPER (simulated, Kite is not called), Zerodha
  BUY 39 RELIANCE on NSE, market, intraday (MIS), good for today
  then: protective stop 1223.10 (order 2), target 1245.90 watched by alerts
  max loss about ₹495.48 if the stop fills at 1223.10, charges included (it can fill worse in a fast market)
  READY: in-trader-risk PASS, waiting for your yes
```

## What it never does

- Never places an order without all three gates, never two orders on one yes, never from a scheduled or background task.
- Never asks for, reads, stores or repeats API keys, passwords, PINs or TOTP codes.
- Never switches `"paper"` to false. The user does that themselves, in their config.
- Never promises a fill price: a market order and an SL-M fill at what the market gives.

<!-- safety:start -->
## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a rules check, not a recommendation. SEBI's study of FY2023 found about 7 in 10 individual intraday equity traders made a loss.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode never calls Kite at all: fills are simulated in `trader/`. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except in-trader-broker, and only when all three hold: in-trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the Kite order tools are set to "Needs approval". Never set an order tool to "Always allow".
- No F&O, options, MTF or leverage, and no short selling, unless the config allows it and the user confirms.
- The Kite login happens on Zerodha's own page. API keys, passwords, PINs and TOTP codes never go in the chat.
<!-- safety:end -->
