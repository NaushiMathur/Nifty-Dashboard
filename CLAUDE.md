# CLAUDE.md — Nifty 50 Dashboard

This file tells Claude everything it needs to know to continue working on this project in future sessions.

---

## What this project is

A personal investment dashboard for tracking Nifty 50 stocks. Built by Naushi (naushimathur1999@gmail.com) to beat the index by systematically identifying the top 25 stocks most likely to outperform. Not a trading tool — a research and prediction-tracking system.

---

## Live URLs

- **Dashboard:** https://naushimathur.github.io/Nifty-Dashboard/
- **GitHub repo:** https://github.com/NaushiMathur/Nifty-Dashboard
- **Local folder:** `C:\Users\Castiel Winchester\OneDrive\Documents\Claude\Projects\Nifty Dashboard`

---

## Tech stack

- **Python** — data fetch script (`fetch_data.py`)
- **yfinance** — single data source (Yahoo Finance). NSE/nsepython was dropped — blocks cloud servers.
- **pandas, numpy** — data processing
- **Vanilla HTML/CSS/JS** — dashboard (no frameworks, single file)
- **GitHub Actions** — daily automation (weekdays 4pm IST = 10:30 UTC)
- **GitHub Pages** — hosting (public repo, index.html serves the dashboard)

---

## Key files

| File | Purpose |
|---|---|
| `fetch_data.py` | Fetches all 50 stocks, computes adjusted EPS, applies scoring model, saves `nifty_data.json` |
| `dashboard.html` | Main dashboard UI — reads `nifty_data.json` via fetch() |
| `index.html` | Copy of dashboard.html — required by GitHub Pages for root URL |
| `nifty_data.json` | Data output — updated daily by fetch script |
| `.github/workflows/daily_fetch.yml` | GitHub Actions workflow |
| `SETUP.md` | Plain English setup guide for non-developers |

---

## Scoring model (do not change weights without telling Naushi)

Total: 100 points across 3 blocks.

**Fundamental Quality — 50pts**
- EPS Growth: 15pts
- Operating Margin Trend: 10pts
- ROE: 10pts
- Debt to Equity: 10pts (banking stocks exempt)
- EPS Consistency (CV): 5pts

**Valuation — 20pts**
- P/E vs Sector Average: 10pts (sector-relative, not absolute)
- PEG Ratio: 10pts

**Momentum vs Nifty 50 — 30pts**
- 6-month relative return: 15pts
- 3-month relative return: 10pts
- 1-month relative return: 5pts

Signal thresholds: Score ≥50 = BUY, 35–49 = HOLD, <35 = AVOID.
Top 25 by score = predicted outperformers.

---

## EPS adjustment pipeline

1. Pull `quarterly_income_stmt` from yfinance
2. Find `Total Unusual Items` (exceptional items)
3. Find `Minority Interest` / `Non Controlling Interest`
4. Adjust: `Adj Net Income = Reported NI - Exceptional Items + (Exceptional × 25% tax) - abs(Minority Interest)`
5. `Adj EPS = Adj Net Income ÷ Shares Outstanding`
6. TTM Adj EPS = sum of last 4 quarters
7. Quality flag: CLEAN (both found), PARTIAL (one found), UNVERIFIED (neither found)

**India corporate tax rate used: 25%**

---

## Forward EPS — Option C (both shown)

- **Derived** = TTM Adj EPS × (1 + eps_growth_rate) — our clean estimate
- **Analyst** = Yahoo `forwardEps` — consensus, may include exceptional items
- **Divergence flag** = if gap >20%, show ⚠ warning on dashboard
- Both feed into separate Forward P/E columns

---

## Data flow

```
Yahoo Finance (yfinance)
    ↓
fetch_data.py (runs daily at 4pm IST via GitHub Actions)
    ↓
nifty_data.json (committed back to GitHub repo)
    ↓
dashboard.html / index.html (reads JSON, renders everything)
    ↓
https://naushimathur.github.io/Nifty-Dashboard/
```

---

## Known issues / limitations

- **yfinance on cloud**: Yahoo occasionally rate-limits GitHub Actions IPs. Solution: 2-second delay between stock fetches + retry logic already in script.
- **TCS D/E anomaly**: Yahoo reports D/E ~10 for TCS — likely deferred revenue counted as debt. IT companies are cash-heavy; this is a data quirk, not real leverage. Dashboard doesn't currently flag this.
- **EPS quality**: Most stocks return PARTIAL (not CLEAN) because Yahoo doesn't always have both exceptional items AND minority interest. This is expected.
- **JSON truncation**: If fetch_data.py is interrupted mid-run, nifty_data.json gets truncated. Solution: re-run the script.
- **Weekend/holiday detection**: Script checks `NSE_HOLIDAYS_2026` dict + weekday check. Update holidays annually.

---

## What's NOT built yet (next sessions)

1. **GitHub Actions testing** — workflow file exists but hasn't been triggered and verified on GitHub yet
2. **Backtesting engine** — point-in-time historical simulation. **Use Opus for this session** — logic is complex and bugs here cause false confidence.
3. **Simulation tracker** — first prediction locked April 18 2026, results due April 2027. Tab exists but needs result-recording logic.
4. **Sharpe ratio / alpha** — evaluation metrics for simulation tab
5. **Promoter holding** — manual quarterly input feature
6. **Nifty 500 expansion** — future, after Nifty 50 is stable

---

## How to run locally

```bash
# Install dependencies (one time)
py -m pip install yfinance pandas numpy

# Fetch data (force run on weekends for testing)
py -c "import fetch_data; fetch_data.is_market_holiday = lambda: False; fetch_data.main()"

# Serve dashboard locally
py -m http.server 8080
# Then open: http://localhost:8080/dashboard.html

# Push updates to GitHub
git add .
git commit -m "Update"
git push
```

---

## Naushi's investment goal

Beat the Nifty 50 index by holding only the top 25 scored stocks. Rebalance quarterly. Track predictions vs reality in the simulation tab. Use 3-5 year rolling window to evaluate if the model has genuine predictive power vs luck.

This is for personal informed investment — not advice to others.

---

*Last updated: April 18, 2026*
