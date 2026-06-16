"""樂透版: 買便宜 option + 掛限價賣單在 N 倍 (不盯盤自動成交), 沒噴到收盤砍。

進場=順格局ORB。掛限價賣 = 真實可執行(不盯盤)。option當日最高>=N倍 -> 自動成交在N倍。
掃『進場權利金』×『賣出倍數』。真實 TXO, 含成本。
"""
from pathlib import Path
import numpy as np
import pandas as pd

from orbital_yang.data_loader import load_daily
from orbital_yang.regime import alignment_sign
from orbital_yang.orb import run_orb, ORBParams
from orbital_yang.orb_options import option_ohlc, buyer_pnl
from orbital_yang.txo_data import fetch_chain, pick_entry_option

HERE = Path(__file__).parent
HS, CO, PV = 1.0, 20.0, 50.0
DATE_FLOOR = "2025-12-13"
PREMIUMS = [10, 15, 30]
MULTS = [2.0, 3.0, 5.0]


def main():
    daily = load_daily(str(HERE / "data" / "TXF_daily.csv"))
    m = pd.read_csv(HERE / "data" / "TXF_1min.csv")
    sign = alignment_sign(daily, 20, 60)
    dd = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d").to_numpy()
    allowed = {dd[i]: int(sign[i]) for i in range(len(dd)) if sign[i] != 0}
    trades = [t for t in run_orb(m, ORBParams(50.0))
              if allowed.get(str(t.date)) == (1 if t.direction == "long" else -1) and str(t.date) >= DATE_FLOOR]

    print(f"近半年訊號 {len(trades)} 筆 | 買便宜option + 掛限價賣在N倍, 沒噴收盤砍")
    print(f"{'權利金':>6}{'賣倍數':>7}{'配對':>6}{'中獎%':>7}{'平均賺':>8}{'平均賠':>8}{'期望':>7}{'ROI':>7}{'總損益':>10}")
    for prem in PREMIUMS:
        for K in MULTS:
            rows = []
            for t in trades:
                kind = "call" if t.direction == "long" else "put"
                try:
                    ch = fetch_chain(str(t.date)); opt = pick_entry_option(ch, kind, float(prem))
                    oh = option_ohlc(ch, opt["contract_date"], opt["strike_price"], kind) if opt else None
                    if not oh or oh["open"] <= 0:
                        continue
                except Exception:
                    continue
                tgt = oh["open"] * K
                if oh["high"] >= tgt:        # 噴到N倍 -> 限價單自動成交
                    ex = tgt
                else:                         # 沒噴到 -> 收盤砍
                    ex = oh["close"]
                rows.append(buyer_pnl(oh["open"], ex, HS, CO, PV))
            if not rows:
                continue
            p = np.array(rows); win = (p > 0)
            hit = float(((p > 0)).mean())  # 中獎=賺錢(噴到倍數)
            ae = prem
            print(f"{prem:>6}{K:>6.0f}x{len(p):>6}{hit:>6.0%}"
                  f"{(p[win].mean() if win.any() else 0):>+8.0f}{(p[~win].mean() if (~win).any() else 0):>+8.0f}"
                  f"{p.mean():>+7.1f}{p.mean()/ae:>+7.0%}{p.sum()*PV:>+10,.0f}")
    print("\n (中獎%=噴到倍數的比例; 真實TXO近半年; 元=點×50)")


if __name__ == "__main__":
    main()
