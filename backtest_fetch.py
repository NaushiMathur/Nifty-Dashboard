"""
Backtest Data Loader
====================
Pulls all historical data needed for the 2022-2025 Nifty 50 backtest and caches
it to disk so the simulator can run repeatedly without re-fetching.

USAGE
-----
    py backtest_fetch.py

This will pull ~60 tickers + the Nifty 50 index over ~4 years of daily prices,
plus quarterly income statements and balance sheet snapshots. Takes ~15-20 min
the first time. Writes to backtest_cache/.

Run once. Re-run only if the ticker list changes or you want fresh data.

OUTPUT FILES
------------
    backtest_cache/prices.parquet          — daily adjusted close for all tickers
    backtest_cache/nifty_index.parquet     — daily Nifty 50 (^NSEI) close
    backtest_cache/quarterly_income/       — one CSV per ticker (quarterly P&L)
    backtest_cache/balance_sheet/          — one CSV per ticker (quarterly BS)
    backtest_cache/info.json               — ticker metadata (sector, shares, etc.)
    backtest_cache/fetch_log.txt           — what succeeded/failed
"""

import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
CACHE_DIR = Path("backtest_cache")
CACHE_DIR.mkdir(exist_ok=True)
(CACHE_DIR / "quarterly_income").mkdir(exist_ok=True)
(CACHE_DIR / "balance_sheet").mkdir(exist_ok=True)

# Pull a bit earlier than the backtest start (Feb 2022) so 6-month momentum
# on the first rebalance has enough lookback.
FETCH_START = "2021-06-01"
FETCH_END   = "2026-01-01"  # covers full 2022-2025 + a buffer

# Universe: all tickers that were ever in Nifty 50 between Feb 2022 and Nov 2025.
# Source: nifty50_historical_composition.json (compiled from NSE reconstitution
# announcements — see CLAUDE.md for citations).
ALL_TICKERS = [
    'ADANIENT','ADANIPORTS','APOLLOHOSP','ASIANPAINT','AXISBANK','BAJAJ-AUTO',
    'BAJAJFINSV','BAJFINANCE','BEL','BHARTIARTL','BPCL','BRITANNIA','CIPLA',
    'COALINDIA','DIVISLAB','DRREDDY','EICHERMOT','GRASIM','HCLTECH','HDFC',
    'HDFCBANK','HDFCLIFE','HEROMOTOCO','HINDALCO','HINDUNILVR','ICICIBANK',
    'INDIGO','INDUSINDBK','INFY','IOC','ITC','JIOFIN','JSWSTEEL','KOTAKBANK',
    'LT','LTIM','M&M','MARUTI','MAXHEALTH','NESTLEIND','NTPC','ONGC',
    'POWERGRID','RELIANCE','SBILIFE','SBIN','SHREECEM','SHRIRAMFIN','SUNPHARMA',
    'TATACONSUM','TATAMOTORS','TATASTEEL','TCS','TECHM','TITAN','TRENT',
    'ULTRACEMCO','UPL','WIPRO','ZOMATO',
]

# HDFC Ltd merged with HDFC Bank on July 13, 2023 — its yfinance ticker was HDFC.NS
# and delisted after merger. Data before that date should still be available.
# IndiGo trades as INDIGO.NS; Zomato as ZOMATO.NS (will become ETERNAL.NS in future
# per rebrand, but Yahoo still serves historical data under ZOMATO.NS for now).

SLEEP_BETWEEN_CALLS = 2.0  # seconds; yfinance rate-limits GitHub IPs
MAX_RETRIES = 3

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(CACHE_DIR / "fetch_log.txt", mode="w"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# FETCHERS (with retry)
# ─────────────────────────────────────────────

def fetch_with_retry(fn, label, attempts=MAX_RETRIES):
    """Retry wrapper with exponential backoff."""
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            wait = 2 ** i
            log.warning(f"  [{label}] attempt {i+1}/{attempts} failed: {e} — waiting {wait}s")
            time.sleep(wait)
    log.error(f"  [{label}] giving up after {attempts} attempts")
    return None


def fetch_prices_for_all():
    """One big download for daily close prices across all tickers.
    yfinance handles multi-ticker downloads efficiently in a single call."""
    log.info(f"Fetching daily prices for {len(ALL_TICKERS)} tickers + ^NSEI ...")
    symbols = [t + ".NS" for t in ALL_TICKERS] + ["^NSEI"]

    def _fetch():
        # auto_adjust=True returns dividend-adjusted close in the 'Close' column
        return yf.download(
            symbols,
            start=FETCH_START,
            end=FETCH_END,
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )

    df = fetch_with_retry(_fetch, "prices_batch")
    if df is None or df.empty:
        log.error("Price batch download returned empty. Aborting.")
        return None

    # Flatten to long format: date | ticker | close
    close_df = pd.DataFrame()
    for sym in symbols:
        try:
            if isinstance(df.columns, pd.MultiIndex):
                if (sym, "Close") in df.columns:
                    s = df[(sym, "Close")]
                elif (sym,) in df.columns:
                    s = df[sym]["Close"] if "Close" in df[sym] else None
                else:
                    log.warning(f"  Ticker {sym} not found in batch result")
                    continue
            else:
                s = df["Close"] if sym == symbols[0] else None
            if s is None or s.dropna().empty:
                log.warning(f"  No price data for {sym}")
                continue
            close_df[sym] = s
        except Exception as e:
            log.warning(f"  Error extracting {sym}: {e}")

    # Separate Nifty index from stocks
    nifty = close_df[["^NSEI"]].dropna() if "^NSEI" in close_df.columns else pd.DataFrame()
    stocks = close_df.drop(columns=["^NSEI"], errors="ignore")

    stocks.to_parquet(CACHE_DIR / "prices.parquet")
    nifty.to_parquet(CACHE_DIR / "nifty_index.parquet")
    log.info(f"  Saved prices.parquet ({stocks.shape[0]} rows x {stocks.shape[1]} cols)")
    log.info(f"  Saved nifty_index.parquet ({nifty.shape[0]} rows)")

    return stocks, nifty


def fetch_financials_for_ticker(ticker):
    """Pull quarterly income stmt, balance sheet, and .info for one ticker."""
    sym = ticker + ".NS"
    result = {"ticker": ticker, "symbol": sym, "income_rows": 0, "bs_rows": 0, "info": False}

    def _fetch():
        t = yf.Ticker(sym)
        return {
            "income":  t.quarterly_income_stmt,
            "bs":      t.quarterly_balance_sheet,
            "info":    t.info,
        }

    data = fetch_with_retry(_fetch, sym)
    if data is None:
        return result

    if data["income"] is not None and not data["income"].empty:
        data["income"].to_csv(CACHE_DIR / "quarterly_income" / f"{ticker}.csv")
        result["income_rows"] = data["income"].shape[1]

    if data["bs"] is not None and not data["bs"].empty:
        data["bs"].to_csv(CACHE_DIR / "balance_sheet" / f"{ticker}.csv")
        result["bs_rows"] = data["bs"].shape[1]

    if data["info"]:
        result["info"] = True
        # keep only the fields we'll actually use for scoring
        info_summary = {
            "sector":              data["info"].get("sector"),
            "industry":            data["info"].get("industry"),
            "sharesOutstanding":   data["info"].get("sharesOutstanding"),
            "trailingPE":          data["info"].get("trailingPE"),
            "forwardEps":          data["info"].get("forwardEps"),
            "bookValue":           data["info"].get("bookValue"),
            "longName":            data["info"].get("longName"),
        }
        result["info_data"] = info_summary

    return result


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info(f"Backtest data fetch started at {datetime.now()}")
    log.info(f"Fetch window: {FETCH_START} to {FETCH_END}")
    log.info(f"Tickers: {len(ALL_TICKERS)}")
    log.info("=" * 60)

    # ---- 1) Prices ----
    prices_result = fetch_prices_for_all()
    if prices_result is None:
        log.error("Price fetch failed. Aborting.")
        return

    # ---- 2) Financials per ticker ----
    log.info("")
    log.info("Fetching financials per ticker...")
    summary = {}
    for i, ticker in enumerate(ALL_TICKERS, 1):
        log.info(f"[{i}/{len(ALL_TICKERS)}] {ticker}")
        r = fetch_financials_for_ticker(ticker)
        summary[ticker] = r
        time.sleep(SLEEP_BETWEEN_CALLS)

    # ---- 3) Write summary ----
    info_map = {t: s.get("info_data") for t, s in summary.items() if s.get("info_data")}
    with open(CACHE_DIR / "info.json", "w") as f:
        json.dump(info_map, f, indent=2, default=str)

    # ---- 4) Report ----
    log.info("")
    log.info("=" * 60)
    log.info("FETCH SUMMARY")
    log.info("=" * 60)
    missing_income = [t for t, s in summary.items() if s["income_rows"] == 0]
    missing_bs     = [t for t, s in summary.items() if s["bs_rows"] == 0]
    missing_info   = [t for t, s in summary.items() if not s["info"]]

    log.info(f"Tickers with income stmt: {len(ALL_TICKERS) - len(missing_income)}/{len(ALL_TICKERS)}")
    log.info(f"Tickers with balance sheet: {len(ALL_TICKERS) - len(missing_bs)}/{len(ALL_TICKERS)}")
    log.info(f"Tickers with .info: {len(ALL_TICKERS) - len(missing_info)}/{len(ALL_TICKERS)}")

    if missing_income:
        log.warning(f"MISSING INCOME STMT: {missing_income}")
    if missing_bs:
        log.warning(f"MISSING BALANCE SHEET: {missing_bs}")
    if missing_info:
        log.warning(f"MISSING INFO: {missing_info}")

    log.info("")
    log.info("Done. Next step: run `py backtest_simulate.py`")


if __name__ == "__main__":
    main()
