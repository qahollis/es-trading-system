# Project 2 — ES Futures Volume Profile Backtesting Framework

## Overview

This project builds a quantitative backtesting engine to answer one specific question:

> **"If I entered a trade at this exact volume profile level with a 16-tick fixed stop and 60-tick target, what percentage of the time would I have won?"**

The engine tests volume profile levels against a simple support/resistance baseline, analyzes approach direction and confluence effects, and simulates realistic trading session outcomes under prop firm execution constraints.

---

## Research Question

ES futures traders use volume profile levels — Value Area High (VAH), Point of Control (POC), and Value Area Low (VAL) — as reference points for trade entries. This project answers whether these levels provide statistically meaningful edge over:

1. Random entry (does any strategy beat noise?)
2. Simple support/resistance (does volume profile add value over basic S/R?)
3. Realistic execution constraints (does the edge survive sequential trading with daily loss limits?)

---

## Dataset

- **Instrument:** ES Futures (E-mini S&P 500)
- **Data source:** Databento API (GLBX.MDP3, continuous front month)
- **Bar size:** 1-minute OHLCV
- **Date range:** April 2021 — April 2026 (2.4M+ bars)
- **Storage:** PostgreSQL database (`es_trading`)
- **Levels calculated:** Previous Overnight, Previous Day RTH, Previous Week sessions

---

## Methodology

### Entry Logic

A trade is entered when a 1-minute bar's high-low range contains the level price:

```
bar_low <= level_price <= bar_high
```

This confirms price actually traded at the level during that bar — equivalent to a limit order fill at the exact level price. Entries are restricted to the 6:30pm–10:00pm Eastern trading window.

### Exit Logic

- **Stop loss:** 16 ticks (4.00 points) adverse from entry — fixed, not trailing
- **Profit target:** 60 ticks (15.00 points) favorable from entry
- **Session end:** 9:30am Eastern next morning — trade closes as timeout if neither stop nor target hit

### Approach Direction

Each entry is tagged with the direction price was traveling in the 3 bars before the touch:
- **Bearish:** price falling into the level
- **Bullish:** price rising into the level
- **Neutral:** minimal price movement

### Confluence

Confluence is counted when other volume profile levels fall within 4 ticks (1.00 point) of the touched level. Multiple levels stacking in the same price zone strengthen the signal.

### Cooldown

A 10-bar (10-minute) cooldown between touches of the same level prevents duplicate entries from price oscillating near a level.

---

## Backtest Modes

### Mode 1 — Research Mode (`backtest.py`)

Tests all valid signals independently with no session constraints. Establishes the raw win rate of every setup combination. Also runs a simple S/R comparison baseline using previous day and overnight high/low levels.

### Mode 2 — Execution Simulation (`mode2.py`)

Simulates realistic prop firm trading conditions with two rules:

- **Rule 1 — One trade at a time:** No new entry while a trade is open
- **Rule 2 — Daily loss limit:** Stop taking entries after 2 losses in a session

**Mode 2A:** Previous Day levels only (highest quality filter)
**Mode 2B:** All session types (broader coverage, similar win rate)

---

## Key Findings

### Approach Direction Is the Dominant Factor

| Setup | Win Rate | Expectancy |
|---|---|---|
| Bearish approach → long at any PD level | 85–89% | +49–52 ticks |
| Bullish approach → long at any PD level | 66–70% | +34–38 ticks |
| Bearish approach → short at any level | 4–6% | negative |
| Bullish approach → short at VAH | 25–27% | near break-even |

Price falling into a support level and entering long is the highest probability setup in the dataset.

### Confluence Adds Consistent Edge

Using 4-tick tolerance (1.00 point) for confluence detection:

| Confluence Count | Win Rate | Sample Size |
|---|---|---|
| 0 confluences | 85.0% | 720 trades |
| 1 confluence | 93.4% | 226 trades |

The 8.4 percentage point gap between confluent and non-confluent setups is the largest signal differentiator found in the research.

### Volume Profile vs Simple S/R

| Strategy | Overall Win Rate | Expectancy |
|---|---|---|
| Volume Profile | 46.1% | +16.0t |
| Simple S/R | 45.8% | +15.7t |

At the overall level both strategies perform similarly. The VP edge concentrates in specific approach direction and confluence combinations that S/R levels do not capture.

### Mode 2 Execution Results (2024–2026)

| Metric | Mode 2A | Mode 2B |
|---|---|---|
| Win rate | 87.0% | 87.5% |
| Trades per month | 31.8 | 50.6 |
| Active sessions/month | 9.2 | 11.4 |
| Profitable sessions | 88.1% | 89.0% |
| Sessions stopped early | 11.9% | 18.3% |

Mode 2B is recommended — virtually identical win rate with 59% more monthly trade opportunities.

### Market Regime Matters

The same backtest run on 2022 bear market data shows dramatically different results:

| Period | Market | Long Win Rate | Random Baseline |
|---|---|---|---|
| 2024–2026 | Strong bull | 78–84% | 76.1% |
| 2022 | Bear market | 34–59% | 50.6% |

Volume profile levels add 3–9% edge above random in both periods. Market regime dominates absolute win rates. A market regime filter is identified as the most important next addition to the strategy.

---

## Honest Limitations

1. **Simulation overestimates real performance.** Entries assume perfect limit order fills at exact level prices. Real trading involves slippage (1–2 ticks), commissions ($10 round trip), and missed fills on fast-moving bars. Apply a 30–50% discount to simulated win rates when estimating live performance.

2. **Bull market bias.** The primary test period (2024–2026) was a strong uptrend. Long entry win rates reflect market drift as much as level quality. The 2022 validation confirms this — win rates drop significantly in downtrending conditions.

3. **1-minute bar resolution.** Stops and targets are checked against bar highs and lows. In reality, within a single bar both stop and target could be hit — the order of execution is unknown. Stop-first assumption is used as a conservative convention.

4. **No market regime filter.** The current strategy enters signals regardless of broader market direction. Adding a regime filter (trending vs ranging) is the highest priority enhancement identified by the research.

---

## Project Structure

```
es-trading-system/
├── backtest/
│   ├── backtest.py          # Mode 1 research backtest + S/R comparison
│   ├── mode2.py             # Mode 2A and 2B execution simulation
│   ├── trades_raw.csv       # Mode 1 raw trade results
│   ├── mode2a_trades.csv    # Mode 2A trade records
│   ├── mode2b_trades.csv    # Mode 2B trade records
│   ├── mode2a_sessions.csv  # Mode 2A session summaries
│   └── mode2b_sessions.csv  # Mode 2B session summaries
└── pipeline/
    ├── extract.py           # Databento API data pull
    ├── transform.py         # Volume profile calculation
    ├── load.py              # Daily ETL pipeline
    ├── scheduler.py         # Automated daily runs
    └── backfill_levels.py   # Historical level calculation
```

---

## How To Run

### Prerequisites

```bash
pip install pandas sqlalchemy psycopg2 python-dotenv databento
```

Set up `.env` file:
```
DATABENTO_API_KEY=your_key
PG_PASSWORD=your_password
```

### Run Mode 1 Backtest

```bash
python backtest/backtest.py
```

### Run Mode 2 Execution Simulation

```bash
python backtest/mode2.py
```

---

## Strategy Parameters

| Parameter | Value |
|---|---|
| Stop loss | 16 ticks (4.00 points) |
| Profit target | 60 ticks (15.00 points) |
| Break-even win rate | 21.1% |
| Entry window | 6:30pm–10:00pm Eastern |
| Session end | 9:30am Eastern next morning |
| Confluence tolerance | 4 ticks (1.00 point) |
| Cooldown between touches | 10 bars (10 minutes) |
| Daily loss limit (Mode 2) | 2 losses |

---

## Skills Demonstrated

- Python data pipeline engineering (ETL, scheduling, PostgreSQL)
- Financial data API integration (Databento)
- Quantitative backtesting methodology
- Statistical analysis and result validation
- Market regime analysis across bull and bear periods
- Prop firm evaluation constraint modeling
- Data-driven strategy refinement
