---
name: in-trader-news
description: >-
  News Monitor for Indian stocks. Tracks what is new on every stock you watch:
  the company's own NSE filings (results, outcome of board meeting, fund raising,
  resignations, credit ratings, insolvency...), the NSE event calendar (the next
  results board meeting), Yahoo Finance and Google News India headlines, and how far
  each stock is from the previous close. Shows only what is new since the last
  check, newest first, in IST, tags each item (results, dividend, corporate action,
  capital, deal, orders, people, rating, regulatory, legal, promoter, block deal,
  surveillance, analyst, macro) and marks important filings. Use when the user says
  "any news on RELIANCE", "why is this moving", "news on my watchlist", "morning
  briefing", "pre-market news", "any filings", "when are results", "did anything
  break", or after in-trader-scanner finds setups.
argument-hint: "[symbols]"
---

# in-trader-news

A chart can look perfect and still be about to gap on results, a block deal, an
ASM listing or a SEBI order. Before a setup becomes a trade, this skill reads the
feeds that carry those first and tells you only what is new, next to how far each
stock has moved today.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                               # watchlist + plan + portfolio
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE TCS --hours 12
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-nse --json               # headlines only
python3 "${CLAUDE_SKILL_DIR}/news.py" --all --dry-run               # include seen items, keep state
```

## What it reads and writes

| feed / file | what |
| --- | --- |
| `--tickers`, else `trader/watchlist.json`, `plan.json`, `portfolio.json` | the symbols |
| NSE `/api/corporate-announcements` | the company's filings to the exchange, with the PDF link |
| NSE `/api/event-calendar` | board meetings in the next 10 days (results, dividends, fund raising) |
| Yahoo Finance RSS (SYMBOL.NS) and Google News India RSS | headlines |
| Yahoo chart | last price against the previous close (unofficial, can lag) |
| `trader/state/news.json` | items already shown (kept 30 days) |

NSE's site wants a browser-like visit first; the tool collects its cookies
politely and pauses between calls. If NSE blocks it, the tool says so and the
headlines still run.

## The rules

- **Headlines are leads, not facts.** Open the filing or the story before saying
  something happened. Quote the source and link it. Never summarise a paywalled
  story you could not read.
- **Filings beat headlines.** If an NSE filing and a headline disagree, the filing
  is what the company told the exchange.
- **`!` marks important filings**: outcome of board meeting, financial results,
  resignations, insolvency/NCLT, credit ratings, fund raising, acquisitions,
  schemes of arrangement, pledges, fraud, default, cyber incidents.
- **UPCOMING results** inside the next few sessions: say it before in-trader-exit.
  A day trade flat by 15:05 is not exposed to an after-hours result; anything held
  overnight is, and an Indian stock can open many percent away, or at a circuit.
- **MOVING** marks a stock 3 % or more from the previous close (`--move-pct`). A
  move with no news is worth saying out loud.
- **No predictions.** Report what was published and the move. Never what comes next.

## Steps

1. `news.py`. Exit 1 means nothing new.
2. Read what matters first: every `!` filing, results, regulatory, legal,
   surveillance, block deal, and every MOVING symbol.
3. A short brief per symbol: what happened, source and link, the move, and one
   line on why it matters to the setup.
4. If a story changes the picture (results tomorrow, an ASM listing, an OFS), say so
   before `/in-trader-entry` and `/in-trader-exit`. Never act on a headline alone.

During the session: `/loop 15m /in-trader-news`, or a scheduled task at 8:45 IST.

## Example: RELIANCE, the weekend before Monday 2 November 2026

```
RELIANCE
  !11-01 23:09 NSE filing [results] Analysts/Institutional Investor Meet/Con. Call Updates: Transcript of the discussion on the Unaudited Financial Results ...
   10-30 19:47 NSE filing [-] Investor Presentation: ...
  !10-30 19:40 NSE filing [results, board] Outcome of Board Meeting: ... approved the unaudited Financial Results ... for the quarter and half year ended September 30, 2026
```

And on Wednesday 28 October: `UPCOMING Fri 2026-10-30: board meeting, Financial
Results/Fund Raising <- results inside a few sessions: a gap can jump any stop`.

## What it never does

Never invents or embellishes a story, a quote or a number; never trades on news
or tells the user to buy or sell because of it; never hammers a server.

<!-- safety:start -->
## Safety

- Education and tooling, not financial advice, and not SEBI-registered investment advice. A PASS is a rules check, not a recommendation. SEBI's study of FY2023 found about 7 in 10 individual intraday equity traders made a loss.
- Paper trading by default (`"paper": true`). Zerodha has no paper account, so paper mode never calls Kite at all: fills are simulated in `trader/`. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except in-trader-broker, and only when all three hold: in-trader-risk passed that exact order today, the user typed an explicit yes for that one order in the chat, and the user clicked Allow once on Claude's own card because the Kite order tools are set to "Needs approval". Never set an order tool to "Always allow".
- No F&O, options, MTF or leverage, and no short selling, unless the config allows it and the user confirms.
- The Kite login happens on Zerodha's own page. API keys, passwords, PINs and TOTP codes never go in the chat.
<!-- safety:end -->
