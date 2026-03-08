"""
新聞爬蟲 - 爬取成功 & 失敗交易期間的新聞
==========================================

方案：使用 Google 新聞搜尋（透過網頁爬蟲）
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd
import time
import json

def search_news_google(stock_code, start_date, end_date):
    """
    使用 Google 新聞搜尋
    返回該股票在時間段內的新聞標題
    """
    try:
        # 格式化日期
        start_str = datetime.strptime(start_date, '%Y%m%d').strftime('%Y-%m-%d')
        end_str = datetime.strptime(end_date, '%Y%m%d').strftime('%Y-%m-%d')
        
        # Google 新聞搜尋 URL（台湾新闻）
        url = f"https://news.google.com/search?q={stock_code}%20{start_str}..{end_str}&hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 提取新聞標題
        articles = []
        for item in soup.find_all('article'):
            title_elem = item.find('h3')
            if title_elem:
                articles.append(title_elem.get_text())
        
        return articles
        
    except Exception as e:
        print(f"  ⚠️ 搜尋失敗：{e}")
        return []

def search_news_yahoo(stock_code, start_date, end_date):
    """
    使用 Yahoo Finance 台股新聞
    """
    try:
        start_dt = datetime.strptime(start_date, '%Y%m%d')
        end_dt = datetime.strptime(end_date, '%Y%m%d')
        
        # Yahoo Finance 新聞 API（台股）
        url = f"https://tw.stock.yahoo.com/quote/{stock_code}/news"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 提取新聞標題和日期
        articles = []
        for item in soup.find_all('h2'):
            if item.get_text().strip():
                articles.append(item.get_text().strip())
        
        return articles[:5]  # 返回最新5則
        
    except Exception as e:
        print(f"  ⚠️ Yahoo 搜尋失敗：{e}")
        return []

print("="*80)
print("新聞分析：成功 vs 失敗交易的新聞特徵")
print("="*80)
print()

# 讀取交易列表
try:
    trades_df = pd.read_csv('/tmp/trades_for_news_analysis.csv')
    success_trades = trades_df[trades_df['net_return_pct'] > 0].sort_values('net_return_pct', ascending=False)
    failed_trades = trades_df[trades_df['net_return_pct'] <= 0].sort_values('net_return_pct')
    
    print(f"✓ 讀取交易列表：{len(trades_df)} 筆交易")
    print(f"  成功：{len(success_trades)} 筆 | 失敗：{len(failed_trades)} 筆")
    print()
    
except Exception as e:
    print(f"❌ 讀取失敗：{e}")
    exit(1)

# ── 分析成功交易的新聞 ──

print("【成功交易新聞分析】")
print("="*80)

success_news_data = []

for idx, row in success_trades.head(10).iterrows():
    stock = row['stock']
    buy_date = row['buy_date']
    exit_date = row['exit_date']
    return_pct = row['net_return_pct']
    
    print(f"\n{idx+1}. 【{stock}】 {buy_date} → {exit_date} (收益 {return_pct:+.1f}%)")
    
    # 爬取新聞
    news_count = 0
    print("  爬取新聞中...")
    time.sleep(1)  # 禮貌延遲
    
    # 嘗試 Google 新聞
    articles = search_news_google(stock, buy_date, exit_date)
    if articles:
        print(f"  ✓ 找到 {len(articles)} 則新聞：")
        for article in articles[:3]:
            print(f"    - {article[:60]}...")
            news_count += len(articles)
    else:
        print(f"  ⚠️ 未找到新聞")
    
    success_news_data.append({
        'stock': stock,
        'return_pct': return_pct,
        'news_count': news_count,
        'news_found': len(articles) > 0,
    })

# ── 分析失敗交易的新聞 ──

print("\n\n【失敗交易新聞分析】")
print("="*80)

failed_news_data = []

for idx, row in failed_trades.head(10).iterrows():
    stock = row['stock']
    buy_date = row['buy_date']
    exit_date = row['exit_date']
    return_pct = row['net_return_pct']
    
    print(f"\n{idx+1}. 【{stock}】 {buy_date} → {exit_date} (虧損 {return_pct:+.1f}%)")
    
    # 爬取新聞
    news_count = 0
    print("  爬取新聞中...")
    time.sleep(1)  # 禮貌延遲
    
    # 嘗試 Google 新聞
    articles = search_news_google(stock, buy_date, exit_date)
    if articles:
        print(f"  ⚠️ 找到 {len(articles)} 則新聞：")
        for article in articles[:3]:
            print(f"    - {article[:60]}...")
        news_count = len(articles)
    else:
        print(f"  ✓ 未找到新聞")
    
    failed_news_data.append({
        'stock': stock,
        'return_pct': return_pct,
        'news_count': news_count,
        'news_found': len(articles) > 0,
    })

# ── 統計對比 ──

print("\n\n【統計對比】")
print("="*80)

if success_news_data and failed_news_data:
    success_df = pd.DataFrame(success_news_data)
    failed_df = pd.DataFrame(failed_news_data)
    
    print(f"\n成功交易新聞統計：")
    print(f"  有新聞的筆數：{success_df['news_found'].sum()}/{len(success_df)}")
    print(f"  平均新聞數：{success_df['news_count'].mean():.1f} 則")
    
    print(f"\n失敗交易新聞統計：")
    print(f"  有新聞的筆數：{failed_df['news_found'].sum()}/{len(failed_df)}")
    print(f"  平均新聞數：{failed_df['news_count'].mean():.1f} 則")
    
    print(f"\n【結論】")
    if success_df['news_found'].sum() > failed_df['news_found'].sum():
        print("✓ 成功交易的新聞更多")
        print("→ 新聞有推升效應！")
    elif failed_df['news_found'].sum() > success_df['news_found'].sum():
        print("✗ 失敗交易的新聞更多")
        print("→ 可能是負面新聞導致下跌")
    else:
        print("≈ 兩者新聞數量相似")
        print("→ 新聞不是主要因素")

print("\n" + "="*80)
print("⚠️  注意：Google 新聞搜尋可能需要處理反爬蟲。")
print("建議改用台股新聞網站 API 或專業金融資料源。")
print("="*80)

