"""เปรียบเทียบ 2 strategies side-by-side บน universe + period เดียวกัน.

Usage:
  python compare_strategies.py
  UNIVERSE=sp500 YEARS=5 python compare_strategies.py
"""
import os
import pandas as pd
import yfinance as yf

from backtest import (
    SIGNAL_FUNCS, fetch_history, get_universe, run_backtest, compute_metrics
)


def benchmark_buy_hold(symbol: str, years: int) -> dict:
    """Buy-and-hold benchmark (QQQ หรือ SPY)."""
    df = yf.download(symbol, period=f"{years}y", interval="1d",
                      progress=False, auto_adjust=False)
    if hasattr(df.columns, "get_level_values"):
        df.columns = df.columns.get_level_values(0)
    start = float(df["Close"].iloc[0])
    end = float(df["Close"].iloc[-1])
    peak = df["Close"].cummax()
    dd = float(((df["Close"] / peak - 1) * 100).min())
    return {
        "symbol": symbol,
        "total_return_pct": round((end/start - 1) * 100, 2),
        "max_drawdown_pct": round(dd, 2),
    }


def render_comparison(results: dict, benchmark: dict, universe_name: str, years: int) -> str:
    keys = list(results.keys())
    metrics_to_show = [
        ("n_trades", "Total trades", "", lambda v: f"{v}"),
        ("win_rate", "Win rate", "%", lambda v: f"{v}%"),
        ("avg_return_pct", "Avg return / trade", "%", lambda v: f"{v:+.2f}%"),
        ("median_return_pct", "Median return / trade", "%", lambda v: f"{v:+.2f}%"),
        ("avg_win_pct", "Avg win", "%", lambda v: f"{v:+.2f}%"),
        ("avg_loss_pct", "Avg loss", "%", lambda v: f"{v:+.2f}%"),
        ("best_trade_pct", "Best trade", "%", lambda v: f"{v:+.2f}%"),
        ("worst_trade_pct", "Worst trade", "%", lambda v: f"{v:+.2f}%"),
        ("avg_hold_days", "Avg hold (days)", "", lambda v: f"{v}"),
        ("profit_factor", "Profit factor", "", lambda v: f"{v}"),
        ("total_return_pct", "Total return (sequential)", "%", lambda v: f"{v:+.2f}%"),
        ("max_drawdown_pct", "Max drawdown", "%", lambda v: f"{v:.2f}%"),
    ]

    def cell(strategy, key, fmt):
        v = results[strategy].get(key)
        return f"<td>{fmt(v) if v is not None else '—'}</td>"

    rows = ""
    for key, label, _unit, fmt in metrics_to_show:
        # Highlight winner per row
        vals = {s: results[s].get(key) for s in keys}
        if all(v is not None for v in vals.values()) and key not in ("n_trades", "avg_hold_days"):
            # higher = better เกือบทุก metric ยกเว้น max_drawdown_pct, avg_loss_pct, worst_trade_pct
            higher_better = key not in ("max_drawdown_pct", "avg_loss_pct", "worst_trade_pct")
            best_strat = max(vals, key=vals.get) if higher_better else min(vals, key=vals.get)
        else:
            best_strat = None

        row = f"<tr><td><b>{label}</b></td>"
        for s in keys:
            v = vals[s]
            text = fmt(v) if v is not None else "—"
            style = "background:#dcfce7;font-weight:bold" if s == best_strat else ""
            row += f"<td style='{style}'>{text}</td>"
        row += "</tr>"
        rows += row

    headers = "".join(f"<th>{s}</th>" for s in keys)

    # Year-by-year for each strategy
    yearly_html = ""
    for s in keys:
        df = pd.read_csv(f"trades_{s}.csv")
        if df.empty:
            continue
        df["year"] = pd.to_datetime(df["entry_date"]).dt.year
        yearly = df.groupby("year").agg(
            n=("return_pct", "size"),
            win_rate=("return_pct", lambda x: round((x > 0).mean() * 100, 0)),
            avg_ret=("return_pct", lambda x: round(x.mean(), 2)),
        ).reset_index()
        yr_rows = "".join(
            f"<tr><td>{r['year']}</td><td>{r['n']}</td><td>{r['win_rate']}%</td>"
            f"<td style='color:{'#16a34a' if r['avg_ret']>0 else '#dc2626'}'>{r['avg_ret']:+.2f}%</td></tr>"
            for _, r in yearly.iterrows()
        )
        yearly_html += f"""
        <h3>{s}</h3>
        <table cellpadding="6" style="border-collapse:collapse;border:1px solid #ddd">
          <thead style="background:#f3f4f6"><tr><th>Year</th><th>Trades</th><th>Win%</th><th>Avg/trade</th></tr></thead>
          <tbody>{yr_rows}</tbody>
        </table>
        """

    return f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:1000px;margin:auto">
<h1>🧪 Strategy Comparison</h1>
<p><b>Universe:</b> {universe_name} &nbsp;|&nbsp; <b>Period:</b> {years} years</p>

<h2>📊 Side-by-side</h2>
<table cellpadding="10" style="border-collapse:collapse;border:1px solid #ddd">
<thead style="background:#1f2937;color:white"><tr><th>Metric</th>{headers}</tr></thead>
<tbody>{rows}</tbody>
</table>
<p style="color:#666;font-size:13px">🟩 = ดีกว่าในแถวนั้น</p>

<h2>🎯 Benchmark: {benchmark['symbol']} buy-and-hold</h2>
<table cellpadding="8" style="border-collapse:collapse;border:1px solid #ddd">
<tr><td><b>Total return</b></td><td>{benchmark['total_return_pct']:+.2f}%</td></tr>
<tr><td><b>Max drawdown</b></td><td>{benchmark['max_drawdown_pct']:.2f}%</td></tr>
</table>

<h2>📅 Performance by year</h2>
{yearly_html}

<hr><p style="color:#888;font-size:12px">
Same exit rules for both strategies: -7% stop / Close &lt; SMA50 / Max 60 days / Cost 0.2% round-trip<br>
⚠️ Survivorship bias: universe ปัจจุบัน — ไม่รวมหุ้นที่ออกจาก index
</p>
</body></html>"""


def main():
    years = int(os.environ.get("YEARS", "5"))
    universe_name, universe = get_universe()
    benchmark_symbol = "QQQ" if "Nasdaq" in universe_name else "SPY"

    print(f"=== Comparing strategies — {universe_name}, {years}y ===\n")

    # ดาวน์โหลดข้อมูล**ครั้งเดียว** ใช้ร่วมกันทั้ง 2 strategies
    data = fetch_history(universe, years)

    results = {}
    for strategy_key in SIGNAL_FUNCS:
        print(f"\n--- Running {strategy_key} ---")
        _, metrics = run_backtest(strategy_key, data, universe_name, years)
        results[strategy_key] = metrics

    print(f"\n--- Benchmark {benchmark_symbol} buy-and-hold ---")
    benchmark = benchmark_buy_hold(benchmark_symbol, years)
    print(f"  {benchmark_symbol}: {benchmark['total_return_pct']:+.2f}% return, {benchmark['max_drawdown_pct']:.2f}% drawdown")

    # === Print comparison ===
    print("\n" + "=" * 70)
    print(f"{'Metric':<28} " + " ".join(f"{s:>18}" for s in results))
    print("-" * 70)
    common_keys = ["n_trades", "win_rate", "avg_return_pct", "avg_win_pct",
                   "avg_loss_pct", "profit_factor", "total_return_pct",
                   "max_drawdown_pct"]
    for key in common_keys:
        row = f"{key:<28} "
        for s in results:
            v = results[s].get(key)
            row += f"{str(v):>18} "
        print(row)
    print("=" * 70)
    print(f"{benchmark_symbol} buy-and-hold: {benchmark['total_return_pct']:+.2f}%   DD: {benchmark['max_drawdown_pct']:.2f}%")

    # === Generate HTML ===
    html = render_comparison(results, benchmark, universe_name, years)
    with open("compare.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("\n[OK] Wrote compare.html (เปิดด้วย browser)")


if __name__ == "__main__":
    main()
