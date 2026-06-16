"""卡片回測: 完全照 LINE 卡的買賣規則, 逐筆列出『哪天買C/P、幾點買、幾點賣、賺賠』。

規則(=卡片): 順大小流氓方向; 站上8:46高買CALL(或破低買PUT); 賣在 +2滿(50點);
放生=基準另一邊。期貨含成本; 買方用真實TXO權利金(近半年逐筆)。
"""
from pathlib import Path
import numpy as np
import pandas as pd

from orbital_yang.data_loader import load_daily
from orbital_yang.regime import alignment_sign
from orbital_yang.orb import run_orb, ORBParams
from orbital_yang.orb_options import apply_futures_cost, option_ohlc, buyer_pnl
from orbital_yang.txo_data import fetch_chain, pick_entry_option

HERE = Path(__file__).parent
PV_F, PV_O = 200.0, 50.0
HALF_SPREAD, COMM_O = 1.0, 20.0
DATE_FLOOR = "2025-12-13"


def main():
    daily = load_daily(str(HERE / "data" / "TXF_daily.csv"))
    m = pd.read_csv(HERE / "data" / "TXF_1min.csv")
    sign = alignment_sign(daily, 20, 60)
    dd = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d").to_numpy()
    allowed = {dd[i]: int(sign[i]) for i in range(len(dd)) if sign[i] != 0}
    trades = [t for t in run_orb(m, ORBParams(take_profit=50.0))
              if allowed.get(str(t.date)) == (1 if t.direction == "long" else -1)]

    net = np.array([apply_futures_cost(t.pnl, 1.0, 40.0, PV_F) for t in trades])
    wins = net > 0
    eq = np.concatenate([[0.0], np.cumsum(net)])
    maxdd = float((eq - np.maximum.accumulate(eq)).min())

    print("=" * 56)
    print(" 卡片回測 — 順格局 ORB (買點/賣點 = LINE卡)")
    print("=" * 56)
    print(f" 全年: {len(trades)} 筆 (全多單, 因這年是多頭格局)")
    print(f" 勝率 {wins.mean():.0%} | 淨期望 {net.mean():+.1f}點/筆 | 全年 {net.sum():+.0f}點 ({net.sum()*PV_F:+,.0f}元)")
    print(f" 最大回撤 {maxdd:+.0f}點 ({maxdd*PV_F:+,.0f}元) | 最長連虧 ", end="")
    cur = mx = 0
    for x in net:
        cur = cur + 1 if x <= 0 else 0; mx = max(mx, cur)
    print(f"{mx}筆")

    # 逐筆(近半年, 帶真實選擇權)
    print("\n 逐筆(近半年, 真實選擇權買方):")
    print(f" {'日期':<11}{'買':<5}{'買點':>7}{'賣/出場':>9}{'期貨':>6}  選擇權買→賣(倍數)")
    op_pnls = []
    for t in trades:
        if str(t.date) < DATE_FLOOR:
            continue
        kind = "call" if t.direction == "long" else "put"
        buy_pt = t.ref_high if t.direction == "long" else t.ref_low
        op_str = ""
        try:
            ch = fetch_chain(str(t.date))
            opt = pick_entry_option(ch, kind, 30.0)
            oh = option_ohlc(ch, opt["contract_date"], opt["strike_price"], kind) if opt else None
            if oh and oh["open"] > 0:
                ex = oh["high"] if t.reason == "tp" else (oh["low"] if t.reason == "stop" else oh["close"])
                opnl = buyer_pnl(oh["open"], ex, HALF_SPREAD, COMM_O, PV_O)
                op_pnls.append(opnl)
                op_str = f"{oh['open']:.0f}→{ex:.0f} ({ex/oh['open']:.1f}x) {opnl:+.0f}點"
        except Exception:
            pass
        cp = "CALL" if t.direction == "long" else "PUT"
        print(f" {str(t.date):<11}{cp:<5}{buy_pt:>7.0f}{t.exit:>9.0f}{t.pnl:>+6.0f}  {op_str}")

    if op_pnls:
        op = np.array(op_pnls)
        print(f"\n 選擇權買方(近半年 {len(op)} 筆): 勝率 {(op>0).mean():.0%} | "
              f"期望 {op.mean():+.1f}點/筆 ({op.mean()*PV_O:+,.0f}元) | ROI {op.mean()/30:+.0%} | "
              f"總 {op.sum()*PV_O:+,.0f}元")
        print(" (賣=贏賣當日高/輸賣當日低; 買方虧損被權利金封頂)")


if __name__ == "__main__":
    main()
