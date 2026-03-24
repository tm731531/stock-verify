"""
簡化爬蟲 - requests + BeautifulSoup
嘗試直接爬取 WantGoo 新聞（無需瀏覽器）
"""

import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime

# User-Agent 偽造
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def fetch_news_from_wantgoo(stock_code):
    """直接從 WantGoo 爬取新聞"""
    url = f'https://www.wantgoo.com/stock/{stock_code}/news'

    try:
        print(f"  → 訪問 {url}")
        response = requests.get(url, headers=HEADERS, timeout=10)

        if response.status_code != 200:
            print(f"  ✗ HTTP {response.status_code}")
            return []

        soup = BeautifulSoup(response.content, 'html.parser')

        # 查找新聞項目
        news_items = []

        # 方法 1：查找 news-item 類別
        items = soup.find_all('div', class_='news-item')
        if items:
            print(f"  ✓ 找到 {len(items)} 條新聞")
            for item in items:
                try:
                    title_elem = item.find('a')
                    date_elem = item.find('span', class_='news-date')

                    if title_elem and date_elem:
                        news_items.append({
                            'title': title_elem.text.strip(),
                            'date': date_elem.text.strip(),
                            'link': title_elem.get('href', '')
                        })
                except:
                    pass

        # 方法 2：查找表格
        if not news_items:
            table = soup.find('table')
            if table:
                rows = table.find_all('tr')[1:]  # 跳過表頭
                print(f"  ✓ 找到 {len(rows)} 行新聞表格")
                for row in rows:
                    try:
                        cells = row.find_all('td')
                        if len(cells) >= 2:
                            date = cells[0].text.strip()
                            title_link = cells[1].find('a')
                            if title_link:
                                news_items.append({
                                    'title': title_link.text.strip(),
                                    'date': date,
                                    'link': title_link.get('href', '')
                                })
                    except:
                        pass

        return news_items

    except Exception as e:
        print(f"  ✗ 爬蟲錯誤：{e}")
        return []

# ── 主程式 ──

print("="*80)
print("簡化新聞爬蟲 - requests 版本")
print("="*80 + "\n")

test_stocks = ['2330', '6217', '8054', '4991']

for stock in test_stocks:
    print(f"\n📰 {stock}：")
    news = fetch_news_from_wantgoo(stock)

    if news:
        print(f"  ✅ 成功抓取 {len(news)} 條新聞")
        for item in news[:3]:
            print(f"    • [{item['date']}] {item['title'][:50]}")
    else:
        print(f"  ⚠️ 無新聞或頁面結構不同")

    time.sleep(1)  # 禮貌延遲
