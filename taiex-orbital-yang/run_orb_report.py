"""順格局 ORB 全年回測『體質報告』: 權益曲線/最大回撤/連虧/月損益/最佳最差。

期貨含成本(滑價1+手續費40/邊)。格局用同日 MA20/MA60(日對日變動極小, lookahead 可忽略)。
"""
from pathlib import Path
import numpy as np
import pandas as pd

from orbital_yang.data_loader import load_daily
from orbital_yang.regime import alignment_sign
from orbital_yang.orb import run_orb, ORBParams
from orbital_yang.orb_options import apply_futures_cost

HERE = Path(__file__).parent
PV = 200.0


def main():
    daily = load_daily(str(HERE / "data" / "TXF_daily.csv"))
    m = pd.read_csv(HERE / "data" / "TXF_1min.csv")
    sign = alignment_sign(daily, 20, 60)
    dd = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d").to_numpy()
    allowed = {dd[i]: int(sign[i]) for i in range(len(dd)) if sign[i] != 0}

    trades = run_orb(m, ORBParams(take_profit=50.0))
    filt = [t for t in trades
            if allowed.get(str(t.date)) == (1 if t.direction == "long" else -1)]
    net = np.array([apply_futures_cost(t.pnl, 1.0, 40.0, PV) for t in filt], float)
    dates = pd.to_datetime([str(t.date) for t in filt])

    n = len(net)
    wins = net > 0
    equity = np.concatenate([[0.0], np.cumsum(net)])
    peak = np.maximum.accumulate(equity)
    maxdd = float((equity - peak).min())

    # 連虧
    cur = mx = 0
    for x in net:
        cur = cur + 1 if x <= 0 else 0
        mx = max(mx, cur)

    # 月損益
    dfm = pd.DataFrame({"ym": dates.strftime("%Y-%m"), "net": net})
    monthly = dfm.groupby("ym")["net"].agg(["count", "sum"])

    L = ["# 順格局 ORB 體質報告 (台指期, 全年, 含成本)", "",
         f"- 交易數: {n}  | 多 {sum(t.direction=='long' for t in filt)} / 空 {sum(t.direction=='short' for t in filt)}",
         f"- 勝率: {wins.mean():.1%}",
         f"- 淨期望: {net.mean():+.1f} 點/筆 ({net.mean()*PV:+,.0f} 元)",
         f"- 總淨利: {net.sum():+.0f} 點 ({net.sum()*PV:+,.0f} 元大台一口)",
         f"- 平均賺 / 賠: {net[wins].mean():+.1f} / {net[~wins].mean():+.1f} 點",
         f"- 最佳 / 最差單筆: {net.max():+.0f} / {net.min():+.0f} 點",
         f"- **最大回撤: {maxdd:+.0f} 點 ({maxdd*PV:+,.0f} 元)**",
         f"- 最長連虧: {mx} 筆",
         f"- 出場: 停利 {sum(t.reason=='tp' for t in filt)} / 停損 {sum(t.reason=='stop' for t in filt)} / 收盤 {sum(t.reason=='eod' for t in filt)}",
         "", "## 月損益 (點)", "", "| 月份 | 筆數 | 淨損益 |", "|---|---|---|"]
    for ym, r in monthly.iterrows():
        L.append(f"| {ym} | {int(r['count'])} | {r['sum']:+.0f} |")
    md = "\n".join(L) + "\n"
    out = HERE / "reports" / "orb_report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(md)
    print(md)


if __name__ == "__main__":
    main()
