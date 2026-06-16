"""盤前『昨日關卡計畫卡』: 用昨天以前的固定關卡(盤前畫好), 順格局, 推 LINE。

關卡全部來自昨日日盤 OHLC + 夜盤高低 → 盤前就知道, 不依賴今天的盤中K。
用法: python run_levelcard.py 2026-06-16 [--send]
"""
import sys
from pathlib import Path
import pandas as pd

from orbital_yang.data_loader import load_daily
from orbital_yang.regime import alignment_sign
from orbital_yang.notify import send_line

HERE = Path(__file__).parent
MAN = 25


def prior_regime(daily, date_str):
    s = alignment_sign(daily, 20, 60)
    d = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d").to_numpy()
    before = [i for i in range(len(d)) if d[i] < date_str]
    return int(s[before[-1]]) if before else 0


def prior_levels(m, date_str):
    """昨日日盤 OHLC + 夜盤高低 (盤前可知)。"""
    m = m.copy()
    m["ts"] = pd.to_datetime(m["ts"]); m["d"] = m["ts"].dt.strftime("%Y-%m-%d"); m["t"] = m["ts"].dt.strftime("%H:%M")
    days = [d for d in sorted(m["d"].unique()) if d < date_str and
            ((m["d"] == d) & (m["t"] >= "08:45") & (m["t"] <= "13:45")).sum() > 10]
    if not days:
        return None
    pv = days[-1]
    g = m[(m["d"] == pv) & (m["t"] >= "08:45") & (m["t"] <= "13:45")].sort_values("ts")
    night = m[(m["ts"] > pd.Timestamp(pv + " 13:45")) & (m["ts"] < pd.Timestamp(date_str + " 08:45"))]
    lv = {"昨高": g["High"].max(), "昨開": float(g.iloc[0]["Open"]), "昨收": float(g.iloc[-1]["Close"]),
          "昨低": g["Low"].min()}
    if len(night):
        lv["夜高"] = night["High"].max(); lv["夜低"] = night["Low"].min()
    return pv, lv


def fmt(date_str, regime, pv, lv):
    if regime == 0:
        return f"📊 軌道鞅當沖｜{date_str}\n今天無格局 → 不做"
    side, opt = ("多", "CALL") if regime == 1 else ("空", "PUT")
    items = sorted(lv.items(), key=lambda kv: kv[1], reverse=True)
    L = [f"📊 軌道鞅當沖｜{date_str}（盤前計畫）", "",
         f"格局：{side} → 今天只做{side}（買 {opt}）", "",
         f"【昨日關卡｜盤前畫好的線（{pv}）】"]
    for k, v in items:
        L.append(f"　{k} {v:.0f}")
    if regime == 1:
        L += ["", "【怎麼做】",
              f"　台指期回測到【下方支撐關卡】站穩不破（等打腳確認，別一碰就買）→ 買 {opt}",
              f"　🎯 賣點：噴到【上一條關卡】或 +2~4滿（{2*MAN}~{4*MAN}點）就賣",
              "　🛑 放生：直接摜破那條支撐關卡 → 放到歸零（賠權利金）"]
    else:
        L += ["", "【怎麼做】",
              f"　台指期反彈到【上方壓力關卡】壓不過（等打腳確認）→ 買 {opt}",
              f"　🎯 賣點：殺到【下一條關卡】或 +2~4滿就賣",
              "　🛑 放生：直接站上那條壓力關卡 → 放到歸零"]
    L += ["", "※ 順格局方向才做；沒到關卡/沒確認 → 不開槍。一天1-2次，當天平倉。"]
    return "\n".join(L)


def main():
    args = [a for a in sys.argv[1:] if a != "--send"]
    dry = "--send" not in sys.argv
    date_str = args[0] if args else None
    daily = load_daily(str(HERE / "data" / "TXF_daily.csv"))
    m = pd.read_csv(HERE / "data" / "TXF_1min.csv")
    if not date_str:
        mm = m.copy(); mm["ts"] = pd.to_datetime(mm["ts"])
        date_str = mm["ts"].dt.strftime("%Y-%m-%d").max()
    regime = prior_regime(daily, date_str)
    pl = prior_levels(m, date_str)
    if pl is None:
        print("無昨日關卡資料"); return
    pv, lv = pl
    send_line(fmt(date_str, regime, pv, lv), dry=dry)


if __name__ == "__main__":
    main()
