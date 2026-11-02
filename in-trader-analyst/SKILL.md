---
name: in-trader-analyst
description: >-
  Results Analyst for Indian companies. Lines up a company's quarterly numbers
  (revenue, gross, EBITDA, operating and net margins, net profit and diluted EPS)
  quarter by quarter in crore, with year-on-year and quarter-on-quarter growth and
  the last four quarters, labelled in Indian fiscal quarters (Q2 FY27 = Jul-Sep
  2026). Finds the latest results filing on NSE and says when Yahoo's numbers lag
  it, and reads the NSE event calendar for the next results board meeting, for one
  stock or a whole watchlist. Use when the user says "how were Reliance's results",
  "analyse the quarterly results", "what changed this quarter", "is revenue
  growing", "compare margins", "sum up the con call", "when are TCS results",
  "results this week", or before trading a stock around its results.
argument-hint: "[symbols] | calendar"
---

# in-trader-analyst

Results move Indian stocks more than anything else on the calendar, and the press
release puts the best number first. This skill lines up the reported numbers and
says plainly what changed. For an intraday trader it answers two questions: what
did the last results say, and are the next ones inside this trade?

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE
python3 "${CLAUDE_SKILL_DIR}/facts.py" TCS INFY HCLTECH --quarters 8 --metrics trader/metrics.json
python3 "${CLAUDE_SKILL_DIR}/facts.py" calendar --days 7          # results meetings for your symbols
python3 "${CLAUDE_SKILL_DIR}/facts.py" calendar --days 3 --all    # everyone on NSE
```

## What it reads and writes

- **Numbers:** Yahoo Finance's fundamentals timeseries for SYMBOL.NS
  (quarterly revenue, gross profit, operating income, EBITDA, net income,
  diluted EPS), consolidated as Yahoo reports them. Free and unofficial; it lags
  the filing and can skip a quarter. The tool says when it does.
- **Filings:** NSE corporate announcements, for the latest "Outcome of Board
  Meeting" / financial results PDF. When that filing is newer than Yahoo's last
  quarter, the tool prints a NOTE: open the PDF and read the new quarter yourself.
- **Next results:** NSE's event calendar (companies give notice about a week ahead).
- `--metrics FILE` writes one row per company for notes or a spreadsheet.
- **Con calls:** the tool does not fetch transcripts. NSE filings carry the link
  (the "Analysts/Institutional Investor Meet/Con. Call Updates" item); if the user
  pastes or links one, read it and sum up what management said changed:
  guidance, margins, demand, capex, anything they declined to answer.

## The rules

- **Filed numbers first, and say where each came from** (Yahoo, or the PDF you read).
- **Like with like.** Growth is against the same quarter a year earlier; many
  Indian businesses are seasonal (festive quarter, monsoon). QoQ is shown, not the headline.
- **Standalone vs consolidated.** Indian companies file both. Say which one a
  number is; for groups like RELIANCE they differ a lot.
- **Flag one-offs.** Net profit above operating profit means other income or an
  exceptional item is inside it. Banks and NBFCs have no gross margin: blank, not zero.
- **Gaps are gaps.** A missing quarter is never estimated.

## Steps

1. `facts.py SYMBOL` (or the watchlist's symbols).
2. If there is a NOTE that the NSE filing is newer, open the PDF and read the quarter.
3. Write the summary: one line on the quarter (revenue, profit, EPS, YoY), one on
   margins, one on anything unusual (one-off, gap, standalone vs consolidated), and links.
4. If the next results fall inside the planned trade (an overnight hold, or results
   during market hours), say it before `/in-trader-exit`: a stop does not protect against a gap.

## Example: RELIANCE on 2 November 2026 (real Yahoo and NSE data)

```
  Q4 FY26  2026-03-31     294,059 cr   +12.5%   +11.0%     16,971 cr   -12.6%    12.54   -12.6%    10.0%
  Q1 FY27  2026-06-30     309,468 cr   +27.0%    +5.2%     20,946 cr   -22.4%    15.48   -22.4%    10.5%
  NOTE: Yahoo skips Q1 FY26 to Q3 FY26: growth across a gap is not shown.
  Latest results filing on NSE: 30-Oct-2026 19:40:11, https://nsearchives.nseindia.com/corporate/..._Results.pdf
  NOTE: that filing is newer than Yahoo's last quarter (Q1 FY27): Yahoo lags. Open the filing and read the new quarter before summarising.
```

So the honest summary of Q2 FY27 comes from the PDF, not from Yahoo, and says so.

## What it never does

Never calls a stock cheap, expensive, a buy or a sell; never invents or estimates
a number the filings do not have; never presents Yahoo's figures as the filing.

<!-- safety:start -->
## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a rules check, not a recommendation. SEBI's study of FY2023 found about 7 in 10 individual intraday equity traders made a loss.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode never calls Kite at all: fills are simulated in `trader/`. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except in-trader-broker, and only when all three hold: in-trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the Kite order tools are set to "Needs approval". Never set an order tool to "Always allow".
- No F&O, options, MTF or leverage, and no short selling, unless the config allows it and the user confirms.
- The Kite login happens on Zerodha's own page. API keys, passwords, PINs and TOTP codes never go in the chat.
<!-- safety:end -->
