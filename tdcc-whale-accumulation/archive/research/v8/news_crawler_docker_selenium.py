"""
Docker Selenium 新聞爬蟲
連接到容器內的 Selenium Chrome 進行爬取
"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
import time
import psycopg2
from psycopg2.extras import RealDictCursor

def get_remote_driver(docker_host='localhost', docker_port=4444):
    """連接到 Docker 容器內的 Selenium"""
    chrome_options = ChromeOptions()
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')

    # 連接到遠端 Selenium
    remote_url = f'http://{docker_host}:{docker_port}/wd/hub'
    print(f"連接到遠端 Selenium：{remote_url}")

    try:
        driver = webdriver.Remote(
            command_executor=remote_url,
            options=chrome_options
        )
        print("✓ 連接成功")
        return driver
    except Exception as e:
        print(f"✗ 連接失敗：{e}")
        return None

def fetch_wantgoo_news(stock_code, driver, max_wait=10):
    """從 WantGoo 爬取新聞"""
    try:
        url = f'https://www.wantgoo.com/stock/{stock_code}/news'
        print(f"  訪問 {url}")
        driver.get(url)

        # 等待新聞區域加載
        try:
            WebDriverWait(driver, max_wait).until(
                EC.presence_of_all_elements_located((By.CLASS_NAME, 'parts_news-list'))
            )
        except:
            pass

        time.sleep(2)  # 等待 Vue 渲染

        # 查找所有新聞項目
        news_items = []
        try:
            # 方法 1：查找新聞列表
            items = driver.find_elements(By.XPATH, '//div[@class="news-item"]')

            if items:
                print(f"  ✓ 找到 {len(items)} 條新聞")
                for item in items[:10]:  # 最多 10 條
                    try:
                        # 提取日期
                        date_elem = item.find_element(By.CLASS_NAME, 'news-date')
                        date = date_elem.text if date_elem else ''

                        # 提取標題和連結
                        link_elem = item.find_element(By.CLASS_NAME, 'news-link')
                        title = link_elem.text if link_elem else ''
                        href = link_elem.get_attribute('href') if link_elem else ''

                        if date and title:
                            news_items.append({
                                'title': title,
                                'date': date,
                                'link': href
                            })
                    except Exception as e:
                        pass

            if not news_items:
                print(f"  ⚠️ 無新聞或渲染失敗")

                # 偵錯：輸出頁面中的內容
                page_source = driver.page_source
                if '目前尚無相關新聞資訊' in page_source:
                    print(f"  ℹ️ 該股票尚無新聞")
                else:
                    print(f"  ℹ️ 頁面包含內容，可能是結構差異")

        except Exception as e:
            print(f"  ✗ 解析錯誤：{e}")

        return news_items

    except Exception as e:
        print(f"  ✗ 爬蟲錯誤：{e}")
        return []

def main():
    print("="*80)
    print("Docker Selenium 新聞爬蟲")
    print("="*80 + "\n")

    # 連接到遠端 Selenium
    driver = get_remote_driver()
    if not driver:
        print("\n✗ 無法連接到 Docker Selenium，請確保容器正在運行")
        print("\n請執行：")
        print("  docker run -d -p 4444:4444 --name selenium-chrome selenium/standalone-chromium:latest")
        return

    test_stocks = ['6217', '8054', '4991', '2465', '2743']

    all_news = {}

    try:
        for stock in test_stocks:
            print(f"\n📰 {stock}：")
            news = fetch_wantgoo_news(stock, driver)

            if news:
                all_news[stock] = news
                for item in news[:3]:
                    print(f"    [{item['date']}] {item['title'][:60]}")

            time.sleep(2)

    finally:
        driver.quit()
        print("\n✓ 瀏覽器已關閉")

    print(f"\n{'='*80}")
    print(f"總結：成功取得新聞的股票：{list(all_news.keys())}")
    print(f"{'='*80}")

if __name__ == '__main__':
    main()
