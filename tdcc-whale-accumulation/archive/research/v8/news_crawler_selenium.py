"""
用 Selenium 爬取 WantGoo 股票新聞
"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

import psycopg2
from psycopg2.extras import RealDictCursor
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from datetime import datetime, timedelta
import pandas as pd
import time

def get_db_connection():
    return psycopg2.connect(
        host="localhost", port=5432, dbname="tdcc",
        user="tdcc", password="tdcc1234"
    )

def fetch_wantgoo_news(stock_code, max_wait=10):
    """從 WantGoo 抓取股票新聞"""
    try:
        # 初始化 Chrome WebDriver
        options = webdriver.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        # options.add_argument('--headless')  # 去掉註解可無頭運行

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )

        url = f'https://www.wantgoo.com/stock/{stock_code}/news'
        print(f"  → 訪問 {url}")
        driver.get(url)

        # 等待新聞容器加載
        try:
            WebDriverWait(driver, max_wait).until(
                EC.presence_of_all_elements_located((By.CLASS_NAME, 'news-item'))
            )
        except:
            print(f"  ⚠️ 未能加載新聞容器，嘗試查找其他元素...")

        # 嘗試多種選擇器查找新聞項目
        news_items = []

        # 方法 1：查找新聞項目
        try:
            items = driver.find_elements(By.CLASS_NAME, 'news-item')
            if items:
                print(f"  ✓ 找到 {len(items)} 條新聞（news-item）")
                for item in items:
                    try:
                        title = item.find_element(By.TAG_NAME, 'a').text
                        date = item.find_element(By.CLASS_NAME, 'news-date').text
                        news_items.append({'title': title, 'date': date})
                    except:
                        pass
        except:
            pass

        # 方法 2：查找表格行（舊版本）
        if not news_items:
            try:
                rows = driver.find_elements(By.CSS_SELECTOR, 'table tr')
                if rows:
                    print(f"  ✓ 找到 {len(rows)} 行表格")
                    for row in rows[1:]:  # 跳過表頭
                        try:
                            cells = row.find_elements(By.TAG_NAME, 'td')
                            if len(cells) >= 2:
                                date = cells[0].text
                                title = cells[1].text
                                if date and title:
                                    news_items.append({'title': title, 'date': date})
                        except:
                            pass
            except:
                pass

        # 方法 3：查找所有 a 標籤和日期
        if not news_items:
            try:
                links = driver.find_elements(By.TAG_NAME, 'a')
                print(f"  ℹ️ 頁面有 {len(links)} 個超連結")

                # 嘗試找新聞相關的連結
                for link in links:
                    try:
                        href = link.get_attribute('href')
                        if 'news' in href or '新聞' in link.text:
                            print(f"    - {link.text[:50]}")
                    except:
                        pass
            except:
                pass

        driver.quit()
        return news_items

    except Exception as e:
        print(f"  ✗ 爬蟲錯誤：{e}")
        try:
            driver.quit()
        except:
            pass
        return []

def fetch_trades_from_db():
    """從資料庫獲取交易記錄"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT DISTINCT stock_code FROM daily_prices
        WHERE stock_code NOT LIKE '00%%'
        LIMIT 20
    """)

    stocks = [row['stock_code'] for row in cursor.fetchall()]
    conn.close()
    return stocks

# ── 主程式 ──

print("="*80)
print("WantGoo 新聞爬蟲 - Selenium 版本")
print("="*80 + "\n")

# 測試幾支股票
test_stocks = ['6217', '8054', '4991', '2465', '2743', '8422', '3056', '4772']

all_news = {}

for stock in test_stocks:
    print(f"\n📰 {stock}：")
    news = fetch_wantgoo_news(stock, max_wait=15)

    if news:
        print(f"  ✅ 成功抓取 {len(news)} 條新聞")
        for item in news[:5]:  # 只顯示前 5 條
            print(f"    • [{item['date']}] {item['title'][:60]}")
        all_news[stock] = news
    else:
        print(f"  ⚠️ 無新聞或加載失敗")

    time.sleep(2)  # 延遲以避免被封

print(f"\n{'='*80}")
print(f"總結：成功取得新聞的股票：{list(all_news.keys())}")
print(f"{'='*80}")
