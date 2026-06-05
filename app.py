import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

from presets import PRESETS, get_sp500
from strategies import STRATEGIES

st.set_page_config(page_title="Stock Breakout Scanner", layout="wide", page_icon="🚀")

st.title("🚀 Stock Breakout Scanner")
st.caption("คัดกรองหุ้นตามกลยุทธ์ที่เลือก — มี 2 แบบ: Near 52W High (continuation) และ Fresh Breakout (early trend)")


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


def plot_chart(df: pd.DataFrame, ticker: str, strategy_key: str, metrics: dict) -> go.Figure:
    df = df.copy()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["High52"] = df["High"].rolling(252).max()
    df_plot = df.tail(252)

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df_plot.index, open=df_plot["Open"], high=df_plot["High"],
        low=df_plot["Low"], close=df_plot["Close"], name="Price",
    ))
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["SMA50"], name="SMA50", line=dict(color="orange", width=1.5)))
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["SMA200"], name="SMA200", line=dict(color="red", width=1.5)))

    if strategy_key == "near_52w_high":
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["High52"], name="52W High",
                                 line=dict(color="green", width=1, dash="dot")))
    elif strategy_key == "fresh_breakout" and "pivot" in metrics:
        # เส้น pivot (base high)
        fig.add_hline(y=metrics["pivot"], line=dict(color="purple", width=1.5, dash="dash"),
                      annotation_text=f"Pivot ${metrics['pivot']:.2f}", annotation_position="right")
        if "base_low" in metrics:
            fig.add_hline(y=metrics["base_low"], line=dict(color="gray", width=1, dash="dot"),
                          annotation_text=f"Base Low ${metrics['base_low']:.2f}", annotation_position="right")

    fig.update_layout(
        title=f"{ticker} — Last 12 months",
        xaxis_rangeslider_visible=False, height=520,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


# ───────── Sidebar ─────────
with st.sidebar:
    st.header("⚙️ Settings")
    mode = st.radio("โหมด", ["Single", "Batch Scan"], horizontal=True)

    st.markdown("---")
    strategy_key = st.selectbox(
        "🎯 Strategy",
        list(STRATEGIES.keys()),
        format_func=lambda k: STRATEGIES[k]["thai_label"],
        index=0,  # near_52w_high (backtest ดีกว่า — ดู compare_strategies.py)
    )
    strategy = STRATEGIES[strategy_key]
    st.caption(strategy["description"])

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
            r = strategy["analyze"](df)
            if r is None:
                st.warning(f"ข้อมูล {symbol} ไม่พอสำหรับคำนวณ (ต้องการอย่างน้อย ~250 วัน)")
            else:
                m = r["metrics"]
                status_map = {"BUY": "success", "SELL/WAIT": "error", "HOLD/WAIT": "warning"}
                status_fn = getattr(st, status_map[r["signal"]])
                status_fn(f"**{r['signal']}** ({strategy['label']}) — ราคา ${m['close']:.2f}")

                # Strategy-specific metric cards
                c1, c2, c3, c4 = st.columns(4)
                if strategy_key == "near_52w_high":
                    c1.metric("Close", f"${m['close']:.2f}")
                    c2.metric("SMA200", f"${m['sma200']:.2f}",
                              delta=f"{m['pct_above_sma200']:+.1f}%")
                    c3.metric("52W High", f"${m['high52']:.2f}",
                              delta=f"{m['pct_from_high52']:+.2f}%")
                    c4.metric("Volume", f"{m['vol']/1e6:.1f}M",
                              delta=f"{(m['vol_ratio']-1)*100:+.0f}%")
                else:  # fresh_breakout
                    c1.metric("Close", f"${m['close']:.2f}")
                    c2.metric("Pivot (base high)", f"${m['pivot']:.2f}",
                              delta=f"{m['pct_from_pivot']:+.2f}%")
                    c3.metric("Base Range", f"{m['base_range_pct']:.1f}%",
                              delta="tight" if m['base_range_pct'] < 15 else "loose",
                              delta_color="normal" if m['base_range_pct'] < 15 else "inverse")
                    c4.metric("Vol Surge", f"{m['vol_ratio']:.2f}×",
                              delta="confirmed" if m['vol_ratio'] > 1.5 else "weak")

                with st.expander("✅ Conditions checklist", expanded=True):
                    for label, passed in r["conditions"].items():
                        st.write(f"{'✅' if passed else '❌'} {label}")

                st.plotly_chart(plot_chart(df, symbol, strategy_key, m), use_container_width=True)


# ───────── Batch Scan ─────────
else:
    st.subheader("เลือกชุดหุ้น")
    c1, c2 = st.columns([2, 1])
    with c1:
        preset_name = st.selectbox(
            "Preset",
            list(PRESETS.keys()) + ["Custom (พิมพ์เอง)"],
            index=2,
        )
    with c2:
        only_buy = st.checkbox("แสดงเฉพาะ BUY signal", value=False)

    if preset_name == "Custom (พิมพ์เอง)":
        default_text = "NVDA, AAPL, TSLA, MSFT, GOOGL"
    else:
        preset_val = PRESETS[preset_name]
        if preset_val == "sp500":
            with st.spinner("ดึงรายชื่อ S&P 500..."):
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

        with st.spinner(f"กำลังดาวน์โหลด {len(tickers)} ตัว..."):
            data = fetch_many(tickers)

        # Build rows based on strategy
        rows = []
        progress = st.progress(0.0, text="วิเคราะห์...")
        for i, t in enumerate(tickers, 1):
            df = data.get(t)
            if df is None or df.empty:
                rows.append({"Ticker": t, "Signal": "NO DATA", **{h: None for h in strategy["headers"][1:]}})
            else:
                r = strategy["analyze"](df)
                if r is None:
                    rows.append({"Ticker": t, "Signal": "INSUFFICIENT", **{h: None for h in strategy["headers"][1:]}})
                else:
                    m = r["metrics"]
                    row = {"Ticker": t, "Signal": r["signal"]}
                    if strategy_key == "near_52w_high":
                        row.update({
                            "Close": round(m["close"], 2),
                            "% from 52W H": round(m["pct_from_high52"], 2),
                            "% vs SMA200": round(m["pct_above_sma200"], 1),
                            "Vol vs Avg": round(m["vol_ratio"], 2),
                        })
                    else:
                        row.update({
                            "Close": round(m["close"], 2),
                            "Pivot": round(m["pivot"], 2),
                            "+% from Pivot": round(m["pct_from_pivot"], 2),
                            "Base Range": round(m["base_range_pct"], 1),
                            "Vol Surge": round(m["vol_ratio"], 2),
                        })
                    rows.append(row)
            progress.progress(i / len(tickers))
        progress.empty()

        result_df = pd.DataFrame(rows)

        # Summary
        buy_count = (result_df["Signal"] == "BUY").sum()
        hold_count = (result_df["Signal"] == "HOLD/WAIT").sum()
        sell_count = (result_df["Signal"] == "SELL/WAIT").sum()
        nodata = (result_df["Signal"].isin(["NO DATA", "INSUFFICIENT"])).sum()

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("🟢 BUY", int(buy_count))
        s2.metric("🟡 HOLD/WAIT", int(hold_count))
        s3.metric("🔴 SELL/WAIT", int(sell_count))
        s4.metric("⚪ NO DATA", int(nodata))

        if only_buy:
            result_df = result_df[result_df["Signal"] == "BUY"]

        # Sort: BUY ก่อน, แล้วเรียงตามสัญญาณคุณภาพ
        sort_col = "% from 52W H" if strategy_key == "near_52w_high" else "+% from Pivot"
        sort_ascending = strategy_key == "fresh_breakout"  # fresh: น้อยสุดอยู่บน
        result_df = result_df.sort_values(
            by=["Signal", sort_col],
            key=lambda col: col.map({"BUY": 0, "HOLD/WAIT": 1, "SELL/WAIT": 2}).fillna(3) if col.name == "Signal" else col,
            ascending=[True, sort_ascending],
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
        st.download_button(
            "📥 Download CSV", csv,
            f"scan_{strategy_key}_{preset_name.replace(' ', '_')}.csv",
            "text/csv",
        )
