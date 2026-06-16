"""產生『軌道鞅順格局 ORB 交易卡』並推播 LINE。

用法:
  python run_notify.py            # dry-run, 自動挑最後一個有訊號的日子, 印出不發送
  python run_notify.py --send     # 真的發 LINE
  python run_notify.py 2026-06-11 --send   # 指定日期
"""
import sys
from pathlib import Path
import pandas as pd

from orbital_yang.data_loader import load_daily
from orbital_yang.bot import trade_card
from orbital_yang.orb import ORBParams
from orbital_yang.notify import send_line

HERE = Path(__file__).parent


def fmt(c) -> str:
    reg = {1: "多", -1: "空", 0: "無"}[c.regime]
    if c.regime == 0:
        return f"📊 軌道鞅順格局ORB｜{c.date}\n格局：無 → 今日不做"
    side = "多" if c.regime == 1 else "空"
    trig = "1分K收破基準高 → 買 CALL" if c.regime == 1 else "1分K收破基準低 → 買 PUT"
    L = [f"📊 軌道鞅順格局ORB｜{c.date}",
         f"格局：{reg}（月線>季線，只做{side}）",
         f"8:46基準：高{c.ref_high:.0f} / 低{c.ref_low:.0f}",
         f"進場：{trig}"]
    if c.has_trade:
        sgn = 1 if c.direction == "long" else -1
        e = c.entry
        L += [f"　實際 {c.entry_time} @ {e:.0f}",
              "🎯 賣點目標（噴到就賣）：",
              f"　+2滿 {e + sgn * 50:.0f}（基本停利）",
              f"　+4滿 {e + sgn * 100:.0f}",
              f"🛑 停損 {c.stop:.0f}（買方=賠掉權利金）",
              f"📈 回測結果 {c.exit_time} {c.reason} {c.pnl:+.0f}點"]
    else:
        L.append("→ 今日無順格局訊號（沒順向收破基準）")
    L.append("💡 買~30點OTM(CALL/PUT)，噴到目標就賣，當日平倉，一天1-2筆")
    return "\n".join(L)


def main():
    args = [a for a in sys.argv[1:] if a != "--send"]
    dry = "--send" not in sys.argv
    daily = load_daily(str(HERE / "data" / "TXF_daily.csv"))
    m = pd.read_csv(HERE / "data" / "TXF_1min.csv")
    m["d"] = pd.to_datetime(m["ts"]).dt.strftime("%Y-%m-%d")

    date_str = args[0] if args else None
    if not date_str:
        for d in sorted(m["d"].unique(), reverse=True):
            if trade_card(daily, m, d, ORBParams(50.0)).has_trade:
                date_str = d
                break
    c = trade_card(daily, m, date_str, ORBParams(50.0))
    send_line(fmt(c), dry=dry)


if __name__ == "__main__":
    main()
