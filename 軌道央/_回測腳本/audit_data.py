#!/usr/bin/env python3
# 資料健檢:在信任任何回測/統計前,先確認 TXF_1min.csv 本身沒問題。
import pandas as pd, numpy as np, datetime as dt

P="/home/tom/stock-verify/taiex-orbital-yang/data/TXF_1min.csv"
df = pd.read_csv(P, parse_dates=["ts"])
print("="*70)
print("1) 基本:", df.shape, "| 欄位:", list(df.columns))
print("   dtypes:", dict(df.dtypes.astype(str)))
print("   期間:", df["ts"].min(), "→", df["ts"].max())

# 2) 排序/重複
print("\n2) 時序健康")
print("   已排序(ts遞增)?", df["ts"].is_monotonic_increasing)
dup = df["ts"].duplicated().sum()
print("   重複timestamp數:", dup)

# 3) 價格/量 合法性
print("\n3) 欄位合法性")
for col in ["Open","High","Low","Close","Volume"]:
    s=df[col]
    print(f"   {col}: NaN={s.isna().sum()} 非正(<=0)={int((s<=0).sum())} min={s.min()} max={s.max()}")
bad_hl = (df["High"]<df["Low"]).sum()
bad_h  = (df["High"]<df[["Open","Close"]].max(axis=1)).sum()
bad_l  = (df["Low"]>df[["Open","Close"]].min(axis=1)).sum()
print(f"   OHLC違規: High<Low={bad_hl}  High<max(O,C)={bad_h}  Low>min(O,C)={bad_l}")

# 4) 交易時段分布(看是否日盤+夜盤、每日bar數)
df["date"]=df["ts"].dt.date; df["t"]=df["ts"].dt.time
day = df[(df["t"]>=dt.time(8,45))&(df["t"]<=dt.time(13,45))]
print("\n4) 時段")
print("   全資料每分鐘時間範圍:", df["t"].min(), "→", df["t"].max())
perday = day.groupby("date").size()
print(f"   日盤(08:45-13:45)每日bar數: 中位={perday.median():.0f} min={perday.min()} max={perday.max()} (理論~301)")
print(f"   交易日數: {day['date'].nunique()}")
shortdays = perday[perday<295]
print(f"   日盤<295根的日子數(可能缺資料): {len(shortdays)}", "" if len(shortdays)==0 else f"例:{list(shortdays.index[:3])}")

# 5) 連續分鐘的跳動(同一日盤內,相鄰bar的%變動)→ 抓壞tick
day = day.sort_values("ts").copy()
day["ret"] = day.groupby("date")["Close"].pct_change()  # 只在同日內算
print("\n5) 日內相鄰分鐘跳動(同日)")
print(f"   |ret| 分位: P99={day['ret'].abs().quantile(.99)*100:.3f}%  P999={day['ret'].abs().quantile(.999)*100:.3f}%  max={day['ret'].abs().max()*100:.3f}%")
big_jump = day[day["ret"].abs()>0.01]   # >1% 一分鐘跳動 = 可疑
print(f"   單分鐘跳動>1%的根數: {len(big_jump)}", "" if len(big_jump)==0 else "(列前5)")
for _,r in big_jump.head(5).iterrows():
    print(f"      {r['ts']}  ret={r['ret']*100:+.2f}%  Close={r['Close']:.0f}")

# 6) 隔夜跳空(看是否有contract roll造成的人為斷裂)
daily = day.groupby("date").agg(open=("Open","first"), close=("Close","last")).reset_index()
daily["gap"] = daily["open"]/daily["close"].shift(1)-1
print("\n6) 隔夜跳空(前日收→當日開)")
print(f"   |gap| 分位: P95={daily['gap'].abs().quantile(.95)*100:.2f}%  P99={daily['gap'].abs().quantile(.99)*100:.2f}%  max={daily['gap'].abs().max()*100:.2f}%")
biggap = daily[daily["gap"].abs()>0.03]  # >3% 隔夜 = 可能roll/異常
print(f"   隔夜跳空>3%的日子: {len(biggap)}", "(換月roll嫌疑,列出)" if len(biggap) else "")
for _,r in biggap.iterrows():
    print(f"      {r['date']}  gap={r['gap']*100:+.2f}%  前收→今開")

# 7) +118%是漸進還是跳躍(逐月收盤)
mc = day.groupby(day["ts"].dt.to_period("M"))["Close"].last()
print("\n7) 逐月收盤(看漲勢是否平滑、有無人為斷點)")
prev=None
for ym,px in mc.items():
    chg = f"{(px/prev-1)*100:+.1f}%" if prev else "  —"
    print(f"   {ym}: {px:8.0f}  月變動 {chg}")
    prev=px
print("="*70)
print("判讀準則:若隔夜跳空有多個>3%且集中在每月特定日 → 是未調整的換月roll斷裂,會污染回測(假獲利/假波動)。")
