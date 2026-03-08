"""
新聞因果分析 - 分析新聞發布時間 vs 股價漲幅時間 vs 大戶行為
"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from datetime import datetime, timedelta
import time

def get_db_connection():
    return psycopg2.connect(
        host="localhost", port=5432, dbname="tdcc",
        user="tdcc", password="tdcc1234"
    )

def get_remote_driver(docker_host='localhost', docker_port=4444):
    """連接到 Docker 容器內的 Selenium"""
    chrome_options = ChromeOptions()
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')

    remote_url = f'http://{docker_host}:{docker_port}/wd/hub'

    try:
        driver = webdriver.Remote(command_executor=remote_url, options=chrome_options)
        return driver
    except:
        return None

def fetch_wantgoo_news_by_date(stock_code, start_date, end_date, driver):
    """爬取日期範圍內的新聞"""
    try:
        url = f'https://www.wantgoo.com/stock/{stock_code}/news'
        driver.get(url)
        time.sleep(2)

        news_items = []
        items = driver.find_elements(By.XPATH, '//div[@class="news-item"]')

        if items:
            for item in items:
                try:
                    date_elem = item.find_element(By.CLASS_NAME, 'news-date')
                    link_elem = item.find_element(By.CLASS_NAME, 'news-link')

                    date_str = date_elem.text
                    title = link_elem.text

                    # 簡單的日期解析 (例如 "2023-01-15")
                    if date_str and title:
                        news_items.append({
                            'date': date_str,
                            'title': title
                        })
                except:
                    pass

        return news_items

    except Exception as e:
        return []

def analyze_price_movement(stock_code, buy_date, exit_date):
    """分析交易期間的股價變動"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT date, close_price FROM daily_prices
        WHERE stock_code = %s::text AND date >= %s AND date <= %s
        ORDER BY date
    """, (str(stock_code), buy_date, exit_date))

    prices = cursor.fetchall()
    conn.close()

    if not prices:
        return None

    # 分析每天的漲幅
    entry_price = float(prices[0]['close_price'])
    daily_movements = []

    for i, price_row in enumerate(prices):
        price = float(price_row['close_price'])
        pct_change = (price - entry_price) / entry_price * 100
        days_from_entry = i

        daily_movements.append({
            'date': price_row['date'],
            'days_from_entry': days_from_entry,
            'price': price,
            'pct_change': pct_change
        })

    return daily_movements

def analyze_tdcc_behavior(stock_code, signal_date, buy_date):
    """分析大戶在交易期間的行為"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # 獲取信號日期前後的 TDCC 數據
    cursor.execute("""
        SELECT date, ratio_400_above, ratio_1000_above, total_holders
        FROM holdings
        WHERE stock_code = %s AND date >= %s AND date <= %s
        ORDER BY date
    """, (stock_code,
          (datetime.strptime(signal_date, '%Y%m%d') - timedelta(days=30)).strftime('%Y%m%d'),
          buy_date))

    holdings = cursor.fetchall()
    conn.close()

    return holdings if holdings else []

# ── 主程式 ──

print("="*80)
print("新聞因果分析系統")
print("="*80 + "\n")

# 讀取交易清單
trades_df = pd.read_csv('v8/trades_6week_detail.csv')

# 篩選盈利的交易（更容易看出新聞推升效果）
profitable_trades = trades_df[trades_df['net_return_pct'] > 5].head(10)
losing_trades = trades_df[trades_df['net_return_pct'] < -5].head(10)

print(f"✓ 盈利交易（>5%）：{len(profitable_trades)} 筆")
print(f"✓ 虧損交易（<-5%）：{len(losing_trades)} 筆\n")

# 啟動 Docker Selenium
print("連接 Docker Selenium...")
driver = get_remote_driver()

if not driver:
    print("✗ 無法連接到 Docker Selenium")
    print("\n手動分析模式：分析交易清單中的股價變動")
    print("\n盈利交易範例（前 5 筆）：")
    print(profitable_trades[['stock', 'buy_date', 'exit_date', 'entry_price', 'exit_price', 'net_return_pct']].head().to_string())
    print("\n虧損交易範例（前 5 筆）：")
    print(losing_trades[['stock', 'buy_date', 'exit_date', 'entry_price', 'exit_price', 'net_return_pct']].head().to_string())
else:
    print("✓ 連接成功\n")

    # 分析前 5 個盈利交易
    print("分析盈利交易（>5%）的新聞：\n")

    for idx, row in profitable_trades.head(5).iterrows():
        stock = row['stock']
        buy_date = str(int(row['buy_date']))
        exit_date = str(int(row['exit_date']))
        ret = row['net_return_pct']

        print(f"📊 {stock} | {buy_date} 買 → {exit_date} 賣 | 報酬 {ret:+.2f}%")

        # 爬新聞
        news = fetch_wantgoo_news_by_date(stock, buy_date, exit_date, driver)
        if news:
            print(f"  ✓ 找到 {len(news)} 條新聞：")
            for n in news[:3]:
                print(f"    • [{n['date']}] {n['title'][:50]}")
        else:
            print(f"  ⚠️ 無新聞或爬取失敗")

        # 分析股價變動
        price_movements = analyze_price_movement(stock, buy_date, exit_date)
        if price_movements:
            print(f"  股價變動：")
            for pm in price_movements[:5]:
                print(f"    • Day {pm['days_from_entry']}: {pm['pct_change']:+.2f}%")

        print()
        time.sleep(1)

    driver.quit()

print("="*80)
print("✓ 分析完成")
print("="*80)

# 導出結果供進一步分析
analysis_output = {
    'profitable_trades': profitable_trades[['stock', 'buy_date', 'exit_date', 'net_return_pct']].to_dict('records'),
    'losing_trades': losing_trades[['stock', 'buy_date', 'exit_date', 'net_return_pct']].to_dict('records'),
}

print("\n建議檢查的交易：")
print("\n盈利交易（需驗證新聞是否後發）：")
for trade in analysis_output['profitable_trades'][:3]:
    print(f"  • {trade['stock']}: {trade['buy_date']} → {trade['exit_date']} ({trade['net_return_pct']:+.2f}%)")

print("\n虧損交易（驗證是否缺乏新聞支持）：")
for trade in analysis_output['losing_trades'][:3]:
    print(f"  • {trade['stock']}: {trade['buy_date']} → {trade['exit_date']} ({trade['net_return_pct']:+.2f}%)")
