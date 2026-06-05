"""Backtest กลยุทธ์ใดก็ได้บนข้อมูลย้อนหลัง.

Usage:
  python backtest.py                              # default: fresh_breakout, Nasdaq 100, 5y
  STRATEGY=near_52w_high python backtest.py       # เปลี่ยนกลยุทธ์
  UNIVERSE=sp500 python backtest.py               # เปลี่ยน universe (ช้ามาก)
  YEARS=3 python backtest.py                      # ปรับช่วงเวลา

Outputs (เปลี่ยนชื่อตาม strategy):
  - trades_<strategy>.csv  : ทุก trade
  - backtest_<strategy>.html : สรุปสถิติ
"""
import os
from datetime import datetime

import yfinance as yf
import pandas as pd
import numpy as np

from presets import NASDAQ_100, get_sp500, DOW_30

# ═════════ Backtest parameters ═════════
STOP_LOSS_PCT = -7.0       # -7% จาก entry
MAX_HOLD_DAYS = 60         # ถือไม่เกิน 60 trading days
TRADING_COST_PCT = 0.10    # 0.1% per side


def get_universe() -> tuple[str, list[str]]:
    spec = os.environ.get("UNIVERSE", "nasdaq100").strip().lower()
    if spec == "sp500":
        return "S&P 500", get_sp500()
    if spec == "dow30":
        return "Dow 30", DOW_30
    return "Nasdaq 100", NASDAQ_100


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add ทุก indicator ที่ใช้ในทั้ง 2 กลยุทธ์ + simulate_trade."""
    df = df.copy()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["SMA200_lag20"] = df["SMA200"].shift(20)
    df["VolSMA50"] = df["Volume"].rolling(50).mean()
    df["High52"] = df["High"].rolling(252).max()
    df["Low52"] = df["Low"].rolling(252).min()
    # Base = 30 วันก่อนหน้า (ไม่นับวันนี้ — shift 1)
    df["BaseHigh"] = df["High"].shift(1).rolling(30).max()
    df["BaseLow"] = df["Low"].shift(1).rolling(30).min()
    df["BaseRange"] = (df["BaseHigh"] - df["BaseLow"]) / df["BaseLow"] * 100
    return df


def find_signals_fresh_breakout(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Fresh Breakout — 7 เงื่อนไข (Stage 2 + tight base + breakout + fresh + vol)."""
    c = (
        (df["Close"] > df["SMA50"]) & (df["SMA50"] > df["SMA200"]) &
        (df["SMA200"] > df["SMA200_lag20"]) &
        (df["BaseRange"] < 15) &
        (df["Close"] > df["BaseHigh"]) &
        (df["Close"] < df["BaseHigh"] * 1.05) &
        (df["Volume"] > df["VolSMA50"] * 1.5) &
        (df["Close"] > df["Low52"] * 1.30)
    )
    return df.index[c.fillna(False)]


def find_signals_near_52w_high(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Near 52W High — ครบ 3 เงื่อนไข."""
    c = (
        (df["Close"] > df["SMA200"]) &
        (df["Close"] >= df["High52"] * 0.99) &
        (df["Volume"] > df["VolSMA50"])
    )
    return df.index[c.fillna(False)]


SIGNAL_FUNCS = {
    "fresh_breakout": find_signals_fresh_breakout,
    "near_52w_high": find_signals_near_52w_high,
}


def simulate_trade(df: pd.DataFrame, signal_idx: int) -> dict | None:
    """Enter at next day's open, exit at first hit of stop/trailing/max-hold."""
    if signal_idx + 1 >= len(df):
        return None
    entry_idx = signal_idx + 1
    entry_date = df.index[entry_idx]
    entry_price = float(df.iloc[entry_idx]["Open"])
    if not (entry_price > 0):
        return None
    stop_price = entry_price * (1 + STOP_LOSS_PCT / 100)

    for offset in range(1, MAX_HOLD_DAYS + 1):
        bar_idx = entry_idx + offset
        if bar_idx >= len(df):
            # หมดข้อมูล — หา close ล่าสุดที่ไม่ใช่ NaN
            valid = df["Close"].dropna()
            if valid.empty:
                return None
            exit_date = valid.index[-1]
            exit_idx = df.index.get_loc(exit_date)
            exit_price = float(valid.iloc[-1])
            exit_reason = "EOD"
            break

        bar = df.iloc[bar_idx]
        low = float(bar["Low"])
        close = float(bar["Close"])
        sma50 = bar["SMA50"]

        # 1. Stop loss (intraday)
        if low <= stop_price:
            exit_idx = bar_idx
            exit_price = stop_price
            exit_reason = "STOP_LOSS"
            break
        # 2. Trailing: close < SMA50
        if pd.notna(sma50) and close < float(sma50):
            exit_idx = bar_idx
            exit_price = close
            exit_reason = "SMA50_BREAK"
            break
        # 3. Max hold
        if offset == MAX_HOLD_DAYS:
            exit_idx = bar_idx
            exit_price = close
            exit_reason = "MAX_HOLD"
            break
    else:
        return None

    gross = (exit_price / entry_price - 1) * 100
    net = gross - TRADING_COST_PCT * 2
    return {
        "entry_date": entry_date.strftime("%Y-%m-%d"),
        "exit_date": df.index[exit_idx].strftime("%Y-%m-%d"),
        "entry_price": round(entry_price, 2),
        "exit_price": round(exit_price, 2),
        "return_pct": round(net, 2),
        "hold_days": offset,
        "exit_reason": exit_reason,
    }


def backtest_ticker(ticker: str, df: pd.DataFrame, find_signals) -> list[dict]:
    """Run backtest on one ticker. No overlapping positions allowed."""
    if len(df) < 252:
        return []
    df = compute_indicators(df)
    signals = find_signals(df)
    trades = []
    skip_until_idx = -1
    for sig_date in signals:
        sig_idx = df.index.get_loc(sig_date)
        if sig_idx <= skip_until_idx:
            continue  # ยังถือ position เดิม
        trade = simulate_trade(df, sig_idx)
        if trade is None:
            continue
        trade["ticker"] = ticker
        trades.append(trade)
        # บล็อก signal จนกว่า exit
        exit_idx = df.index.get_loc(pd.to_datetime(trade["exit_date"]))
        skip_until_idx = exit_idx
    return trades


def fetch_history(tickers: list[str], years: int) -> dict[str, pd.DataFrame]:
    """Download N years of OHLCV for batch."""
    period = f"{years}y"
    print(f"Downloading {len(tickers)} tickers, period={period}...")
    data = yf.download(
        tickers, period=period, interval="1d", progress=False,
        auto_adjust=False, group_by="ticker", threads=True,
    )
    out = {}
    for t in tickers:
        try:
            df = data[t].dropna(how="all")
            if not df.empty:
                out[t] = df
        except KeyError:
            pass
    print(f"Got data for {len(out)} tickers")
    return out


def compute_metrics(trades_df: pd.DataFrame) -> dict:
    if trades_df.empty:
        return {"n_trades": 0}
    # ทิ้ง trades ที่มี NaN (ถ้ามี) เพื่อไม่ให้ stats เพี้ยน
    trades_df = trades_df.dropna(subset=["return_pct"])
    if trades_df.empty:
        return {"n_trades": 0}
    rets = trades_df["return_pct"].values
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    # Equity curve assuming equal weight + sequential trades
    equity = (1 + trades_df.sort_values("entry_date")["return_pct"] / 100).cumprod()
    peak = equity.cummax()
    drawdown = (equity / peak - 1) * 100
    return {
        "n_trades": len(trades_df),
        "win_rate": round(len(wins) / len(rets) * 100, 1),
        "avg_return_pct": round(rets.mean(), 2),
        "median_return_pct": round(float(np.median(rets)), 2),
        "avg_win_pct": round(wins.mean(), 2) if len(wins) else 0,
        "avg_loss_pct": round(losses.mean(), 2) if len(losses) else 0,
        "best_trade_pct": round(rets.max(), 2),
        "worst_trade_pct": round(rets.min(), 2),
        "avg_hold_days": round(trades_df["hold_days"].mean(), 1),
        "total_return_pct": round((equity.iloc[-1] - 1) * 100, 2),
        "max_drawdown_pct": round(drawdown.min(), 2),
        "profit_factor": round(wins.sum() / abs(losses.sum()), 2) if len(losses) else float("inf"),
    }


def render_html(metrics: dict, trades_df: pd.DataFrame, universe_name: str,
                years: int, equity: pd.Series) -> str:
    # Equity curve as simple inline SVG-free → use base64 chart? เอาเป็นตาราง + key stats ก่อน
    exit_dist = trades_df["exit_reason"].value_counts().to_dict() if not trades_df.empty else {}
    exit_html = "".join(f"<li>{reason}: {n} ({n/len(trades_df)*100:.1f}%)</li>"
                        for reason, n in exit_dist.items())

    # Top 10 winners and losers
    if not trades_df.empty:
        top = trades_df.nlargest(10, "return_pct")[["ticker", "entry_date", "return_pct", "hold_days", "exit_reason"]]
        bot = trades_df.nsmallest(10, "return_pct")[["ticker", "entry_date", "return_pct", "hold_days", "exit_reason"]]
    else:
        top = bot = pd.DataFrame()

    def df_to_html(df_):
        if df_.empty:
            return "<p>(no trades)</p>"
        rows = ""
        for _, r in df_.iterrows():
            color = "#16a34a" if r["return_pct"] > 0 else "#dc2626"
            rows += (f"<tr><td>{r['ticker']}</td><td>{r['entry_date']}</td>"
                     f"<td style='color:{color}'><b>{r['return_pct']:+.2f}%</b></td>"
                     f"<td>{r['hold_days']}d</td><td>{r['exit_reason']}</td></tr>")
        return ("<table cellpadding='6' style='border-collapse:collapse;border:1px solid #ddd'>"
                "<thead style='background:#f3f4f6'><tr><th>Ticker</th><th>Entry</th>"
                "<th>Return</th><th>Hold</th><th>Exit</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>")

    return f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:900px;margin:auto">
<h1>🧪 Fresh Breakout Backtest</h1>
<p><b>Universe:</b> {universe_name} &nbsp;|&nbsp; <b>Period:</b> {years} years &nbsp;|&nbsp; <b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<h2>📊 Performance</h2>
<table cellpadding="8" style="border-collapse:collapse;border:1px solid #ddd">
<tr><td><b>Total trades</b></td><td>{metrics['n_trades']}</td></tr>
<tr><td><b>Win rate</b></td><td>{metrics['win_rate']}%</td></tr>
<tr><td><b>Average return / trade</b></td><td>{metrics['avg_return_pct']:+.2f}%</td></tr>
<tr><td><b>Median return / trade</b></td><td>{metrics['median_return_pct']:+.2f}%</td></tr>
<tr><td><b>Average win</b></td><td style="color:#16a34a">{metrics['avg_win_pct']:+.2f}%</td></tr>
<tr><td><b>Average loss</b></td><td style="color:#dc2626">{metrics['avg_loss_pct']:+.2f}%</td></tr>
<tr><td><b>Best trade</b></td><td style="color:#16a34a">{metrics['best_trade_pct']:+.2f}%</td></tr>
<tr><td><b>Worst trade</b></td><td style="color:#dc2626">{metrics['worst_trade_pct']:+.2f}%</td></tr>
<tr><td><b>Avg hold</b></td><td>{metrics['avg_hold_days']} trading days</td></tr>
<tr><td><b>Profit factor</b></td><td>{metrics['profit_factor']}</td></tr>
<tr style="background:#fef3c7"><td><b>Compounded total return (all trades sequential, equal weight)</b></td><td><b>{metrics['total_return_pct']:+.2f}%</b></td></tr>
<tr style="background:#fee2e2"><td><b>Max drawdown</b></td><td><b>{metrics['max_drawdown_pct']:.2f}%</b></td></tr>
</table>

<h2>🚪 Exit reasons</h2>
<ul>{exit_html}</ul>

<h2>🏆 Top 10 winners</h2>
{df_to_html(top)}

<h2>💀 Top 10 losers</h2>
{df_to_html(bot)}

<hr><p style="color:#888;font-size:12px">
Strategy: Stage 2 + Tight base (30d, range &lt; 15%) + Breakout + Fresh (≤5% from pivot) + Vol 1.5×<br>
Exits: -7% stop / Close &lt; SMA50 / Max 60 days / Cost 0.2% round-trip<br>
⚠️ Survivorship bias: ใช้ {universe_name} ปัจจุบัน — ไม่รวมหุ้นที่ออกจาก index ใน 5 ปีที่ผ่านมา
</p>
</body></html>"""


def run_backtest(strategy_key: str, data: dict, universe_name: str, years: int) -> tuple[pd.DataFrame, dict]:
    """Run a single strategy across all tickers. Returns (trades_df, metrics)."""
    find_signals = SIGNAL_FUNCS[strategy_key]
    all_trades = []
    for i, (ticker, df) in enumerate(data.items(), 1):
        try:
            trades = backtest_ticker(ticker, df, find_signals)
            all_trades.extend(trades)
            if i % 20 == 0:
                print(f"  [{strategy_key}] {i}/{len(data)}  ({len(all_trades)} trades)")
        except Exception as e:
            print(f"  [warn] {ticker}: {e}")

    if not all_trades:
        return pd.DataFrame(), {"n_trades": 0}

    trades_df = pd.DataFrame(all_trades)
    trades_df = trades_df[["ticker", "entry_date", "exit_date", "entry_price",
                            "exit_price", "return_pct", "hold_days", "exit_reason"]]
    trades_df.to_csv(f"trades_{strategy_key}.csv", index=False)

    metrics = compute_metrics(trades_df)
    return trades_df, metrics


def main():
    years = int(os.environ.get("YEARS", "5"))
    strategy_key = os.environ.get("STRATEGY", "fresh_breakout")
    if strategy_key not in SIGNAL_FUNCS:
        print(f"[error] Unknown STRATEGY={strategy_key}. Choices: {list(SIGNAL_FUNCS.keys())}")
        return
    universe_name, universe = get_universe()
    print(f"=== Backtest: {strategy_key}, {universe_name}, {years}y ===\n")

    data = fetch_history(universe, years)
    trades_df, metrics = run_backtest(strategy_key, data, universe_name, years)

    print(f"\nTotal trades: {metrics['n_trades']}")
    if metrics["n_trades"] == 0:
        print("No trades generated.")
        return

    print("\n--- Summary ---")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    eq = (1 + trades_df.sort_values("entry_date")["return_pct"] / 100).cumprod()
    html = render_html(metrics, trades_df, universe_name, years, eq)
    with open(f"backtest_{strategy_key}.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[OK] Wrote trades_{strategy_key}.csv ({len(trades_df)} rows) + backtest_{strategy_key}.html")


if __name__ == "__main__":
    main()
