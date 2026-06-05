"""Trading strategies. แต่ละ strategy คืน:
    {"signal": "BUY" | "HOLD/WAIT" | "SELL/WAIT", "metrics": {...}}
หรือ None ถ้าข้อมูลไม่พอ

Strategies:
- near_52w_high   : ใกล้ 52W High + Vol สูง (continuation)
- fresh_breakout  : Stage 2 + เพิ่งทะลุฐาน (early trend entry)
"""
import pandas as pd


# ═══════════════════ Strategy 1: Near 52W High ═══════════════════
def analyze_near_52w_high(df: pd.DataFrame) -> dict | None:
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
def analyze_fresh_breakout(df: pd.DataFrame) -> dict | None:
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

    # Base = 30 วันก่อนหน้า (ไม่นับวันนี้)
    base = df.iloc[-31:-1]
    base_high = float(base["High"].max())
    base_low = float(base["Low"].min())
    base_range_pct = (base_high - base_low) / base_low * 100

    # 52W
    yr = df.iloc[-252:]
    h52 = float(yr["High"].max())
    l52 = float(yr["Low"].min())

    # === 7 เงื่อนไข ===
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
        signal = "HOLD/WAIT"  # uptrend แต่ยังไม่ breakout
    else:
        signal = "SELL/WAIT"  # ไม่ uptrend แล้ว

    return {
        "signal": signal,
        "metrics": {
            "close": c,
            "pivot": base_high,
            "base_low": base_low,
            "base_range_pct": base_range_pct,
            "sma50": s50,
            "sma200": s200_now,
            "pct_from_pivot": (c/base_high - 1) * 100,
            "pct_from_52wh": (c/h52 - 1) * 100,
            "above_52wl_pct": (c/l52 - 1) * 100,
            "vol": v,
            "vol_avg": v_avg,
            "vol_ratio": v / v_avg,
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


# ═══════════════════ Registry ═══════════════════
STRATEGIES = {
    "near_52w_high": {
        "label": "Near 52W High (continuation)",
        "thai_label": "ใกล้ 52W High — เกาะเทรนด์ที่กำลังวิ่ง",
        "description": "Close > SMA200 · ≥99% ของ 52W High · Vol > avg",
        "analyze": analyze_near_52w_high,
        "headers": ["Ticker", "Close", "% from 52W H", "% vs SMA200", "Vol vs Avg"],
        "html_row": _near_52w_high_html_row,
    },
    "fresh_breakout": {
        "label": "Fresh Breakout from Base (early trend)",
        "thai_label": "Fresh Breakout — เข้าตั้งแต่ต้นเทรนด์",
        "description": "Stage 2 · ฐานแน่น 30 วัน · เพิ่งทะลุ ≤5% · Vol 1.5×",
        "analyze": analyze_fresh_breakout,
        "headers": ["Ticker", "Close", "Pivot", "+% from Pivot", "Base Range", "Vol Surge"],
        "html_row": _fresh_breakout_html_row,
    },
}
