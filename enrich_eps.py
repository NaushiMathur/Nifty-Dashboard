"""
enrich_eps.py — BSE Exceptional Items Enrichment Script
========================================================
Run this on your LAPTOP (not GitHub Actions) once per quarter, ideally
1-2 weeks after each quarterly results season ends (mid-Feb, mid-May,
mid-Aug, mid-Nov).

What it does:
  1. Reads nifty_data.json to find stocks with eps_quality = PARTIAL or UNVERIFIED
  2. For each such stock, calls BSE India's resultsSnapshot() API via the
     `bse` Python library — this API works from laptops but is blocked from
     cloud/GitHub Actions servers
  3. Extracts the "Exceptional Items" row from BSE's quarterly P&L data
  4. Writes eps_overrides.json — a file fetch_data.py reads to fill in
     missing exceptional items data that Yahoo Finance doesn't provide

How to run:
  pip install bse
  py enrich_eps.py

After it completes:
  git add eps_overrides.json
  git commit -m "Quarterly EPS enrichment — <month> <year>"
  git push

The next fetch_data.py run (or your next manual run) will pick up the
overrides automatically and upgrade PARTIAL → CLEAN for affected stocks.
"""

import json
import os
import time
import logging
from datetime import datetime, timedelta
from dateutil import parser as dateutil_parser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# NSE ticker → BSE scrip code lookup table
# These are the Nifty 50 constituents as of April 2026.
# If the index composition changes, update this dict.
# Format: "NSE_TICKER.NS" → BSE_SCRIP_CODE (integer as string)
# ─────────────────────────────────────────────────────────────────────────────
NSE_TO_BSE = {
    "RELIANCE.NS":    "500325",
    "TCS.NS":         "532540",
    "HDFCBANK.NS":    "500180",
    "BHARTIARTL.NS":  "532454",
    "ICICIBANK.NS":   "532174",
    "INFOSYS.NS":     "500209",
    "SBIN.NS":        "500112",
    "HINDUNILVR.NS":  "500696",
    "ITC.NS":         "500875",
    "LT.NS":          "500510",
    "KOTAKBANK.NS":   "500247",
    "BAJFINANCE.NS":  "500034",
    "HCLTECH.NS":     "532281",
    "MARUTI.NS":      "532500",
    "AXISBANK.NS":    "532215",
    "ASIANPAINT.NS":  "500820",
    "TITAN.NS":       "500114",
    "BAJAJFINSV.NS":  "532978",
    "SUNPHARMA.NS":   "524715",
    "POWERGRID.NS":   "532898",
    "NTPC.NS":        "532555",
    "ULTRACEMCO.NS":  "532538",
    "WIPRO.NS":       "507685",
    "ONGC.NS":        "500312",
    "TECHM.NS":       "532755",
    "TATAMOTORS.NS":  "500570",
    "TATASTEEL.NS":   "500470",
    "JSWSTEEL.NS":    "500228",
    "M&M.NS":         "500520",
    "COALINDIA.NS":   "533278",
    "ADANIENT.NS":    "512599",
    "ADANIPORTS.NS":  "532921",
    "APOLLOHOSP.NS":  "508869",
    "BAJAJ-AUTO.NS":  "532977",
    "BRITANNIA.NS":   "500825",   # may have exited index; kept for historical overrides
    "CIPLA.NS":       "500087",
    "DIVISLAB.NS":    "532488",
    "DRREDDY.NS":     "500124",
    "EICHERMOT.NS":   "505200",
    "GRASIM.NS":      "500300",
    "HEROMOTOCO.NS":  "500182",
    "HINDALCO.NS":    "500440",
    "INDUSINDBK.NS":  "532187",
    "JIOFIN.NS":      "543260",
    "NESTLEIND.NS":   "500790",
    "SHRIRAMFIN.NS":  "511218",
    "TRENT.NS":       "500251",
    "BEL.NS":         "500049",
    "ZOMATO.NS":      "543320",
    "INDIGO.NS":      "521064",
    "MAXHEALTH.NS":   "543220",
    "LTIM.NS":        "540005",   # may have exited; kept for historical overrides
}


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
NIFTY_DATA_FILE    = "nifty_data.json"
OVERRIDES_FILE     = "eps_overrides.json"
BSE_DOWNLOAD_FOLDER = "./.bse_cache"   # temporary BSE library cache
REQUEST_DELAY_SEC  = 1.5               # polite delay between BSE API calls
MAX_QUARTERS_BACK  = 8                 # how many quarters to look back (2 years)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def load_existing_overrides():
    """Load eps_overrides.json if it exists, so we can merge/update entries."""
    if os.path.exists(OVERRIDES_FILE):
        with open(OVERRIDES_FILE, "r") as f:
            data = json.load(f)
        log.info(f"Loaded existing overrides: {len(data.get('overrides', {}))} stocks")
        return data
    return {
        "generated_at": None,
        "description": (
            "BSE-sourced exceptional items per stock per quarter. "
            "Run enrich_eps.py on laptop to regenerate. "
            "Merged into fetch_data.py when Yahoo data is missing."
        ),
        "overrides": {}
    }


def parse_bse_period_to_date(period_str):
    """
    Convert BSE period string like 'Dec 2024' or '31-Dec-2024' to YYYY-MM-DD.
    Returns the last day of the relevant month/quarter.
    """
    period_str = period_str.strip()
    # Try direct parse first (handles '31-Dec-2024' etc.)
    try:
        dt = dateutil_parser.parse(period_str, dayfirst=True)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    # Try 'Mon YYYY' format (e.g. 'Dec 2024' → last day of Dec 2024)
    try:
        dt = datetime.strptime(period_str, "%b %Y")
        # Move to last day of that month
        if dt.month == 12:
            last_day = dt.replace(day=31)
        else:
            last_day = dt.replace(month=dt.month + 1, day=1) - timedelta(days=1)
        return last_day.strftime("%Y-%m-%d")
    except Exception:
        pass
    return None


def crores_from_unit(value, currency_unit):
    """
    BSE reports values in Crores or Millions (Lakhs). Normalise to crores.
    currency_unit is a string like 'Crores' or 'Millions' or 'Lakhs'.
    Returns float in crores, or None if value is blank/non-numeric.
    """
    if value is None or str(value).strip() in ("", "-", "N/A"):
        return None
    try:
        v = float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return None

    unit = (currency_unit or "Crores").lower()
    if "million" in unit or "lakh" in unit:
        return round(v / 100, 2)   # 1 crore = 100 lakhs = 10 million
    return round(v, 2)              # already in crores


def find_exceptional_items(data_rows, periods, currency_unit):
    """
    Search the BSE results data rows for exceptional items.

    data_rows: list of [title, val1, val2, val3, ...] from BSE API
    periods:   list of period label strings (same order as columns)

    Returns dict: { "YYYY-MM-DD": value_in_crores_or_None, ... }
    for each period in the BSE data.
    """
    EXCEPTIONAL_LABELS = [
        "exceptional items",
        "exceptional and extraordinary items",
        "extraordinary items",
        "total unusual items",
        "unusual items",
        "other non operating income expenses",
    ]

    results = {}
    matched_row = None

    for row in data_rows:
        if not row:
            continue
        title = str(row[0]).lower().strip()
        # Match on any of the exceptional label patterns
        if any(lbl in title for lbl in EXCEPTIONAL_LABELS):
            matched_row = row
            break

    if matched_row is None:
        # No exceptional items row found — that's fine, many quarters have none
        for p in periods:
            date = parse_bse_period_to_date(p)
            if date:
                results[date] = 0.0   # explicitly zero — not missing, just nil
        return results, False

    # Row found — extract values for each period
    for i, p in enumerate(periods):
        date = parse_bse_period_to_date(p)
        if date is None:
            continue
        val_raw = matched_row[i + 1] if (i + 1) < len(matched_row) else None
        val_crores = crores_from_unit(val_raw, currency_unit)
        results[date] = val_crores  # None means data was blank in BSE source

    return results, True


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENRICHMENT LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def enrich_stock(bse_client, nse_symbol, scrip_code):
    """
    Fetch BSE quarterly P&L for one stock and extract exceptional items.

    Returns dict: { "YYYY-MM-DD": exceptional_crores, ... }
                  or None on failure
    """
    log.info(f"  Fetching BSE data for {nse_symbol} (scrip {scrip_code})...")
    try:
        snap = bse_client.resultsSnapshot(scrip_code)
    except Exception as e:
        log.warning(f"  BSE API error for {nse_symbol}: {e}")
        return None

    if not snap:
        log.warning(f"  Empty response for {nse_symbol}")
        return None

    # BSE returns results_in_crores and results_in_millions — prefer crores
    results_block = snap.get("results_in_crores") or snap.get("results_in_millions")
    if not results_block:
        log.warning(f"  No results block in response for {nse_symbol}")
        return None

    currency_unit = snap.get("currency_unit", "Crores")
    if snap.get("results_in_millions") and not snap.get("results_in_crores"):
        currency_unit = "Millions"

    periods = snap.get("periods", [])
    if not periods:
        log.warning(f"  No period labels for {nse_symbol}")
        return None

    data_rows = results_block.get("data", [])
    if not data_rows:
        log.warning(f"  No data rows for {nse_symbol}")
        return None

    quarterly_data, found_exc = find_exceptional_items(data_rows, periods, currency_unit)

    if found_exc:
        log.info(f"  ✓ {nse_symbol}: Found exceptional items row — {len(quarterly_data)} quarters")
    else:
        log.info(f"  ○ {nse_symbol}: No exceptional items row (all zeros assigned)")

    return quarterly_data


def main():
    log.info("=" * 60)
    log.info("enrich_eps.py — BSE Exceptional Items Enrichment")
    log.info("=" * 60)

    # ── Check bse library is installed ──
    try:
        from bse import BSE
    except ImportError:
        log.error("The 'bse' library is not installed. Run: pip install bse")
        raise SystemExit(1)

    # ── Check dateutil is installed ──
    try:
        from dateutil import parser as _
    except ImportError:
        log.error("The 'python-dateutil' library is not installed. Run: pip install python-dateutil")
        raise SystemExit(1)

    # ── Load current nifty_data.json to find target stocks ──
    if not os.path.exists(NIFTY_DATA_FILE):
        log.error(f"{NIFTY_DATA_FILE} not found. Run fetch_data.py first.")
        raise SystemExit(1)

    with open(NIFTY_DATA_FILE, "r") as f:
        nifty_data = json.load(f)

    stocks = nifty_data.get("stocks", [])
    if not stocks:
        log.error("No stocks in nifty_data.json")
        raise SystemExit(1)

    # ── Identify which stocks need enrichment ──
    # We enrich ALL stocks, not just PARTIAL/UNVERIFIED, because:
    # 1. Conditions change — a stock may have been PARTIAL last run but Yahoo
    #    improved; we want fresh BSE data to compare against
    # 2. The override only takes effect when Yahoo is missing the data anyway
    target_stocks = []
    for s in stocks:
        nse_sym = s.get("symbol")
        quality = s.get("eps_quality", "UNVERIFIED")
        if nse_sym in NSE_TO_BSE:
            target_stocks.append((nse_sym, quality, NSE_TO_BSE[nse_sym]))
        else:
            log.warning(f"No BSE code for {nse_sym} — skipping")

    # Sort: UNVERIFIED first, then PARTIAL, then CLEAN (highest value first)
    quality_order = {"UNVERIFIED": 0, "PARTIAL": 1, "CLEAN": 2}
    target_stocks.sort(key=lambda x: quality_order.get(x[1], 99))

    unverified_count = sum(1 for _, q, _ in target_stocks if q == "UNVERIFIED")
    partial_count    = sum(1 for _, q, _ in target_stocks if q == "PARTIAL")
    clean_count      = sum(1 for _, q, _ in target_stocks if q == "CLEAN")

    log.info(f"Target stocks: {len(target_stocks)} total")
    log.info(f"  UNVERIFIED: {unverified_count} | PARTIAL: {partial_count} | CLEAN: {clean_count}")
    log.info("")

    # ── Load existing overrides (merge-safe) ──
    existing = load_existing_overrides()
    overrides = existing.get("overrides", {})

    # ── Initialise BSE client ──
    os.makedirs(BSE_DOWNLOAD_FOLDER, exist_ok=True)
    bse = BSE(download_folder=BSE_DOWNLOAD_FOLDER)

    # ── Fetch data for each stock ──
    success_count = 0
    fail_count    = 0

    try:
        for i, (nse_sym, quality, scrip_code) in enumerate(target_stocks):
            log.info(f"[{i+1}/{len(target_stocks)}] {nse_sym} (quality: {quality})")

            quarterly_data = enrich_stock(bse, nse_sym, scrip_code)

            if quarterly_data is not None:
                # Store under the NSE symbol (without .NS suffix for readability)
                key = nse_sym.replace(".NS", "")
                overrides[key] = {
                    "scrip_code":   scrip_code,
                    "updated_at":   datetime.now().isoformat(),
                    "eps_quality_at_fetch": quality,
                    "exceptional_items_cr": quarterly_data
                    # dict of { "YYYY-MM-DD": crores_or_None, ... }
                    # None = data present in BSE but value was blank
                    # 0.0  = no exceptional items that quarter (explicitly zero)
                    # float = actual exceptional items value in crores
                }
                success_count += 1
            else:
                fail_count += 1

            if i < len(target_stocks) - 1:
                time.sleep(REQUEST_DELAY_SEC)

    finally:
        bse.exit()
        log.info("BSE client closed.")

    # ── Write eps_overrides.json ──
    output = {
        "generated_at": datetime.now().isoformat(),
        "description": (
            "BSE-sourced exceptional items per stock per quarter. "
            "Run enrich_eps.py on laptop to regenerate. "
            "Merged into fetch_data.py when Yahoo data is missing."
        ),
        "overrides": overrides
    }

    with open(OVERRIDES_FILE, "w") as f:
        json.dump(output, f, indent=2)

    log.info("")
    log.info("=" * 60)
    log.info(f"Done. Success: {success_count} | Failed: {fail_count}")
    log.info(f"Overrides written to {OVERRIDES_FILE}")
    log.info("")
    log.info("Next steps:")
    log.info("  git add eps_overrides.json")
    log.info("  git commit -m 'Quarterly EPS enrichment — <month> <year>'")
    log.info("  git push")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
