"""Daily scan → JSON output (สำหรับ scanner-app web).

ใช้ logic เดียวกับ scan_alert.py แต่ output เป็น JSON ไม่ส่งอีเมล

รัน:
    python scan_json.py
    python scan_json.py --output ../scanner-app/data
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# reuse logic จาก scan_alert.py
from scan_alert import (build_context, fetch_many, get_universe,
                        run_strategy, STRATEGIES)
from strategies import STRATEGIES as _STRATEGIES_REGISTRY

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def serialize_result(result: dict) -> dict:
    """แปลง strategy result → JSON-friendly dict"""
    return {
        "key": result["key"],
        "label": result["strategy"]["thai_label"],
        "description": result["strategy"]["description"],
        "needs_fundamentals": result["strategy"]["needs_fundamentals"],
        "buys": [
            {
                "ticker": b["ticker"],
                "metrics": {k: (round(v, 2) if isinstance(v, float) else v)
                            for k, v in b["metrics"].items()},
                "conditions": b["conditions"],
            }
            for b in result["buys"]
        ],
        "counts": {
            "buy": len(result["buys"]),
            "hold": result["hold"],
            "sell": result["sell"],
            "nodata": result["nodata"],
        },
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="../scanner-app/data",
                   help="โฟลเดอร์ปลายทางของ JSON files")
    p.add_argument("--strategies", default="all",
                   help="strategies (comma-separated) หรือ 'all'")
    p.add_argument("--universe", default=None,
                   help="override UNIVERSE env var (sp500/nasdaq100/dow30)")
    args = p.parse_args()

    # ปรับ env vars ตาม args (เพื่อใช้ helper เดิม)
    if args.strategies:
        os.environ["STRATEGY"] = args.strategies
    if args.universe:
        os.environ["UNIVERSE"] = args.universe

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "history").mkdir(exist_ok=True)

    # ─── เลือก strategies ───
    spec = os.environ.get("STRATEGY", "all").lower()
    if spec == "all":
        strategy_keys = list(STRATEGIES.keys())
    else:
        strategy_keys = [k.strip() for k in spec.split(",") if k.strip() in STRATEGIES]
        if not strategy_keys:
            strategy_keys = list(STRATEGIES.keys())

    universe_name, universe = get_universe()
    print(f"Strategies: {strategy_keys}")
    print(f"Universe:   {universe_name} ({len(universe)} tickers)")

    # ─── Download data ───
    download_set = list(set(universe) | {"SPY"})
    print(f"\nDownloading data for {len(download_set)} tickers...")
    data = fetch_many(tuple(download_set))
    print(f"Got data for {len(data)} tickers")

    # ─── Pre-screen + fundamentals (CAN SLIM) ───
    needs_fundamentals = any(STRATEGIES[k]["needs_fundamentals"] for k in strategy_keys)
    pre_pass = []
    if needs_fundamentals:
        for t in universe:
            df = data.get(t)
            if df is None or len(df) < 253:
                continue
            try:
                sma200 = float(df["Close"].rolling(200).mean().iloc[-1])
                h52 = float(df["High"].iloc[-252:].max())
                c = float(df["Close"].iloc[-1])
                if c > sma200 and c >= h52 * 0.75:
                    pre_pass.append(t)
            except Exception:
                continue
        print(f"Pre-screen: {len(pre_pass)} candidates for fundamentals")

    # ─── Build context ───
    print("\nBuilding context (regime, RS ratings, fundamentals)...")
    ctx = build_context(data, pre_pass if needs_fundamentals else None)
    print(f"  Market: {'UPTREND' if ctx['market_uptrend'] else 'DOWNTREND/SIDEWAYS'}")
    print(f"  RS ratings: {len(ctx['rs_ratings'])} tickers")

    # ─── Run all strategies ───
    results = []
    for key in strategy_keys:
        print(f"\n→ Running: {key}")
        r = run_strategy(key, universe, data, ctx)
        print(f"  BUY={len(r['buys'])}  HOLD={r['hold']}  SELL={r['sell']}")
        results.append(r)

    # ─── Compute intersection (หุ้นที่ขึ้นใน strategies หลายตัว) ───
    ticker_strategy_count = {}
    for r in results:
        for b in r["buys"]:
            ticker_strategy_count.setdefault(b["ticker"], []).append(r["key"])

    high_conviction = [
        {"ticker": t, "strategies": s, "count": len(s)}
        for t, s in ticker_strategy_count.items() if len(s) >= 2
    ]
    high_conviction.sort(key=lambda x: -x["count"])

    # ─── Build JSON payload ───
    now = datetime.now()
    payload = {
        "generated_at": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "universe": {
            "name": universe_name,
            "size": len(universe),
            "data_received": len(data),
        },
        "market_regime": {
            "uptrend": ctx["market_uptrend"],
            "info": ctx.get("regime_info", {}),
        },
        "strategies": [serialize_result(r) for r in results],
        "high_conviction": high_conviction,
        "stats": {
            "total_buy_signals": sum(len(r["buys"]) for r in results),
            "unique_tickers": len(ticker_strategy_count),
            "strategies_run": len(results),
        },
    }

    # ─── Save files ───
    latest_path = output_dir / "latest.json"
    history_path = output_dir / "history" / f"{now.strftime('%Y-%m-%d')}.json"

    with latest_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with history_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # ─── Update history index ───
    history_dir = output_dir / "history"
    history_files = sorted([f.stem for f in history_dir.glob("*.json")], reverse=True)
    index_payload = {
        "updated_at": now.isoformat(),
        "dates": history_files[:90],  # เก็บ 90 วันล่าสุด
    }
    with (output_dir / "history" / "index.json").open("w", encoding="utf-8") as f:
        json.dump(index_payload, f, indent=2)

    print(f"\n✅ Saved:")
    print(f"   latest:  {latest_path}")
    print(f"   history: {history_path}")
    print(f"   index:   {output_dir / 'history' / 'index.json'} ({len(history_files)} dates)")
    print(f"\n📊 Summary: {payload['stats']['total_buy_signals']} total BUY signals, "
          f"{len(high_conviction)} high-conviction (2+ strategies)")


if __name__ == "__main__":
    main()
