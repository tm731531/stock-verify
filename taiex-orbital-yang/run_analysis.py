"""Step 2 壓力分析主流程: 下殺段表現 + 多空拆解 + 區間期望值 + 權益回撤。"""
from pathlib import Path

from orbital_yang.data_loader import load_daily
from orbital_yang.body_levels import detect_levels
from orbital_yang.backtest import BacktestParams, run_backtest, summarize
from orbital_yang.analyze import (
    find_selloffs, trades_in_episodes, split_long_short,
    split_by_down_regime, equity_max_drawdown,
)

DATA = Path(__file__).parent / "data" / "TWII_daily.csv"
OUT = Path(__file__).parent / "reports" / "step2_stress.md"

N, K = 20, 1.5
# 用 Step 2 最佳組合
PARAMS = BacktestParams(breakout_pct=0.001, stop_buffer_pct=0.003, target_mult=2.0, max_hold=20)
POINT_VALUE = 200


def _line(tag, perf):
    return (f"- **{tag}**: {perf.n_trades} 筆, 勝率 {perf.win_rate:.2f}, "
            f"賠率 {perf.payoff:.2f}, 期望 {perf.expectancy:+.1f} 點, "
            f"總損益 {perf.total_pnl:+.0f} 點 ({perf.total_pnl*POINT_VALUE:+,.0f} 元)")


def main():
    df = load_daily(str(DATA))
    c = df["close"].to_numpy(float)
    dates = df["date"].dt.date.to_numpy()
    levels = detect_levels(df, n=N, k=K)
    trades = run_backtest(df, levels, PARAMS)

    lines = ["# Step 2 壓力分析 (target_mult=2.0)", ""]
    lines.append(f"資料 {len(df)} 根, {dates[0]} ~ {dates[-1]}, 交易 {len(trades)} 筆")
    lines.append(f"策略權益最大回撤: {equity_max_drawdown(trades):+.0f} 點 "
                 f"({equity_max_drawdown(trades)*POINT_VALUE:+,.0f} 元)")
    lines.append("")

    lines.append("## 多空拆解")
    longs, shorts = split_long_short(trades)
    lines.append(_line("全部", summarize(trades)))
    lines.append(_line("只看多 (突破壓力)", summarize(longs)))
    lines.append(_line("只看空 (跌破支撐)", summarize(shorts)))
    lines.append("")

    lines.append("## 動能區間拆解 (前20根報酬正/負)")
    up, down = split_by_down_regime(df, trades, lookback=20)
    lines.append(_line("上漲動能進場", summarize(up)))
    lines.append(_line("下跌動能進場", summarize(down)))
    lines.append("")

    lines.append("## 指數下殺段 (峰到谷 >= 5%) 及策略當段表現")
    eps = find_selloffs(c, min_drop=0.05)
    if not eps:
        lines.append("(無符合門檻的下殺段)")
    for (p, tr, drop) in eps:
        seg_trades = trades_in_episodes(trades, [(p, tr, drop)])
        sl, ss = split_long_short(seg_trades)
        perf = summarize(seg_trades)
        lines.append(
            f"- {dates[p]} → {dates[tr]} 跌 {drop*100:.1f}%: "
            f"交易 {perf.n_trades} (多{len(sl)}/空{len(ss)}), "
            f"損益 {perf.total_pnl:+.0f} 點 ({perf.total_pnl*POINT_VALUE:+,.0f} 元)"
        )
    lines.append("")

    md = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print(md)


if __name__ == "__main__":
    main()
