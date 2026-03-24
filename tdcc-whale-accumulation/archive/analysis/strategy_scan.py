#!/usr/bin/env python3
"""Fast strategy parameter scan - scan once, filter many times."""

import json, sqlite3, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import numpy as np
import pandas as pd
from crawler.price_fetcher import PriceFetcher

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "tdcc_holdings.db")
COST = 0.585
HOLD_WEEKS = 9

def load_data():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    tdcc = pd.read_sql("SELECT * FROM holdings ORDER BY stock_code, date", conn)
    conn.close()

    date_counts = tdcc.groupby("date").size()
    valid_dates = sorted(date_counts[date_counts > 500].index.tolist())
    tdcc = tdcc[tdcc["date"].isin(valid_dates)]

    fetcher = PriceFetcher(request_delay=0, db_path=DB_PATH)
    for d in valid_dates:
        fetcher.fetch_market_day(d)

    return tdcc, fetcher, valid_dates


def scan_all_signals(tdcc, fetcher):
    """Scan once with widest conditions (2-week rising, ratio>=0.5, all prices).
    Records consecutive rising weeks count (2,3,4+) for later filtering."""
    signals = []
    stocks = tdcc["stock_code"].unique()

    for si, stock in enumerate(stocks):
        if stock.startswith("00"):
            continue

        df = tdcc[tdcc["stock_code"] == stock].sort_values("date")
        if len(df) < 3:
            continue

        ratios = df["ratio_400_above"].values
        dates = df["date"].values

        for i in range(2, len(ratios)):
            # Count consecutive rising weeks
            consec = 0
            for k in range(1, i + 1):
                if ratios[i - k + 1] > ratios[i - k]:
                    consec += 1
                else:
                    break

            if consec < 2:
                continue

            # Ratio changes for different window sizes
            rc2 = ratios[i] - ratios[i - 2] if i >= 2 else 0
            rc3 = ratios[i] - ratios[i - 3] if i >= 3 else 0
            rc4 = ratios[i] - ratios[i - 4] if i >= 4 else 0

            signal_date = dates[i]
            signal_price = fetcher._cache.get(signal_date, {}).get(stock)
            if not signal_price or signal_price <= 0:
                continue

            # Buy next week
            idx = i
            if idx + 1 >= len(dates):
                continue
            buy_date = dates[idx + 1]
            buy_price = fetcher._cache.get(buy_date, {}).get(stock)
            if not buy_price or buy_price <= 0:
                continue

            # Acc period price change (use 3-week window as reference)
            lookback = min(3, i)
            start_date = dates[i - lookback]
            sp = fetcher._cache.get(start_date, {}).get(stock)
            acc_change = abs((signal_price - sp) / sp * 100) if sp and sp > 0 else 999

            # Exit
            exit_idx = min(idx + 1 + HOLD_WEEKS, len(dates) - 1)
            exit_date = dates[exit_idx]
            exit_price = fetcher._cache.get(exit_date, {}).get(stock)
            if not exit_price:
                continue

            # Min price during hold
            min_p = buy_price
            max_p = buy_price
            for j in range(idx + 1, exit_idx + 1):
                p = fetcher._cache.get(dates[j], {}).get(stock)
                if p:
                    min_p = min(min_p, p)
                    max_p = max(max_p, p)

            hold_ret = (exit_price - buy_price) / buy_price * 100
            max_dd = (min_p - buy_price) / buy_price * 100
            max_gain = (max_p - buy_price) / buy_price * 100

            signals.append({
                "stock": stock,
                "signal_date": signal_date,
                "buy_date": buy_date,
                "buy_price": round(buy_price, 2),
                "exit_price": round(exit_price, 2),
                "consec_weeks": consec,
                "rc2": round(rc2, 2),
                "rc3": round(rc3, 2),
                "rc4": round(rc4, 2),
                "acc_change": round(acc_change, 2),
                "hold_ret": round(hold_ret, 2),
                "max_dd": round(max_dd, 2),
                "max_gain": round(max_gain, 2),
            })

        if (si + 1) % 500 == 0:
            print(f"  掃描進度: {si+1}/{len(stocks)}")

    return pd.DataFrame(signals)


def apply_stop_loss(df, stop_pct=-5):
    """Apply stop loss to net return."""
    df = df.copy()
    df["net"] = df["hold_ret"] - COST
    df.loc[df["max_dd"] < stop_pct, "net"] = stop_pct - COST
    return df


def evaluate(df, label=""):
    n = len(df)
    if n == 0:
        return None
    wins = (df["hold_ret"] > 0).sum()
    big = (df["hold_ret"] > 10).sum()
    stops = (df["max_dd"] < -5).sum()
    return {
        "label": label,
        "n": n,
        "win%": round(wins / n * 100, 1),
        "avg": round(df["net"].mean(), 2),
        "med": round(df["net"].median(), 2),
        "big%": round(big / n * 100, 1),
        "stop%": round(stops / n * 100, 1),
        "best": round(df["net"].max(), 2),
        "worst": round(df["net"].min(), 2),
    }


def main():
    print("載入資料...")
    tdcc, fetcher, valid_dates = load_data()
    print(f"  {len(valid_dates)} 週, {len(tdcc)} 筆 TDCC, {len(fetcher._cache)} 天股價")

    print("\n掃描全部訊號 (最寬條件: 2週連升, ratio>=0.5)...")
    all_sig = scan_all_signals(tdcc, fetcher)
    print(f"  原始訊號: {len(all_sig)}")

    all_sig = apply_stop_loss(all_sig)

    # ── v4 原始條件 ──
    print("\n" + "=" * 75)
    print("【v4 原始】3週連升, ratio>=1%, 15-50元, 盤整<1%")
    v4 = all_sig[(all_sig["consec_weeks"] >= 3) & (all_sig["rc3"] >= 1.0) &
                 (all_sig["buy_price"] >= 15) & (all_sig["buy_price"] <= 50) &
                 (all_sig["acc_change"] <= 1.0)]
    r = evaluate(v4, "v4")
    if r:
        print(f"  {r}")

    # ── 參數掃描 ──
    print("\n" + "=" * 75)
    print("參數掃描 (84 組合)")
    print("=" * 75)

    results = []
    for min_w in [2, 3, 4]:
        rc_col = f"rc{min_w}" if min_w <= 4 else "rc4"
        for min_r in [0.5, 1.0, 1.5, 2.0]:
            for plo, phi in [(0, 9999), (10, 30), (10, 50), (15, 50), (15, 100), (30, 100), (50, 200)]:
                mask = ((all_sig["consec_weeks"] >= min_w) &
                        (all_sig[rc_col] >= min_r) &
                        (all_sig["buy_price"] >= plo) &
                        (all_sig["buy_price"] <= phi))
                sub = all_sig[mask]
                if len(sub) < 5:
                    continue
                r = evaluate(sub, f"w{min_w}_r{min_r}_{plo}-{phi}")
                if r:
                    results.append(r)

    # Also scan with acc_change filter
    for acc_max in [1.0, 3.0, 5.0]:
        for min_w in [2, 3, 4]:
            rc_col = f"rc{min_w}" if min_w <= 4 else "rc4"
            for min_r in [0.5, 1.0, 1.5, 2.0]:
                for plo, phi in [(10, 50), (15, 50), (15, 100), (10, 100)]:
                    mask = ((all_sig["consec_weeks"] >= min_w) &
                            (all_sig[rc_col] >= min_r) &
                            (all_sig["buy_price"] >= plo) &
                            (all_sig["buy_price"] <= phi) &
                            (all_sig["acc_change"] <= acc_max))
                    sub = all_sig[mask]
                    if len(sub) < 5:
                        continue
                    r = evaluate(sub, f"w{min_w}_r{min_r}_{plo}-{phi}_acc{acc_max}")
                    if r:
                        results.append(r)

    res = pd.DataFrame(results)

    # Dedup by label
    res = res.drop_duplicates(subset="label")

    print(f"\n共 {len(res)} 組有效參數組合\n")

    # Top by avg
    print("Top 15 (平均淨報酬):")
    print(f"{'label':<35} {'n':>5} {'win%':>6} {'avg':>7} {'med':>7} {'big%':>6} {'stop%':>6}")
    print("-" * 80)
    for _, r in res.sort_values("avg", ascending=False).head(15).iterrows():
        print(f"{r['label']:<35} {r['n']:>5} {r['win%']:>5.1f}% {r['avg']:>+6.2f}% {r['med']:>+6.2f}% {r['big%']:>5.1f}% {r['stop%']:>5.1f}%")

    # Top by median
    print(f"\nTop 15 (中位數報酬):")
    print(f"{'label':<35} {'n':>5} {'win%':>6} {'avg':>7} {'med':>7} {'big%':>6} {'stop%':>6}")
    print("-" * 80)
    for _, r in res.sort_values("med", ascending=False).head(15).iterrows():
        print(f"{r['label']:<35} {r['n']:>5} {r['win%']:>5.1f}% {r['avg']:>+6.2f}% {r['med']:>+6.2f}% {r['big%']:>5.1f}% {r['stop%']:>5.1f}%")

    # Top by win rate (min 10 signals)
    enough = res[res["n"] >= 10]
    print(f"\nTop 15 (勝率, 至少10筆):")
    print(f"{'label':<35} {'n':>5} {'win%':>6} {'avg':>7} {'med':>7} {'big%':>6} {'stop%':>6}")
    print("-" * 80)
    for _, r in enough.sort_values("win%", ascending=False).head(15).iterrows():
        print(f"{r['label']:<35} {r['n']:>5} {r['win%']:>5.1f}% {r['avg']:>+6.2f}% {r['med']:>+6.2f}% {r['big%']:>5.1f}% {r['stop%']:>5.1f}%")

    # Save
    res.to_csv(os.path.join(os.path.dirname(__file__), "data", "strategy_scan.csv"), index=False)
    all_sig.to_csv(os.path.join(os.path.dirname(__file__), "data", "all_signals_raw.csv"), index=False)
    print(f"\n已存檔: data/strategy_scan.csv, data/all_signals_raw.csv")


if __name__ == "__main__":
    main()
