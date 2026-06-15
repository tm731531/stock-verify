"""Step 2B+成本: 把買賣價差+手續費加上去, 看買方正期望扣完還剩不剩。

成本設定(保守): 半價差 1 點 (來回 2 點), 手續費 NT$20/邊。
"""
from pathlib import Path

from orbital_yang.data_loader import load_daily
from orbital_yang.body_levels import detect_levels
from orbital_yang.backtest import BacktestParams, run_backtest
from orbital_yang.option_buyer import OptionParams, simulate_option_trades, summarize_options

DATA = Path(__file__).parent / "data" / "TWII_daily.csv"
OUT = Path(__file__).parent / "reports" / "step2b_costs.md"

N, K = 20, 1.5
SIG = BacktestParams(breakout_pct=0.001, stop_buffer_pct=0.003, target_mult=2.0, max_hold=20)
IV_GRID = [0.15, 0.20, 0.25]
EXPIRY_GRID = [3, 5]
TARGET_PREMIUM = 30.0
PV = 50.0
HALF_SPREAD = 1.0      # 來回價差 2 點
COMMISSION = 20.0      # NT$/邊


def main():
    df = load_daily(str(DATA))
    levels = detect_levels(df, n=N, k=K)
    trades = run_backtest(df, levels, SIG)
    print(f"資料 {len(df)} 根, {len(trades)} 筆訊號 (tm=2.0); 成本: 半價差 {HALF_SPREAD} 點, 手續費 {COMMISSION:.0f}/邊")

    header = "| IV | 到期 | 毛期望(點) | 淨期望(點) | 成本吃掉 | 淨ROI | 淨每筆NT$ | 撐過成本? |"
    sep = "|" + "---|" * 8
    lines = ["# Step 2B + 真實成本 (買賣價差 + 手續費)", "",
             f"資料 {len(df)} 根, {len(trades)} 筆訊號, 半價差 {HALF_SPREAD} 點(來回2), 手續費 NT${COMMISSION:.0f}/邊。",
             "> 仍是 BS 模型估的權利金, 但已扣交易成本。", "",
             header, sep]
    for iv in IV_GRID:
        for ed in EXPIRY_GRID:
            gross = summarize_options(simulate_option_trades(
                df, trades, OptionParams(iv, ed, TARGET_PREMIUM, PV)))
            net = summarize_options(simulate_option_trades(
                df, trades, OptionParams(iv, ed, TARGET_PREMIUM, PV,
                                         half_spread_pts=HALF_SPREAD, commission_ntd=COMMISSION)))
            survive = "✅ 是" if net.expectancy > 0 else "❌ 否"
            lines.append(
                f"| {iv:.0%} | {ed} | {gross.expectancy:+.1f} | {net.expectancy:+.1f} "
                f"| {gross.expectancy-net.expectancy:.1f} | {net.roi:+.0%} "
                f"| {net.expectancy*PV:+,.0f} | {survive} |"
            )
            print(f"IV={iv:.0%} 到期{ed}: 毛{gross.expectancy:+.1f} -> 淨{net.expectancy:+.1f} 點 "
                  f"(吃{gross.expectancy-net.expectancy:.1f}) ROI{net.roi:+.0%} {survive}")

    md = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print(f"\n報告寫入 {OUT}")
    print(md)


if __name__ == "__main__":
    main()
