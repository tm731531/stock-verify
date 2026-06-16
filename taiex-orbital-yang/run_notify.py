"""產生『軌道鞅當沖行動卡』(白話: 買啥/看哪點/賣哪點) 並推播 LINE。

用法:
  python run_notify.py                 # dry, 自動挑最後有日盤資料的日子
  python run_notify.py 2026-06-16 --send
"""
import sys
from pathlib import Path
import pandas as pd

from orbital_yang.data_loader import load_daily
from orbital_yang.bot import trade_card
from orbital_yang.orb import ORBParams
from orbital_yang.notify import send_line

HERE = Path(__file__).parent
MAN = 25  # 1滿=25點


def fmt(c, cur_price: float) -> str:
    if c.regime == 0:
        return f"📊 軌道鞅當沖｜{c.date}\n今天無格局 → 不做"
    if c.regime == 1:
        opt, trig, bust = "CALL", c.ref_high, c.ref_low
        t2, t4 = trig + 2 * MAN, trig + 4 * MAN
        tw, bw = "站上", "跌破"
        side = "多"
    else:
        opt, trig, bust = "PUT", c.ref_low, c.ref_high
        t2, t4 = trig - 2 * MAN, trig - 4 * MAN
        tw, bw = "跌破", "站上"
        side = "空"

    L = [f"📊 軌道鞅當沖｜{c.date}", "",
         f"① 買 {opt}（今天{side}格局，只買 {opt}）", "",
         f"② 進場：台指期【{tw} {trig:.0f}】就買一口 ~20-30 的 {opt}（價外）"]
    if c.has_trade:
        L.append(f"　　✅ 已{tw} {trig:.0f}（{c.entry_time}）→ 可以買了")
    else:
        reached = (cur_price >= trig) if c.regime == 1 else (cur_price <= trig)
        if reached:
            L.append(f"　　台指期現在 {cur_price:.0f}，已{tw} {trig:.0f} → 可以買")
        else:
            L.append(f"　　台指期現在 {cur_price:.0f}，還沒{tw} {trig:.0f} → 先別買，等它")
    L += ["",
          f"③ 賣點：買了之後，台指期到這就賣掉 {opt}：",
          f"　　🎯 {t2:.0f}（先賣一半/全賣）",
          f"　　🎯 {t4:.0f}（想貪到這）",
          "",
          f"④ 放生：台指期【{bw} {bust:.0f}】→ 這單不管，放到歸零（賠掉那 20-30 權利金）",
          "",
          f"※ 沒{tw} {trig:.0f} = 今天空手不買。一天最多1-2次，當天一定平倉。"]
    return "\n".join(L)


def main():
    args = [a for a in sys.argv[1:] if a != "--send"]
    dry = "--send" not in sys.argv
    daily = load_daily(str(HERE / "data" / "TXF_daily.csv"))
    m = pd.read_csv(HERE / "data" / "TXF_1min.csv")
    m["ts"] = pd.to_datetime(m["ts"])
    m["d"] = m["ts"].dt.strftime("%Y-%m-%d")

    date_str = args[0] if args else None
    if not date_str:
        for d in sorted(m["d"].unique(), reverse=True):
            tt = m[m["d"] == d]["ts"].dt.strftime("%H:%M")
            if ((tt >= "08:45") & (tt <= "13:45")).any():
                date_str = d
                break

    # 當日日盤最後一根收盤 = 目前價
    day = m[m["d"] == date_str]
    tt = day["ts"].dt.strftime("%H:%M")
    sess = day[(tt >= "08:45") & (tt <= "13:45")].sort_values("ts")
    cur = float(sess.iloc[-1]["Close"]) if len(sess) else 0.0

    c = trade_card(daily, m, date_str, ORBParams(50.0))
    send_line(fmt(c, cur), dry=dry)


if __name__ == "__main__":
    main()
