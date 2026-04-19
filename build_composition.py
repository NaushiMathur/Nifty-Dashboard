"""
Build nifty50_historical_composition.json — the source of truth for which
50 stocks were in Nifty 50 at each quarterly rebalance date during the backtest
window (Feb 2022 - Nov 2025).

Run once:  py build_composition.py
Output:    nifty50_historical_composition.json in the current directory.

Sources (NSE reconstitution announcements — all verified via public news):
  2022-03-31: IOC out, APOLLOHOSP in
  2022-09-30: SHREECEM out, ADANIENT in
  2023-07-13: HDFC Ltd out (merger with HDFC Bank), LTIM in
  2024-03-28: UPL out, SHRIRAMFIN in
  2024-09-30: DIVISLAB, LTIM out; TRENT, BEL in
  2025-03-28: BPCL, BRITANNIA out; JIOFIN, ZOMATO in
  2025-09-30: HEROMOTOCO, INDUSINDBK out; INDIGO, MAXHEALTH in
"""
import json
from copy import deepcopy

# Pre-Feb-2022 composition (post-Mar-2021 TATACONSUM/GAIL swap, pre-Mar-2022 IOC/APOLLOHOSP swap)
pre_2022 = {
    'ADANIPORTS', 'ASIANPAINT', 'AXISBANK', 'BAJAJ-AUTO', 'BAJAJFINSV', 'BAJFINANCE',
    'BHARTIARTL', 'BPCL', 'BRITANNIA', 'CIPLA', 'COALINDIA', 'DIVISLAB', 'DRREDDY',
    'EICHERMOT', 'GRASIM', 'HCLTECH', 'HDFC', 'HDFCBANK', 'HDFCLIFE', 'HEROMOTOCO',
    'HINDALCO', 'HINDUNILVR', 'ICICIBANK', 'INDUSINDBK', 'INFY', 'IOC', 'ITC',
    'JSWSTEEL', 'KOTAKBANK', 'LT', 'M&M', 'MARUTI', 'NESTLEIND', 'NTPC', 'ONGC',
    'POWERGRID', 'RELIANCE', 'SBILIFE', 'SBIN', 'SHREECEM', 'SUNPHARMA', 'TATACONSUM',
    'TATAMOTORS', 'TATASTEEL', 'TCS', 'TECHM', 'TITAN', 'ULTRACEMCO', 'UPL', 'WIPRO'
}

changes = [
    ('2022-03-31', {'IOC'}, {'APOLLOHOSP'}),
    ('2022-09-30', {'SHREECEM'}, {'ADANIENT'}),
    ('2023-07-13', {'HDFC'}, {'LTIM'}),
    ('2024-03-28', {'UPL'}, {'SHRIRAMFIN'}),
    ('2024-09-30', {'DIVISLAB', 'LTIM'}, {'TRENT', 'BEL'}),
    ('2025-03-28', {'BPCL', 'BRITANNIA'}, {'JIOFIN', 'ZOMATO'}),
    ('2025-09-30', {'HEROMOTOCO', 'INDUSINDBK'}, {'INDIGO', 'MAXHEALTH'}),
]

# 16 quarterly rebalance dates: first trading day of Feb/May/Aug/Nov, 2022-2025.
rebalance_dates = [
    '2022-02-01', '2022-05-02', '2022-08-01', '2022-11-01',
    '2023-02-01', '2023-05-02', '2023-08-01', '2023-11-01',
    '2024-02-01', '2024-05-02', '2024-08-01', '2024-11-01',
    '2025-02-03', '2025-05-02', '2025-08-01', '2025-11-03',
]

comp = deepcopy(pre_2022)
change_idx = 0
compositions = {}

for rd in rebalance_dates:
    while change_idx < len(changes) and changes[change_idx][0] <= rd:
        eff, removed, added = changes[change_idx]
        comp = (comp - removed) | added
        change_idx += 1
    compositions[rd] = sorted(comp)
    assert len(comp) == 50, f"ERROR at {rd}: {len(comp)} stocks"

all_tickers = set(pre_2022)
for _, _, added in changes:
    all_tickers |= added

out = {
    'rebalance_dates': rebalance_dates,
    'changes': [{'date': d, 'removed': sorted(r), 'added': sorted(a)} for d, r, a in changes],
    'composition_by_date': compositions,
    'all_tickers': sorted(all_tickers),
    'yf_ticker_map': {t: t + '.NS' for t in sorted(all_tickers)},
    'notes': 'Nifty 50 constituents active AT each rebalance date. Source: public NSE reconstitution announcements.',
}

with open('nifty50_historical_composition.json', 'w') as f:
    json.dump(out, f, indent=2)

print(f"Wrote nifty50_historical_composition.json")
print(f"  {len(rebalance_dates)} rebalance dates, {len(all_tickers)} unique tickers in universe")
print(f"  All compositions have exactly 50 stocks: {all(len(c)==50 for c in compositions.values())}")
