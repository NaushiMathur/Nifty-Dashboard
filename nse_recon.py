"""
nse_recon.py — NSE XBRL reconnaissance script
===============================================
Run this ONCE on your laptop to show us what NSE's API returns.
We use this output to understand the data structure before building
the real minority interest fetcher.

Usage:
    py nse_recon.py

Paste the full output back to Claude.
"""

import requests
import json
import time

# NSE requires a browser-like session with cookies
# We hit the main page first to get cookies, then call the API

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

# Test stocks — one conglomerate (Grasim, known high minority interest)
# and one clean company (TCS, known zero minority interest)
TEST_SYMBOLS = ["GRASIM", "TCS", "LT", "RELIANCE"]

def get_session():
    s = requests.Session()
    print("Hitting NSE homepage to get cookies...")
    try:
        r = s.get("https://www.nseindia.com", headers=HEADERS, timeout=15)
        print(f"  Homepage status: {r.status_code}")
        print(f"  Cookies received: {list(r.cookies.keys())}")
        time.sleep(2)
    except Exception as e:
        print(f"  Homepage error: {e}")
    return s

def fetch_financial_results(session, symbol):
    """Fetch the list of financial result filings for a symbol."""
    url = f"https://www.nseindia.com/api/corporates-financial-results"
    params = {
        "index": "equities",
        "symbol": symbol,
        "period": "Quarterly",
        "type": "Consolidated",
    }
    try:
        r = session.get(url, headers=HEADERS, params=params, timeout=15)
        print(f"\n  Financial results list — status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            return data
        else:
            print(f"  Response text: {r.text[:300]}")
            return None
    except Exception as e:
        print(f"  Error: {e}")
        return None

def fetch_xbrl_file(session, xbrl_url):
    """Try to download an actual XBRL file."""
    try:
        r = session.get(xbrl_url, headers=HEADERS, timeout=20)
        print(f"  XBRL file status: {r.status_code}  size: {len(r.content)} bytes")
        if r.status_code == 200:
            # Show first 2000 chars of the XML
            text = r.text[:2000]
            return text
        return None
    except Exception as e:
        print(f"  XBRL fetch error: {e}")
        return None

def main():
    print("=" * 60)
    print("NSE XBRL Reconnaissance")
    print("=" * 60)

    session = get_session()

    for symbol in TEST_SYMBOLS:
        print(f"\n{'='*60}")
        print(f"SYMBOL: {symbol}")
        print(f"{'='*60}")

        filings = fetch_financial_results(session, symbol)
        if not filings:
            print("  No data returned.")
            continue

        if isinstance(filings, list):
            print(f"  Total filings found: {len(filings)}")
            if filings:
                print(f"  Keys in each record: {list(filings[0].keys())}")
                print(f"\n  Most recent 2 filings:")
                for filing in filings[:2]:
                    print(f"    ---")
                    for k, v in filing.items():
                        print(f"    {k}: {v}")

                # Try to find XBRL file link
                recent = filings[0]
                xbrl_link = None
                for key in recent:
                    val = str(recent[key])
                    if '.zip' in val.lower() or 'xbrl' in val.lower() or '.xml' in val.lower():
                        print(f"\n  Possible XBRL link found in field '{key}': {val}")
                        xbrl_link = val

                if xbrl_link:
                    print(f"\n  Attempting to fetch XBRL file: {xbrl_link}")
                    # NSE links are relative — prepend base URL if needed
                    if xbrl_link.startswith('/'):
                        xbrl_link = f"https://www.nseindia.com{xbrl_link}"
                    xml_content = fetch_xbrl_file(session, xbrl_link)
                    if xml_content:
                        print(f"\n  XBRL file preview (first 2000 chars):")
                        print(xml_content)
                else:
                    print("\n  No XBRL/ZIP link found in filing record.")
                    print("  All field values:")
                    for k, v in recent.items():
                        print(f"    {k}: {v}")

        elif isinstance(filings, dict):
            print(f"  Response is dict. Keys: {list(filings.keys())}")
            print(json.dumps(filings, indent=2)[:1000])

        time.sleep(2)  # Be polite

    print("\n" + "="*60)
    print("Recon complete. Paste this full output back to Claude.")
    print("="*60)

if __name__ == "__main__":
    main()
