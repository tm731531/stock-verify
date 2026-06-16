"""掛單在前盤關卡(順大小流氓)回測 — 全年體質 + 月損益 + 樣本交易卡。"""
from pathlib import Path
import pandas as pd

from orbital_yang.data_loader import load_daily
from orbital_yang.levels_lo import run_lo, summarize_lo, LOParams

HERE = Path(__file__).parent
PV = 200.0


def main():
    daily = load_daily(str(HERE / "data" / "TXF_daily.csv"))
    m = pd.read_csv(HERE / "data" / "TXF_1min.csv")
    trades = run_lo(daily, m, LOParams(take_profit=50.0, stop=50.0))
    s = summarize_lo(trades)
    if not s:
        print("無交易"); return
    nlong = sum(t.direction == "long" for t in trades)
    L = ["# 掛單在前盤關卡 (順大小流氓) 回測 — 含成本", "",
         f"- 交易數: {s['n']} (多 {nlong}/空 {s['n']-nlong})",
         f"- 勝率: {s['win_rate']:.1%}",
         f"- 淨期望: {s['net_exp']:+.1f} 點/筆 ({s['net_exp']*PV:+,.0f} 元)",
         f"- 總淨利: {s['total']:+.0f} 點 ({s['total']*PV:+,.0f} 元大台)",
         f"- 平均賺/賠: {s['avg_win']:+.1f}/{s['avg_loss']:+.1f}",
         f"- 最大回撤: {s['maxdd']:+.0f} 點 ({s['maxdd']*PV:+,.0f} 元)",
         f"- 出場: 停利 {s['n_tp']}/停損 {s['n_stop']}/收盤 {s['n_eod']}"]
    # 月損益
    dfm = pd.DataFrame({"ym": [t.date[:7] for t in trades], "net": s["net"]})
    L += ["", "## 月損益(點)", "| 月 | 筆 | 淨 |", "|---|---|---|"]
    for ym, gg in dfm.groupby("ym"):
        L.append(f"| {ym} | {len(gg)} | {gg['net'].sum():+.0f} |")
    # 樣本交易卡 (最後 5 筆)
    L += ["", "## 最後 5 筆樣本"]
    for t in trades[-5:]:
        L.append(f"- {t.date} {t.direction} 掛 {t.line_label}{t.line:.0f} → {t.entry_time}成交 "
                 f"→ {t.exit_time} {t.reason} {t.pnl:+.0f}點")
    md = "\n".join(L) + "\n"
    out = HERE / "reports" / "lo_backtest.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(md)
    print(md)


if __name__ == "__main__":
    main()
