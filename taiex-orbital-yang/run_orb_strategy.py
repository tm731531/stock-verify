"""軌道鞅完整策略: 大小流氓剛轉勢 + 順向 ORB + 真實成本 + 真實選擇權買方。
對照『天天做 ORB』看選擇性有沒有把好日子濃縮出來。"""
from pathlib import Path
import numpy as np
import pandas as pd

from orbital_yang.data_loader import load_daily
from orbital_yang.orb import run_orb, summarize_orb, ORBParams
from orbital_yang.orb_options import apply_futures_cost, option_ohlc, buyer_pnl
from orbital_yang.txo_data import fetch_chain, pick_entry_option
from orbital_yang.regime import fresh_turn_direction

HERE = Path(__file__).parent
DAILY = HERE / "data" / "TXF_daily.csv"
MIN1 = HERE / "data" / "TXF_1min.csv"
OUT = HERE / "reports" / "orb_strategy.md"
SLIP, COMM_F, PV_F = 1.0, 40.0, 200.0
HALF_SPREAD, COMM_O, PV_O = 1.0, 20.0, 50.0
TARGET_PREMIUM = 30.0
TURN_WINDOWS = [20, 40, 60]
DATE_FLOOR = "2025-12-13"


def fut_net(trades):
    if not trades:
        return 0.0, 0
    net = [apply_futures_cost(t.pnl, SLIP, COMM_F, PV_F) for t in trades]
    return sum(net) / len(net), len(trades)


def opt_map(trades, date_floor=DATE_FLOOR):
    rows = []
    for t in trades:
        if date_floor is not None and str(t.date) < date_floor:
            continue
        kind = "call" if t.direction == "long" else "put"
        try:
            ch = fetch_chain(str(t.date))
            opt = pick_entry_option(ch, kind, TARGET_PREMIUM)
            if opt is None:
                continue
            oh = option_ohlc(ch, opt["contract_date"], opt["strike_price"], kind)
            if oh is None or oh["open"] <= 0:
                continue
        except Exception:
            continue
        rows.append({"entry": oh["open"],
                     "base": buyer_pnl(oh["open"], oh["close"], HALF_SPREAD, COMM_O, PV_O),
                     "best": buyer_pnl(oh["open"], oh["high"], HALF_SPREAD, COMM_O, PV_O),
                     "mult": oh["high"] / oh["open"]})
    if not rows:
        return None
    ent = np.array([r["entry"] for r in rows], float)
    base = np.array([r["base"] for r in rows], float)
    best = np.array([r["best"] for r in rows], float)
    mult = np.array([r["mult"] for r in rows], float)
    ae = float(ent.mean())
    return dict(n=len(rows), base_roi=base.mean() / ae, best_roi=best.mean() / ae,
               rate_2x=float((mult >= 2).mean()), rate_3x=float((mult >= 3).mean()))


def orow(tag, g, net, o):
    s = (f"| {tag} | {g.n} | {g.win_rate:.2f} | {net[0]:+.1f} |")
    if o:
        s += f" {o['n']} | {o['base_roi']:+.0%} | {o['best_roi']:+.0%} | {o['rate_2x']:.0%} | {o['rate_3x']:.0%} |"
    else:
        s += " 0 | - | - | - | - |"
    return s


def main():
    daily = load_daily(str(DAILY))
    df1 = pd.read_csv(MIN1)
    allt = run_orb(df1, ORBParams(take_profit=50.0))

    # 全天 baseline: 與轉勢窗無關, 只算一次; 用 DATE_FLOOR 限制請求量
    ga, na = summarize_orb(allt), fut_net(allt)
    oa = opt_map(allt, date_floor=DATE_FLOOR)
    print(f"全部 ORB {len(allt)} 筆")

    rows = [orow("天天做 ORB", ga, na, oa)]
    for window in TURN_WINDOWS:
        allowed = fresh_turn_direction(daily, 20, 60, window)
        filt = [t for t in allt
                if allowed.get(str(t.date)) == (1 if t.direction == "long" else -1)]
        gf, nf = summarize_orb(filt), fut_net(filt)
        # 過濾後筆數少, 抓全部日期真實鏈 (date_floor=None)
        of = opt_map(filt, date_floor=None)
        print(f"剛轉勢順向 窗 {window} 日: {len(filt)} 筆")
        rows.append(orow(f"剛轉勢順向 (窗 {window} 日)", gf, nf, of))

    lines = ["# 軌道鞅完整策略: 大小流氓剛轉勢 + 順向 ORB", "",
             "轉勢窗掃描 [20/40/60] 日; 期貨含成本; 選擇權真實權利金 "
             "(baseline 用 DATE_FLOOR 限請求, 過濾組抓全部日期)。", "",
             "| 版本 | 期貨筆數 | 勝率 | 期貨淨期望 | 買方配對 | base ROI | best ROI | best 2x | best 3x |",
             "|---|---|---|---|---|---|---|---|---|"]
    lines += rows
    lines += ["",
              "> 隨轉勢窗放寬, 看勝率/淨期望/2x 率是否撐得住, 還是 9 筆只是雜訊。"]
    md = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print("\n" + md)


if __name__ == "__main__":
    main()
