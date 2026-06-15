"""ORB 主流程: 載盤中 1分K -> 跑開盤 ORB -> 績效。

資料檔 data/TXF_1min.csv (欄位 ts,Open,High,Low,Close,Volume) 由明天 Shioaji 額度
重置後抓取寫入。檔案不存在時提示。
"""
from pathlib import Path
import pandas as pd

from orbital_yang.orb import run_orb, summarize_orb, ORBParams

DATA = Path(__file__).parent / "data" / "TXF_1min.csv"
OUT = Path(__file__).parent / "reports" / "orb_result.md"
PV = 200  # 大台 NT$/點


def main():
    if not DATA.exists():
        print(f"⏳ 還沒有盤中資料 {DATA.name} — 等明天 Shioaji 額度重置後抓 1分K 再跑。")
        return
    df = pd.read_csv(DATA)
    trades = run_orb(df, ORBParams(take_profit=50.0))
    p = summarize_orb(trades)
    longs = [t for t in trades if t.direction == "long"]
    shorts = [t for t in trades if t.direction == "short"]
    lines = ["# 軌道鞅 開盤 ORB 回測 (台指期 1分K, +50點停利)", "",
             f"交易日數產生交易 {p.n} 筆 | 多 {len(longs)} / 空 {len(shorts)}", "",
             f"- 勝率: {p.win_rate:.2f}",
             f"- 平均賺 / 賠: {p.avg_win:+.1f} / {p.avg_loss:+.1f} 點",
             f"- 期望: {p.expectancy:+.1f} 點/筆 ({p.expectancy*PV:+,.0f} 元大台)",
             f"- 總損益: {p.total_pnl:+.0f} 點",
             f"- 出場分布: 停利 {p.n_tp} / 停損 {p.n_stop} / 收盤 {p.n_eod}"]
    md = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print(md)


if __name__ == "__main__":
    main()
