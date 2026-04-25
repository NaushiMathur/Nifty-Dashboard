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

- **Python** — data fetch script (`fetch_data.py`) and backtest scripts
- **yfinance** — single data source (Yahoo Finance). NSE/nsepython was dropped — blocks cloud servers.
- **pandas, numpy** — data processing
- **pyarrow / parquet** — backtest cache storage format
- **bse** (BseIndiaApi) — BSE India unofficial API library, used in `enrich_eps.py` (laptop only)
- **python-dateutil** — date parsing in `enrich_eps.py`
- **Vanilla HTML/CSS/JS + Chart.js** — dashboard (no frameworks, single file)
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
| `backtest_fetch.py` | Downloads and caches all historical data for 2022–2025 backtest (~15–20 min first run) |
| `backtest_simulate.py` | Runs point-in-time simulation: 16 quarterly rebalances, Feb 2022–Nov 2025 |
| `backtest_report.py` | Reads results.json, generates self-contained HTML report |
| `build_composition.py` | Builds nifty50_historical_composition.json with historical NSE index membership |
| `nifty50_historical_composition.json` | Historical Nifty 50 constituents at each rebalance — solves survivorship bias |
| `enrich_eps.py` | **Laptop-only** script: fetches BSE quarterly P&L via `bse` library, extracts exceptional items, writes `eps_overrides.json` |
| `eps_overrides.json` | BSE-sourced exceptional items data per stock per quarter — read by `fetch_data.py` when Yahoo data is missing |
| `minority_overrides.json` | Research-based annual minority interest figures for all 50 stocks — read by `fetch_data.py` when Yahoo NCI data is missing. Update annually after FY Annual Reports (June–July). |

### Backtest directories (gitignored or large — do not commit)

| Directory | Contents |
|---|---|
| `backtest_cache/` | `prices.parquet`, `nifty_index.parquet`, `quarterly_income/` CSVs, `balance_sheet/` CSVs, `info.json`, `fetch_log.txt` |
| `backtest_results/` | `results.json`, `trades.csv`, `nav.csv`, `simulate_log.txt`, `report.html` |

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

## Dashboard tabs (dashboard.html — ~1450 lines)

The dashboard is a single-file vanilla HTML/CSS/JS app using Chart.js (loaded from CDN). It has 5 tabs:

1. **Overview** — KPI bar (Nifty index price, avg P/E, BUY/HOLD/AVOID counts, EPS adjusted count, data freshness), warnings panel, Top 25 vs Bottom 25 split panel, P/E gauge with contextual description, sector cards, EPS quality data panel
2. **All Stocks** — sortable/filterable table with signal chip, score bar + F/V/M breakdown chips, EPS, dual forward P/E, divergence flag, ROE, D/E, margin trend, 6M/3M/1M relative returns. Click any row to expand full score breakdown + quarterly EPS detail + forward EPS + key metrics
3. **Scoring Model** — static explanation of the 3-block model with visual bar weights
4. **Backtest** — reads `backtest_results/results.json` via fetch(). Shows NAV chart (portfolio vs Nifty 50 buy-and-hold), quarterly spread bar chart, per-quarter table with expandable pick list, full KPI grid (total return, CAGR, alpha, Sharpe, beta, hit rate, W/L record). Shows empty state if results.json not present
5. **Simulation** — shows current top-25 prediction locked in April 18, 2026. Results due April 2027

The dashboard loads `nifty_data.json` for the live data tabs and `backtest_results/results.json` for the backtest tab. Both require an HTTP server — file:// protocol won't work due to browser security.

---

## Backtest infrastructure

### Purpose
Point-in-time simulation of whether the scoring model would have beaten the Nifty 50 index from Feb 2022 to Nov 2025, across 16 quarterly rebalances. Designed to avoid look-ahead bias and survivorship bias.

### How to run (in order)

```bash
# Step 1 — build historical composition (run once)
py build_composition.py

# Step 2 — download all historical data (run once, ~15-20 min)
py backtest_fetch.py

# Step 3 — run simulation
py backtest_simulate.py

# Step 4 — generate HTML report
py backtest_report.py
# → opens backtest_results/report.html
```

### Key assumptions (hardcoded in backtest_simulate.py — document any changes)

| Assumption | Value | Why |
|---|---|---|
| Transaction cost | 0.20% per side | Discount broker (India) estimate |
| Risk-free rate | 7% annual | ~10y G-Sec rate over period |
| India tax rate | 25% | Same as live scoring model |
| Initial capital | ₹10,00,000 | Notional — only affects absolute P&L |
| Top N | 25 | Matches live model |
| Fundamental lag | 45 days | Conservative: Q end → results publication ~30–45 days |

### Survivorship bias handling

`nifty50_historical_composition.json` contains the actual Nifty 50 membership at each rebalance date, built from NSE reconstitution announcements. Historical changes tracked:

- 2022-03-31: IOC out, APOLLOHOSP in
- 2022-09-30: SHREECEM out, ADANIENT in
- 2023-07-13: HDFC out (merger with HDFCBANK), LTIM in
- 2024-03-28: UPL out, SHRIRAMFIN in
- 2024-09-30: DIVISLAB + LTIM out, TRENT + BEL in
- 2025-03-28: BPCL + BRITANNIA out, JIOFIN + ZOMATO in
- 2025-09-30: HEROMOTOCO + INDUSINDBK out, INDIGO + MAXHEALTH in

The backtest fetches ~60 tickers total (all stocks that were ever constituents) to ensure no survivorship bias.

### Backtest output fields (results.json summary)

Key fields: `total_return_pct`, `total_benchmark_return_pct`, `spread_pct`, `annual_return_pct`, `annual_benchmark_return_pct`, `annual_alpha_pct`, `sharpe_portfolio`, `sharpe_benchmark`, `beta`, `tracking_error_annual_pct`, `overall_hit_rate`, `num_quarters`, `years_simulated`, `final_portfolio_value`, `initial_capital`

Per-quarter fields: `nominal_date`, `execution_day`, `return_pct`, `nifty_return_pct`, `spread_pct`, `hit_rate`, `portfolio_value_post_rebalance`, `top_25` list

---

## BSE Exceptional Items Enrichment (hybrid workflow)

### Why it exists
Yahoo Finance often lacks exceptional items data for Indian companies, causing most stocks to be PARTIAL or UNVERIFIED quality. BSE India publishes quarterly P&L filings with explicit "Exceptional Items" rows via their API — but the API blocks cloud/GitHub Actions IPs (403 Forbidden). Solution: run enrichment manually on laptop once per quarter.

### Files involved
- `enrich_eps.py` — laptop-only enrichment script
- `eps_overrides.json` — output file, committed to repo and read by `fetch_data.py`

### How to run (quarterly, after results season ends)
```bash
pip install bse python-dateutil   # one-time
py enrich_eps.py
# → writes eps_overrides.json

git add eps_overrides.json
git commit -m "Quarterly EPS enrichment — May 2026"
git push
```

### How it integrates with fetch_data.py
- On startup, `fetch_data.py` loads `eps_overrides.json` into `_EPS_OVERRIDES` dict
- In `_clean_one_quarter()`, if Yahoo has no exceptional items for a quarter, it checks `_EPS_OVERRIDES[ticker][quarter_date]`
- If an override value exists, it's used for the EPS adjustment (same formula: remove exceptional + add back 25% tax shield)
- The `detail` dict for each quarter now includes `"exceptional_source"`: `"yahoo"`, `"bse_override"`, or `None`
- The summary block in `nifty_data.json` includes `"bse_enriched_count"` — how many stocks used at least one BSE override

### When to run
Run `enrich_eps.py` once per quarter, ideally:
- Mid-February (after Q3 results season)
- Mid-May (after Q4/full-year results season)
- Mid-August (after Q1 results season)
- Mid-November (after Q2 results season)

### NSE → BSE scrip code mapping
`enrich_eps.py` has a hardcoded `NSE_TO_BSE` dict. If the Nifty 50 composition changes (new stock added), look up the BSE scrip code at bseindia.com and add it to that dict.

---

## Minority Interest Overrides

### Why it exists
Yahoo Finance does not provide quarterly minority interest (Non-Controlling Interest) data for Indian companies. NSE and BSE APIs block automated access to consolidated P&L data where NCI appears. Solution: `minority_overrides.json` stores annual NCI figures per stock, derived from published FY2024-25 consolidated annual reports. `fetch_data.py` applies these when Yahoo is missing the data.

### File: `minority_overrides.json`
- Annual MI in crores (`mi_cr_annual`) divided by 4 to estimate each quarter
- Confidence levels: **HIGH** (structurally stable, large listed subsidiaries), **MEDIUM** (stable but can fluctuate), **LOW** (estimated from structure, not independently verified), **ZERO** (confirmed no material NCI)
- Data vintage: FY2024-25
- Each entry includes `note`, `how_to_get_exact`, and `ownership_detail` fields

### Stocks where MI matters most (update these first annually)
| Stock | MI% of NI | Confidence | Why |
|---|---|---|---|
| GRASIM | 57% | HIGH | UltraTech (43% external) + AB Capital (44% external) |
| BAJAJFINSV | 48% | HIGH | Bajaj Finance (47.5% external) |
| LT | 16% | HIGH | LT Finance, LTTS, LTIMindtree minorities |
| ADANIENT | 15% | LOW | Complex unlisted subsidiary structure |
| TATASTEEL | 11% | MEDIUM | Tata Steel Long Products (25% external) |
| M&M | 8% | MEDIUM | Mahindra Finance, Lifespace |
| SUNPHARMA | 6% | MEDIUM | Taro Pharmaceutical (24% external, NYSE listed) |
| RELIANCE | 5% | MEDIUM | Jio Platforms (33% external), Reliance Retail (5% external) |

### How to update annually (June–July after FY Annual Reports)
1. Download Annual Report PDF from `bseindia.com → Company Search → Annual Report`
2. Find "Non-Controlling Interest" in the **Consolidated Statement of Profit & Loss**
3. Update `mi_cr_annual` and `mi_pct_of_ni` in `minority_overrides.json`
4. Bump `data_as_of` and `_last_updated` fields
5. Commit and push — `fetch_data.py` picks up automatically on next run

### Dashboard disclosure
The dashboard Overview tab has a **"ⓘ How is this data sourced?"** button next to the EPS Data Quality panel. Clicking it expands a full disclosure showing:
- What adjustments are made and why
- All three data sources (Yahoo → BSE → minority overrides) in priority order
- Per-stock minority interest confidence cards for all stocks using overrides
- Exact instructions for getting 100% accurate data

---

## Known issues / limitations

- **yfinance on cloud**: Yahoo occasionally rate-limits GitHub Actions IPs. Solution: 2-second delay between stock fetches + retry logic already in script.
- **TCS D/E anomaly**: Yahoo reports D/E ~10 for TCS — likely deferred revenue counted as debt. IT companies are cash-heavy; this is a data quirk, not real leverage. Dashboard doesn't currently flag this.
- **EPS quality**: Most stocks return PARTIAL (not CLEAN) because Yahoo doesn't always have both exceptional items AND minority interest. This is expected.
- **JSON truncation**: If fetch_data.py is interrupted mid-run, nifty_data.json gets truncated. Solution: re-run the script.
- **Weekend/holiday detection**: Script checks `NSE_HOLIDAYS_2026` dict + weekday check. Update holidays annually.
- **Backtest survivorship bias**: Historical composition is based on announced reconstitution dates. Pre-announcement price run-ups are not captured.
- **yfinance 1.3.0 multi-level columns**: Fixed in fetch_data.py via `get_close_series()` helper that handles both flat and `(field, ticker)` multi-level DataFrame columns.

---

## What's NOT built yet (next sessions)

1. **GitHub Actions testing** — workflow file exists but hasn't been triggered and verified on GitHub yet
2. **Backtesting — push results to GitHub** — backtest_results/results.json needs to be committed so the Backtest tab renders on the live dashboard
3. **Simulation tracker result-recording** — first prediction locked April 18 2026, results due April 2027. Tab exists but result-recording logic not built yet
4. **Sharpe ratio / alpha** — already computed in backtest; needs wiring into the simulation tab as results come in
5. **Promoter holding** — manual quarterly input feature
6. **Nifty 500 expansion** — future, after Nifty 50 is stable
7. **BSE enrichment — push to GitHub** — `enrich_eps.py` has been run and `eps_overrides.json` written. Still needs: `git add eps_overrides.json && git commit -m "..."  && git push`.
8. **Minority overrides — push to GitHub** — `minority_overrides.json` written. Push with `git add minority_overrides.json && git commit && git push` so GitHub Actions picks it up.
9. **Minority overrides — annual verification** — HIGH/MEDIUM confidence entries should be verified against actual FY25 Annual Reports. Current figures from training data knowledge are good approximations but not independently confirmed.
10. **Change 2 (1M → 12M momentum)** — flagged in the Change Log doc; not yet implemented in fetch_data.py or scoring engine
11. **Change 3 (divergence news deep-link)** — flagged in the Change Log doc; not yet implemented in dashboard.html

---

## How to run locally

```bash
# Install dependencies (one time)
py -m pip install yfinance pandas numpy pyarrow

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

*Last updated: April 25, 2026 (minority_overrides.json added, dashboard EPS disclosure built)*
