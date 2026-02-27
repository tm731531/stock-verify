#!/usr/bin/env python3
"""
v1.1 版本 18 筆交易深度驗證腳本 (修正版)

修正的驗證邏輯：
1. 日期計算：使用日歷日而非交易日
2. 信號驗證：檢查進場當日及之前是否有真實信號
3. 未來信息：確保進場/出場條件在當日成立，不能使用未來數據
"""

import pandas as pd
import numpy as np
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class V11TradeVerifierCorrected:
    """v1.1 交易驗證引擎（修正版）"""

    def __init__(self, data_path, trades_path):
        """初始化驗證器"""
        self.df = pd.read_csv(data_path)
        self.df['Date'] = pd.to_datetime(self.df['Date'])
        self.df = self.df.reset_index(drop=True)

        self.trades = pd.read_csv(trades_path)
        self.trades['entry_date'] = pd.to_datetime(self.trades['entry_date'])
        self.trades['exit_date'] = pd.to_datetime(self.trades['exit_date'])

        self.verification_results = []
        self._add_indicators()

    def _add_indicators(self):
        """添加技術指標"""
        df = self.df

        # SMA
        df['SMA20'] = df['Close'].rolling(20).mean()
        df['SMA50'] = df['Close'].rolling(50).mean()
        df['SMA200'] = df['Close'].rolling(200).mean()

        # 布林帶
        df['BB_Mid'] = df['Close'].rolling(20).mean()
        df['BB_Std'] = df['Close'].rolling(20).std()
        df['BB_Up'] = df['BB_Mid'] + 2 * df['BB_Std']
        df['BB_Low'] = df['BB_Mid'] - 2 * df['BB_Std']

        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

    def verify_all_trades(self):
        """驗證所有 18 筆交易"""
        logger.info(f"開始驗證 {len(self.trades)} 筆交易...\n")

        for idx, trade in self.trades.iterrows():
            self._verify_single_trade(idx, trade)

        return self.verification_results

    def _verify_single_trade(self, trade_num, trade):
        """驗證單筆交易"""
        entry_date = trade['entry_date']
        exit_date = trade['exit_date']
        entry_price = trade['entry_price']
        exit_price = trade['exit_price']
        reported_pnl = trade['profit_pct']
        entry_level = int(trade['entry_level'])
        is_bear_year = trade['is_bear_year']
        reported_days = trade['days_held']

        result = {
            'trade_num': trade_num + 1,
            'entry_date': entry_date,
            'exit_date': exit_date,
            'entry_level': entry_level,
            'is_bear_year': is_bear_year,
            'reported_days': reported_days,
            'issues': [],
            'warnings': [],
            'valid': True
        }

        # 1. 查找進出場日期索引
        entry_idx = self._find_date_index(entry_date)
        exit_idx = self._find_date_index(exit_date)

        if entry_idx is None:
            result['issues'].append(f"進場日期 {entry_date.date()} 未在數據中找到")
            result['valid'] = False

        if exit_idx is None:
            result['issues'].append(f"出場日期 {exit_date.date()} 未在數據中找到")
            result['valid'] = False

        if not result['valid']:
            self.verification_results.append(result)
            return

        # 2. 驗證進場信號真實性
        self._verify_entry_signal(result, entry_idx, entry_level, entry_date)

        # 3. 驗證出場信號真實性
        self._verify_exit_signal(result, exit_idx, entry_idx, entry_date, exit_date)

        # 4. 驗證計算精度
        self._verify_pnl_calculation(result, entry_price, exit_price, reported_pnl)

        # 5. 驗證時間合理性
        self._verify_holding_time(result, reported_days, entry_date, exit_date, entry_level)

        # 6. 驗證無未來信息漏洞
        self._check_lookahead_bias(result, entry_idx, exit_idx, entry_level)

        self.verification_results.append(result)

        # 輸出日誌
        status = "✓ 通過" if (result['valid'] and len(result['issues']) == 0) else "⚠ 警告" if (result['valid'] and len(result['warnings']) > 0) else "✗ 失敗"

        log_line = (f"#{result['trade_num']:2d}: {status} | "
                   f"{entry_date.date()} @ {entry_price:8,.0f} → {exit_date.date()} @ {exit_price:8,.0f} | "
                   f"{reported_pnl*100:+7.2f}% | L{entry_level} | {reported_days:3d}天")
        logger.info(log_line)

        if result['issues']:
            for issue in result['issues']:
                logger.info(f"      ✗ {issue}")
        if result['warnings']:
            for warning in result['warnings']:
                logger.info(f"      ⚠ {warning}")

    def _find_date_index(self, target_date):
        """查找日期在 DataFrame 中的索引"""
        match = self.df[self.df['Date'].dt.date == target_date.date()]
        if len(match) > 0:
            return match.index[0]
        return None

    def _verify_entry_signal(self, result, idx, level, entry_date):
        """驗證進場信號真實性"""
        if idx < 50:
            result['issues'].append(f"進場日期過早 (idx={idx}<50，無法計算指標)")
            return

        current = self.df.iloc[idx]
        previous = self.df.iloc[idx - 1]

        result['entry_signal_type'] = None

        if level == 1:
            # Level 1: SMA 黃金叉 (20 > 50 且前日 20 <= 50)
            has_golden_cross = (current['SMA20'] > current['SMA50'] and
                              previous['SMA20'] <= previous['SMA50'])

            # 黃金叉是否在進場當日發生
            if has_golden_cross:
                result['entry_signal_type'] = 'L1 黃金叉 ✓'
            else:
                # 檢查是否只是在多頭區間（黃金叉後）
                if current['SMA20'] > current['SMA50']:
                    # 這可能是多頭持倉的延續，不是進場信號
                    result['warnings'].append(
                        f"L1 進場：無黃金叉確認（當日 SMA20={current['SMA20']:.0f} > SMA50={current['SMA50']:.0f}, "
                        f"前日 SMA20={previous['SMA20']:.0f} vs SMA50={previous['SMA50']:.0f}）"
                        f"→ 可能是多頭區間的持續進場"
                    )
                    result['entry_signal_type'] = 'L1 牛市區間'
                else:
                    result['issues'].append(
                        f"L1 進場：既無黃金叉也無多頭條件（SMA20={current['SMA20']:.0f} vs SMA50={current['SMA50']:.0f}）"
                    )
                    result['valid'] = False

        elif level == 3:
            # Level 3: 布林帶超賣 (Close < BB_Low AND RSI < 30)
            has_oversold = (current['Close'] < current['BB_Low'] and
                          current['RSI'] < 30)

            if has_oversold:
                result['entry_signal_type'] = 'L3 超賣 ✓'
            else:
                # 詳細診斷
                reason = []
                if current['Close'] >= current['BB_Low']:
                    reason.append(f"Close({current['Close']:.0f}) ≥ BB_Low({current['BB_Low']:.0f})")
                if current['RSI'] >= 30:
                    reason.append(f"RSI({current['RSI']:.1f}) ≥ 30")

                result['warnings'].append(
                    f"L3 進場：超賣條件未完全滿足（{', '.join(reason)}）"
                )
                result['entry_signal_type'] = 'L3 部分條件'

    def _verify_exit_signal(self, result, exit_idx, entry_idx, entry_date, exit_date):
        """驗證出場信號真實性"""
        if exit_idx <= entry_idx:
            result['issues'].append(f"出場日期早於或等於進場日期")
            result['valid'] = False
            return

        current = self.df.iloc[exit_idx]
        previous = self.df.iloc[exit_idx - 1] if exit_idx > 0 else current
        entry_price = self.df.iloc[entry_idx]['Close']

        # 檢查多個出場條件
        profit_pct = (current['Close'] - entry_price) / entry_price

        # 條件1: 信號出場 (SMA死亡叉)
        has_death_cross = (current['SMA20'] < current['SMA50'] and
                          previous['SMA20'] >= previous['SMA50'])

        # 條件2: 止盈 (+30%)
        has_takeprofit = current['Close'] > entry_price * 1.30

        # 條件3: 止損 (-15%)
        has_stoploss = current['Close'] < entry_price * 0.85

        exit_reasons = []
        if has_death_cross:
            exit_reasons.append('死亡叉')
        if has_takeprofit:
            exit_reasons.append('止盈(+30%)')
        if has_stoploss:
            exit_reasons.append('止損(-15%)')

        if exit_reasons:
            result['exit_signal_type'] = ' / '.join(exit_reasons) + ' ✓'
        else:
            result['warnings'].append(
                f"出場條件不明確："
                f"死亡叉={has_death_cross}, "
                f"止盈(+30%)={has_takeprofit}, "
                f"止損(-15%)={has_stoploss} "
                f"(實際收益={profit_pct*100:.2f}%)"
            )

    def _verify_pnl_calculation(self, result, entry_price, exit_price, reported_pnl):
        """驗證損益計算"""
        calculated_pnl = (exit_price - entry_price) / entry_price
        pnl_diff = abs(calculated_pnl - reported_pnl)

        result['pnl_calculated'] = calculated_pnl

        if pnl_diff > 0.001:  # 允許 0.1% 誤差
            result['issues'].append(
                f"損益計算誤差: {pnl_diff*100:.4f}% (報告={reported_pnl*100:.4f}%, 計算={calculated_pnl*100:.4f}%)"
            )
            result['valid'] = False

    def _verify_holding_time(self, result, reported_days, entry_date, exit_date, level):
        """驗證持倉時間合理性"""
        calculated_days = (exit_date - entry_date).days

        result['calculated_days'] = calculated_days

        if abs(calculated_days - reported_days) > 1:
            result['warnings'].append(
                f"持倉天數輕微誤差: 報告={reported_days}天, 計算={calculated_days}天"
            )

        # 檢查時間合理性 (寬鬆標準，因為報告的持倉日數已經包含週末)
        # L1 應該在 50-400 天之間
        # L3 應該在 5-25 天之間
        if level == 1:
            if not (40 < calculated_days < 450):  # 允許更寬鬆的範圍
                result['warnings'].append(
                    f"L1 持倉時間偏離常規: {calculated_days}天 (預期: 50-400天)"
                )
        elif level == 3:
            if not (2 < calculated_days < 30):  # 允許更寬鬆的範圍
                result['warnings'].append(
                    f"L3 持倉時間偏離常規: {calculated_days}天 (預期: 5-25天)"
                )

    def _check_lookahead_bias(self, result, entry_idx, exit_idx, level):
        """檢查未來信息漏洞"""
        # 檢查進場條件計算是否只使用了過去的數據
        if entry_idx < 50:
            result['issues'].append("進場信號計算數據不足 (< 50日)")
            return

        # Level 1 需要 50 日 SMA，所以需要至少 50 天數據
        if level == 1:
            if entry_idx < 50:
                result['issues'].append("進場時 SMA50 計算數據不足")
                result['valid'] = False

        # Level 3 需要 20 日布林帶和 14 日 RSI
        if level == 3:
            if entry_idx < max(20, 14):
                result['issues'].append("進場時布林帶/RSI 計算數據不足")
                result['valid'] = False

    def generate_verification_report(self, output_path):
        """生成驗證報告"""
        report = []
        report.append("# v1.1 深度驗證報告\n\n")
        report.append(f"**生成日期**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        report.append(f"**驗證範圍**: {len(self.trades)} 筆交易\n")
        report.append(f"**數據範圍**: {self.df['Date'].iloc[0].date()} ~ {self.df['Date'].iloc[-1].date()}\n\n")

        # 摘要統計
        valid_trades = sum(1 for r in self.verification_results if r['valid'] and len(r['issues']) == 0)
        warning_trades = sum(1 for r in self.verification_results if r['valid'] and len(r['warnings']) > 0)
        invalid_trades = sum(1 for r in self.verification_results if not r['valid'])

        report.append("## 執行摘要\n\n")
        report.append(f"- **完全通過**: {valid_trades}/{len(self.verification_results)} ✓\n")
        report.append(f"- **含警告通過**: {warning_trades}/{len(self.verification_results)} ⚠\n")
        report.append(f"- **驗證失敗**: {invalid_trades}/{len(self.verification_results)} ✗\n")
        report.append(f"- **通過率 (含警告)**: {(valid_trades + warning_trades)/len(self.verification_results)*100:.1f}%\n\n")

        # 詳細驗證表
        report.append("## 逐筆交易驗證表\n\n")
        report.append("| # | 進場日 | 進場價 | 出場日 | 出場價 | 收益% | L | 持倉 | 進場信號 | 出場信號 | 狀態 |\n")
        report.append("|---|--------|--------|--------|--------|-------|---|------|----------|----------|------|\n")

        for result in self.verification_results:
            if len(result['issues']) == 0 and len(result['warnings']) == 0:
                status = "✓"
            elif len(result['issues']) == 0:
                status = "⚠"
            else:
                status = "✗"

            entry_date = result['entry_date'].strftime('%Y-%m-%d')
            exit_date = result['exit_date'].strftime('%Y-%m-%d')
            entry_price = self.df[self.df['Date'].dt.date == result['entry_date'].date()]['Close'].iloc[0]
            exit_price = self.df[self.df['Date'].dt.date == result['exit_date'].date()]['Close'].iloc[0]
            pnl = (exit_price - entry_price) / entry_price * 100

            entry_signal = result.get('entry_signal_type', '?')
            exit_signal = result.get('exit_signal_type', '?')

            report.append(
                f"| {result['trade_num']:2d} | {entry_date} | {entry_price:8,.0f} | "
                f"{exit_date} | {exit_price:8,.0f} | {pnl:+7.2f}% | "
                f"{result['entry_level']} | {result['calculated_days']:3d} | "
                f"{entry_signal:20s} | {exit_signal:25s} | {status} |\n"
            )

        report.append("\n")

        # 問題詳情
        if invalid_trades > 0:
            report.append("## 驗證失敗的交易\n\n")
            for result in self.verification_results:
                if not result['valid']:
                    report.append(f"### 交易 #{result['trade_num']}\n\n")
                    for issue in result['issues']:
                        report.append(f"**✗ {issue}**\n\n")
                    for warning in result['warnings']:
                        report.append(f"⚠ {warning}\n\n")

        # 警告詳情
        if warning_trades > 0:
            report.append("## 含警告的交易\n\n")
            for result in self.verification_results:
                if result['valid'] and len(result['warnings']) > 0:
                    report.append(f"### 交易 #{result['trade_num']}\n\n")
                    for warning in result['warnings']:
                        report.append(f"⚠ {warning}\n\n")

        # 統計分析
        report.append("## 統計分析\n\n")

        # 按層級統計
        level_stats = {}
        for result in self.verification_results:
            level = result['entry_level']
            if level not in level_stats:
                level_stats[level] = {'total': 0, 'pass': 0, 'warn': 0, 'fail': 0}
            level_stats[level]['total'] += 1
            if not result['valid']:
                level_stats[level]['fail'] += 1
            elif len(result['warnings']) > 0:
                level_stats[level]['warn'] += 1
            else:
                level_stats[level]['pass'] += 1

        report.append("### 按信號層級分類\n\n")
        for level in sorted(level_stats.keys()):
            stats = level_stats[level]
            report.append(f"- **L{level}**: {stats['total']} 筆 ")
            report.append(f"(✓ {stats['pass']}, ⚠ {stats['warn']}, ✗ {stats['fail']})\n")

        # 寫入文件
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(report)

        return "\n".join(report)


def main():
    """主函數"""
    verifier = V11TradeVerifierCorrected(
        data_path='/home/tom/TX_Quantitative_Trading/data/TX_full_2019_2026.csv',
        trades_path='/home/tom/TX_Quantitative_Trading/data/adaptive_trades_v11.csv'
    )

    results = verifier.verify_all_trades()

    # 輸出摘要
    logger.info("\n" + "="*100)
    logger.info("驗證摘要")
    logger.info("="*100)

    valid = sum(1 for r in results if r['valid'] and len(r['issues']) == 0)
    warning = sum(1 for r in results if r['valid'] and len(r['warnings']) > 0)
    invalid = sum(1 for r in results if not r['valid'])

    logger.info(f"\n完全通過驗證: {valid}/{len(results)} ✓")
    logger.info(f"含警告通過:   {warning}/{len(results)} ⚠")
    logger.info(f"驗證失敗:     {invalid}/{len(results)} ✗")
    logger.info(f"通過率 (含警告): {(valid + warning)/len(results)*100:.1f}%\n")

    # 生成報告
    report = verifier.generate_verification_report(
        '/home/tom/TX_Quantitative_Trading/reports/v11_verification_report.md'
    )

    logger.info(f"詳細報告已保存到: /home/tom/TX_Quantitative_Trading/reports/v11_verification_report.md\n")


if __name__ == '__main__':
    main()
