"""Daily auto-scan + email alert.

Env vars (required for email):
  EMAIL_USER       Gmail address (ผู้ส่ง)
  EMAIL_PASSWORD   Gmail App Password 16 ตัว
  EMAIL_TO         อีเมลผู้รับ
Optional:
  UNIVERSE         "sp500" (default) | "nasdaq100" | "dow30" | "ticker1,ticker2,..."
  STRATEGY         "fresh_breakout" (default) | "near_52w_high"
                   | "minervini_tt" | "canslim" | "all" (รันทุก strategy แล้วรวมอีเมล)
"""
import os
import smtplib
import sys
import time
from datetime import datetime
from email.message import EmailMessage

import yfinance as yf
import pandas as pd

from presets import get_sp500, NASDAQ_100, DOW_30
from strategies import (STRATEGIES, compute_rs_rating, is_market_in_uptrend)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Data fetch
# ──────────────────────────────────────────────────────────────────────────────
def fetch_many(tickers: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    if not tickers:
        return {}
    data = yf.download(
        list(tickers), period="2y", interval="1d",
        progress=False, auto_adjust=False, group_by="ticker", threads=True,
    )
    out: dict[str, pd.DataFrame] = {}
    if len(tickers) == 1:
        t = tickers[0]
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        out[t] = data
    else:
        for t in tickers:
            try:
                df = data[t].dropna(how="all")
                if not df.empty:
                    out[t] = df
            except KeyError:
                pass
    return out


def fetch_fundamentals(tickers: list[str], max_tickers: int = 300) -> dict[str, dict]:
    """ดึง fundamental data จาก yfinance.info (ช้า) — เรียกเฉพาะ ticker ที่ผ่าน tech filter
    คืน dict: {ticker: {earnings_quarterly_growth, earnings_growth, revenue_growth}}"""
    if not tickers:
        return {}
    if len(tickers) > max_tickers:
        print(f"  (limiting fundamentals to first {max_tickers} tickers)")
        tickers = tickers[:max_tickers]

    out = {}
    for i, t in enumerate(tickers, 1):
        try:
            info = yf.Ticker(t).info
            out[t] = {
                "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "revenue_growth": info.get("revenueGrowth"),
                "return_on_equity": info.get("returnOnEquity"),
                "market_cap": info.get("marketCap"),
            }
            if i % 20 == 0:
                print(f"  fundamentals: {i}/{len(tickers)}")
        except Exception as e:
            out[t] = {}
        # rate-limit เล็กน้อย กัน yfinance ban
        time.sleep(0.05)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Context builder — สร้าง shared context สำหรับทุก strategy
# ──────────────────────────────────────────────────────────────────────────────
def build_context(data: dict[str, pd.DataFrame],
                  needs_fundamentals_tickers: list[str] = None) -> dict:
    """คำนวณ:
      - SPY 252d return + market regime
      - RS Rating ของทุก ticker (percentile rank ของ 252d return)
      - Fundamentals (ถ้าต้องการ)"""
    ctx = {
        "spy_df": None, "spy_return_252": 0.0,
        "market_uptrend": True, "regime_info": {},
        "rs_ratings": {}, "fundamentals": {},
    }

    # ─── SPY for market regime + relative strength baseline ───
    spy = data.get("SPY")
    if spy is None or len(spy) < 253:
        print("  ⚠️  SPY data missing — ดึงแยก")
        spy_only = fetch_many(("SPY",))
        spy = spy_only.get("SPY")

    if spy is not None and len(spy) >= 253:
        ctx["spy_df"] = spy
        spy_close = spy["Close"]
        ctx["spy_return_252"] = (float(spy_close.iloc[-1]) /
                                 float(spy_close.iloc[-253]) - 1) * 100
        is_up, info = is_market_in_uptrend(spy)
        ctx["market_uptrend"] = is_up
        ctx["regime_info"] = info

    # ─── RS Ratings (percentile rank ของ 12-month return) ───
    returns_252 = {}
    for t, df in data.items():
        if df is None or len(df) < 253:
            continue
        try:
            ret = (float(df["Close"].iloc[-1]) /
                   float(df["Close"].iloc[-253]) - 1) * 100
            returns_252[t] = ret
        except Exception:
            continue

    all_returns = list(returns_252.values())
    for t, ret in returns_252.items():
        ctx["rs_ratings"][t] = compute_rs_rating(ret, all_returns)

    # ─── Fundamentals (สำหรับ CAN SLIM) ───
    if needs_fundamentals_tickers:
        print(f"\nFetching fundamentals for {len(needs_fundamentals_tickers)} tickers...")
        ctx["fundamentals"] = fetch_fundamentals(needs_fundamentals_tickers)

    return ctx


# ──────────────────────────────────────────────────────────────────────────────
# Universe + strategy selection
# ──────────────────────────────────────────────────────────────────────────────
def get_universe() -> tuple[str, list[str]]:
    spec = os.environ.get("UNIVERSE", "sp500").strip()
    if spec.lower() == "sp500":
        return "S&P 500", get_sp500()
    if spec.lower() == "nasdaq100":
        return "Nasdaq 100", NASDAQ_100
    if spec.lower() == "dow30":
        return "Dow 30", DOW_30
    if "," in spec:
        return "Custom", [t.strip().upper() for t in spec.split(",") if t.strip()]
    return "S&P 500", get_sp500()


def get_strategy_keys() -> list[str]:
    spec = os.environ.get("STRATEGY", "fresh_breakout").lower()
    if spec == "all":
        return list(STRATEGIES.keys())
    keys = [k.strip() for k in spec.split(",") if k.strip()]
    valid = [k for k in keys if k in STRATEGIES]
    if not valid:
        print(f"[warn] Unknown STRATEGY={spec}, falling back to fresh_breakout")
        return ["fresh_breakout"]
    return valid


# ──────────────────────────────────────────────────────────────────────────────
# Run single strategy
# ──────────────────────────────────────────────────────────────────────────────
def run_strategy(strategy_key: str, universe: list[str],
                 data: dict[str, pd.DataFrame], ctx: dict) -> dict:
    """รัน strategy หนึ่งตัว — คืน {buys, hold, sell, nodata}"""
    strategy = STRATEGIES[strategy_key]
    analyze = strategy["analyze"]

    buys, hold, sell, nodata = [], 0, 0, 0
    for t in universe:
        df = data.get(t)
        if df is None or df.empty:
            nodata += 1
            continue
        r = analyze(df, ticker=t, ctx=ctx)
        if r is None:
            nodata += 1
            continue
        if r["signal"] == "BUY":
            buys.append({"ticker": t, **r})
        elif r["signal"] == "HOLD/WAIT":
            hold += 1
        else:
            sell += 1

    # sort
    if strategy_key == "fresh_breakout":
        buys.sort(key=lambda b: b["metrics"]["pct_from_pivot"])
    elif strategy_key == "near_52w_high":
        buys.sort(key=lambda b: b["metrics"]["pct_from_high52"], reverse=True)
    elif strategy_key == "minervini_tt":
        buys.sort(key=lambda b: (-b["metrics"]["rs_rating"], b["metrics"]["pct_from_52wh"]))
    elif strategy_key == "canslim":
        buys.sort(key=lambda b: (-b["metrics"]["passed"],
                                 -b["metrics"]["rs_rating"]))
    elif strategy_key == "weekly_breakout":
        # ใหม่สุดอยู่บน (1 สัปดาห์ก่อน = สดที่สุด) → เบรกเมื่อ 3 สัปดาห์อยู่ล่าง
        buys.sort(key=lambda b: (b["metrics"]["weeks_since_breakout"],
                                 -b["metrics"]["vol_ratio"]))

    return {"buys": buys, "hold": hold, "sell": sell, "nodata": nodata,
            "strategy": strategy, "key": strategy_key}


# ──────────────────────────────────────────────────────────────────────────────
# HTML render
# ──────────────────────────────────────────────────────────────────────────────
def render_strategy_section(result: dict) -> str:
    strategy = result["strategy"]
    buys = result["buys"]
    headers = strategy["headers"]
    head_html = "".join(f'<th style="border:1px solid #ddd;padding:8px;background:#16a34a;color:white">{h}</th>'
                        for h in headers)

    if buys:
        rows = "".join(strategy["html_row"](b["ticker"], b["metrics"]) for b in buys)
        table = f"""
        <table cellpadding="0" cellspacing="0"
               style="border-collapse:collapse;font-family:sans-serif;border:1px solid #ddd;margin-top:10px;width:100%">
          <thead><tr>{head_html}</tr></thead>
          <tbody style="background:white">{rows}</tbody>
        </table>"""
    else:
        table = "<p style='color:#666'>ไม่พบหุ้นที่เข้าเงื่อนไข BUY ครบทุกข้อวันนี้</p>"

    return f"""
    <div style="margin-top:30px">
      <h3 style="color:#1f2937;border-bottom:2px solid #16a34a;padding-bottom:6px">
        {strategy['thai_label']}
      </h3>
      <p style="color:#666;font-size:13px;margin:4px 0"><i>{strategy['description']}</i></p>
      <p style="font-size:14px">
        🟢 BUY: <b style="color:#16a34a">{len(buys)}</b> &nbsp;|&nbsp;
        🟡 HOLD: {result['hold']} &nbsp;|&nbsp;
        🔴 SELL/WAIT: {result['sell']} &nbsp;|&nbsp;
        ⚪ NO DATA: {result['nodata']}
      </p>
      {table}
    </div>"""


def render_html(results: list[dict], universe_name: str, ctx: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_buys = sum(len(r["buys"]) for r in results)

    regime_info = ctx.get("regime_info", {})
    regime_html = ""
    if regime_info and "conditions" in regime_info:
        c = regime_info["conditions"]
        icon = "🟢" if ctx.get("market_uptrend") else "🔴"
        status = "UPTREND ✓" if ctx.get("market_uptrend") else "DOWNTREND/SIDEWAYS ✗"
        rows = "".join(
            f"<li>{'✅' if v else '❌'} {k}</li>"
            for k, v in c.items()
        )
        regime_html = f"""
        <div style="background:#f0f9ff;padding:12px;border-left:4px solid #0284c7;margin:10px 0;border-radius:4px">
          <b>{icon} Market Regime: {status}</b><br>
          <small>SPY ${regime_info.get('spy_close',0):.2f} ·
                 SMA50 ${regime_info.get('spy_sma50',0):.2f} ·
                 SMA200 ${regime_info.get('spy_sma200',0):.2f}</small>
          <ul style="margin:6px 0 0 0;padding-left:20px;font-size:13px">{rows}</ul>
        </div>"""

    sections = "".join(render_strategy_section(r) for r in results)

    return f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:1000px;margin:0 auto;padding:20px">
  <h2 style="color:#1f2937;margin-bottom:8px">🎯 Daily Stock Scanner — {now}</h2>
  <p style="color:#666"><b>Universe:</b> {universe_name} &nbsp;|&nbsp;
     <b>Total BUY signals:</b> <span style="color:#16a34a;font-weight:bold;font-size:18px">{total_buys}</span></p>
  {regime_html}
  {sections}
  <hr style="margin-top:30px;border:none;border-top:1px solid #ddd">
  <p style="color:#888;font-size:12px;margin-top:10px">
    Auto-generated by Daily Stock Scanner<br>
    📚 Strategies: Minervini SEPA · O'Neil CAN SLIM · Stage 2 Breakout<br>
    ⚠️ ไม่ใช่คำแนะนำการลงทุน — ใช้ดุลพินิจตัดสินใจเอง
  </p>
</body></html>"""


# ──────────────────────────────────────────────────────────────────────────────
# Email
# ──────────────────────────────────────────────────────────────────────────────
def send_email(html: str, subject: str):
    user = os.environ["EMAIL_USER"]
    password = os.environ["EMAIL_PASSWORD"]
    to = os.environ["EMAIL_TO"]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content("View this email in HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    strategy_keys = get_strategy_keys()
    universe_name, universe = get_universe()

    print(f"Strategies: {strategy_keys}")
    print(f"Universe: {universe_name} ({len(universe)} tickers)")

    # ensure SPY in download (สำหรับ regime + RS baseline)
    download_set = list(set(universe) | {"SPY"})
    print(f"\nDownloading price data for {len(download_set)} tickers...")
    data = fetch_many(tuple(download_set))
    print(f"Got data for {len(data)} tickers")

    # ─── Pre-scan technical strategies เพื่อหา tickers ที่ผ่าน → ส่งไป fetch fundamentals ───
    needs_fundamentals = any(STRATEGIES[k]["needs_fundamentals"] for k in strategy_keys)
    pre_pass_tickers: list[str] = []
    if needs_fundamentals:
        # quick pre-scan: หุ้นที่ Close > SMA200 + ภายใน 25% ของ 52w high
        print("\nPre-scanning for fundamental candidates...")
        for t in universe:
            df = data.get(t)
            if df is None or len(df) < 253:
                continue
            try:
                close = df["Close"]
                sma200 = float(close.rolling(200).mean().iloc[-1])
                h52 = float(df["High"].iloc[-252:].max())
                c = float(close.iloc[-1])
                if c > sma200 and c >= h52 * 0.75:
                    pre_pass_tickers.append(t)
            except Exception:
                continue
        print(f"  → {len(pre_pass_tickers)} tickers ผ่าน pre-screen ส่งไปดึง fundamentals")

    # ─── Build shared context ───
    print("\nBuilding context (regime, RS ratings, fundamentals)...")
    ctx = build_context(data, pre_pass_tickers if needs_fundamentals else None)
    print(f"  Market regime: {'UPTREND' if ctx['market_uptrend'] else 'DOWNTREND/SIDEWAYS'}")
    print(f"  RS ratings computed: {len(ctx['rs_ratings'])} tickers")
    if ctx["fundamentals"]:
        print(f"  Fundamentals: {len(ctx['fundamentals'])} tickers")

    # ─── Run each strategy ───
    results = []
    for key in strategy_keys:
        print(f"\n→ Running strategy: {key}")
        r = run_strategy(key, universe, data, ctx)
        print(f"  BUY={len(r['buys'])}  HOLD={r['hold']}  SELL={r['sell']}  ND={r['nodata']}")
        if r["buys"]:
            print(f"  BUY tickers: {', '.join(b['ticker'] for b in r['buys'])}")
        results.append(r)

    # ─── Email / dry-run ───
    html = render_html(results, universe_name, ctx)
    total_buys = sum(len(r["buys"]) for r in results)
    if total_buys > 0:
        labels = "+".join(k for k in strategy_keys)
        subject = f"🎯 [{labels}] {total_buys} BUY signal(s) — {datetime.now():%Y-%m-%d}"
    else:
        subject = f"📊 No BUY signals today — {datetime.now():%Y-%m-%d}"

    if all(os.environ.get(k) for k in ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_TO")):
        send_email(html, subject)
        print(f"\n[OK] Sent email to {os.environ['EMAIL_TO']}")
    else:
        with open("last_scan.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("\n[DRY RUN] EMAIL env vars not set — HTML saved to last_scan.html")


if __name__ == "__main__":
    main()
