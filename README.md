# The Indian Day Trader skill

11 Claude skills for intraday trading on NSE and BSE: scan Nifty and F&O charts,
read every company filing, time each entry and exit, size in rupees with the real
charges inside, and replay the outcome 10,000 times before you risk a rupee.

An India-market adaptation of Jake Schincariol's
[day-trader-skill](https://github.com/jakeschincariol/day-trader-skill) (MIT):
the same pipeline and the same "nothing trades without your yes" design, rebuilt
for IST, the NSE calendar and tick sizes, the closing auction, Indian charges,
SEBI disclosures and Zerodha Kite.

Free, MIT, no signup, no API key for the data. Plain Python 3.8+ (standard library
only) reading free public data: Yahoo Finance charts and fundamentals for
`SYMBOL.NS` / `.BO`, nseindia.com (filings, event calendar, SEBI insider
disclosures, bulk and block deals, ASM/GSM), niftyindices.com, Yahoo and Google
News India RSS.

Nothing in this pack can place an order on its own. **Paper trading is the
default, and in paper mode Kite is never called.**

## Install

In Claude Code, as a plugin:

```
/plugin marketplace add <your-github-user>/indian-trader-skill
/plugin install indian-day-trader-skill@indian-day-trader-skill
```

Or copy the folders for plain `/in-trader-scanner` names:

```bash
cp -r in-trader-* ~/.claude/skills/        # or your project's .claude/skills/
```

No Claude Code? Paste any single `SKILL.md` at the top of a chat and it runs as a
mode; you lose the Python tools, but the method works.

## The eleven

| command | job | what it does |
| --- | --- | --- |
| `/in-trader-scanner` | Chart Scanner | F&O / Nifty 500 / all-NSE universe, opening-range breakouts, 20-day breakouts, bull flags, oversold; ASM/GSM list. |
| `/in-trader-news` | News Monitor | NSE filings, the next results date, Yahoo and Google News India headlines, the move vs the previous close. |
| `/in-trader-entry` | Entry Timer | Watches a setup bar by bar from 9:15 IST and says the moment to get in. |
| `/in-trader-exit` | Exit Planner | Stop and target on the NSE tick, flat by 15:05, before the closing auction. |
| `/in-trader-timemachine` | Time Machine | 10,000 replays from the stock's own 60 days of 5-minute bars, plus every past day the rule fired. |
| `/in-trader-budget` | Budget Manager | Sizes in rupees to your max loss, with brokerage, STT, exchange, SEBI, stamp duty and GST inside it. |
| `/in-trader-risk` | Risk Manager | PASS or BLOCK: max loss, daily loss, trades a day, IST window, surveillance stocks, ticks, no F&O/MTF/shorts. |
| `/in-trader-broker` | Order Executor | Kite tickets, your yes word for word, local paper fills by default, Zerodha's Kite MCP when you go live. |
| `/in-trader-alerts` | Price Alerts | Stop, target, flat-by, opening bell, % moves; NSE holidays and Muhurat built in. |
| `/in-trader-analyst` | Results Analyst | Quarters in crore and Indian fiscal quarters, YoY, margins; flags when Yahoo lags the NSE filing; results calendar. |
| `/in-trader-insiders` | Insider & Big-Money Tracker | SEBI insider-trading disclosures (promoter buys, sells, pledges) and bulk/block deals by the investors you follow. |

## How to use it

Everything lands in a `trader/` folder in your project, and each skill reads what
the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker    (one trade)
alerts: stop, target, flat by 15:05                                              (while it is open)
news / analyst / insiders                                                        (on a schedule)
```

An example with real data: RELIANCE, Monday 2 November 2026, the first session
after its Q2 FY27 results (filed on NSE on Friday 30 October at 19:40).

1. **`/in-trader-news RELIANCE`** before the open: the "Outcome of Board Meeting"
   filing with the results PDF, the investor presentation and the con-call
   transcript, all marked. The results are already out, so there is no results
   gap inside today's trade.
2. **`/in-trader-scanner orb`** at 10:00: RELIANCE closed above its 15-minute
   opening range (1,214.60 to 1,231.60) at 9:35, 0.24 % over the top.
3. **`/in-trader-entry RELIANCE`**: at 9:34 it said waiting (the 9:30 bar was
   still forming); at 9:35, triggered at ₹1,234.50.
4. **`/in-trader-exit`**: stop at the range midpoint rounded down to the ₹0.10
   tick, ₹1,223.10, so ₹11.40 a share at risk; target 1R, ₹1,245.90; flat by 15:05.
5. **`/in-trader-timemachine --until 15:05`**, on the 19 full sessions in the test
   fixture (a live run uses about 40): target first 33.8 %, stop first 47.1 %,
   neither 19.1 %, seed 19. The same rule on those 19 real days fired 12 times:
   5 target, 5 stop, 2 neither. Verdict: leans toward the stop. (The real day hit
   the target at 10:25. One day is one draw.)
6. **`/in-trader-budget`** with ₹1,00,000 and ₹500 max loss: 39 shares
   (₹48,145.50). At the stop: ₹444.60 on the shares + ₹50.88 charges = ₹495.48.
   It writes an MIS market BUY and an SL-M stop to place after the fill.
7. **`/in-trader-risk`**: PASS, ₹495.48 of the ₹500 limit, 0 of 3 trades today.
   At 9:20 it would have blocked the entry ("no new entries before 09:30"); with
   40 shares, ₹508.19 at the stop, blocked.
8. **`/in-trader-broker`**: the ticket in plain words, your "yes", and a paper
   fill recorded locally. Live, Claude would call Kite's `place_order` and
   Claude's own Allow once / Deny card would ask one more time.
9. **`/in-trader-alerts`** rings the stop, the target and 15:05.

## The tools

```bash
python3 in-trader-scanner/scan.py universe                       # F&O stocks (or --index nifty500, --all)
python3 in-trader-scanner/scan.py surveillance                   # NSE ASM/GSM
python3 in-trader-scanner/scan.py daily                          # before 9:15
python3 in-trader-scanner/scan.py orb --at 10:00                 # opening-range breakouts
python3 in-trader-news/news.py --tickers RELIANCE --hours 24     # filings, results date, headlines, move
python3 in-trader-entry/entry.py check RELIANCE                  # waiting / triggered / expired
python3 in-trader-entry/entry.py watch RELIANCE --until 14:45    # bar by bar until it triggers
python3 in-trader-exit/exit.py plan --stop or-mid --target 1R --write
python3 in-trader-timemachine/timemachine.py run --until 15:05 --write
python3 in-trader-budget/size.py --write                         # -> trader/orders.json
python3 in-trader-risk/check.py                                  # PASS / BLOCK
python3 in-trader-broker/ticket.py show                          # READY or not
python3 in-trader-alerts/alerts.py add --from-plan && python3 in-trader-alerts/alerts.py check
python3 in-trader-analyst/facts.py RELIANCE                      # quarters, YoY, margins, next results
python3 in-trader-analyst/facts.py calendar --days 7             # results this week
python3 in-trader-insiders/insiders.py pit RELIANCE              # SEBI insider disclosures
python3 in-trader-insiders/insiders.py deals --client kacholia --days 30
```

```bash
python3 -m unittest discover -s tests -v
```

The tests run offline on responses saved on 2 November 2026: RELIANCE's real
5-minute bars from 29 September, NSE filings and event calendar, Yahoo
fundamentals, SEBI PIT disclosures and bulk/block deals. They reproduce every
number in the example above.

`common/inmarket.py` is the shared toolkit (IST clock, NSE calendar, ticks,
charges, Yahoo and NSE fetching). Each skill folder carries its own copy so it
works on its own; after editing it, run `python3 tools/sync_common.py`.

## What is different from the US version

| | US (original) | India (this pack) |
| --- | --- | --- |
| Session | 9:30-16:00 ET, DST | 9:15-15:30 IST, no DST; F&O stocks in a closing auction from 15:15 (no stop-loss orders) |
| Full 5-minute day | 78 bars | 73 bars (9:15 to the 15:15 bar) |
| Default flat by | 15:55 | 15:05 (Zerodha squares off MIS at 15:25, with a fee) |
| Prices | cents | NSE tick bands: ₹0.01 / 0.05 / 0.10 / 0.50 / 1 / 5 |
| Costs | ~zero | brokerage, STT, exchange, SEBI, stamp duty, GST: inside the max loss |
| Broker | Alpaca (paper account) | Zerodha Kite MCP; no paper account, so paper fills are simulated locally |
| Bracket orders | yes | no: an SL-M stop after the fill, the target watched by alerts |
| Filings | SEC 8-K, XBRL | NSE announcements, event calendar; Yahoo fundamentals with a lag check |
| "Pelosi" | Congress PTRs | SEBI PIT insider disclosures, bulk and block deals, investors you follow |
| Extra checks | PDT (optional) | ASM/GSM surveillance, BE (trade-to-trade) series, holidays and Muhurat |

## Fine print

**Not financial advice, and not SEBI-registered investment advice.** This is
software that reads public data and does arithmetic. It does not know your
situation and cannot see the future. SEBI's study of FY2023 found that about 7 in
10 individual intraday equity traders lost money. Decide for yourself, and talk to
a SEBI-registered adviser if you need advice.

**No trade goes through until you say yes.** Only `/in-trader-broker` can lead to
an order, and only after `/in-trader-risk` passes that exact order and you type yes
for it. Set the Kite order tools to "Needs approval", never "Always allow". No F&O,
options, MTF, leverage or short selling unless you turn them on.

**Paper first.** `"paper": true` is the default; Kite is not called at all in paper
mode. Your Zerodha login happens on Zerodha's page; credentials never go in the chat.

**The Time Machine is a simulation, not a prediction.** Built from the stock's
last 60 days. Results, a block deal, an ASM listing or a circuit can do what those
days never did.

**A stop is a plan, not a guarantee.** A gap, a circuit limit or a fast market can
fill an SL-M well past its trigger. Stop-loss orders are not accepted in the
15:15 closing auction: be flat before it.

**The data is free and unofficial.** Yahoo's endpoints can lag, change or
rate-limit; nseindia.com can block scripted access. 1-minute or 5-minute bars,
never ticks. Check anything that matters in Kite before you act.

**Calendar.** The NSE 2026 holidays and Muhurat session are built in. Add 2027's
list to `"extra_holidays"` in `trader/config.json` when NSE publishes it.

**Taxes.** Intraday equity gains are speculative business income in India. Nothing
here is tax advice.

## Files

```
in-trader-scanner/     SKILL.md, scan.py
in-trader-news/        SKILL.md, news.py
in-trader-entry/       SKILL.md, entry.py
in-trader-exit/        SKILL.md, exit.py
in-trader-timemachine/ SKILL.md, timemachine.py
in-trader-budget/      SKILL.md, size.py, config.example.json
in-trader-risk/        SKILL.md, check.py
in-trader-broker/      SKILL.md, ticket.py, claude_desktop_config.example.json
in-trader-alerts/      SKILL.md, alerts.py, alerts.example.json
in-trader-analyst/     SKILL.md, facts.py
in-trader-insiders/    SKILL.md, insiders.py
(each folder also holds inmarket.py, a copy of common/inmarket.py)
common/                inmarket.py, SAFETY.md
tools/                 sync_common.py
tests/                 unittest suite + offline fixtures
```

MIT. Adapted from [day-trader-skill](https://github.com/jakeschincariol/day-trader-skill)
by Jake Schincariol (MIT).
