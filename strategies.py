"""Trading strategies. แต่ละ strategy คืน:
    {"signal": "BUY" | "HOLD/WAIT" | "SELL/WAIT", "metrics": {...}}
หรือ None ถ้าข้อมูลไม่พอ

Strategies:
- near_52w_high     : ใกล้ 52W High + Vol สูง (continuation)
- fresh_breakout    : Stage 2 + เพิ่งทะลุฐาน (early trend entry)
- minervini_tt      : Mark Minervini Trend Template — 8 ข้อ
- canslim           : William O'Neil CAN SLIM (technical + EPS)
- weekly_breakout   : Weekly TF — เพิ่งเบรก 52W high ไม่เกิน 3 สัปดาห์
"""
import pandas as pd


# ═══════════════════ Helpers (used by Minervini + CAN SLIM) ═══════════════════
def compute_rs_rating(ticker_return_12m: float,
                      all_returns_12m: list[float]) -> int:
    """IBD-style Relative Strength Rating 1-99 (percentile rank ของผลตอบแทน 12 เดือน)
    99 = top 1% performer"""
    if not all_returns_12m:
        return 50
    rank = sum(1 for r in all_returns_12m if r < ticker_return_12m)
    pct = rank / len(all_returns_12m)
    return max(1, min(99, int(pct * 99) + 1))


def is_market_in_uptrend(spy_df: pd.DataFrame) -> tuple[bool, dict]:
    """ตรวจ Market Regime — สำหรับ "M" ใน CAN SLIM
    Uptrend = SPY > SMA50 + SMA50 > SMA200 + SMA200 ชี้ขึ้น"""
    if spy_df is None or spy_df.empty or len(spy_df) < 220:
        return False, {"reason": "ไม่มีข้อมูล SPY"}
    sma50 = spy_df["Close"].rolling(50).mean()
    sma200 = spy_df["Close"].rolling(200).mean()
    c = float(spy_df["Close"].iloc[-1])
    s50 = float(sma50.iloc[-1])
    s200 = float(sma200.iloc[-1])
    s200_20d = float(sma200.iloc[-21])

    cond = {
        "SPY > SMA50": c > s50,
        "SMA50 > SMA200": s50 > s200,
        "SMA200 rising (20d)": s200 > s200_20d,
    }
    return all(cond.values()), {
        "spy_close": c, "spy_sma50": s50, "spy_sma200": s200,
        "conditions": cond,
    }


# ═══════════════════ Strategy 1: Near 52W High ═══════════════════
def analyze_near_52w_high(df: pd.DataFrame, ticker: str = None,
                          ctx: dict = None) -> dict | None:
    if df is None or df.empty or len(df) < 200:
        return None
    df = df.copy()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["High52"] = df["High"].rolling(252).max()
    df["VolSMA50"] = df["Volume"].rolling(50).mean()

    last = df.iloc[-1]
    close = float(last["Close"])
    sma200 = float(last["SMA200"]) if pd.notna(last["SMA200"]) else None
    high52 = float(last["High52"]) if pd.notna(last["High52"]) else None
    vol = float(last["Volume"])
    vol_avg = float(last["VolSMA50"]) if pd.notna(last["VolSMA50"]) else None

    above_sma200 = sma200 is not None and close > sma200
    near_high = high52 is not None and close >= high52 * 0.99
    vol_high = vol_avg is not None and vol > vol_avg

    if above_sma200 and near_high and vol_high:
        signal = "BUY"
    elif sma200 is not None and close < sma200:
        signal = "SELL/WAIT"
    else:
        signal = "HOLD/WAIT"

    return {
        "signal": signal,
        "metrics": {
            "close": close, "sma200": sma200, "high52": high52,
            "vol": vol, "vol_avg": vol_avg,
            "pct_from_high52": (close/high52 - 1) * 100 if high52 else None,
            "pct_above_sma200": (close/sma200 - 1) * 100 if sma200 else None,
            "vol_ratio": vol/vol_avg if vol_avg else None,
        },
        "conditions": {
            "Close > SMA200": above_sma200,
            "Close ≥ 99% of 52W High": near_high,
            "Volume > VolSMA50": vol_high,
        },
    }


def _near_52w_high_html_row(ticker: str, m: dict) -> str:
    return (
        f"<tr><td><b>{ticker}</b></td>"
        f"<td>${m['close']:.2f}</td>"
        f"<td>{m['pct_from_high52']:+.2f}%</td>"
        f"<td>{m['pct_above_sma200']:+.1f}%</td>"
        f"<td>{m['vol_ratio']:.2f}×</td></tr>"
    )


# ═══════════════════ Strategy 2: Fresh Breakout from Base ═══════════════════
def analyze_fresh_breakout(df: pd.DataFrame, ticker: str = None,
                           ctx: dict = None) -> dict | None:
    if df is None or df.empty or len(df) < 252:
        return None
    df = df.copy()
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]

    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    vol_avg = vol.rolling(50).mean()

    c = float(close.iloc[-1])
    s50 = float(sma50.iloc[-1]) if pd.notna(sma50.iloc[-1]) else None
    s200_now = float(sma200.iloc[-1]) if pd.notna(sma200.iloc[-1]) else None
    s200_20d = float(sma200.iloc[-21]) if pd.notna(sma200.iloc[-21]) else None
    v = float(vol.iloc[-1])
    v_avg = float(vol_avg.iloc[-1]) if pd.notna(vol_avg.iloc[-1]) else None

    if None in (s50, s200_now, s200_20d, v_avg):
        return None

    base = df.iloc[-31:-1]
    base_high = float(base["High"].max())
    base_low = float(base["Low"].min())
    base_range_pct = (base_high - base_low) / base_low * 100

    yr = df.iloc[-252:]
    h52 = float(yr["High"].max())
    l52 = float(yr["Low"].min())

    cond = {
        "Uptrend (C > SMA50 > SMA200)": c > s50 > s200_now,
        "SMA200 rising (20d)": s200_now > s200_20d,
        "Tight base (range < 15%)": base_range_pct < 15,
        "Breakout (Close > base high)": c > base_high,
        "Fresh (≤ 5% above pivot)": c < base_high * 1.05,
        "Volume surge (> 1.5× avg)": v > v_avg * 1.5,
        "Above 30% of 52W Low": c > l52 * 1.30,
    }

    if all(cond.values()):
        signal = "BUY"
    elif cond["Uptrend (C > SMA50 > SMA200)"] and cond["SMA200 rising (20d)"]:
        signal = "HOLD/WAIT"
    else:
        signal = "SELL/WAIT"

    return {
        "signal": signal,
        "metrics": {
            "close": c, "pivot": base_high, "base_low": base_low,
            "base_range_pct": base_range_pct,
            "sma50": s50, "sma200": s200_now,
            "pct_from_pivot": (c/base_high - 1) * 100,
            "pct_from_52wh": (c/h52 - 1) * 100,
            "above_52wl_pct": (c/l52 - 1) * 100,
            "vol": v, "vol_avg": v_avg, "vol_ratio": v / v_avg,
        },
        "conditions": cond,
    }


def _fresh_breakout_html_row(ticker: str, m: dict) -> str:
    return (
        f"<tr><td><b>{ticker}</b></td>"
        f"<td>${m['close']:.2f}</td>"
        f"<td>${m['pivot']:.2f}</td>"
        f"<td>{m['pct_from_pivot']:+.2f}%</td>"
        f"<td>{m['base_range_pct']:.1f}%</td>"
        f"<td>{m['vol_ratio']:.2f}×</td></tr>"
    )


# ═══════════════════ Strategy 3: Minervini Trend Template (8 ข้อ) ═══════════════════
def analyze_minervini_tt(df: pd.DataFrame, ticker: str = None,
                         ctx: dict = None) -> dict | None:
    """Mark Minervini Trend Template — 8 ข้อ จากหนังสือ Trade Like a Stock Market Wizard"""
    if df is None or df.empty or len(df) < 252:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    sma50 = close.rolling(50).mean()
    sma150 = close.rolling(150).mean()
    sma200 = close.rolling(200).mean()

    c = float(close.iloc[-1])
    s50 = float(sma50.iloc[-1]) if pd.notna(sma50.iloc[-1]) else None
    s150 = float(sma150.iloc[-1]) if pd.notna(sma150.iloc[-1]) else None
    s200_now = float(sma200.iloc[-1]) if pd.notna(sma200.iloc[-1]) else None
    s200_20d = float(sma200.iloc[-21]) if pd.notna(sma200.iloc[-21]) else None
    s200_100d = float(sma200.iloc[-101]) if pd.notna(sma200.iloc[-101]) else None

    if None in (s50, s150, s200_now, s200_20d, s200_100d):
        return None

    yr = df.iloc[-252:]
    h52 = float(yr["High"].max())
    l52 = float(yr["Low"].min())

    # RS Rating — ดึงจาก ctx ถ้ามี ถ้าไม่มีคำนวณเองจาก return 252d เทียบ SPY
    rs_rating = None
    if ctx and ticker and "rs_ratings" in ctx:
        rs_rating = ctx["rs_ratings"].get(ticker)

    if rs_rating is None and ctx and "spy_return_252" in ctx:
        # fallback: คำนวณ relative strength แบบง่ายเทียบ SPY
        try:
            ret_252 = (c / float(close.iloc[-253]) - 1) * 100
            spy_ret = ctx["spy_return_252"]
            # ถ้าหุ้นชนะ SPY → rating > 50
            diff = ret_252 - spy_ret
            rs_rating = max(1, min(99, int(50 + diff)))  # ใกล้เคียง
        except Exception:
            rs_rating = 50

    if rs_rating is None:
        rs_rating = 50

    # ═══ Minervini 8 conditions ═══
    cond = {
        "1. Close > SMA150 & SMA200": c > s150 and c > s200_now,
        "2. SMA150 > SMA200": s150 > s200_now,
        "3. SMA200 rising (≥1 month)": s200_now > s200_20d,
        "4. SMA50 > SMA150 > SMA200": s50 > s150 > s200_now,
        "5. Close > SMA50": c > s50,
        "6. Close ≥ +30% from 52W Low": c >= l52 * 1.30,
        "7. Close within 25% of 52W High": c >= h52 * 0.75,
        "8. RS Rating ≥ 70": rs_rating >= 70,
    }

    passed = sum(cond.values())

    if passed == 8:
        signal = "BUY"
    elif passed >= 6:
        signal = "HOLD/WAIT"
    else:
        signal = "SELL/WAIT"

    # bonus metric: SMA200 ชี้ขึ้นต่อเนื่อง 5 เดือน (Minervini ชอบ)
    sma200_5mo_up = s200_now > s200_100d

    return {
        "signal": signal,
        "metrics": {
            "close": c, "sma50": s50, "sma150": s150, "sma200": s200_now,
            "high52": h52, "low52": l52,
            "pct_from_52wh": (c/h52 - 1) * 100,
            "pct_above_52wl": (c/l52 - 1) * 100,
            "rs_rating": rs_rating,
            "passed": passed,
            "sma200_5mo_up": sma200_5mo_up,
        },
        "conditions": cond,
    }


def _minervini_tt_html_row(ticker: str, m: dict) -> str:
    rs = m["rs_rating"]
    rs_color = "#16a34a" if rs >= 80 else ("#f59e0b" if rs >= 70 else "#ef4444")
    return (
        f"<tr><td><b>{ticker}</b></td>"
        f"<td>${m['close']:.2f}</td>"
        f"<td>{m['pct_from_52wh']:+.1f}%</td>"
        f"<td>+{m['pct_above_52wl']:.0f}%</td>"
        f"<td style='color:{rs_color};font-weight:bold'>{rs}</td>"
        f"<td>{m['passed']}/8</td></tr>"
    )


# ═══════════════════ Strategy 4: CAN SLIM (William O'Neil) ═══════════════════
def analyze_canslim(df: pd.DataFrame, ticker: str = None,
                    ctx: dict = None) -> dict | None:
    """O'Neil CAN SLIM — Technical + Fundamental (EPS/Revenue)
    ต้องการ ctx ที่มี fundamentals + market_regime + rs_ratings"""
    if df is None or df.empty or len(df) < 252:
        return None

    close = df["Close"]
    vol = df["Volume"]

    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    vol_avg = vol.rolling(50).mean()

    c = float(close.iloc[-1])
    s50 = float(sma50.iloc[-1]) if pd.notna(sma50.iloc[-1]) else None
    s200 = float(sma200.iloc[-1]) if pd.notna(sma200.iloc[-1]) else None
    v = float(vol.iloc[-1])
    v_avg = float(vol_avg.iloc[-1]) if pd.notna(vol_avg.iloc[-1]) else None

    if None in (s50, s200, v_avg):
        return None

    yr = df.iloc[-252:]
    h52 = float(yr["High"].max())
    l52 = float(yr["Low"].min())

    # ─── ดึง fundamentals จาก ctx ───
    fundamentals = (ctx or {}).get("fundamentals", {}).get(ticker, {}) if ctx else {}
    eps_growth_qoq = fundamentals.get("earnings_quarterly_growth")  # YoY quarterly
    revenue_growth = fundamentals.get("revenue_growth")
    eps_annual = fundamentals.get("earnings_growth")  # YoY annual

    # ─── RS Rating ───
    rs_rating = (ctx or {}).get("rs_ratings", {}).get(ticker, 50) if ctx else 50

    # ─── Market Regime ("M") ───
    market_uptrend = (ctx or {}).get("market_uptrend", True) if ctx else True

    # ═══ CAN SLIM conditions ═══
    # C: Current quarterly EPS ≥ 25%
    c_pass = eps_growth_qoq is not None and eps_growth_qoq >= 0.25
    # A: Annual EPS growth ≥ 25%
    a_pass = eps_annual is not None and eps_annual >= 0.25
    # N: New high (within 5% of 52w high)
    n_pass = c >= h52 * 0.95
    # S: Supply & Demand proxy = volume breakout
    s_pass = v > v_avg * 1.5
    # L: Leader = RS rating ≥ 80
    l_pass = rs_rating >= 80
    # I: Institutional sponsorship — ใช้ revenue growth + EPS QoQ เป็น proxy
    i_pass = (revenue_growth is not None and revenue_growth >= 0.15) or c_pass
    # M: Market in uptrend
    m_pass = market_uptrend

    # นับคะแนน
    cond = {
        "C: EPS QoQ ≥ 25%": c_pass,
        "A: EPS Annual ≥ 25%": a_pass,
        "N: ≤5% of 52W High": n_pass,
        "S: Volume surge > 1.5×": s_pass,
        "L: RS Rating ≥ 80": l_pass,
        "I: Revenue growth proxy": i_pass,
        "M: Market in uptrend": m_pass,
    }

    passed = sum(cond.values())
    fundamentals_available = eps_growth_qoq is not None or eps_annual is not None

    # ต้องผ่าน M (market regime) เสมอ — กฎหลักของ O'Neil
    if not m_pass:
        signal = "SELL/WAIT"
    elif passed >= 6 and fundamentals_available:
        signal = "BUY"
    elif passed >= 4:
        signal = "HOLD/WAIT"
    else:
        signal = "SELL/WAIT"

    return {
        "signal": signal,
        "metrics": {
            "close": c, "sma50": s50, "sma200": s200,
            "high52": h52, "pct_from_52wh": (c/h52 - 1) * 100,
            "rs_rating": rs_rating,
            "vol_ratio": v / v_avg,
            "eps_qoq": (eps_growth_qoq * 100) if eps_growth_qoq is not None else None,
            "eps_annual": (eps_annual * 100) if eps_annual is not None else None,
            "rev_growth": (revenue_growth * 100) if revenue_growth is not None else None,
            "passed": passed,
            "market_uptrend": m_pass,
            "fundamentals_available": fundamentals_available,
        },
        "conditions": cond,
    }


def _canslim_html_row(ticker: str, m: dict) -> str:
    rs = m["rs_rating"]
    rs_color = "#16a34a" if rs >= 80 else ("#f59e0b" if rs >= 70 else "#ef4444")
    eps_qoq = f"{m['eps_qoq']:+.0f}%" if m["eps_qoq"] is not None else "—"
    eps_ann = f"{m['eps_annual']:+.0f}%" if m["eps_annual"] is not None else "—"
    rev = f"{m['rev_growth']:+.0f}%" if m["rev_growth"] is not None else "—"
    return (
        f"<tr><td><b>{ticker}</b></td>"
        f"<td>${m['close']:.2f}</td>"
        f"<td>{m['pct_from_52wh']:+.1f}%</td>"
        f"<td style='color:{rs_color};font-weight:bold'>{rs}</td>"
        f"<td>{eps_qoq}</td>"
        f"<td>{eps_ann}</td>"
        f"<td>{rev}</td>"
        f"<td>{m['vol_ratio']:.1f}×</td>"
        f"<td>{m['passed']}/7</td></tr>"
    )


# ═══════════════════ Strategy 5: Weekly Breakout (ไม่เกิน 3 สัปดาห์) ═══════════════════
def analyze_weekly_breakout(df: pd.DataFrame, ticker: str = None,
                            ctx: dict = None) -> dict | None:
    """Weekly timeframe. หา breakout จากฐาน 52 สัปดาห์ที่เพิ่งเกิดขึ้นภายใน 3 สัปดาห์ล่าสุด
    เงื่อนไข:
      1. Weekly Close > SMA40 (≈ SMA200 daily) — uptrend
      2. Close อยู่ ≥ 99% ของ 52W High
      3. Weekly Volume > Weekly VolSMA10 — vol ยืนยัน
      4. **Breakout ภายใน 3 สัปดาห์ล่าสุด** — คือ close ใน 3 สัปดาห์ล่าสุด
         มีสัปดาห์ที่ปิดสูงกว่า peak close ของ 52 สัปดาห์ก่อนหน้า
    """
    if df is None or df.empty or len(df) < 300:  # ~55 weeks
        return None

    # Resample daily → weekly (จบวันศุกร์)
    weekly = df.resample("W-FRI").agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum",
    }).dropna()

    if len(weekly) < 55:
        return None

    wc = weekly["Close"]
    weekly["SMA40"] = wc.rolling(40).mean()
    weekly["High52W"] = weekly["High"].rolling(52).max()
    weekly["VolSMA10"] = weekly["Volume"].rolling(10).mean()

    c = float(wc.iloc[-1])
    sma40 = weekly["SMA40"].iloc[-1]
    h52 = weekly["High52W"].iloc[-1]
    vol = float(weekly["Volume"].iloc[-1])
    vol_avg = weekly["VolSMA10"].iloc[-1]
    if pd.isna(sma40) or pd.isna(h52) or pd.isna(vol_avg):
        return None
    sma40 = float(sma40); h52 = float(h52); vol_avg = float(vol_avg)

    # ─── หา "breakout ภายใน 3 สัปดาห์" ───
    # peak close ของ 52 สัปดาห์ก่อน "หน้าต่างสด" (สัปดาห์ -52 ถึง -4)
    prior_window = wc.iloc[-52:-3] if len(wc) >= 52 else wc.iloc[:-3]
    if prior_window.empty:
        return None
    peak_before = float(prior_window.max())

    # หาว่ามีสัปดาห์ใดในช่วง 3 สัปดาห์ล่าสุด (index -3, -2, -1) ที่ close > peak_before
    weeks_since_breakout = None
    for i in range(3, 0, -1):  # -3 → -2 → -1 (ย้อนเก่าไปใหม่)
        if float(wc.iloc[-i]) > peak_before:
            weeks_since_breakout = i  # จำนวนสัปดาห์นับจากตอนนี้ย้อนกลับไปวันที่เบรก
            break
    breakout_recent = weeks_since_breakout is not None

    # ─── Conditions ───
    above_sma40 = c > sma40
    near_high = c >= h52 * 0.99
    vol_confirmed = vol > vol_avg

    cond = {
        "1. Weekly Close > SMA40 (~SMA200 daily)": above_sma40,
        "2. Close ≥ 99% ของ 52W High": near_high,
        "3. Weekly Volume > Avg 10 สัปดาห์": vol_confirmed,
        "4. เบรกภายใน 3 สัปดาห์ล่าสุด": breakout_recent,
    }

    if all(cond.values()):
        signal = "BUY"
    elif above_sma40:
        signal = "HOLD/WAIT"
    else:
        signal = "SELL/WAIT"

    return {
        "signal": signal,
        "metrics": {
            "close": c,
            "sma40w": sma40,
            "high52w": h52,
            "peak_before": peak_before,
            "weeks_since_breakout": weeks_since_breakout if weeks_since_breakout else 0,
            "pct_from_high52": (c/h52 - 1) * 100,
            "pct_above_sma40": (c/sma40 - 1) * 100,
            "pct_above_peak": (c/peak_before - 1) * 100 if peak_before > 0 else 0,
            "vol": vol,
            "vol_avg": vol_avg,
            "vol_ratio": vol / vol_avg if vol_avg > 0 else 0,
        },
        "conditions": cond,
    }


def _weekly_breakout_html_row(ticker: str, m: dict) -> str:
    w = m["weeks_since_breakout"]
    weeks_str = f"{w}w ago" if w > 0 else "—"
    week_color = "#16a34a" if w == 1 else ("#65a30d" if w == 2 else "#84cc16")
    return (
        f"<tr><td><b>{ticker}</b></td>"
        f"<td>${m['close']:.2f}</td>"
        f"<td>{m['pct_from_high52']:+.2f}%</td>"
        f"<td style='color:{week_color};font-weight:bold'>{weeks_str}</td>"
        f"<td>+{m['pct_above_peak']:.1f}%</td>"
        f"<td>{m['vol_ratio']:.2f}×</td></tr>"
    )


# ═══════════════════ Registry ═══════════════════
STRATEGIES = {
    "near_52w_high": {
        "label": "Near 52W High (continuation)",
        "thai_label": "ใกล้ 52W High — เกาะเทรนด์ที่กำลังวิ่ง",
        "description": "Close > SMA200 · ≥99% ของ 52W High · Vol > avg",
        "analyze": analyze_near_52w_high,
        "needs_fundamentals": False,
        "headers": ["Ticker", "Close", "% from 52W H", "% vs SMA200", "Vol vs Avg"],
        "html_row": _near_52w_high_html_row,
    },
    "fresh_breakout": {
        "label": "Fresh Breakout from Base (early trend)",
        "thai_label": "Fresh Breakout — เข้าตั้งแต่ต้นเทรนด์",
        "description": "Stage 2 · ฐานแน่น 30 วัน · เพิ่งทะลุ ≤5% · Vol 1.5×",
        "analyze": analyze_fresh_breakout,
        "needs_fundamentals": False,
        "headers": ["Ticker", "Close", "Pivot", "+% from Pivot", "Base Range", "Vol Surge"],
        "html_row": _fresh_breakout_html_row,
    },
    "minervini_tt": {
        "label": "Minervini Trend Template (8/8)",
        "thai_label": "Minervini Trend Template — 8 ข้อครบ",
        "description": "SMA50 > 150 > 200 + Close ใน 25% ของ 52W High + RS ≥ 70",
        "analyze": analyze_minervini_tt,
        "needs_fundamentals": False,
        "headers": ["Ticker", "Close", "% from 52W H", "Above 52W L", "RS Rating", "Pass"],
        "html_row": _minervini_tt_html_row,
    },
    "canslim": {
        "label": "O'Neil CAN SLIM (technical + EPS)",
        "thai_label": "CAN SLIM — Earnings ดี + RS สูง + Market uptrend",
        "description": "EPS QoQ ≥25% · EPS Annual ≥25% · RS ≥80 · 52W High · Market uptrend",
        "analyze": analyze_canslim,
        "needs_fundamentals": True,
        "headers": ["Ticker", "Close", "% from 52W H", "RS", "EPS QoQ", "EPS Ann", "Rev", "Vol", "Pass"],
        "html_row": _canslim_html_row,
    },
    "weekly_breakout": {
        "label": "Weekly Breakout (fresh, ≤3 weeks)",
        "thai_label": "Weekly Breakout — เพิ่งเบรกไม่เกิน 3 สัปดาห์",
        "description": "Weekly TF · Close > SMA40w · ≥99% ของ 52W High · เบรกภายใน 3 สัปดาห์ล่าสุด · Vol confirming",
        "analyze": analyze_weekly_breakout,
        "needs_fundamentals": False,
        "headers": ["Ticker", "Close", "% from 52W H", "Breakout", "Above Prior Peak", "Vol Ratio"],
        "html_row": _weekly_breakout_html_row,
    },
}
