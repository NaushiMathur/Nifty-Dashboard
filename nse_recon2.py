"""
nse_recon2.py — NSE XBRL recon using Playwright (real browser)
===============================================================
NSE blocks plain HTTP requests. This uses a real Chromium browser
to get past the JS-based cookie protection.

Install first:
    pip install playwright
    playwright install chromium

Then run:
    py nse_recon2.py
"""

import json
import time

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright not installed.")
    print("Run these two commands first:")
    print("    pip install playwright")
    print("    playwright install chromium")
    raise SystemExit(1)

TEST_SYMBOLS = ["GRASIM", "LT", "RELIANCE", "TCS"]

def main():
    print("=" * 60)
    print("NSE XBRL Recon — Playwright browser")
    print("=" * 60)

    with sync_playwright() as p:
        # Launch real Chromium browser (headless = no visible window)
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Step 1: Load NSE homepage to get session cookies
        print("\nLoading NSE homepage to establish session...")
        try:
            page.goto("https://www.nseindia.com", timeout=20000)
            page.wait_for_timeout(3000)  # Let JS run
            cookies = context.cookies()
            print(f"  Cookies after homepage load: {[c['name'] for c in cookies]}")
        except Exception as e:
            print(f"  Homepage error: {e}")

        for symbol in TEST_SYMBOLS:
            print(f"\n{'='*60}")
            print(f"SYMBOL: {symbol}")
            print(f"{'='*60}")

            # Step 2: Call the financial results API with active session
            api_url = f"https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol={symbol}&period=Quarterly&type=Consolidated"

            try:
                response = page.goto(api_url, timeout=15000)
                page.wait_for_timeout(1000)
                content = page.content()

                # Extract JSON from page content
                # Playwright wraps JSON in <html><body><pre>...</pre></body></html>
                import re
                json_match = re.search(r'<pre[^>]*>(.*?)</pre>', content, re.DOTALL)
                if json_match:
                    raw_json = json_match.group(1).strip()
                    try:
                        data = json.loads(raw_json)
                        if isinstance(data, list):
                            print(f"  Filings found: {len(data)}")
                            if data:
                                print(f"  Keys: {list(data[0].keys())}")
                                print(f"\n  Most recent filing:")
                                for k, v in data[0].items():
                                    print(f"    {k}: {v}")

                                # Look for XBRL/ZIP links
                                print(f"\n  Scanning for XBRL/ZIP links...")
                                for filing in data[:3]:
                                    for k, v in filing.items():
                                        val = str(v or '')
                                        if any(x in val.lower() for x in ['.zip', 'xbrl', '.xml', '.xbrl']):
                                            print(f"    FOUND in '{k}': {val}")

                                # Try to fetch the XBRL file from most recent filing
                                recent = data[0]
                                xbrl_key = None
                                xbrl_url = None
                                for k, v in recent.items():
                                    val = str(v or '')
                                    if '.zip' in val.lower() or '.xbrl' in val.lower():
                                        xbrl_key = k
                                        xbrl_url = val
                                        break

                                if xbrl_url:
                                    if xbrl_url.startswith('/'):
                                        xbrl_url = f"https://www.nseindia.com{xbrl_url}"
                                    print(f"\n  Fetching XBRL file: {xbrl_url}")
                                    try:
                                        r2 = page.goto(xbrl_url, timeout=20000)
                                        page.wait_for_timeout(1000)
                                        xbrl_content = page.content()
                                        print(f"  XBRL content length: {len(xbrl_content)} chars")
                                        print(f"  Preview (first 1500 chars):")
                                        # Strip HTML wrapper if present
                                        xml_match = re.search(r'<pre[^>]*>(.*?)</pre>', xbrl_content, re.DOTALL)
                                        if xml_match:
                                            print(xml_match.group(1)[:1500])
                                        else:
                                            print(xbrl_content[:1500])
                                    except Exception as e:
                                        print(f"  XBRL fetch error: {e}")
                                else:
                                    print("  No XBRL/ZIP link found in filing records.")

                        elif isinstance(data, dict):
                            print(f"  Response is dict. Keys: {list(data.keys())}")
                            print(json.dumps(data, indent=2)[:500])
                        else:
                            print(f"  Unexpected type: {type(data)}")
                            print(str(data)[:500])

                    except json.JSONDecodeError as e:
                        print(f"  JSON parse error: {e}")
                        print(f"  Raw content preview: {raw_json[:500]}")
                else:
                    print(f"  No <pre> block found in response")
                    print(f"  Raw content preview: {content[:500]}")

            except Exception as e:
                print(f"  Error: {e}")

            time.sleep(2)

        browser.close()

    print("\n" + "="*60)
    print("Recon complete. Paste full output back to Claude.")
    print("="*60)

if __name__ == "__main__":
    main()
