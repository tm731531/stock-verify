"""ORB 選擇權買方 — 掃進場權利金, 看便宜(高gamma)option 能否到 2-3 倍。"""
from pathlib import Path
import numpy as np
import pandas as pd

from orbital_yang.orb import run_orb, ORBParams
from orbital_yang.orb_options import option_ohlc, buyer_pnl
from orbital_yang.txo_data import fetch_chain, pick_entry_option

DATA = Path(__file__).parent / "data" / "TXF_1min.csv"
OUT = Path(__file__).parent / "reports" / "orb_options_sweep.md"
HALF_SPREAD, COMM_O, PV_O = 1.0, 20.0, 50.0
DATE_FLOOR = "2025-12-13"
PREMIUMS = [5, 10, 15, 20, 30]


def main():
    df = pd.read_csv(DATA)
    trades = [t for t in run_orb(df, ORBParams(take_profit=50.0)) if str(t.date) >= DATE_FLOOR]
    print(f"近半年 ORB {len(trades)} 筆; 掃權利金 {PREMIUMS}")
    lines = ["# ORB 選擇權買方 — 掃進場權利金 (真實 TXO, 近半年)", "",
             "進場=當日該檔 option 開盤; best=賣在當日最高(上界)。2x/3x率=當日最高/開盤達倍數比例。", "",
             "| 目標權利金 | 配對 | 平均進場 | base ROI(開→收) | best ROI(開→高) | best 2x率 | best 3x率 |",
             "|---|---|---|---|---|---|---|"]
    for tp in PREMIUMS:
        rows = []
        for t in trades:
            kind = "call" if t.direction == "long" else "put"
            ds = str(t.date)
            try:
                ch = fetch_chain(ds)
                opt = pick_entry_option(ch, kind, float(tp))
                if opt is None:
                    continue
                oh = option_ohlc(ch, opt["contract_date"], opt["strike_price"], kind)
                if oh is None or oh["open"] <= 0:
                    continue
            except Exception:
                continue
            base = buyer_pnl(oh["open"], oh["close"], HALF_SPREAD, COMM_O, PV_O)
            best = buyer_pnl(oh["open"], oh["high"], HALF_SPREAD, COMM_O, PV_O)
            rows.append({"entry": oh["open"], "base": base, "best": best,
                         "mult": oh["high"] / oh["open"]})
        if not rows:
            lines.append(f"| {tp} | 0 | - | - | - | - | - |")
            print(f"prem~{tp}: 0 配對")
            continue
        ent = np.array([r["entry"] for r in rows], float)
        base = np.array([r["base"] for r in rows], float)
        best = np.array([r["best"] for r in rows], float)
        mult = np.array([r["mult"] for r in rows], float)
        ae = float(ent.mean())
        lines.append(f"| {tp} | {len(rows)} | {ae:.1f} | {base.mean()/ae:+.0%} "
                     f"| {best.mean()/ae:+.0%} | {(mult>=2).mean():.0%} | {(mult>=3).mean():.0%} |")
        print(f"prem~{tp}: 配對{len(rows)} 平均進場{ae:.1f} baseROI{base.mean()/ae:+.0%} "
              f"bestROI{best.mean()/ae:+.0%} 2x{(mult>=2).mean():.0%} 3x{(mult>=3).mean():.0%}")
    md = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print("\n" + md)


if __name__ == "__main__":
    main()
