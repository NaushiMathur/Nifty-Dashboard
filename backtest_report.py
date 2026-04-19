"""
Backtest Report Generator
=========================
Reads backtest_results/results.json and produces a self-contained HTML report
you can open in a browser or push to GitHub Pages.

USAGE
-----
    py backtest_report.py

Output: backtest_results/report.html
"""

import json
from pathlib import Path
from datetime import datetime

RESULTS_DIR = Path("backtest_results")

def fmt_pct(x, decimals=2, plus=True):
    if x is None:
        return "—"
    s = f"{x:+.{decimals}f}%" if plus else f"{x:.{decimals}f}%"
    return s

def fmt_money(x):
    if x is None:
        return "—"
    return f"₹{x:,.0f}"

def color_class(x):
    if x is None: return ""
    return "pos" if x > 0 else ("neg" if x < 0 else "flat")


def build_html(result):
    s = result["summary"]
    a = result["assumptions"]
    quarters = result["quarters"]

    # Quarter rows
    quarter_rows = []
    for q in quarters:
        quarter_rows.append(f"""
        <tr>
            <td>{q['nominal_date']}</td>
            <td>{q['execution_day']}</td>
            <td class="{color_class(q['return_pct'])}">{fmt_pct(q['return_pct'])}</td>
            <td class="{color_class(q['nifty_return_pct'])}">{fmt_pct(q['nifty_return_pct'])}</td>
            <td class="{color_class(q['spread_pct'])}"><strong>{fmt_pct(q['spread_pct'])}</strong></td>
            <td>{q['hit_rate']*100:.1f}% ({int(round(q['hit_rate']*len(q['top_25'])))}/{len(q['top_25'])})</td>
            <td style="font-size:0.85em;color:#666;">{', '.join(p['ticker'] for p in q['top_25'][:10])}...</td>
        </tr>""")

    # Cumulative chart data (rebalance-point NAV)
    port_nav = result["portfolio_nav_at_rebalance"]
    bench_nav = result["benchmark_nav_at_rebalance"]
    # dates align: [start] + each quarter's exec day + [final]
    labels = ["Start"] + [q["execution_day"] for q in quarters] + ["End"]
    labels = labels[:len(port_nav)]  # safety

    chart_port = ",".join(f"{v:.0f}" for v in port_nav)
    chart_bench = ",".join(f"{v:.0f}" for v in bench_nav)
    chart_labels = ",".join(f'"{l}"' for l in labels)

    summary_cards = f"""
    <div class="cards">
        <div class="card">
            <div class="label">Portfolio Total Return</div>
            <div class="value {color_class(s['total_return_pct'])}">{fmt_pct(s['total_return_pct'])}</div>
        </div>
        <div class="card">
            <div class="label">Nifty 50 Total Return</div>
            <div class="value {color_class(s['total_benchmark_return_pct'])}">{fmt_pct(s['total_benchmark_return_pct'])}</div>
        </div>
        <div class="card">
            <div class="label">Spread (Alpha over index)</div>
            <div class="value {color_class(s['spread_pct'])}">{fmt_pct(s['spread_pct'])}</div>
        </div>
        <div class="card">
            <div class="label">Annualized Return</div>
            <div class="value {color_class(s['annual_return_pct'])}">{fmt_pct(s['annual_return_pct'])}</div>
            <div class="sub">vs Nifty {fmt_pct(s['annual_benchmark_return_pct'])}</div>
        </div>
        <div class="card">
            <div class="label">Jensen's Alpha (annual)</div>
            <div class="value {color_class(s['annual_alpha_pct'])}">{fmt_pct(s['annual_alpha_pct'])}</div>
            <div class="sub">Beta: {s['beta']:.3f}</div>
        </div>
        <div class="card">
            <div class="label">Sharpe Ratio</div>
            <div class="value">{s['sharpe_portfolio']:.3f}</div>
            <div class="sub">vs Nifty {s['sharpe_benchmark']:.3f}</div>
        </div>
        <div class="card">
            <div class="label">Overall Hit Rate</div>
            <div class="value">{s['overall_hit_rate']*100:.1f}%</div>
            <div class="sub">avg picks beating Nifty/quarter</div>
        </div>
        <div class="card">
            <div class="label">Tracking Error</div>
            <div class="value">{s['tracking_error_annual_pct']:.2f}%</div>
            <div class="sub">annualized</div>
        </div>
    </div>
    """

    assumptions_html = f"""
    <ul>
        <li><strong>Rebalance cadence:</strong> first trading day of Feb, May, Aug, Nov (16 quarters, 2022-2025)</li>
        <li><strong>Portfolio:</strong> equal-weighted top {a['top_n']} by total score</li>
        <li><strong>Execution:</strong> next trading day's close (proxy for open — see limitations)</li>
        <li><strong>Transaction cost:</strong> {a['transaction_cost_per_side']*100:.2f}% per side (conservative discount-broker estimate)</li>
        <li><strong>Risk-free rate:</strong> {a['risk_free_rate_annual']*100:.1f}% annualized (Indian 10y G-Sec proxy)</li>
        <li><strong>Fundamentals lag:</strong> {a['fundamental_lag_days']} days (only use quarterly filings this old at rebalance time)</li>
        <li><strong>Initial capital:</strong> {fmt_money(a['initial_capital'])} notional</li>
    </ul>
    """

    limitations_html = """
    <div class="limit-item">
        <div class="limit-title">1. Fundamental data restatement (upward bias)</div>
        <p>Yahoo Finance returns <em>current</em> versions of historical financial statements,
        not the as-reported numbers from the time. Companies restate earnings (often favorably)
        with the benefit of hindsight. A truly audit-grade backtest would require paid point-in-time
        data (Bloomberg PIT, FactSet). The practical impact is that the scoring model sees a cleaner
        version of the past than was actually knowable at the time.</p>
        <p><strong>Directional impact:</strong> results may be modestly better than reality. Hard to
        quantify without PIT data, but typical estimates from academic literature put this at
        10-30 bps of annualized return.</p>
    </div>
    <div class="limit-item">
        <div class="limit-title">2. Sample size (4 years, 16 quarters)</div>
        <p>Sixteen observations is a small sample. 2022-2025 is one market regime — rising rates,
        PSU rally, IT drawdown, mid/small-cap frenzy then correction. A model that fit this period
        may not survive another. Treat any statistical significance claim with suspicion.</p>
    </div>
    <div class="limit-item">
        <div class="limit-title">3. Execution price simplification</div>
        <p>The simulator uses next-day close as the execution price because Yahoo Finance's daily
        bars don't cleanly expose open prices for Indian equities in all cases. A proper backtest
        would use next-day open (which was our stated methodology). Impact is typically a few bps
        per rebalance — close vs open drift — and can go either direction. Not biased upward
        systematically.</p>
    </div>
    <div class="limit-item">
        <div class="limit-title">4. Partial EPS coverage</div>
        <p>For stocks with fewer than 4 available quarters at a rebalance date (typical for
        newly-listed names like Zomato, Jio Financial, Max Healthcare in early quarters),
        TTM metrics are annualized from partial data. This is marked in the scoring quality
        flag but affects scores during the first few quarters after a stock enters the index.</p>
    </div>
    <div class="limit-item">
        <div class="limit-title">5. What the backtest does NOT cover</div>
        <ul>
            <li>Dividend reinvestment beyond what yfinance's adjusted-close captures</li>
            <li>Taxes on capital gains (STCG/LTCG would further reduce realized returns by 10-15%)</li>
            <li>Slippage on large orders (negligible for Nifty 50 names at your capital scale)</li>
            <li>Market impact of quarterly rebalancing (again, negligible at your scale)</li>
        </ul>
    </div>
    <div class="limit-item">
        <div class="limit-title">6. Survivorship — handled correctly, but noted</div>
        <p>The backtest uses the <em>actual</em> Nifty 50 constituents at each rebalance date,
        reconstructed from NSE reconstitution announcements. Former constituents (HDFC Ltd, UPL,
        Shree Cement, IOC, BPCL, Britannia, Dr Reddy's, LTIMindtree, Hero MotoCorp, IndusInd Bank,
        Divi's Lab) are included when they were in the index and dropped when they exited.
        This is the correct treatment and avoids the most common amateur backtest error.</p>
    </div>
    """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Nifty 50 Backtest Report — Feb 2022 to Nov 2025</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
    body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 1200px; margin: 2em auto; padding: 0 1em; color: #222; line-height: 1.55; }}
    h1 {{ color: #1a1a2e; border-bottom: 3px solid #e94560; padding-bottom: 0.3em; }}
    h2 {{ color: #1a1a2e; margin-top: 2em; }}
    .meta {{ color: #666; font-size: 0.9em; margin-bottom: 2em; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1em; margin: 2em 0; }}
    .card {{ background: #f8f9fa; padding: 1em 1.2em; border-radius: 8px; border-left: 4px solid #0f3460; }}
    .card .label {{ font-size: 0.8em; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
    .card .value {{ font-size: 1.8em; font-weight: 700; margin: 0.2em 0; }}
    .card .sub {{ font-size: 0.85em; color: #888; }}
    .pos {{ color: #16a34a; }}
    .neg {{ color: #dc2626; }}
    .flat {{ color: #888; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.92em; }}
    th, td {{ padding: 0.6em 0.8em; text-align: left; border-bottom: 1px solid #eee; }}
    th {{ background: #f1f2f6; font-weight: 600; }}
    tr:hover {{ background: #fafbfc; }}
    .chart-wrap {{ background: white; padding: 1em; border: 1px solid #eee; border-radius: 8px; margin: 1em 0; }}
    .limit-item {{ background: #fff9e6; border-left: 4px solid #f59e0b; padding: 1em 1.2em; margin: 1em 0; border-radius: 4px; }}
    .limit-title {{ font-weight: 700; color: #92400e; margin-bottom: 0.4em; }}
    .assumptions {{ background: #eff6ff; padding: 1em 1.4em; border-radius: 6px; }}
    .verdict {{ background: #1a1a2e; color: white; padding: 1.2em 1.4em; border-radius: 8px; margin: 2em 0; }}
    .verdict h3 {{ margin-top: 0; color: #ffd700; }}
    code {{ background: #f1f2f6; padding: 0.1em 0.4em; border-radius: 3px; font-size: 0.9em; }}
</style>
</head>
<body>

<h1>Nifty 50 Backtest: Top-25 Scoring Model</h1>
<div class="meta">
    Period: first trading day of Feb 2022 → end of 2025 &nbsp;|&nbsp;
    {s['num_quarters']} quarterly rebalances &nbsp;|&nbsp;
    Generated {datetime.now().strftime('%B %d, %Y %H:%M')}
</div>

<h2>Headline Results</h2>
{summary_cards}

<h2>Cumulative Performance</h2>
<div class="chart-wrap">
    <canvas id="navChart" height="100"></canvas>
</div>

<h2>Per-Quarter Results</h2>
<table>
<thead>
<tr>
    <th>Rebalance</th><th>Exec Day</th><th>Portfolio</th><th>Nifty 50</th>
    <th>Spread</th><th>Hit Rate</th><th>Top Picks (sample)</th>
</tr>
</thead>
<tbody>
{''.join(quarter_rows)}
</tbody>
</table>

<h2>Assumptions</h2>
<div class="assumptions">
{assumptions_html}
</div>

<h2>Limitations and Caveats</h2>
<p>Read this section in full before making any investment decision based on the numbers above.
A backtest that looks good but has subtle logical flaws is worse than no backtest — it produces
false confidence.</p>
{limitations_html}

<div class="verdict">
<h3>How to interpret these numbers</h3>
<p>This backtest is one data point. A single historical period cannot confirm a scoring model's
predictive power — it can only rule out models that obviously don't work. If the spread is
large and positive <em>and</em> the hit rate is consistently above 50%, that's a necessary but
not sufficient condition for the model to be useful going forward. If the spread is negative
or the hit rate hovers around 50%, that's a strong signal the model may not be differentiating
winners from losers better than chance.</p>
<p>The live prediction locked on April 18, 2026 is the real test. Results due April 2027.</p>
</div>

<script>
const ctx = document.getElementById('navChart');
new Chart(ctx, {{
    type: 'line',
    data: {{
        labels: [{chart_labels}],
        datasets: [
            {{ label: 'Top-25 Portfolio', data: [{chart_port}], borderColor: '#e94560', backgroundColor: 'rgba(233,69,96,0.1)', tension: 0.15, borderWidth: 2.5 }},
            {{ label: 'Nifty 50',          data: [{chart_bench}], borderColor: '#0f3460', backgroundColor: 'rgba(15,52,96,0.1)', tension: 0.15, borderWidth: 2.5 }},
        ]
    }},
    options: {{
        responsive: true,
        plugins: {{ legend: {{ position: 'top' }} }},
        scales: {{
            y: {{
                ticks: {{ callback: v => '₹' + v.toLocaleString('en-IN') }}
            }}
        }}
    }}
}});
</script>

</body>
</html>
"""
    return html


def main():
    with open(RESULTS_DIR / "results.json") as f:
        result = json.load(f)

    html = build_html(result)

    out = RESULTS_DIR / "report.html"
    out.write_text(html, encoding="utf-8")
    print(f"Report written to {out}")

    # Also produce a simple text summary
    s = result["summary"]
    txt = f"""
NIFTY 50 BACKTEST — SUMMARY
===========================
Period: Feb 2022 - end 2025  ({s['num_quarters']} rebalances, {s['years_simulated']:.2f} years)

HEADLINE
  Portfolio total return:   {s['total_return_pct']:+.2f}%
  Nifty 50 total return:    {s['total_benchmark_return_pct']:+.2f}%
  Spread:                   {s['spread_pct']:+.2f}%

  Annualized portfolio:     {s['annual_return_pct']:+.2f}%/yr
  Annualized benchmark:     {s['annual_benchmark_return_pct']:+.2f}%/yr

RISK-ADJUSTED
  Jensen's alpha (annual):  {s['annual_alpha_pct']:+.2f}%/yr
  Beta:                     {s['beta']:.3f}
  Sharpe (portfolio):       {s['sharpe_portfolio']:.3f}
  Sharpe (benchmark):       {s['sharpe_benchmark']:.3f}
  Tracking error (annual):  {s['tracking_error_annual_pct']:.2f}%

HIT RATE
  Avg picks beating Nifty/quarter: {s['overall_hit_rate']*100:.1f}%

Open report.html in your browser for full per-quarter breakdown and limitations.
"""
    (RESULTS_DIR / "summary.txt").write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
