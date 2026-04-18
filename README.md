# Nifty 50 Investment Dashboard

A personal investment dashboard that tracks all 50 Nifty stocks daily, computes clean adjusted EPS, scores every stock on a 100-point model, and ranks them to identify the top 25 most likely to outperform the index.

**Live dashboard:** https://naushimathur.github.io/Nifty-Dashboard/

---

## What this does

Every weekday at 4pm IST, a Python script automatically fetches data for all 50 Nifty stocks from Yahoo Finance, cleans the EPS numbers, runs a scoring model, and updates the dashboard. No manual work needed.

The goal is to systematically identify which 25 of the 50 Nifty stocks are most likely to outperform the index — and track whether those predictions are correct over time.

---

## The Scoring Model (100 points)

Every stock gets a score out of 100 based on three blocks:

### Fundamental Quality — 50 points
| Signal | Points | How scored |
|---|---|---|
| EPS Growth (YoY) | 15 | >30%=15, 20–30%=12, 10–20%=9, 0–10%=5, Negative=0 |
| Operating Margin Trend | 10 | Expanding=10, Flat=5, Contracting=0 |
| Return on Equity (ROE) | 10 | >25%=10, 15–25%=7, 10–15%=4, Below=0 |
| Debt to Equity | 10 | <0.5=10, 0.5–1=7, 1–2=4, Above=0 (banks exempt) |
| EPS Consistency | 5 | CV<15%=5, 15–30%=3, Above=0 |

### Valuation — 20 points
| Signal | Points | How scored |
|---|---|---|
| P/E vs Sector Average | 10 | 20%+ below avg=10, 10–20%=7, Near=5, Above=2/0 |
| PEG Ratio | 10 | <0.75=10, 0.75–1=8, 1–1.5=5, 1.5–2=2, Above=0 |

### Momentum vs Nifty 50 — 30 points
| Signal | Points | How scored |
|---|---|---|
| 6-Month relative return | 15 | >10% above Nifty=15, 5–10%=11, 0–5%=7, Below=0 |
| 3-Month relative return | 10 | >5% above Nifty=10, 0–5%=6, Below=0 |
| 1-Month relative return | 5 | Above Nifty=5, Below=0 |

**Top 25 by score = BUY signal. Bottom 25 = AVOID.**

---

## How EPS is Adjusted

Raw EPS from Yahoo Finance includes one-time exceptional items that distort the real picture. We clean it:

1. **Fetch** quarterly income statement from Yahoo Finance
2. **Find** exceptional items (`Total Unusual Items` row)
3. **Strip** minority interest (profit belonging to subsidiary shareholders)
4. **Apply** 25% Indian corporate tax rate adjustment to exceptional items
5. **Compute** clean Adjusted EPS = Adjusted Net Income ÷ Shares Outstanding

TTM Adjusted EPS = sum of last 4 quarters of adjusted EPS.

### Forward EPS — Two versions shown
- **Our derived estimate** = TTM Adjusted EPS × (1 + EPS growth rate). Fully clean.
- **Analyst consensus** = Yahoo Finance aggregated analyst estimates. May include exceptional items.
- If the two diverge by >20%, a ⚠ flag appears — it means analysts see something the trend doesn't capture.

---

## Data Source

**Yahoo Finance** (via `yfinance` Python library) — single source for all data:
- Daily closing prices
- Quarterly income statements (for EPS adjustment)
- Shares outstanding, ROE, D/E, operating margins
- Analyst forward EPS estimates
- Nifty 50 index price (`^NSEI`)

---

## Project Structure

```
Nifty Dashboard/
├── fetch_data.py              # Main data fetch + scoring script
├── dashboard.html             # Dashboard UI
├── index.html                 # Same as dashboard.html (for GitHub Pages)
├── nifty_data.json            # Output data file (auto-updated daily)
├── last_successful_run.txt    # Heartbeat — timestamp of last clean run
├── fetch_log.txt              # Log of each fetch run
├── SETUP.md                   # Step-by-step setup guide
├── README.md                  # This file
└── .github/
    └── workflows/
        └── daily_fetch.yml    # GitHub Actions — runs fetch daily at 4pm IST
```

---

## Setup

See [SETUP.md](SETUP.md) for complete step-by-step instructions.

**Quick version:**
1. Install Python from python.org
2. `py -m pip install yfinance pandas numpy`
3. `py fetch_data.py` — fetches all 50 stocks (~8 minutes)
4. `py -m http.server 8080` — serve locally
5. Open `http://localhost:8080/dashboard.html`

---

## Automation (GitHub Actions)

The script runs automatically every weekday at 4:00pm IST (10:30 UTC) via GitHub Actions. It:
- Checks if today is an NSE market holiday (skips if so)
- Fetches all 50 stocks
- Computes adjusted EPS and scores
- Commits updated `nifty_data.json` back to the repo
- GitHub Pages serves the fresh data automatically

If a run fails, GitHub sends an email notification.

---

## Simulation Tracker

First prediction locked in: **April 18, 2026**

The top 25 stocks by score on this date are recorded as the predicted outperformers. In April 2027, we compare their actual returns against the Nifty 50 index return to measure:
- Hit rate (how many of the 25 actually outperformed)
- Alpha generated vs index
- Whether the scoring model is predictive

---

## Limitations

- EPS data quality: Most stocks show PARTIAL (one of two adjustments applied). CLEAN (both) is rare due to Yahoo data availability.
- Yahoo Finance has no official SLA — if it breaks, the daily fetch fails until yfinance is patched.
- Forward EPS analyst consensus may not be fully adjusted for exceptional items.
- Historical index composition not accounted for — backtests will have survivorship bias.
- Banking stocks are exempt from D/E scoring (structural leverage is normal for banks).

---

## Future Plans

- Backtesting engine (point-in-time simulation)
- Nifty 500 expansion
- Sharpe ratio and alpha tracking in simulation tab
- Promoter holding data (manual quarterly input)

---

*Built April 2026 | Data: Yahoo Finance | For personal investment research only — not financial advice*
