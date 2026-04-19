"""
Nifty 50 Backtest Simulator
===========================
Runs a point-in-time simulation of the top-25 scoring model from Feb 2022
through Nov 2025 (16 quarterly rebalances), using cached data from
backtest_fetch.py.

USAGE
-----
    py backtest_simulate.py

Prerequisites:
    1. backtest_fetch.py has been run (backtest_cache/ populated)
    2. nifty50_historical_composition.json exists in the project root

OUTPUT
------
    backtest_results/results.json   — per-quarter picks, returns, metrics
    backtest_results/trades.csv     — every simulated buy/sell
    backtest_results/nav.csv        — daily NAV of portfolio vs benchmark

This file is structured for verification: each function has clear inputs
and outputs, and the main loop logs every decision made.
"""

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────
# CONFIG — single source of truth for backtest assumptions
# ─────────────────────────────────────────────
CACHE_DIR     = Path("backtest_cache")
RESULTS_DIR   = Path("backtest_results")
RESULTS_DIR.mkdir(exist_ok=True)

COMPOSITION_FILE = Path("nifty50_historical_composition.json")

# Assumptions (flagged in final report)
TRANSACTION_COST_PER_SIDE = 0.0020   # 0.20% per side (discount broker, India)
RISK_FREE_RATE_ANNUAL     = 0.07     # ~7% for 10y G-Sec over period
INDIA_TAX_RATE            = 0.25     # For exceptional-item adjustment
INITIAL_CAPITAL           = 1_000_000  # ₹10L notional — only affects absolute P&L, not returns
TOP_N                     = 25
FUNDAMENTAL_LAG_DAYS      = 45       # Conservative lag: Q end → filing typically 30-45 days later

# Banking sectors — high D/E is structural, so not scored
BANKING_SECTORS = {"Financial Services", "Banking"}

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(RESULTS_DIR / "simulate_log.txt", mode="w"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# DATA LOADERS
# ─────────────────────────────────────────────

def _normalize_dt_index(idx):
    """Coerce any date-like index to a plain ns-precision, tz-naive DatetimeIndex.
    Parquet preserves datetime64[ms] which trips pandas-2.x comparisons against
    default ns Timestamps on newer Python; forcing ns here avoids that."""
    idx = pd.to_datetime(idx)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    # Force ns precision — parquet may load as [ms]
    return pd.DatetimeIndex(idx.values.astype("datetime64[ns]"))


def load_prices() -> pd.DataFrame:
    """Daily close prices, columns=tickers.NS, index=date."""
    df = pd.read_parquet(CACHE_DIR / "prices.parquet")
    df.index = _normalize_dt_index(df.index)
    return df.sort_index()


def load_nifty() -> pd.Series:
    """Daily Nifty 50 close, name='^NSEI'."""
    df = pd.read_parquet(CACHE_DIR / "nifty_index.parquet")
    df.index = _normalize_dt_index(df.index)
    return df["^NSEI"].dropna().sort_index()


def load_info() -> dict:
    with open(CACHE_DIR / "info.json") as f:
        return json.load(f)


def load_income(ticker: str) -> Optional[pd.DataFrame]:
    path = CACHE_DIR / "quarterly_income" / f"{ticker}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0)
    df.columns = pd.to_datetime(df.columns)
    return df


def load_balance_sheet(ticker: str) -> Optional[pd.DataFrame]:
    path = CACHE_DIR / "balance_sheet" / f"{ticker}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0)
    df.columns = pd.to_datetime(df.columns)
    return df


def load_composition() -> dict:
    with open(COMPOSITION_FILE) as f:
        return json.load(f)


# ─────────────────────────────────────────────
# POINT-IN-TIME FUNDAMENTALS
# ─────────────────────────────────────────────

def compute_adjusted_eps_pit(
    income_df: pd.DataFrame,
    shares_out: Optional[float],
    as_of_date: pd.Timestamp,
) -> dict:
    """
    Compute trailing-4-quarter adjusted EPS using only quarters that were
    reportable before `as_of_date` (quarter end + FUNDAMENTAL_LAG_DAYS).

    Also returns the PRIOR TTM (quarters 5-8 back) so we can compute real
    TTM-YoY earnings growth.

    Returns dict with: ttm_adj_eps, prior_ttm_adj_eps, eps_quarters, quality,
    ttm_reported_ni, ttm_revenue
    """
    out = {"ttm_adj_eps": None, "prior_ttm_adj_eps": None,
           "eps_quarters": [], "quality": "UNVERIFIED",
           "ttm_reported_ni": None, "ttm_revenue": None}

    if income_df is None or income_df.empty:
        return out

    # Filter to quarters whose filing date would have been public by as_of_date
    cutoff = as_of_date - pd.Timedelta(days=FUNDAMENTAL_LAG_DAYS)
    usable = sorted([q for q in income_df.columns if q <= cutoff], reverse=True)

    if len(usable) < 2:
        return out

    # Split: most-recent-4 vs next-4 (for YoY)
    recent_4 = usable[:4]
    prior_4  = usable[4:8]

    def _process_quarters(qs):
        """Process a list of quarter-end dates → dict with adj_eps_list, ni_list, rev_list, exc_any, min_any."""
        r = {"adj_eps_list": [], "ni_list": [], "rev_list": [],
             "exc_any": False, "min_any": False}
        for q in qs:
            col = income_df[q]

            ni = None
            for label in ["Net Income", "Net Income Common Stockholders"]:
                if label in col.index and pd.notna(col[label]):
                    ni = float(col[label]); break
            if ni is None:
                continue

            adj_ni = ni

            exc = None
            for label in ["Total Unusual Items", "Unusual Items", "Exceptional Items"]:
                if label in col.index and pd.notna(col[label]):
                    exc = float(col[label]); r["exc_any"] = True; break
            if exc is not None:
                adj_ni = adj_ni - exc + exc * INDIA_TAX_RATE

            minor = None
            for label in ["Minority Interest", "Non Controlling Interest"]:
                if label in col.index and pd.notna(col[label]):
                    minor = float(col[label]); r["min_any"] = True; break
            if minor is not None:
                adj_ni = adj_ni - abs(minor)

            if shares_out and shares_out > 0:
                r["adj_eps_list"].append(adj_ni / shares_out)
                r["ni_list"].append(ni)

            for label in ["Total Revenue", "Revenue"]:
                if label in col.index and pd.notna(col[label]):
                    r["rev_list"].append(float(col[label])); break

        return r

    recent = _process_quarters(recent_4)
    prior  = _process_quarters(prior_4)

    # TTM from recent 4
    if recent["adj_eps_list"]:
        n_recent = len(recent["adj_eps_list"])
        if n_recent == 4:
            out["ttm_adj_eps"]     = sum(recent["adj_eps_list"])
            out["ttm_reported_ni"] = sum(recent["ni_list"])
        else:
            # Annualize from partial data (noted as limitation in report)
            out["ttm_adj_eps"]     = sum(recent["adj_eps_list"]) * 4 / n_recent
            out["ttm_reported_ni"] = sum(recent["ni_list"]) * 4 / n_recent if recent["ni_list"] else None
        out["eps_quarters"] = recent["adj_eps_list"]

    # Prior TTM — only set if we have a full 4-quarter prior window
    if len(prior["adj_eps_list"]) == 4:
        out["prior_ttm_adj_eps"] = sum(prior["adj_eps_list"])

    if recent["rev_list"]:
        out["ttm_revenue"] = (sum(recent["rev_list"]) if len(recent["rev_list"]) == 4
                              else sum(recent["rev_list"]) * 4 / len(recent["rev_list"]))

    exc_found = recent["exc_any"] or prior["exc_any"]
    min_found = recent["min_any"] or prior["min_any"]
    if exc_found and min_found:
        out["quality"] = "CLEAN"
    elif exc_found or min_found:
        out["quality"] = "PARTIAL"

    return out


def compute_margin_trend_pit(income_df, as_of_date):
    if income_df is None or income_df.empty:
        return None, "unknown"
    cutoff = as_of_date - pd.Timedelta(days=FUNDAMENTAL_LAG_DAYS)
    usable = sorted([q for q in income_df.columns if q <= cutoff], reverse=True)[:4]
    if len(usable) < 2:
        return None, "unknown"

    margins = []
    for q in usable:
        col = income_df[q]
        op = None
        for l in ["Operating Income", "EBIT"]:
            if l in col.index and pd.notna(col[l]):
                op = float(col[l]); break
        rev = None
        for l in ["Total Revenue", "Revenue"]:
            if l in col.index and pd.notna(col[l]):
                rev = float(col[l]); break
        if op is not None and rev and rev != 0:
            margins.append(op / rev * 100)
        else:
            margins.append(None)

    valid = [m for m in margins if m is not None]
    if len(valid) < 2:
        return margins, "unknown"

    # Newest is usable[0] → valid[0] if present; oldest is valid[-1]
    if valid[0] > valid[-1] + 0.5:
        return margins, "expanding"
    if valid[0] < valid[-1] - 0.5:
        return margins, "contracting"
    return margins, "flat"


def compute_roe_pit(bs_df, ttm_ni, as_of_date):
    """ROE = TTM net income / average shareholders' equity."""
    if bs_df is None or bs_df.empty or ttm_ni is None:
        return None
    cutoff = as_of_date - pd.Timedelta(days=FUNDAMENTAL_LAG_DAYS)
    usable = sorted([q for q in bs_df.columns if q <= cutoff], reverse=True)[:4]
    if not usable:
        return None

    equities = []
    for q in usable:
        col = bs_df[q]
        for label in ["Stockholders Equity", "Total Stockholder Equity",
                      "Common Stock Equity", "Total Equity Gross Minority Interest"]:
            if label in col.index and pd.notna(col[label]):
                equities.append(float(col[label])); break

    if not equities:
        return None
    avg_equity = np.mean(equities)
    if avg_equity <= 0:
        return None
    return ttm_ni / avg_equity * 100


def compute_debt_equity_pit(bs_df, as_of_date):
    if bs_df is None or bs_df.empty:
        return None
    cutoff = as_of_date - pd.Timedelta(days=FUNDAMENTAL_LAG_DAYS)
    usable = sorted([q for q in bs_df.columns if q <= cutoff], reverse=True)
    if not usable:
        return None

    col = bs_df[usable[0]]
    debt = None
    for label in ["Total Debt", "Long Term Debt"]:
        if label in col.index and pd.notna(col[label]):
            debt = float(col[label]); break
    equity = None
    for label in ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"]:
        if label in col.index and pd.notna(col[label]):
            equity = float(col[label]); break

    if debt is None or equity is None or equity <= 0:
        return None
    return debt / equity


# ─────────────────────────────────────────────
# MOMENTUM — from price history alone (always truly point-in-time)
# ─────────────────────────────────────────────

def trading_day_offset(prices: pd.DataFrame, as_of: pd.Timestamp, days_back: int) -> Optional[pd.Timestamp]:
    """Find the trading date ~N calendar days before as_of that exists in the index."""
    target = as_of - pd.Timedelta(days=days_back)
    idx = prices.index[prices.index <= target]
    return idx[-1] if len(idx) else None


def compute_momentum_pit(prices_col: pd.Series, nifty: pd.Series, as_of: pd.Timestamp):
    """Returns (rel_1m, rel_3m, rel_6m) in percentage points."""
    # Guard: if caller passed an empty / non-datetime-indexed series (e.g. the
    # ticker has no price history in cache), skip momentum scoring entirely.
    if prices_col is None or len(prices_col) == 0 or not isinstance(prices_col.index, pd.DatetimeIndex):
        return None, None, None
    if nifty is None or len(nifty) == 0 or not isinstance(nifty.index, pd.DatetimeIndex):
        return None, None, None

    def price_at(series, d):
        idx = series.index[series.index <= d]
        return float(series.loc[idx[-1]]) if len(idx) else None

    p_now = price_at(prices_col, as_of)
    n_now = price_at(nifty, as_of)
    if p_now is None or n_now is None:
        return None, None, None

    def rel_return(days_back):
        p_old = price_at(prices_col, as_of - pd.Timedelta(days=days_back))
        n_old = price_at(nifty, as_of - pd.Timedelta(days=days_back))
        if p_old is None or n_old is None or p_old == 0 or n_old == 0:
            return None
        stock_ret = (p_now - p_old) / p_old * 100
        nifty_ret = (n_now - n_old) / n_old * 100
        return stock_ret - nifty_ret

    return rel_return(30), rel_return(90), rel_return(180)


# ─────────────────────────────────────────────
# SCORING (mirror of live fetch_data.py)
# ─────────────────────────────────────────────

def score_eps_growth(eps_growth_pct):
    if eps_growth_pct is None: return 0
    if eps_growth_pct >= 30: return 15
    if eps_growth_pct >= 20: return 12
    if eps_growth_pct >= 10: return 9
    if eps_growth_pct >= 0:  return 5
    return 0

def score_margin_trend(trend):
    return {"expanding": 10, "flat": 5, "contracting": 0}.get(trend, 0)

def score_roe(roe):
    if roe is None: return 0
    if roe >= 25: return 10
    if roe >= 15: return 7
    if roe >= 10: return 4
    return 0

def score_de(de, is_banking):
    if is_banking: return 5
    if de is None: return 0
    if de <= 0.5: return 10
    if de <= 1.0: return 7
    if de <= 2.0: return 4
    return 0

def score_consistency(eps_quarters):
    valid = [x for x in (eps_quarters or []) if x is not None]
    if len(valid) < 3: return 0
    avg = np.mean(valid)
    if avg == 0: return 0
    cv = np.std(valid) / abs(avg) * 100
    if cv < 15: return 5
    if cv < 30: return 3
    return 0

def score_pe_vs_sector(pe, sector_avg):
    if pe is None or sector_avg is None or sector_avg == 0: return 0
    diff = (sector_avg - pe) / sector_avg * 100
    if diff >= 20: return 10
    if diff >= 10: return 7
    if diff >= -10: return 5
    if diff >= -20: return 2
    return 0

def score_peg(peg):
    if peg is None or peg <= 0: return 0
    if peg <= 0.75: return 10
    if peg <= 1.0: return 8
    if peg <= 1.5: return 5
    if peg <= 2.0: return 2
    return 0

def score_mom_6m(r):
    if r is None: return 0
    if r >= 10: return 15
    if r >= 5: return 11
    if r >= 0: return 7
    return 0

def score_mom_3m(r):
    if r is None: return 0
    if r >= 5: return 10
    if r >= 0: return 6
    return 0

def score_mom_1m(r):
    if r is None: return 0
    if r >= 0: return 5
    return 0


# ─────────────────────────────────────────────
# POINT-IN-TIME SCORING ENGINE
# ─────────────────────────────────────────────

@dataclass
class StockScore:
    ticker: str
    total: float = 0.0
    fundamental: float = 0.0
    valuation: float = 0.0
    momentum: float = 0.0
    details: dict = field(default_factory=dict)


def score_universe_pit(universe_tickers, as_of, prices, nifty, income_cache, bs_cache, info_map):
    """
    Score the given list of Nifty 50 constituents as of `as_of` date.
    Returns list of StockScore sorted descending by total.
    """
    # First pass: compute raw fundamentals for everyone to enable sector P/E average
    raw = {}
    for ticker in universe_tickers:
        sym = ticker + ".NS"
        info = info_map.get(ticker, {})
        shares = info.get("sharesOutstanding")
        sector = info.get("sector")

        inc = income_cache.get(ticker)
        bs  = bs_cache.get(ticker)

        eps_pit = compute_adjusted_eps_pit(inc, shares, as_of)
        margins, trend = compute_margin_trend_pit(inc, as_of)
        roe = compute_roe_pit(bs, eps_pit["ttm_reported_ni"], as_of)
        de  = compute_debt_equity_pit(bs, as_of)

        # Price at as_of
        if sym not in prices.columns:
            price_now = None
        else:
            idx = prices.index[prices.index <= as_of]
            price_now = float(prices.loc[idx[-1], sym]) if len(idx) else None
            if price_now is not None and (math.isnan(price_now) or price_now == 0):
                price_now = None

        # EPS growth: TTM vs prior-TTM (real YoY). Needs 8 quarters of history.
        # Stocks newly-listed with <8 quarters will get None here, which the scorer
        # treats as 0 points for eps_growth.
        eps_growth = None
        ttm = eps_pit["ttm_adj_eps"]
        prior_ttm = eps_pit["prior_ttm_adj_eps"]
        if ttm is not None and prior_ttm is not None and prior_ttm > 0:
            eps_growth = (ttm / prior_ttm - 1) * 100

        # Adjusted TTM P/E
        adj_pe = None
        if eps_pit["ttm_adj_eps"] and eps_pit["ttm_adj_eps"] > 0 and price_now:
            adj_pe = price_now / eps_pit["ttm_adj_eps"]

        # PEG = PE / growth
        peg = None
        if adj_pe and eps_growth and eps_growth > 0:
            peg = adj_pe / eps_growth

        # Momentum
        rel_1m, rel_3m, rel_6m = compute_momentum_pit(
            prices[sym] if sym in prices.columns else pd.Series(dtype=float),
            nifty, as_of,
        )

        raw[ticker] = {
            "sector": sector,
            "price": price_now,
            "ttm_adj_eps": eps_pit["ttm_adj_eps"],
            "adj_pe": adj_pe,
            "eps_growth": eps_growth,
            "eps_quarters": eps_pit["eps_quarters"],
            "eps_quality": eps_pit["quality"],
            "margin_trend": trend,
            "roe": roe,
            "de": de,
            "peg": peg,
            "rel_1m": rel_1m, "rel_3m": rel_3m, "rel_6m": rel_6m,
        }

    # Sector P/E averages (from this quarter's universe only)
    sector_pes = {}
    for t, r in raw.items():
        if r["sector"] and r["adj_pe"] and 0 < r["adj_pe"] < 200:
            sector_pes.setdefault(r["sector"], []).append(r["adj_pe"])
    sector_avg_pe = {s: np.mean(ps) for s, ps in sector_pes.items()}

    # Score
    scores = []
    for ticker, r in raw.items():
        is_bank = r["sector"] in BANKING_SECTORS
        s_eps = score_eps_growth(r["eps_growth"])
        s_mar = score_margin_trend(r["margin_trend"])
        s_roe = score_roe(r["roe"])
        s_de  = score_de(r["de"], is_bank)
        s_con = score_consistency(r["eps_quarters"])
        s_pe  = score_pe_vs_sector(r["adj_pe"], sector_avg_pe.get(r["sector"]))
        s_peg = score_peg(r["peg"])
        s_6m  = score_mom_6m(r["rel_6m"])
        s_3m  = score_mom_3m(r["rel_3m"])
        s_1m  = score_mom_1m(r["rel_1m"])

        fundamental = s_eps + s_mar + s_roe + s_de + s_con
        valuation   = s_pe + s_peg
        momentum    = s_6m + s_3m + s_1m
        total       = fundamental + valuation + momentum

        scores.append(StockScore(
            ticker=ticker, total=total,
            fundamental=fundamental, valuation=valuation, momentum=momentum,
            details={
                **r,
                "sector_avg_pe": sector_avg_pe.get(r["sector"]),
                "s_eps": s_eps, "s_mar": s_mar, "s_roe": s_roe, "s_de": s_de,
                "s_con": s_con, "s_pe": s_pe, "s_peg": s_peg,
                "s_6m": s_6m, "s_3m": s_3m, "s_1m": s_1m,
                "is_banking": is_bank,
            }
        ))

    scores.sort(key=lambda x: x.total, reverse=True)
    return scores


# ─────────────────────────────────────────────
# PORTFOLIO SIMULATOR
# ─────────────────────────────────────────────

def find_trading_day(prices_index, target_date):
    """Nearest trading day on or after target_date."""
    idx = prices_index[prices_index >= target_date]
    return idx[0] if len(idx) else None


def simulate(compositions, prices, nifty, income_cache, bs_cache, info_map):
    """Run the full 16-quarter simulation.
    Returns a list of quarter results and a daily NAV series."""
    rebalance_dates_raw = compositions["rebalance_dates"]

    # Resolve nominal rebalance dates to actual trading days
    rebalance_days = []
    for rd in rebalance_dates_raw:
        td = find_trading_day(prices.index, pd.Timestamp(rd))
        if td is None:
            raise RuntimeError(f"No trading day found for {rd}")
        rebalance_days.append((rd, td))

    log.info("Resolved rebalance dates:")
    for nominal, actual in rebalance_days:
        log.info(f"  nominal={nominal}  -> actual={actual.date()}")

    # Portfolio NAV tracker
    cash = INITIAL_CAPITAL
    holdings = {}  # ticker -> shares
    trades = []
    quarter_results = []

    # Initialize Nifty benchmark (buy & hold from first rebalance execution day)
    exec_days = [rd for (_, rd) in rebalance_days]
    first_exec_idx = prices.index.searchsorted(exec_days[0]) + 1
    if first_exec_idx >= len(prices.index):
        raise RuntimeError("Not enough price data beyond first rebalance")
    first_exec_day = prices.index[first_exec_idx]

    nifty_at_start = nifty.loc[nifty.index <= first_exec_day].iloc[-1]
    bench_units = INITIAL_CAPITAL / nifty_at_start

    for i, (nominal, rd) in enumerate(rebalance_days):
        log.info("")
        log.info("=" * 60)
        log.info(f"REBALANCE {i+1}/16: nominal={nominal} actual={rd.date()}")
        log.info("=" * 60)

        universe = compositions["composition_by_date"][nominal]

        # Score universe AS OF the rebalance day (using close of rd for prices
        # and fundamentals lagged by FUNDAMENTAL_LAG_DAYS)
        scores = score_universe_pit(universe, rd, prices, nifty,
                                    income_cache, bs_cache, info_map)

        # Top 25 picks
        top = [s for s in scores[:TOP_N]]
        top_tickers = [s.ticker for s in top]
        log.info(f"  Top 25 picks: {', '.join(top_tickers)}")

        # Execution price: next trading day OPEN. We only have close prices
        # in cache; use next-day close as proxy and document the simplification.
        # (Using close-of-decision-day would leak info — avoid that.)
        exec_idx = prices.index.searchsorted(rd) + 1
        if exec_idx >= len(prices.index):
            log.warning(f"  No execution day available beyond {rd}; ending simulation")
            break
        exec_day = prices.index[exec_idx]
        log.info(f"  Execution day: {exec_day.date()}")

        # Compute portfolio value at exec_day BEFORE rebalancing (sell side)
        portfolio_value = cash
        for t, sh in holdings.items():
            sym = t + ".NS"
            if sym in prices.columns:
                idx = prices.index[prices.index <= exec_day]
                if len(idx):
                    p = prices.loc[idx[-1], sym]
                    if pd.notna(p):
                        portfolio_value += sh * p

        log.info(f"  Portfolio value pre-rebalance: ₹{portfolio_value:,.0f}")

        # Determine which positions are changing
        new_set = set(top_tickers)
        old_set = set(holdings.keys())

        sells = old_set - new_set  # exit
        keeps = old_set & new_set  # stay
        buys  = new_set - old_set  # new

        # Target value per position (equal-weight after costs)
        # Execute sells first to raise cash (less exact than a simultaneous
        # approach but close enough — each side pays 0.20%)
        for t in sells:
            sym = t + ".NS"
            idx = prices.index[prices.index <= exec_day]
            if not len(idx):
                continue
            p = prices.loc[idx[-1], sym]
            if pd.isna(p):
                # Last known price fallback
                p = prices[sym].dropna().iloc[-1] if sym in prices.columns else 0
            sh = holdings[t]
            proceeds = sh * p * (1 - TRANSACTION_COST_PER_SIDE)
            cash += proceeds
            trades.append({"date": str(exec_day.date()), "ticker": t, "side": "SELL",
                           "shares": sh, "price": float(p), "cash_after": cash})
            del holdings[t]

        # Now portfolio_value is still the pre-cost figure, which is fine as
        # a denominator for sizing new positions since keeps absorb the cost
        # on their rebalanced portion.
        # Actually simpler: target weight per name = portfolio_value / 25 AFTER costs.
        # But because we're mostly holding keeps and only swapping sells→buys,
        # the friction is modest. We'll rebalance all 25 names equally each quarter
        # for simplicity — meaning "keeps" also get trimmed or topped up.
        #
        # Full rebalance approach: after selling exits, rebalance all 25 to equal weight.

        # Recompute current value (cash + keeps at current price)
        cur_val = cash
        for t in keeps:
            sym = t + ".NS"
            idx = prices.index[prices.index <= exec_day]
            if len(idx):
                p = prices.loc[idx[-1], sym]
                if pd.notna(p):
                    cur_val += holdings[t] * p

        target_per_name = cur_val / TOP_N
        log.info(f"  Target per name: ₹{target_per_name:,.0f}")

        # Rebalance keeps + buy new
        for t in top_tickers:
            sym = t + ".NS"
            idx = prices.index[prices.index <= exec_day]
            if not len(idx):
                log.warning(f"  No price data for {t} at exec day; skipping")
                continue
            p = prices.loc[idx[-1], sym]
            if pd.isna(p) or p <= 0:
                # Try last valid price
                if sym in prices.columns:
                    valid = prices[sym].dropna()
                    if len(valid) and valid.index[-1] < exec_day:
                        log.warning(f"  {t} has no recent price (may be delisted); using last known")
                        p = valid.iloc[-1]
                    else:
                        log.warning(f"  {t} has no price data at all; skipping")
                        continue
                else:
                    continue

            current_shares = holdings.get(t, 0)
            current_value = current_shares * float(p)
            diff_value = target_per_name - current_value

            if abs(diff_value) < 1.0:
                continue

            if diff_value > 0:
                # Buy more
                gross_spend = diff_value
                new_shares = gross_spend / (float(p) * (1 + TRANSACTION_COST_PER_SIDE))
                cost = new_shares * float(p) * (1 + TRANSACTION_COST_PER_SIDE)
                if cost > cash:
                    new_shares = cash / (float(p) * (1 + TRANSACTION_COST_PER_SIDE))
                    cost = cash
                cash -= cost
                holdings[t] = current_shares + new_shares
                trades.append({"date": str(exec_day.date()), "ticker": t, "side": "BUY",
                               "shares": new_shares, "price": float(p), "cash_after": cash})
            else:
                # Trim
                sell_shares = -diff_value / float(p)
                proceeds = sell_shares * float(p) * (1 - TRANSACTION_COST_PER_SIDE)
                cash += proceeds
                holdings[t] = current_shares - sell_shares
                trades.append({"date": str(exec_day.date()), "ticker": t, "side": "TRIM",
                               "shares": sell_shares, "price": float(p), "cash_after": cash})

        # Record portfolio state
        post_val = cash + sum(
            holdings[t] * float(prices.loc[prices.index[prices.index <= exec_day][-1], t+".NS"])
            for t in holdings if t+".NS" in prices.columns
            and pd.notna(prices.loc[prices.index[prices.index <= exec_day][-1], t+".NS"])
        )
        log.info(f"  Portfolio value post-rebalance: ₹{post_val:,.0f}  (cash=₹{cash:,.0f})")

        # Store picks for this quarter
        quarter_result = {
            "quarter_idx": i,
            "nominal_date": nominal,
            "actual_rebalance_day": str(rd.date()),
            "execution_day": str(exec_day.date()),
            "top_25": [
                {"ticker": s.ticker, "total_score": s.total,
                 "fundamental": s.fundamental, "valuation": s.valuation,
                 "momentum": s.momentum}
                for s in top
            ],
            "portfolio_value_post_rebalance": post_val,
            "cash": cash,
        }
        quarter_results.append(quarter_result)

    # ─── End of last rebalance: compute returns through end of last quarter ───
    # We simulate up to end of 2025
    final_day = prices.index[-1]
    final_val = cash + sum(
        holdings[t] * float(prices.loc[prices.index[prices.index <= final_day][-1], t+".NS"])
        for t in holdings if t+".NS" in prices.columns
        and pd.notna(prices.loc[prices.index[prices.index <= final_day][-1], t+".NS"])
    )

    # Build per-rebalance NAV series (one value per quarter post-rebalance, plus the final point)
    # portfolio_nav[0] = INITIAL_CAPITAL (pre-first-rebalance)
    # portfolio_nav[i] for i>=1 = value just AFTER rebalance i-1 executed
    # portfolio_nav[-1] = value on final_day (covers holding period after last rebalance)
    log.info("")
    log.info("Building per-rebalance NAV series...")

    portfolio_nav  = [INITIAL_CAPITAL] + [q["portfolio_value_post_rebalance"] for q in quarter_results]
    benchmark_vals = [INITIAL_CAPITAL]
    for q in quarter_results:
        exec_day = pd.Timestamp(q["execution_day"])
        n_val = nifty.loc[nifty.index <= exec_day].iloc[-1]
        benchmark_vals.append(bench_units * n_val)

    # Append final segment value (from last rebalance through end of data)
    portfolio_nav.append(final_val)
    benchmark_vals.append(bench_units * nifty.loc[nifty.index <= final_day].iloc[-1])

    # Per-quarter return (segment)
    for i, q in enumerate(quarter_results):
        start = portfolio_nav[i]
        end = portfolio_nav[i+1]
        seg_return = (end / start - 1) * 100 if start > 0 else 0

        bench_start = benchmark_vals[i]
        bench_end = benchmark_vals[i+1]
        bench_return = (bench_end / bench_start - 1) * 100 if bench_start > 0 else 0

        # Hit rate for THIS quarter's picks: how many of the top 25 beat the nifty over the quarter
        # Need per-stock return over the segment
        if i+1 < len(quarter_results):
            next_exec = pd.Timestamp(quarter_results[i+1]["execution_day"])
        else:
            next_exec = final_day

        cur_exec = pd.Timestamp(q["execution_day"])
        hits = 0
        ticker_returns = []
        for pick in q["top_25"]:
            sym = pick["ticker"] + ".NS"
            if sym not in prices.columns:
                continue
            p_start = prices.loc[prices.index[prices.index <= cur_exec][-1], sym]
            p_end = prices.loc[prices.index[prices.index <= next_exec][-1], sym]
            if pd.notna(p_start) and pd.notna(p_end) and p_start > 0:
                r = (p_end / p_start - 1) * 100
                ticker_returns.append((pick["ticker"], r))
                if r > bench_return:
                    hits += 1

        q["return_pct"] = seg_return
        q["nifty_return_pct"] = bench_return
        q["spread_pct"] = seg_return - bench_return
        q["hit_rate"] = hits / len(q["top_25"]) if q["top_25"] else 0
        q["ticker_returns"] = ticker_returns

    # Cumulative metrics
    total_return = (portfolio_nav[-1] / portfolio_nav[0] - 1) * 100
    total_bench = (benchmark_vals[-1] / benchmark_vals[0] - 1) * 100

    # Period length for annualization
    start_day = pd.Timestamp(quarter_results[0]["execution_day"])
    end_day   = final_day
    years = (end_day - start_day).days / 365.25

    annual_return = ((portfolio_nav[-1] / portfolio_nav[0]) ** (1/years) - 1) * 100
    annual_bench = ((benchmark_vals[-1] / benchmark_vals[0]) ** (1/years) - 1) * 100

    # Sharpe: using quarterly returns
    port_qr = [q["return_pct"] / 100 for q in quarter_results]
    bench_qr = [q["nifty_return_pct"] / 100 for q in quarter_results]
    rf_quarterly = RISK_FREE_RATE_ANNUAL / 4
    port_excess = [r - rf_quarterly for r in port_qr]
    bench_excess = [r - rf_quarterly for r in bench_qr]

    if np.std(port_excess) > 0:
        sharpe_port = np.mean(port_excess) / np.std(port_excess) * np.sqrt(4)
    else:
        sharpe_port = 0
    if np.std(bench_excess) > 0:
        sharpe_bench = np.mean(bench_excess) / np.std(bench_excess) * np.sqrt(4)
    else:
        sharpe_bench = 0

    # Jensen's alpha: regress portfolio excess on benchmark excess
    if len(port_excess) > 2 and np.std(bench_excess) > 0:
        cov = np.cov(port_excess, bench_excess, ddof=0)[0, 1]
        beta = cov / np.var(bench_excess, ddof=0)
        alpha_quarterly = np.mean(port_excess) - beta * np.mean(bench_excess)
        alpha_annual = alpha_quarterly * 4 * 100
    else:
        beta = 0
        alpha_annual = 0

    tracking_error = np.std([p - b for p, b in zip(port_qr, bench_qr)]) * np.sqrt(4) * 100

    summary = {
        "initial_capital": INITIAL_CAPITAL,
        "final_portfolio_value": portfolio_nav[-1],
        "final_benchmark_value": benchmark_vals[-1],
        "total_return_pct": total_return,
        "total_benchmark_return_pct": total_bench,
        "spread_pct": total_return - total_bench,
        "annual_return_pct": annual_return,
        "annual_benchmark_return_pct": annual_bench,
        "annual_alpha_pct": alpha_annual,
        "beta": beta,
        "sharpe_portfolio": sharpe_port,
        "sharpe_benchmark": sharpe_bench,
        "tracking_error_annual_pct": tracking_error,
        "overall_hit_rate": np.mean([q["hit_rate"] for q in quarter_results]),
        "years_simulated": years,
        "num_quarters": len(quarter_results),
    }

    return {
        "summary": summary,
        "quarters": quarter_results,
        "portfolio_nav_at_rebalance": portfolio_nav,
        "benchmark_nav_at_rebalance": benchmark_vals,
        "trades": trades,
        "assumptions": {
            "transaction_cost_per_side": TRANSACTION_COST_PER_SIDE,
            "risk_free_rate_annual": RISK_FREE_RATE_ANNUAL,
            "fundamental_lag_days": FUNDAMENTAL_LAG_DAYS,
            "top_n": TOP_N,
            "initial_capital": INITIAL_CAPITAL,
            "weighting": "equal",
            "execution_price": "next_trading_day_close (proxy for open)",
        },
    }


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    log.info("Loading cached data...")
    prices = load_prices()
    nifty  = load_nifty()
    info_map = load_info()
    compositions = load_composition()

    # Preload financials
    income_cache = {}
    bs_cache = {}
    for t in compositions["all_tickers"]:
        inc = load_income(t)
        bs = load_balance_sheet(t)
        if inc is not None:
            income_cache[t] = inc
        if bs is not None:
            bs_cache[t] = bs

    log.info(f"  Prices: {prices.shape}, Nifty: {nifty.shape}")
    log.info(f"  Income statements: {len(income_cache)}, Balance sheets: {len(bs_cache)}")
    log.info(f"  Info records: {len(info_map)}")

    result = simulate(compositions, prices, nifty, income_cache, bs_cache, info_map)

    # Save
    with open(RESULTS_DIR / "results.json", "w") as f:
        json.dump(result, f, indent=2, default=str)

    trades_df = pd.DataFrame(result["trades"])
    trades_df.to_csv(RESULTS_DIR / "trades.csv", index=False)

    log.info("")
    log.info("=" * 60)
    log.info("SIMULATION COMPLETE")
    log.info("=" * 60)
    s = result["summary"]
    log.info(f"  Portfolio total return:  {s['total_return_pct']:+.2f}%")
    log.info(f"  Benchmark total return:  {s['total_benchmark_return_pct']:+.2f}%")
    log.info(f"  Spread:                  {s['spread_pct']:+.2f}%")
    log.info(f"  Annualized portfolio:    {s['annual_return_pct']:+.2f}%/yr")
    log.info(f"  Annualized benchmark:    {s['annual_benchmark_return_pct']:+.2f}%/yr")
    log.info(f"  Alpha (annualized):      {s['annual_alpha_pct']:+.2f}%/yr")
    log.info(f"  Beta:                    {s['beta']:.3f}")
    log.info(f"  Sharpe (portfolio):      {s['sharpe_portfolio']:.3f}")
    log.info(f"  Sharpe (benchmark):      {s['sharpe_benchmark']:.3f}")
    log.info(f"  Overall hit rate:        {s['overall_hit_rate']*100:.1f}%")
    log.info("")
    log.info(f"Results written to {RESULTS_DIR}/")
    log.info("Next step: run `py backtest_report.py`")


if __name__ == "__main__":
    main()
