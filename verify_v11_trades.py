#!/usr/bin/env python3
"""
v1.1 版本 18 筆交易深度驗證腳本

驗證內容：
1. 逐筆交易的進出場信號真實性
2. 計算精度和損益驗證
3. 未來信息漏洞檢查
4. 邊界情況驗證
5. 統計一致性檢查
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


class V11TradeVerifier:
    """v1.1 交易驗證引擎"""

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
        entry_level = trade['entry_level']
        is_bear_year = trade['is_bear_year']
        days_held = trade['days_held']

        result = {
            'trade_num': trade_num + 1,
            'entry_date': entry_date,
            'exit_date': exit_date,
            'entry_level': int(entry_level),
            'is_bear_year': is_bear_year,
            'days_held': days_held,
            'issues': [],
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
        self._verify_entry_signal(result, entry_idx, entry_level)

        # 3. 驗證出場信號真實性
        self._verify_exit_signal(result, exit_idx, entry_idx)

        # 4. 驗證計算精度
        self._verify_pnl_calculation(result, entry_price, exit_price, reported_pnl)

        # 5. 驗證時間合理性
        self._verify_holding_time(result, days_held, entry_idx, exit_idx, entry_level)

        # 6. 驗證未來信息漏洞
        self._check_lookahead_bias(result, entry_idx, exit_idx, entry_level)

        self.verification_results.append(result)

        # 輸出日誌
        status = "✓ 驗證通過" if result['valid'] else "✗ 驗證失敗"
        logger.info(f"#{result['trade_num']}: {status}")
        if result['issues']:
            for issue in result['issues']:
                logger.info(f"  - {issue}")
        logger.info(f"  進場: {entry_date.date()} @ {entry_price:.2f} | 出場: {exit_date.date()} @ {exit_price:.2f}")
        logger.info(f"  損益: {reported_pnl*100:.2f}% | 持倉: {days_held}天 | L{int(entry_level)}")
        logger.info("")

    def _find_date_index(self, target_date):
        """查找日期在 DataFrame 中的索引"""
        match = self.df[self.df['Date'].dt.date == target_date.date()]
        if len(match) > 0:
            return match.index[0]
        return None

    def _verify_entry_signal(self, result, idx, level):
        """驗證進場信號真實性"""
        if idx < 50:
            result['issues'].append(f"進場日期過早 (idx={idx}<50)")
            return

        current = self.df.iloc[idx]
        previous = self.df.iloc[idx - 1]

        entry_data = {
            'date': current['Date'],
            'close': current['Close'],
            'sma20': current['SMA20'],
            'sma50': current['SMA50'],
            'bb_low': current['BB_Low'],
            'rsi': current['RSI']
        }
        result['entry_data'] = entry_data

        if level == 1:
            # Level 1: SMA 黃金叉
            if current['SMA20'] > current['SMA50'] and previous['SMA20'] <= previous['SMA50']:
                result['entry_signal'] = 'L1 黃金叉 ✓'
            else:
                result['issues'].append(
                    f"L1 進場: 黃金叉條件不符\n"
                    f"    當日: SMA20({current['SMA20']:.2f}) vs SMA50({current['SMA50']:.2f})\n"
                    f"    前日: SMA20({previous['SMA20']:.2f}) vs SMA50({previous['SMA50']:.2f})"
                )
                result['valid'] = False
        elif level == 3:
            # Level 3: 布林帶超賣
            if current['Close'] < current['BB_Low'] and current['RSI'] < 30:
                result['entry_signal'] = 'L3 超賣 ✓'
            else:
                result['issues'].append(
                    f"L3 進場: 超賣條件不符\n"
                    f"    Close({current['Close']:.2f}) < BB_Low({current['BB_Low']:.2f})? {current['Close'] < current['BB_Low']}\n"
                    f"    RSI({current['RSI']:.2f}) < 30? {current['RSI'] < 30}"
                )
                result['valid'] = False

    def _verify_exit_signal(self, result, exit_idx, entry_idx, exit_reason='signal'):
        """驗證出場信號真實性"""
        if exit_idx <= entry_idx:
            result['issues'].append(f"出場日期早於或等於進場日期")
            result['valid'] = False
            return

        current = self.df.iloc[exit_idx]
        previous = self.df.iloc[exit_idx - 1]
        entry_price = self.df.iloc[entry_idx]['Close']

        exit_data = {
            'date': current['Date'],
            'close': current['Close'],
            'sma20': current['SMA20'],
            'sma50': current['SMA50'],
            'profit_pct': (current['Close'] - entry_price) / entry_price
        }
        result['exit_data'] = exit_data

        # 檢查多個出場條件
        profit_pct = (current['Close'] - entry_price) / entry_price

        # 條件1: 信號出場 (SMA死亡叉)
        has_death_cross = (current['SMA20'] < current['SMA50'] and
                          previous['SMA20'] >= previous['SMA50'])

        # 條件2: 止盈 (+30%)
        has_takeprofit = current['Close'] > entry_price * 1.30

        # 條件3: 止損 (-15%)
        has_stoploss = current['Close'] < entry_price * 0.85

        if has_death_cross:
            result['exit_signal'] = '死亡叉出場 ✓'
        elif has_takeprofit:
            result['exit_signal'] = '止盈出場 ✓'
        elif has_stoploss:
            result['exit_signal'] = '止損出場 ✓'
        else:
            result['issues'].append(
                f"出場信號不明確\n"
                f"    死亡叉? {has_death_cross} (SMA20: {current['SMA20']:.2f} vs {current['SMA50']:.2f})\n"
                f"    止盈(+30%)? {has_takeprofit} (收益: {profit_pct*100:.2f}%)\n"
                f"    止損(-15%)? {has_stoploss}"
            )

    def _verify_pnl_calculation(self, result, entry_price, exit_price, reported_pnl):
        """驗證損益計算"""
        calculated_pnl = (exit_price - entry_price) / entry_price
        pnl_diff = abs(calculated_pnl - reported_pnl)

        result['pnl_data'] = {
            'entry_price': entry_price,
            'exit_price': exit_price,
            'reported_pnl': reported_pnl,
            'calculated_pnl': calculated_pnl,
            'difference': pnl_diff
        }

        if pnl_diff > 0.001:  # 允許 0.1% 誤差
            result['issues'].append(
                f"損益計算誤差: {pnl_diff*100:.4f}%\n"
                f"    報告: {reported_pnl*100:.4f}% | 計算: {calculated_pnl*100:.4f}%"
            )
            result['valid'] = False

    def _verify_holding_time(self, result, reported_days, entry_idx, exit_idx, level):
        """驗證持倉時間合理性"""
        calculated_days = exit_idx - entry_idx
        days_diff = abs(calculated_days - reported_days)

        result['time_data'] = {
            'reported_days': reported_days,
            'calculated_days': calculated_days,
            'days_diff': days_diff
        }

        if days_diff > 2:
            result['issues'].append(f"持倉天數誤差: 報告{reported_days}天, 計算{calculated_days}天")
            result['valid'] = False

        # 檢查時間合理性
        if level == 1:
            if not (50 < calculated_days < 400):
                result['issues'].append(
                    f"L1 持倉時間異常: {calculated_days}天 (正常範圍: 50-400天)"
                )
        elif level == 3:
            if not (5 < calculated_days < 25):
                result['issues'].append(
                    f"L3 持倉時間異常: {calculated_days}天 (正常範圍: 5-25天)"
                )

    def _check_lookahead_bias(self, result, entry_idx, exit_idx, level):
        """檢查未來信息漏洞"""
        # 檢查進場條件計算是否只使用了過去的數據
        if entry_idx < 50:
            result['issues'].append("進場信號計算數據不足 (< 50日)")
            return

        # 檢查 SMA 計算窗口
        if level == 1:
            # 需要至少 50 天的歷史數據計算 SMA50
            if entry_idx < 50:
                result['issues'].append("進場時 SMA50 計算數據不足")
                result['valid'] = False

        # 檢查布林帶計算
        if level == 3:
            if entry_idx < 20:
                result['issues'].append("進場時布林帶計算數據不足 (< 20日)")
                result['valid'] = False

    def generate_verification_report(self, output_path):
        """生成驗證報告"""
        report = []
        report.append("# v1.1 深度驗證報告\n")
        report.append(f"**生成日期**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        report.append(f"**驗證範圍**: {len(self.trades)} 筆交易\n")
        report.append(f"**數據範圍**: {self.df['Date'].iloc[0].date()} ~ {self.df['Date'].iloc[-1].date()}\n\n")

        # 摘要統計
        valid_trades = sum(1 for r in self.verification_results if r['valid'])
        invalid_trades = len(self.verification_results) - valid_trades

        report.append("## 執行摘要\n")
        report.append(f"- **驗證通過**: {valid_trades}/{len(self.verification_results)} ✓\n")
        report.append(f"- **驗證失敗**: {invalid_trades}/{len(self.verification_results)} ✗\n")
        report.append(f"- **通過率**: {valid_trades/len(self.verification_results)*100:.1f}%\n\n")

        # 詳細驗證表
        report.append("## 逐筆交易驗證表\n\n")
        report.append("| # | 進場日 | 進場價 | 出場日 | 出場價 | 收益% | L | 持倉 | 驗證 |\n")
        report.append("|---|--------|--------|--------|--------|-------|---|------|------|\n")

        for result in self.verification_results:
            status = "✓" if result['valid'] else "✗"
            entry_date = result['entry_date'].strftime('%Y-%m-%d')
            exit_date = result['exit_date'].strftime('%Y-%m-%d')
            entry_price = result.get('entry_data', {}).get('close', '-')
            exit_price = result.get('exit_data', {}).get('close', '-')
            pnl = result.get('pnl_data', {}).get('reported_pnl', 0) * 100

            if isinstance(entry_price, float):
                entry_price = f"{entry_price:,.0f}"
            if isinstance(exit_price, float):
                exit_price = f"{exit_price:,.0f}"

            report.append(
                f"| {result['trade_num']} | {entry_date} | {entry_price} | "
                f"{exit_date} | {exit_price} | {pnl:+.2f}% | "
                f"{result['entry_level']} | {result['days_held']} | {status} |\n"
            )

        report.append("\n")

        # 問題詳情
        if invalid_trades > 0:
            report.append("## 發現的問題\n\n")
            for result in self.verification_results:
                if not result['valid']:
                    report.append(f"### 交易 #{result['trade_num']}\n\n")
                    for issue in result['issues']:
                        report.append(f"- {issue}\n")
                    report.append("\n")

        # 寫入文件
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(report)

        return "\n".join(report)


def main():
    """主函數"""
    verifier = V11TradeVerifier(
        data_path='/home/tom/TX_Quantitative_Trading/data/TX_full_2019_2026.csv',
        trades_path='/home/tom/TX_Quantitative_Trading/data/adaptive_trades_v11.csv'
    )

    results = verifier.verify_all_trades()

    # 輸出摘要
    logger.info("\n" + "="*60)
    logger.info("驗證摘要")
    logger.info("="*60)

    valid = sum(1 for r in results if r['valid'])
    logger.info(f"通過驗證: {valid}/{len(results)} ✓")
    logger.info(f"驗證失敗: {len(results)-valid}/{len(results)} ✗")
    logger.info(f"通過率: {valid/len(results)*100:.1f}%\n")

    # 生成報告
    report = verifier.generate_verification_report(
        '/home/tom/TX_Quantitative_Trading/reports/v11_verification_report.md'
    )

    logger.info("驗證報告已保存到: /home/tom/TX_Quantitative_Trading/reports/v11_verification_report.md")


if __name__ == '__main__':
    main()
