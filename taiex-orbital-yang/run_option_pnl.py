"""買方回測: 把兩個策略(順格局ORB / 掛單關卡)對映真實 TXO 權利金。

出場條件對映: 贏(tp)=賣在當日高, 輸(stop)=當日低, eod=收盤。買方虧損被權利金封頂。
"""
from pathlib import Path
import numpy as np
import pandas as pd

from orbital_yang.data_loader import load_daily
from orbital_yang.regime import alignment_sign
from orbital_yang.orb import run_orb, ORBParams
from orbital_yang.levels_lo import run_lo, LOParams
from orbital_yang.orb_options import option_ohlc, buyer_pnl
from orbital_yang.txo_data import fetch_chain, pick_entry_option

HERE = Path(__file__).parent
HALF_SPREAD, COMM_O, PV_O = 1.0, 20.0, 50.0
TARGET_PREMIUM = 30.0
DATE_FLOOR = "2025-12-13"


def map_options(trades):
    rows, skipped = [], 0
    for t in trades:
        if str(t.date) < DATE_FLOOR:
            continue
        kind = "call" if t.direction == "long" else "put"
        try:
            ch = fetch_chain(str(t.date))
            opt = pick_entry_option(ch, kind, TARGET_PREMIUM)
            if opt is None:
                skipped += 1; continue
            oh = option_ohlc(ch, opt["contract_date"], opt["strike_price"], kind)
            if oh is None or oh["open"] <= 0:
                skipped += 1; continue
        except Exception:
            skipped += 1; continue
        if t.reason == "tp":
            exit_px = oh["high"]
        elif t.reason == "stop":
            exit_px = oh["low"]
        else:
            exit_px = oh["close"]
        pnl = buyer_pnl(oh["open"], exit_px, HALF_SPREAD, COMM_O, PV_O)
        mult = exit_px / oh["open"] if oh["open"] > 0 else 0.0
        rows.append({"entry": oh["open"], "pnl": pnl, "mult": mult, "won": pnl > 0,
                     "worthless": exit_px <= 1e-6})
    return rows, skipped


def stats(rows):
    if not rows:
        return None
    ent = np.array([r["entry"] for r in rows], float)
    pnl = np.array([r["pnl"] for r in rows], float)
    mult = np.array([r["mult"] for r in rows], float)
    won = pnl > 0
    eq = np.concatenate([[0.0], np.cumsum(pnl)])
    maxdd = float((eq - np.maximum.accumulate(eq)).min())
    ae = float(ent.mean())
    return dict(n=len(rows), winrate=float(won.mean()), avg_prem=ae,
                exp=float(pnl.mean()), roi=float(pnl.mean()) / ae if ae else 0.0,
                total=float(pnl.sum()), nt=float(pnl.sum()) * PV_O,
                avg_win=float(pnl[won].mean()) if won.any() else 0.0,
                avg_loss=float(pnl[~won].mean()) if (~won).any() else 0.0,
                rate_2x=float((mult >= 2).mean()), rate_3x=float((mult >= 3).mean()),
                worthless=float(np.mean([r["worthless"] for r in rows])), maxdd=maxdd)


def main():
    daily = load_daily(str(HERE / "data" / "TXF_daily.csv"))
    m = pd.read_csv(HERE / "data" / "TXF_1min.csv")
    sign = alignment_sign(daily, 20, 60)
    dd = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d").to_numpy()
    allowed = {dd[i]: int(sign[i]) for i in range(len(dd)) if sign[i] != 0}
    orb_all = run_orb(m, ORBParams(take_profit=50.0))
    orb = [t for t in orb_all if allowed.get(str(t.date)) == (1 if t.direction == "long" else -1)]
    lo = run_lo(daily, m, LOParams(take_profit=50.0, stop=50.0))

    out = {}
    for name, trades in [("A 開盤ORB", orb), ("B 掛單關卡", lo)]:
        rows, sk = map_options(trades)
        out[name] = (stats(rows), len(trades), sk)

    L = ["# 買方回測 (真實 TXO 權利金, 近半年, 含成本)", "",
         "出場: 贏=賣在當日高 / 輸=當日低 / eod=收盤。買方虧損被權利金封頂。", "",
         "| 策略 | 配對 | 勝率 | 平均權利金 | 期望(點) | ROI | 每筆NT$ | 2x率 | 歸零率 | 平均賺/賠 | 最大回撤(點) |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, (s, ntot, sk) in out.items():
        if not s:
            L.append(f"| {name} | 0 | - | - | - | - | - | - | - | - | - |"); continue
        L.append(f"| {name} | {s['n']} | {s['winrate']:.0%} | {s['avg_prem']:.1f} | {s['exp']:+.1f} "
                 f"| {s['roi']:+.0%} | {s['exp']*PV_O:+,.0f} | {s['rate_2x']:.0%} | {s['worthless']:.0%} "
                 f"| {s['avg_win']:+.1f}/{s['avg_loss']:+.1f} | {s['maxdd']:+.0f} |")
    md = "\n".join(L) + "\n"
    (HERE / "reports").mkdir(exist_ok=True)
    (HERE / "reports" / "option_pnl.md").write_text(md)
    print(md)
    for name, (s, ntot, sk) in out.items():
        if s:
            print(f"{name}: 總交易{ntot}, 配對{s['n']}(跳過{sk}), 買方總損益 {s['total']:+.0f}點 ({s['nt']:+,.0f}元)")


if __name__ == "__main__":
    main()
