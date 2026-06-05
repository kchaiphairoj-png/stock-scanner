import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

from presets import PRESETS, get_sp500

st.set_page_config(page_title="Stock Breakout Scanner", layout="wide", page_icon="🚀")

st.title("🚀 Stock Breakout Scanner")
st.caption("คัดกรองหุ้นตามกลยุทธ์ Breakout: ราคา > SMA200, ใกล้ 52-Week High, Volume สูงกว่าค่าเฉลี่ย")


# ───────── Data fetching ─────────
@st.cache_data(ttl=900)
def fetch_one(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, period="2y", interval="1d", progress=False, auto_adjust=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


@st.cache_data(ttl=900, show_spinner=False)
def fetch_many(tickers: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    """ดาวน์โหลดทีเดียวพร้อมกัน เร็วกว่าวน loop หลายเท่า"""
    if not tickers:
        return {}
    data = yf.download(
        list(tickers), period="2y", interval="1d",
        progress=False, auto_adjust=False, group_by="ticker", threads=True,
    )
    out: dict[str, pd.DataFrame] = {}
    # yf คืนรูปแบบต่างกันตามจำนวน ticker
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


# ───────── Strategy ─────────
def analyze(df: pd.DataFrame) -> dict | None:
    if df is None or df.empty or len(df) < 200:
        return None
    df = df.copy()
    df["SMA50"] = df["Close"].rolling(50).mean()
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
        signal, status, reason = "BUY", "success", "ทะลุแนวต้านพร้อม Volume"
    elif sma200 is not None and close < sma200:
        signal, status, reason = "SELL/WAIT", "error", "ต่ำกว่า SMA200 (ขาลง)"
    else:
        signal, status, reason = "HOLD/WAIT", "warning", "ยังไม่เข้าเงื่อนไข"

    return {
        "df": df, "signal": signal, "status": status, "reason": reason,
        "close": close, "sma200": sma200, "high52": high52,
        "vol": vol, "vol_avg": vol_avg,
        "above_sma200": above_sma200, "near_high": near_high, "vol_high": vol_high,
    }


def plot_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    df_plot = df.tail(252)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df_plot.index, open=df_plot["Open"], high=df_plot["High"],
        low=df_plot["Low"], close=df_plot["Close"], name="Price",
    ))
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["SMA50"], name="SMA50", line=dict(color="orange", width=1.5)))
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["SMA200"], name="SMA200", line=dict(color="red", width=1.5)))
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["High52"], name="52W High", line=dict(color="green", width=1, dash="dot")))
    fig.update_layout(
        title=f"{ticker} — Last 12 months",
        xaxis_rangeslider_visible=False, height=500,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


# ───────── Sidebar ─────────
with st.sidebar:
    st.header("⚙️ Settings")
    mode = st.radio("โหมด", ["Single", "Batch Scan"], horizontal=True)
    st.markdown("---")
    st.markdown("**Strategy Rules**")
    st.markdown("- Close > SMA200")
    st.markdown("- Close ≥ 99% ของ 52W High")
    st.markdown("- Volume > VolSMA50")
    st.markdown("---")
    st.caption("ข้อมูล Yahoo Finance · cache 15 นาที")


# ───────── Single mode ─────────
if mode == "Single":
    col1, col2 = st.columns([3, 1])
    with col1:
        symbol = st.text_input("ชื่อหุ้น (Ticker)", "NVDA").upper().strip()
    with col2:
        st.write(""); st.write("")
        run = st.button("🔍 วิเคราะห์", use_container_width=True, type="primary")

    if run and symbol:
        with st.spinner(f"กำลังดึงข้อมูล {symbol}..."):
            df = fetch_one(symbol)

        if df.empty:
            st.error(f"ไม่พบข้อมูลของ {symbol}")
        else:
            r = analyze(df)
            if r is None:
                st.warning(f"ข้อมูล {symbol} ไม่พอสำหรับคำนวณ (ต้องการอย่างน้อย 200 วัน)")
            else:
                msg = f"**{r['signal']}** — {r['reason']} (ราคา {r['close']:.2f})"
                getattr(st, r["status"])(msg)

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Close", f"{r['close']:.2f}")
                m2.metric("SMA200", f"{r['sma200']:.2f}" if r["sma200"] else "—",
                          delta=f"{(r['close']-r['sma200']):.2f}" if r["sma200"] else None)
                m3.metric("52W High", f"{r['high52']:.2f}" if r["high52"] else "—",
                          delta=f"{(r['close']/r['high52']*100-100):.1f}%" if r["high52"] else None)
                m4.metric("Volume / Avg50", f"{r['vol']/1e6:.1f}M",
                          delta=f"{(r['vol']/r['vol_avg']-1)*100:.0f}%" if r["vol_avg"] else None)

                with st.expander("✅ Conditions checklist", expanded=True):
                    st.write(f"{'✅' if r['above_sma200'] else '❌'} Close > SMA200")
                    st.write(f"{'✅' if r['near_high'] else '❌'} Close ≥ 99% ของ 52W High")
                    st.write(f"{'✅' if r['vol_high'] else '❌'} Volume > VolSMA50")

                st.plotly_chart(plot_chart(r["df"], symbol), use_container_width=True)


# ───────── Batch Scan ─────────
else:
    st.subheader("เลือกชุดหุ้น")
    c1, c2 = st.columns([2, 1])
    with c1:
        preset_name = st.selectbox(
            "Preset",
            list(PRESETS.keys()) + ["Custom (พิมพ์เอง)"],
            index=2,  # Nasdaq 100 เป็น default
        )
    with c2:
        only_buy = st.checkbox("แสดงเฉพาะ BUY signal", value=False)

    # โหลด preset → เซ็ตค่า textarea
    if preset_name == "Custom (พิมพ์เอง)":
        default_text = "NVDA, AAPL, TSLA, MSFT, GOOGL"
    else:
        preset_val = PRESETS[preset_name]
        if preset_val == "sp500":
            with st.spinner("ดึงรายชื่อ S&P 500 จาก Wikipedia..."):
                preset_val = get_sp500()
        default_text = ", ".join(preset_val)

    raw = st.text_area(
        f"รายชื่อหุ้น ({default_text.count(',') + 1} ตัว) — แก้ไขได้",
        default_text, height=120,
    )

    run = st.button("🔍 สแกนทั้งหมด", type="primary")

    if run:
        tickers = tuple(sorted(set(
            t.strip().upper() for t in raw.replace("\n", ",").split(",") if t.strip()
        )))
        if not tickers:
            st.error("กรุณาใส่อย่างน้อย 1 ticker")
            st.stop()

        with st.spinner(f"กำลังดาวน์โหลดข้อมูล {len(tickers)} ตัวพร้อมกัน..."):
            data = fetch_many(tickers)

        rows = []
        progress = st.progress(0.0, text="กำลังวิเคราะห์...")
        for i, t in enumerate(tickers, 1):
            df = data.get(t)
            if df is None or df.empty:
                rows.append({"Ticker": t, "Signal": "NO DATA", "Close": None,
                             "SMA200": None, "52W High": None, "%from High": None, "Vol/Avg": None})
            else:
                r = analyze(df)
                if r is None:
                    rows.append({"Ticker": t, "Signal": "INSUFFICIENT", "Close": None,
                                 "SMA200": None, "52W High": None, "%from High": None, "Vol/Avg": None})
                else:
                    rows.append({
                        "Ticker": t, "Signal": r["signal"],
                        "Close": round(r["close"], 2),
                        "SMA200": round(r["sma200"], 2) if r["sma200"] else None,
                        "52W High": round(r["high52"], 2) if r["high52"] else None,
                        "%from High": round((r["close"]/r["high52"]-1)*100, 2) if r["high52"] else None,
                        "Vol/Avg": round(r["vol"]/r["vol_avg"], 2) if r["vol_avg"] else None,
                    })
            progress.progress(i / len(tickers))
        progress.empty()

        result_df = pd.DataFrame(rows)

        # Summary stats
        buy_count = (result_df["Signal"] == "BUY").sum()
        hold_count = (result_df["Signal"] == "HOLD/WAIT").sum()
        sell_count = (result_df["Signal"] == "SELL/WAIT").sum()
        nodata = (result_df["Signal"].isin(["NO DATA", "INSUFFICIENT"])).sum()

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("🟢 BUY", buy_count)
        s2.metric("🟡 HOLD/WAIT", hold_count)
        s3.metric("🔴 SELL/WAIT", sell_count)
        s4.metric("⚪ NO DATA", nodata)

        # Filter + sort: BUY ก่อน, แล้วเรียงตาม %from High ใกล้ 0
        if only_buy:
            result_df = result_df[result_df["Signal"] == "BUY"]
        result_df = result_df.sort_values(
            by=["Signal", "%from High"],
            key=lambda col: col.map({"BUY": 0, "HOLD/WAIT": 1, "SELL/WAIT": 2}).fillna(3) if col.name == "Signal" else col,
            ascending=[True, False],
            na_position="last",
        )

        def color_signal(val):
            colors = {
                "BUY": "background-color: #16a34a; color: white",
                "SELL/WAIT": "background-color: #dc2626; color: white",
                "HOLD/WAIT": "background-color: #f59e0b; color: white",
            }
            return colors.get(val, "")

        st.dataframe(
            result_df.style.map(color_signal, subset=["Signal"]),
            use_container_width=True, hide_index=True, height=600,
        )

        csv = result_df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download CSV", csv, f"scan_{preset_name.replace(' ', '_')}.csv", "text/csv")
