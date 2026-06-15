"""Step 2 主流程: 大實體K關卡(他的大K定義 k=1.5) -> 過破方向性回測 -> 期望值。

掃 target 倍數與停損緩衝; 報告勝率/賠率/期望值(點)。
大台(TXF) 1 點 = NT$200; 期望值點數 × 200 = 每筆 NT$。
"""
from pathlib import Path

from orbital_yang.data_loader import load_daily
from orbital_yang.body_levels import detect_levels
from orbital_yang.backtest import BacktestParams, run_backtest, summarize

DATA = Path(__file__).parent / "data" / "TWII_daily.csv"
OUT = Path(__file__).parent / "reports" / "step2_result.md"

N, K = 20, 1.5            # 他的大K定義: 實體 > 1.5x 基準
TARGET_MULTS = [0.5, 1.0, 1.5, 2.0]
STOP_BUFFERS = [0.003, 0.005]
MAX_HOLD = 20
POINT_VALUE = 200        # 大台 NT$/點


def main():
    df = load_daily(str(DATA))
    levels = detect_levels(df, n=N, k=K)
    print(f"資料: {len(df)} 根, {df['date'].min().date()} ~ {df['date'].max().date()}, 關卡 {len(levels)} 個")

    header = "| target_mult | stop_buf | 交易數 | 勝率 | 賺賠比 | 期望值(點) | 每筆NT$ | 總損益(點) |"
    sep = "|---|---|---|---|---|---|---|---|"
    lines = ["# 軌道鞅三法方向性回測 — Step 2", "",
             f"資料 {len(df)} 根, 大K定義 N={N} k={K}, max_hold={MAX_HOLD}, 大台 {POINT_VALUE}元/點", "",
             header, sep]
    for tm in TARGET_MULTS:
        for sb in STOP_BUFFERS:
            params = BacktestParams(breakout_pct=0.001, stop_buffer_pct=sb,
                                    target_mult=tm, max_hold=MAX_HOLD)
            trades = run_backtest(df, levels, params)
            p = summarize(trades)
            lines.append(
                f"| {tm} | {sb} | {p.n_trades} | {p.win_rate:.2f} | {p.payoff:.2f} "
                f"| {p.expectancy:+.1f} | {p.expectancy * POINT_VALUE:+,.0f} | {p.total_pnl:+.0f} |"
            )
            print(f"tm={tm} sb={sb}: 交易{p.n_trades} 勝率{p.win_rate:.2f} "
                  f"賠率{p.payoff:.2f} 期望{p.expectancy:+.1f}點 ({p.expectancy*POINT_VALUE:+.0f}元)")

    md = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print(f"\n報告寫入 {OUT}")
    print(md)


if __name__ == "__main__":
    main()
