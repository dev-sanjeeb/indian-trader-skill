---
name: in-trader-insiders
description: >-
  Insider and Big-Money Tracker for NSE, the Indian answer to a Congress-trades
  tracker. Reads the public SEBI insider-trading (PIT) disclosures of promoters,
  directors, KMP and their relatives for a company, and NSE's bulk and block deals,
  flags promoter market buys, promoter sells, pledges and late filings, follows the
  well-known investors you name (Jhunjhunwala, Kacholia, Kedia, Dolly Khanna,
  Damani... in config "watch_investors"), and alerts once per new filing. Use when
  the user says "what are promoters buying", "insider trading in RELIANCE",
  "promoter buying", "bulk deals today", "block deals", "what is Ashish Kacholia
  buying", "track big investors", "superstar portfolio", "did anyone big buy X", or
  "run the insiders skill".
argument-hint: "[pit SYMBOL | deals | watch]"
---

# in-trader-insiders

Promoters, directors and key managerial people must tell the exchange when they
trade their own company's shares, and the exchange publishes every bulk and block
deal the same evening. This skill reads both, notices what is new, and reads it
for you.

It is fast. It is not early. A SEBI PIT disclosure is due within 2 trading days of
the trade, and the company has 2 more to tell the exchange; a bulk deal is
published after the close. By the time anyone reads them the trade is done. This
is public information, read quickly, never inside information. Say that every time.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/insiders.py" pit RELIANCE                    # last 365 days of PIT filings
python3 "${CLAUDE_SKILL_DIR}/insiders.py" pit ADANIENT --days 90
python3 "${CLAUDE_SKILL_DIR}/insiders.py" deals --days 5                  # bulk + block, biggest first
python3 "${CLAUDE_SKILL_DIR}/insiders.py" deals --type block --symbol ABCAPITAL
python3 "${CLAUDE_SKILL_DIR}/insiders.py" deals --client kacholia --days 30
python3 "${CLAUDE_SKILL_DIR}/insiders.py" watch                           # only what is new
```

## What it reads and writes

- NSE `/api/corporates-pit` (SEBI PIT Regulations 2015, Reg. 7(2) disclosures):
  person, category (Promoter, Promoter Group, Director, KMP, Immediate relative),
  buy/sell/pledge, mode (market purchase, off market, ESOP...), shares, value,
  holding before and after, trade and filing dates, the XBRL link.
- NSE `/api/historicalOR/bulk-block-short-deals`: bulk deals (one client trading
  more than 0.5 % of a company's shares in a day) and block deals (single trades
  of ₹10 crore or more in the block window).
- `trader/config.json` `"watch_investors"`: names to follow in deals (all words of
  a name must match the client name).
- Writes `trader/state/insiders.json` (what was shown, so each item alerts once).

## The rules

- **Quote the filing.** Every row comes from NSE, with its link. Portfolio
  trackers on the web can lag or mislabel; the filing wins.
- **Category and mode matter.** A promoter's market purchase is the one people
  watch. Off-market transfers between family members, ESOP allotments and
  gifts are not buying in the market: say which it was.
- **Say the delay.** Each PIT row shows trading days from the trade to the filing;
  over 4 is flagged LATE.
- **Pledges matter.** A promoter pledging shares is a risk flag, not a trade.
- **Bulk deals are noisy.** Brokers, arbitrage desks and HFT firms (AlphaGrep,
  for example) appear on both sides of the same stock the same day. A name on
  both sides is a round trip, not a view.
- **A big name is not a reason.** Whatever an investor bought is public and old;
  their price, size, time horizon and tax position are not yours.

## Steps

1. One company: `insiders.py pit SYMBOL`. Lead with promoter market buys/sells and pledges.
2. The market: `insiders.py deals --days 5`, biggest first; filter by `--symbol` or `--client`.
3. On a schedule (after 18:00 IST, when NSE posts the deals): `insiders.py watch`.
4. Say what was filed, by whom, how much, at what price, when, the delay, the link,
   and that it is public and old news. Never "they know something".

## Example: real NSE data

```
  filed 03-Oct-2022 18:53  Spitze Trade and Investment  Promoter Group     Buy     336,000 sh  Rs 119.73 cr   at ~3563.36  (0.32 to 0.35%)  PROMOTER MARKET BUY
        Market Purchase, traded 28-Sep-2022, filed 3 trading days later.
  21-OCT-2026 block ABCAPITAL    BUY     3,066,761 sh at    366.00 = Rs 112.24 cr   PI OPPORTUNITIES AIF V LLP
  21-OCT-2026 block ABCAPITAL    SELL    3,066,761 sh at    366.00 = Rs 112.24 cr   PRAZIM TRADING AND INVESTMENT COMPANY PRIVATE LIMITED
```

## What it never does

Never presents a filing as inside information or a tip, never says to copy a
trade, never estimates what a filing does not say, and never hammers NSE.

<!-- safety:start -->
## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a rules check, not a recommendation. SEBI's study of FY2023 found about 7 in 10 individual intraday equity traders made a loss.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode never calls Kite at all: fills are simulated in `trader/`. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except in-trader-broker, and only when all three hold: in-trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the Kite order tools are set to "Needs approval". Never set an order tool to "Always allow".
- No F&O, options, MTF or leverage, and no short selling, unless the config allows it and the user confirms.
- The Kite login happens on Zerodha's own page. API keys, passwords, PINs and TOTP codes never go in the chat.
<!-- safety:end -->
