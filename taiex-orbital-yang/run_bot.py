"""順格局 ORB 交易卡 — 重播某日 (預設最後一日), 印出今日操作卡 + 建議選擇權。"""
import sys
from pathlib import Path
import pandas as pd

from orbital_yang.data_loader import load_daily
from orbital_yang.bot import trade_card
from orbital_yang.orb import ORBParams
from orbital_yang.txo_data import fetch_chain, pick_entry_option

HERE = Path(__file__).parent
DAILY = HERE / "data" / "TXF_daily.csv"
MIN1 = HERE / "data" / "TXF_1min.csv"


def main():
    daily = load_daily(str(DAILY))
    m = pd.read_csv(MIN1)
    m["d"] = pd.to_datetime(m["ts"]).dt.strftime("%Y-%m-%d")
    date_str = sys.argv[1] if len(sys.argv) > 1 else sorted(m["d"].unique())[-1]

    c = trade_card(daily, m, date_str, ORBParams(take_profit=50.0))
    reg = {1: "多", -1: "空", 0: "無格局"}[c.regime]
    print("=" * 44)
    print(f" 軌道鞅 順格局 ORB 交易卡 | {c.date}")
    print("=" * 44)
    print(f" 大小流氓格局: {reg} (依前一交易日 MA20/MA60)")
    if c.regime == 0:
        print(" 無格局, 今日不做。"); return
    print(f" 今日只做: {'多方突破' if c.regime==1 else '空方跌破'}")
    print(f" 8:46 基準: 高 {c.ref_high:.0f} / 低 {c.ref_low:.0f}")
    if not c.has_trade:
        print(" → 今日無順格局訊號 (沒有順向收破基準)。"); return
    kind = "call" if c.direction == "long" else "put"
    print(f" 進場: {c.entry_time} 收破基準 → {'做多' if c.direction=='long' else '做空'} @ {c.entry:.0f}")
    print(f" 停利: {c.tp:.0f} (+50點) | 停損: {c.stop:.0f} (基準{'低' if c.direction=='long' else '高'})")
    print(f" 結果: {c.exit_time} {c.reason} @ {c.exit:.0f} → {c.pnl:+.0f} 點 ({c.pnl*200:+,.0f} 元大台)")
    # 建議買哪檔 option (真實鏈)
    try:
        opt = pick_entry_option(fetch_chain(c.date), kind, 30.0)
        if opt:
            print(f" 建議買方: {opt['contract_date']} {opt['strike_price']:.0f} {kind.upper()} ~{opt['close']:.0f} 點")
    except Exception:
        pass
    print("=" * 44)


if __name__ == "__main__":
    main()
