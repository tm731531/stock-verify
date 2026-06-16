"""ORB + 真實成本 + 真實選擇權買方對映 (近半年, 控資料量)。"""
from pathlib import Path
import pandas as pd

from orbital_yang.orb import run_orb, summarize_orb, ORBParams
from orbital_yang.orb_options import (
    apply_futures_cost, option_ohlc, buyer_pnl, summarize_buyer,
)
from orbital_yang.txo_data import fetch_chain, pick_entry_option

DATA = Path(__file__).parent / "data" / "TXF_1min.csv"
OUT = Path(__file__).parent / "reports" / "orb_options.md"
# 期貨成本
SLIP, COMM_F, PV_F = 1.0, 40.0, 200.0
# 選擇權成本
HALF_SPREAD, COMM_O, PV_O = 1.0, 20.0, 50.0
TARGET_PREMIUM = 30.0
DATE_FLOOR = "2025-12-13"   # 近半年 ORB 交易做選擇權對映 (控 FinMind 請求量)


def main():
    if not DATA.exists():
        print("無 1分K 資料"); return
    df = pd.read_csv(DATA)
    trades = run_orb(df, ORBParams(take_profit=50.0))
    gross = summarize_orb(trades)
    # 期貨淨期望
    net = [apply_futures_cost(t.pnl, SLIP, COMM_F, PV_F) for t in trades]
    net_exp = sum(net) / len(net) if net else 0.0

    # 選擇權買方對映 (近半年)
    sub = [t for t in trades if str(t.date) >= DATE_FLOOR]
    print(f"ORB {len(trades)} 筆; 近半年 {len(sub)} 筆做真實選擇權對映...")
    rows, skipped = [], 0
    for t in sub:
        kind = "call" if t.direction == "long" else "put"
        ds = str(t.date)
        try:
            chain = fetch_chain(ds)
            opt = pick_entry_option(chain, kind, TARGET_PREMIUM)
            if opt is None:
                skipped += 1; continue
            oh = option_ohlc(chain, opt["contract_date"], opt["strike_price"], kind)
            if oh is None or oh["open"] <= 0:
                skipped += 1; continue
        except Exception as e:
            print(f"  {ds} 失敗 {e}"); skipped += 1; continue
        base = buyer_pnl(oh["open"], oh["close"], HALF_SPREAD, COMM_O, PV_O)
        best = buyer_pnl(oh["open"], oh["high"], HALF_SPREAD, COMM_O, PV_O)
        rows.append({"entry": oh["open"], "base_pnl": base, "best_pnl": best})
    b = summarize_buyer(rows)

    lines = ["# ORB + 真實成本 + 真實選擇權買方", "",
             f"台指期 ORB {len(trades)} 筆 (1分K {len(df)} 根)。", "",
             "## 期貨 (含成本)",
             f"- 毛期望: {gross.expectancy:+.1f} 點/筆",
             f"- 淨期望(滑價{SLIP}+手續費{COMM_F:.0f}/邊): {net_exp:+.1f} 點/筆 ({net_exp*PV_F:+,.0f} 元大台)",
             "",
             "## 選擇權買方 (真實權利金, 近半年配對 {})".format(b.n),
             f"- 進場平均權利金: {b.avg_entry_premium:.1f} 點",
             f"- base(開→收) 期望: {b.base_expectancy:+.1f} 點, ROI {b.base_roi:+.0%}, 勝率 {b.base_winrate:.0%}",
             f"- best(開→當日高/賣在噴點) 期望: {b.best_expectancy:+.1f} 點, ROI {b.best_roi:+.0%}",
             "",
             "> 真實買方介於 base 與 best 之間(盤中實際在 TP 賣, 會比 base 收盤好、比 best 高點差)。"]
    md = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print("\n" + md)


if __name__ == "__main__":
    main()
