#!/usr/bin/env python3
"""
生成環境檢測參數優化的對比圖表
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from pathlib import Path

# 設置中文字體
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

def load_logs(version):
    """加載回測日誌"""
    log_file = f'/home/tom/TX_Quantitative_Trading/data/adaptive_backtest_log_{version}.csv'
    return pd.read_csv(log_file)

def generate_environment_distribution_chart():
    """生成環境分佈對比圖"""

    versions = ['conservative', 'moderate', 'aggressive']
    colors = {
        'BULL': '#26a69a',   # 綠色
        'BEAR': '#ef5350',   # 紅色
        'RANGE': '#ffa726',  # 橙色
        'NEUTRAL': '#90a4ae'  # 灰色
    }

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('環境檢測參數優化對比 - 環境分佈分析', fontsize=16, fontweight='bold')

    # 讀取所有版本的數據
    all_data = {}
    for version in versions:
        df = load_logs(version)
        env_counts = df['Environment'].value_counts()
        env_pct = env_counts / len(df) * 100
        all_data[version] = env_pct

    # 1. 環形圖對比 - 保守版
    ax1 = axes[0, 0]
    conservative_data = all_data['conservative']
    colors_list = [colors.get(env, '#999999') for env in conservative_data.index]
    ax1.pie(conservative_data, labels=conservative_data.index, autopct='%1.1f%%',
            colors=colors_list, startangle=90)
    ax1.set_title('保守版 (Conservative)\nNEUTRAL: 5.6%', fontweight='bold')

    # 2. 環形圖對比 - 中等版
    ax2 = axes[0, 1]
    moderate_data = all_data['moderate']
    colors_list = [colors.get(env, '#999999') for env in moderate_data.index]
    ax2.pie(moderate_data, labels=moderate_data.index, autopct='%1.1f%%',
            colors=colors_list, startangle=90)
    ax2.set_title('中等版 (Moderate) ⭐\nNEUTRAL: 4.7%', fontweight='bold')

    # 3. 環形圖對比 - 激進版
    ax3 = axes[1, 0]
    aggressive_data = all_data['aggressive']
    colors_list = [colors.get(env, '#999999') for env in aggressive_data.index]
    ax3.pie(aggressive_data, labels=aggressive_data.index, autopct='%1.1f%%',
            colors=colors_list, startangle=90)
    ax3.set_title('激進版 (Aggressive)\nNEUTRAL: 0.0%', fontweight='bold')

    # 4. 柱狀圖對比
    ax4 = axes[1, 1]
    environments = ['BULL', 'BEAR', 'RANGE', 'NEUTRAL']
    x = np.arange(len(environments))
    width = 0.25

    conservative_vals = [all_data['conservative'].get(env, 0) for env in environments]
    moderate_vals = [all_data['moderate'].get(env, 0) for env in environments]
    aggressive_vals = [all_data['aggressive'].get(env, 0) for env in environments]

    ax4.bar(x - width, conservative_vals, width, label='保守版', color='#64b5f6')
    ax4.bar(x, moderate_vals, width, label='中等版', color='#4db8ff')
    ax4.bar(x + width, aggressive_vals, width, label='激進版', color='#1e88e5')

    ax4.set_xlabel('環境類型')
    ax4.set_ylabel('比例 (%)')
    ax4.set_title('環境分佈柱狀圖對比')
    ax4.set_xticks(x)
    ax4.set_xticklabels(environments)
    ax4.legend()
    ax4.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig('/home/tom/TX_Quantitative_Trading/reports/environment_distribution_comparison.png',
                dpi=300, bbox_inches='tight')
    print("✓ 環境分佈圖已保存")
    plt.close()


def generate_portfolio_value_chart():
    """生成組合價值曲線對比"""

    versions = ['conservative', 'moderate', 'aggressive']
    colors_line = {
        'conservative': '#64b5f6',
        'moderate': '#4db8ff',
        'aggressive': '#1e88e5'
    }

    fig, ax = plt.subplots(figsize=(14, 7))

    for version in versions:
        df = load_logs(version)
        dates = pd.to_datetime(df['Date'])
        values = df['PortfolioValue']

        ax.plot(dates, values, label=f'{version.upper()}',
                color=colors_line[version], linewidth=2, alpha=0.8)

    ax.set_xlabel('日期')
    ax.set_ylabel('組合價值 (元)')
    ax.set_title('三個版本的組合價值曲線對比 (初始資金: 1,000,000元)', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x/1e6:.2f}M'))

    plt.tight_layout()
    plt.savefig('/home/tom/TX_Quantitative_Trading/reports/portfolio_value_comparison.png',
                dpi=300, bbox_inches='tight')
    print("✓ 組合價值曲線圖已保存")
    plt.close()


def generate_performance_metrics_chart():
    """生成績效指標對比圖"""

    # 數據來自回測結果
    metrics_data = {
        '保守版': {
            '年化收益': 0.00,
            'Sharpe': 0.1518,
            '最大回撤': -52.73,
            '交易次': 9
        },
        '中等版': {
            '年化收益': 4.09,
            'Sharpe': 0.2914,
            '最大回撤': -54.17,
            '交易次': 6
        },
        '激進版': {
            '年化收益': 4.09,
            'Sharpe': 0.2926,
            '最大回撤': -55.09,
            '交易次': 3
        }
    }

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('三個版本的績效指標對比', fontsize=16, fontweight='bold')

    versions = list(metrics_data.keys())

    # 1. 年化收益
    ax1 = axes[0, 0]
    annual_returns = [metrics_data[v]['年化收益'] for v in versions]
    colors = ['#ef5350' if r == 0 else '#26a69a' for r in annual_returns]
    bars = ax1.bar(versions, annual_returns, color=colors, alpha=0.7)
    ax1.set_ylabel('年化收益 (%)')
    ax1.set_title('年化收益對比')
    ax1.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax1.grid(axis='y', alpha=0.3)
    for bar in bars:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}%', ha='center', va='bottom' if height >= 0 else 'top')

    # 2. Sharpe比率
    ax2 = axes[0, 1]
    sharpe_ratios = [metrics_data[v]['Sharpe'] for v in versions]
    bars = ax2.bar(versions, sharpe_ratios, color='#42a5f5', alpha=0.7)
    ax2.set_ylabel('Sharpe比率')
    ax2.set_title('Sharpe比率對比 (越高越好)')
    ax2.grid(axis='y', alpha=0.3)
    for bar in bars:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.4f}', ha='center', va='bottom')

    # 3. 最大回撤
    ax3 = axes[1, 0]
    max_drawdowns = [metrics_data[v]['最大回撤'] for v in versions]
    bars = ax3.bar(versions, max_drawdowns, color='#ef5350', alpha=0.7)
    ax3.set_ylabel('最大回撤 (%)')
    ax3.set_title('最大回撤對比 (越小越好)')
    ax3.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax3.grid(axis='y', alpha=0.3)
    for bar in bars:
        height = bar.get_height()
        ax3.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}%', ha='center', va='top')

    # 4. 交易次數
    ax4 = axes[1, 1]
    trade_counts = [metrics_data[v]['交易次'] for v in versions]
    bars = ax4.bar(versions, trade_counts, color='#ffa726', alpha=0.7)
    ax4.set_ylabel('交易次數')
    ax4.set_title('交易頻率對比')
    ax4.grid(axis='y', alpha=0.3)
    for bar in bars:
        height = bar.get_height()
        ax4.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(height)}', ha='center', va='bottom')

    plt.tight_layout()
    plt.savefig('/home/tom/TX_Quantitative_Trading/reports/performance_metrics_comparison.png',
                dpi=300, bbox_inches='tight')
    print("✓ 績效指標對比圖已保存")
    plt.close()


def generate_neutral_reduction_chart():
    """生成NEUTRAL比例削減的進度圖"""

    versions = ['舊參數', '保守版', '中等版', '激進版']
    neutral_values = [45.0, 5.6, 4.7, 0.0]
    colors = ['#ef5350', '#ffa726', '#4db8ff', '#26a69a']

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('NEUTRAL比例削減成果', fontsize=16, fontweight='bold')

    # 1. 柱狀圖
    bars = ax1.bar(versions, neutral_values, color=colors, alpha=0.7, edgecolor='black', linewidth=1.5)
    ax1.set_ylabel('NEUTRAL比例 (%)')
    ax1.set_title('各版本的NEUTRAL比例')
    ax1.axhline(y=10, color='orange', linestyle='--', linewidth=1, label='目標線 (< 10%)')
    ax1.axhline(y=30, color='red', linestyle='--', linewidth=1, label='舊參數 (45%)')
    ax1.legend()
    ax1.grid(axis='y', alpha=0.3)

    for bar in bars:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.1f}%', ha='center', va='bottom', fontweight='bold')

    # 2. 降低比例趨勢
    reductions = [0, 45-5.6, 45-4.7, 45-0]
    percentages = [0, (45-5.6)/45*100, (45-4.7)/45*100, (45-0)/45*100]

    ax2.plot(versions, reductions, marker='o', markersize=10, linewidth=2.5,
            color='#1e88e5', label='絕對降低值')
    ax2.fill_between(range(len(versions)), reductions, alpha=0.3, color='#1e88e5')
    ax2.set_ylabel('NEUTRAL降低值 (%點)')
    ax2.set_title('NEUTRAL比例削減進度')
    ax2.grid(True, alpha=0.3)
    ax2.legend()

    for i, (ver, red, pct) in enumerate(zip(versions, reductions, percentages)):
        ax2.text(i, red + 1, f'{red:.1f}%\n({pct:.1f}%)',
                ha='center', fontweight='bold', fontsize=9)

    plt.tight_layout()
    plt.savefig('/home/tom/TX_Quantitative_Trading/reports/neutral_reduction_progress.png',
                dpi=300, bbox_inches='tight')
    print("✓ NEUTRAL削減進度圖已保存")
    plt.close()


def main():
    """生成所有對比圖表"""

    print("生成環境檢測參數優化對比圖表...\n")

    try:
        print("1. 生成環境分佈對比圖...")
        generate_environment_distribution_chart()

        print("2. 生成組合價值曲線對比...")
        generate_portfolio_value_chart()

        print("3. 生成績效指標對比圖...")
        generate_performance_metrics_chart()

        print("4. 生成NEUTRAL削減進度圖...")
        generate_neutral_reduction_chart()

        print("\n✓ 所有圖表已生成完成！")
        print("\n圖表位置:")
        print("  - /home/tom/TX_Quantitative_Trading/reports/environment_distribution_comparison.png")
        print("  - /home/tom/TX_Quantitative_Trading/reports/portfolio_value_comparison.png")
        print("  - /home/tom/TX_Quantitative_Trading/reports/performance_metrics_comparison.png")
        print("  - /home/tom/TX_Quantitative_Trading/reports/neutral_reduction_progress.png")

    except Exception as e:
        print(f"❌ 生成圖表時出錯: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
