#!/usr/bin/env python3
"""
台指期自適應多層次策略回測系統 v1.1 (2019-2026)

核心改進目標:
1. 提高交易頻率 (6次 → 15-25次) 通過三層信號系統
2. 改進空頭防守 (虧損-4.69% → 獲利+5-8%)

v1.1 新特性:
- Level 1 主信號: SMA黃金叉 (權重60%, BULL/中立) - 保持穩定
- Level 2 次信號: 周線突破 (權重25%, 短期趨勢) - 新增
- Level 3 補充信號: 布林帶反彈 (權重15%, 超賣反彈) - 新增
- 動態倉位管理: BEAR年減倉至0.5口，加強短線信號
- 空頭年檢測: 自動檢測-20%以上年度跌幅，觸發防守模式
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json
import logging
from pathlib import Path
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class BearYearDetector:
    """空頭年檢測器 - 識別並記錄全年下跌的年份"""

    @staticmethod
    def detect_bear_year(df, current_idx):
        """
        檢測當前是否在空頭年中

        信號:
        1. 檢查過去12個月的年初vs年末
        2. 檢查30日MA < 200日MA超過60天
        3. 檢查連續虧損月份

        Returns: (is_bear_year: bool, bear_intensity: float 0-1)
        """
        if current_idx < 200:
            return False, 0.0

        past = df.iloc[:current_idx]
        current_date = pd.to_datetime(past['Date'].iloc[-1])
        current_year = current_date.year

        # 策略1: 檢查年初vs年末
        year_start_idx = None
        for i in range(len(past)-1, -1, -1):
            date = pd.to_datetime(past['Date'].iloc[i])
            if date.year == current_year and date.month == 1:
                year_start_idx = i
                break

        if year_start_idx is not None:
            year_start_price = past['Close'].iloc[year_start_idx]
            current_price = past['Close'].iloc[-1]
            year_return = (current_price - year_start_price) / year_start_price

            # 超過-20%的跌幅視為空頭年
            if year_return < -0.20:
                return True, min(abs(year_return), 1.0)

        # 策略2: 檢查MA趨勢
        sma30 = past['Close'].rolling(30).mean().iloc[-1]
        sma200 = past['Close'].rolling(200).mean().iloc[-1]

        if sma30 < sma200:
            # 計算有多少天SMA30 < SMA200
            bear_days = (past['Close'].rolling(30).mean() < past['Close'].rolling(200).mean()).sum()
            if bear_days > 60:
                return True, 0.5

        return False, 0.0


class MultiLevelSignalGenerator:
    """多層次信號生成器"""

    @staticmethod
    def get_level1_signal(df, current_idx):
        """
        Level 1 主信號: SMA黃金叉 (權重60%)
        - 最可靠，適合長期趨勢
        - BULL環境: SMA20 > SMA50 (黃金叉)
        - 出場: SMA20 < SMA50 (死亡叉)
        """
        if current_idx < 50:
            return 0, 'NONE'

        if (pd.isna(df['SMA20'].iloc[current_idx]) or
            pd.isna(df['SMA50'].iloc[current_idx])):
            return 0, 'NONE'

        current = df.iloc[current_idx]
        previous = df.iloc[current_idx - 1]

        # 黃金叉
        if (current['SMA20'] > current['SMA50'] and
            previous['SMA20'] <= previous['SMA50']):
            return 1, 'GOLDEN_CROSS'

        # 死亡叉
        if (current['SMA20'] < current['SMA50'] and
            previous['SMA20'] >= previous['SMA50']):
            return -1, 'DEATH_CROSS'

        # 持倉中的狀態檢查
        if current['SMA20'] > current['SMA50']:
            return 0.5, 'BULL_HOLD'
        elif current['SMA20'] < current['SMA50']:
            return -0.5, 'BEAR_SIGNAL'

        return 0, 'NONE'

    @staticmethod
    def get_level2_signal(df, current_idx):
        """
        Level 2 次信號: 周線突破 (權重25%)
        - 捕捉短期趨勢 (20-60天持倉)
        - 進場: 收盤 > 5日高點 (周線突破模擬)
        - 出場: 收盤 < 5日低點
        """
        if current_idx < 5:
            return 0, 'NONE'

        current = df.iloc[current_idx]
        previous = df.iloc[current_idx - 1]

        # 周線高點突破 (模擬: 5日高點突破)
        high5 = df['High'].iloc[max(0, current_idx-5):current_idx+1].max()
        low5 = df['Low'].iloc[max(0, current_idx-5):current_idx+1].min()
        high5_prev = df['High'].iloc[max(0, current_idx-6):current_idx].max()
        low5_prev = df['Low'].iloc[max(0, current_idx-6):current_idx].min()

        # 突破高點 (新高)
        if current['Close'] > high5_prev and current['Close'] > previous['Close']:
            return 0.7, 'WEEKLY_BREAKOUT_UP'

        # 跌破低點 (新低)
        if current['Close'] < low5_prev and current['Close'] < previous['Close']:
            return -0.7, 'WEEKLY_BREAKOUT_DOWN'

        # 接近突破
        if current['Close'] > high5 * 0.98:
            return 0.3, 'WEEKLY_NEAR_BREAKOUT'

        return 0, 'NONE'

    @staticmethod
    def get_level3_signal(df, current_idx):
        """
        Level 3 補充信號: 布林帶反彈 (權重15%)
        - 捕捉超賣反彈 (5-20天持倉)
        - 進場: 價格 < 布林帶下軌 且 RSI < 30 (超賣)
        - 出場: 價格 > 布林帶中軌 或 RSI > 50

        這是空頭年防守的主要信號，可以帶來頻繁的小額收益
        """
        if current_idx < 50:
            return 0, 'NONE'

        if (pd.isna(df['BB_Low'].iloc[current_idx]) or
            pd.isna(df['RSI'].iloc[current_idx]) or
            pd.isna(df['BB_Mid'].iloc[current_idx])):
            return 0, 'NONE'

        current = df.iloc[current_idx]

        # 買入信號: 下軌 + 超賣
        if (current['Close'] < current['BB_Low'] and
            current['RSI'] < 30):
            return 1.0, 'BB_OVERSOLD'

        # 賣出信號: 上軌或超買
        if current['Close'] > current['BB_Up'] or current['RSI'] > 70:
            return -1.0, 'BB_OVERBOUGHT'

        # 中軌反彈
        if (current['Close'] < current['BB_Mid'] and
            current['Close'] > current['BB_Low'] and
            current['RSI'] < 50):
            return 0.3, 'BB_RECOVERY'

        return 0, 'NONE'

    @staticmethod
    def combine_signals(l1_signal, l2_signal, l3_signal, is_bear_year,
                       in_position=False):
        """
        組合多層信號

        牛市: L1優先(60%) + L2(25%) + L3(15%)
        空頭年: L3優先(40%) + L2(30%) + L1(30%) - 短線防守

        Returns: (combined_score: float, signal_type: str)
        """
        if is_bear_year:
            # 空頭年: 優先短線反彈和周線突破
            score = l1_signal * 0.30 + l2_signal * 0.30 + l3_signal * 0.40
            signal_type = 'BEAR_MODE'
        else:
            # 牛市: 主信號為主
            score = l1_signal * 0.60 + l2_signal * 0.25 + l3_signal * 0.15
            signal_type = 'BULL_MODE'

        # 信號過濾
        if abs(score) < 0.1:
            return 0, 'NEUTRAL'

        return score, signal_type


class StrategyV11Backtester:
    """台指期 v1.1 回測引擎"""

    def __init__(self, data_path, initial_capital=1000000, leverage=200):
        """初始化"""
        self.data = pd.read_csv(data_path)
        self.data['Date'] = pd.to_datetime(self.data['Date'])
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.trades = []
        self.logs = []

        # 添加技術指標
        self._add_indicators()

    def _add_indicators(self):
        """添加所有技術指標"""
        df = self.data

        # 移動平均
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

        # 高低點
        df['High20'] = df['High'].rolling(20).max()
        df['Low20'] = df['Low'].rolling(20).min()

    def backtest(self):
        """執行完整回測"""
        capital = self.initial_capital
        position = None  # None或(entry_date, entry_price, entry_level)
        trades = []

        logger.info("開始 v1.1 回測...")
        logger.info(f"數據範圍: {self.data['Date'].iloc[0]} ~ {self.data['Date'].iloc[-1]}")
        logger.info(f"初始資金: ¥{capital:,.0f}")
        logger.info("")

        for idx in range(200, len(self.data)):
            current_date = self.data['Date'].iloc[idx]
            current_price = self.data['Close'].iloc[idx]

            # 檢測環境
            is_bear, bear_intensity = BearYearDetector.detect_bear_year(
                self.data, idx
            )

            # 生成多層信號
            l1_sig, l1_type = MultiLevelSignalGenerator.get_level1_signal(
                self.data, idx
            )
            l2_sig, l2_type = MultiLevelSignalGenerator.get_level2_signal(
                self.data, idx
            )
            l3_sig, l3_type = MultiLevelSignalGenerator.get_level3_signal(
                self.data, idx
            )

            # 組合信號
            combined_score, signal_mode = MultiLevelSignalGenerator.combine_signals(
                l1_sig, l2_sig, l3_sig, is_bear,
                in_position=(position is not None)
            )

            # 交易邏輯
            if position is None:
                # 沒有持倉，尋找進場機會
                if combined_score > 0.2:  # 買入信號
                    # 空頭年減倉 (0.5口)，牛市正常(1口)
                    lot_size = 0.5 if is_bear else 1.0
                    position = {
                        'entry_date': current_date,
                        'entry_price': current_price,
                        'entry_level': self._identify_level(l1_sig, l2_sig, l3_sig),
                        'lot_size': lot_size,
                        'l1_sig': l1_sig,
                        'l2_sig': l2_sig,
                        'l3_sig': l3_sig,
                        'is_bear_year': is_bear
                    }

                    logger.info(f"進場: {current_date.date()} @ {current_price:.2f} "
                              f"(L{position['entry_level']} 倉位{lot_size}口) "
                              f"[{l1_type}, {l2_type}, {l3_type}]")
            else:
                # 持倉中，檢查出場信號
                entry_days = (current_date - position['entry_date']).days

                # 出場條件1: 強烈賣出信號
                if combined_score < -0.3:
                    profit = (current_price - position['entry_price']) / position['entry_price']
                    points = current_price - position['entry_price']

                    trade = {
                        'entry_date': position['entry_date'],
                        'entry_price': position['entry_price'],
                        'entry_level': position['entry_level'],
                        'exit_date': current_date,
                        'exit_price': current_price,
                        'profit_pct': profit,
                        'profit_points': points,
                        'days_held': entry_days,
                        'is_bear_year': position['is_bear_year'],
                        'exit_reason': 'signal'
                    }
                    trades.append(trade)

                    logger.info(f"出場: {current_date.date()} @ {current_price:.2f} "
                              f"收益: {profit*100:.2f}% (持倉{entry_days}天)")
                    position = None

                # 出場條件2: 止損 (持倉中下跌-15%)
                elif current_price < position['entry_price'] * 0.85:
                    profit = (current_price - position['entry_price']) / position['entry_price']
                    points = current_price - position['entry_price']

                    trade = {
                        'entry_date': position['entry_date'],
                        'entry_price': position['entry_price'],
                        'entry_level': position['entry_level'],
                        'exit_date': current_date,
                        'exit_price': current_price,
                        'profit_pct': profit,
                        'profit_points': points,
                        'days_held': entry_days,
                        'is_bear_year': position['is_bear_year'],
                        'exit_reason': 'stoploss'
                    }
                    trades.append(trade)

                    logger.info(f"止損: {current_date.date()} @ {current_price:.2f} "
                              f"虧損: {profit*100:.2f}% (持倉{entry_days}天)")
                    position = None

                # 出場條件3: 止盈 (持倉中上漲+30%)
                elif current_price > position['entry_price'] * 1.30:
                    profit = (current_price - position['entry_price']) / position['entry_price']
                    points = current_price - position['entry_price']

                    trade = {
                        'entry_date': position['entry_date'],
                        'entry_price': position['entry_price'],
                        'entry_level': position['entry_level'],
                        'exit_date': current_date,
                        'exit_price': current_price,
                        'profit_pct': profit,
                        'profit_points': points,
                        'days_held': entry_days,
                        'is_bear_year': position['is_bear_year'],
                        'exit_reason': 'takeprofit'
                    }
                    trades.append(trade)

                    logger.info(f"止盈: {current_date.date()} @ {current_price:.2f} "
                              f"收益: {profit*100:.2f}% (持倉{entry_days}天)")
                    position = None

                # 出場條件4: 強制平倉 (持倉超過2年)
                elif entry_days > 730:
                    profit = (current_price - position['entry_price']) / position['entry_price']
                    points = current_price - position['entry_price']

                    trade = {
                        'entry_date': position['entry_date'],
                        'entry_price': position['entry_price'],
                        'entry_level': position['entry_level'],
                        'exit_date': current_date,
                        'exit_price': current_price,
                        'profit_pct': profit,
                        'profit_points': points,
                        'days_held': entry_days,
                        'is_bear_year': position['is_bear_year'],
                        'exit_reason': 'timeout'
                    }
                    trades.append(trade)

                    logger.info(f"超時: {current_date.date()} @ {current_price:.2f} "
                              f"收益: {profit*100:.2f}% (持倉{entry_days}天)")
                    position = None

        self.trades = trades
        return self._calculate_metrics(trades)

    @staticmethod
    def _identify_level(l1, l2, l3):
        """識別交易來自哪個信號層級"""
        abs_signals = [abs(l1), abs(l2), abs(l3)]
        max_idx = abs_signals.index(max(abs_signals))
        return max_idx + 1

    def _calculate_metrics(self, trades):
        """計算性能指標"""
        if not trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'avg_profit_pct': 0,
                'total_profit_pct': 0,
                'annual_return': 0
            }

        df_trades = pd.DataFrame(trades)

        winning = df_trades[df_trades['profit_pct'] > 0]
        losing = df_trades[df_trades['profit_pct'] <= 0]

        # 計算年化收益 (7年回測期)
        total_return = (1 + df_trades['profit_pct']).prod() - 1
        years = (self.data['Date'].iloc[-1] - self.data['Date'].iloc[0]).days / 365.25
        annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        metrics = {
            'total_trades': len(trades),
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'win_rate': len(winning) / len(trades) if trades else 0,
            'avg_profit_pct': df_trades['profit_pct'].mean(),
            'total_profit_pct': total_return,
            'annual_return': annual_return,
            'bull_trades': len(df_trades[df_trades['is_bear_year'] == False]),
            'bear_trades': len(df_trades[df_trades['is_bear_year'] == True]),
            'by_level': self._trades_by_level(df_trades)
        }

        return metrics

    @staticmethod
    def _trades_by_level(df_trades):
        """按層級統計交易"""
        result = {
            'level_1': len(df_trades[df_trades['entry_level'] == 1]),
            'level_2': len(df_trades[df_trades['entry_level'] == 2]),
            'level_3': len(df_trades[df_trades['entry_level'] == 3])
        }
        return result

    def export_trades(self, output_path):
        """導出交易記錄"""
        df = pd.DataFrame(self.trades)
        df.to_csv(output_path, index=False)
        logger.info(f"交易記錄已導出: {output_path}")


def main():
    """主函數"""
    backtest = StrategyV11Backtester(
        data_path='/home/tom/TX_Quantitative_Trading/data/TX_full_2019_2026.csv',
        initial_capital=1000000,
        leverage=200
    )

    metrics = backtest.backtest()

    # 輸出結果摘要
    logger.info("")
    logger.info("=" * 60)
    logger.info("v1.1 回測結果摘要")
    logger.info("=" * 60)
    logger.info(f"總交易數: {metrics['total_trades']}")
    logger.info(f"勝利交易: {metrics['winning_trades']}")
    logger.info(f"虧損交易: {metrics['losing_trades']}")
    logger.info(f"勝率: {metrics['win_rate']*100:.1f}%")
    logger.info(f"平均收益: {metrics['avg_profit_pct']*100:.2f}%")
    logger.info(f"總收益: {metrics['total_profit_pct']*100:.2f}%")
    logger.info(f"年化收益: {metrics['annual_return']*100:.2f}%")
    logger.info("")
    logger.info(f"牛市交易: {metrics['bull_trades']}筆")
    logger.info(f"空頭年交易: {metrics['bear_trades']}筆")
    logger.info("")
    logger.info(f"信號層級分布:")
    logger.info(f"  Level 1 (SMA黃金叉): {metrics['by_level']['level_1']}筆")
    logger.info(f"  Level 2 (周線突破): {metrics['by_level']['level_2']}筆")
    logger.info(f"  Level 3 (布林帶反彈): {metrics['by_level']['level_3']}筆")
    logger.info("=" * 60)
    logger.info("")

    # 導出交易記錄
    backtest.export_trades(
        '/home/tom/TX_Quantitative_Trading/data/adaptive_trades_v11.csv'
    )

    # 保存詳細指標
    with open('/home/tom/TX_Quantitative_Trading/data/v11_metrics.json', 'w') as f:
        json.dump(metrics, f, indent=2, default=str)

    return metrics


if __name__ == '__main__':
    main()
