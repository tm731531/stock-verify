# TDCC 大戶吃貨爬蟲系統 實施計畫

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 建立自動爬蟲系統，蒐集所有台股的 TDCC「400張以上流動持股占比」歷史數據，為大戶吃貨與飆股現象進行實證分析。

**Architecture:**
- Phase 1：初始化 - 爬蟲環境設置 + 股票代號列表
- Phase 2：核心爬蟲 - Selenium 自動化查詢 TDCC 網頁，逐股遍歷日期選單提取數據
- Phase 3：數據管理 - 存儲、清理、去重、與日K線配對
- Phase 4：分析驗證 - 統計吃貨→飆股的成功率、等待時間、標的分類

**Tech Stack:**
- Selenium (網頁自動化)
- Pandas (數據處理)
- SQLite/CSV (數據存儲)
- Requests (HTTP 查詢)
- Pytest (測試框架)

---

## Task 1: 項目初始化與依賴安裝

**Files:**
- Create: `src/crawler/requirements.txt`
- Create: `src/crawler/__init__.py`
- Create: `tests/crawler/__init__.py`

**Step 1: 創建 requirements.txt**

```txt
selenium==4.15.2
pandas==2.1.0
requests==2.31.0
pytest==7.4.3
pytest-cov==4.1.0
python-dotenv==1.0.0
yfinance==0.2.32
```

**Step 2: 安裝依賴**

```bash
cd /home/tom/stock-verify/tdcc-whale-accumulation
pip install -r src/crawler/requirements.txt
```

Expected: 所有套件成功安裝

**Step 3: 建立爬蟲模組結構**

```bash
touch src/crawler/__init__.py tests/crawler/__init__.py
```

**Step 4: Commit**

```bash
git add src/crawler/requirements.txt src/crawler/__init__.py tests/crawler/__init__.py
git commit -m "chore: init tdcc crawler project structure"
```

---

## Task 2: 獲取股票代號列表

**Files:**
- Create: `src/crawler/stock_list.py`
- Create: `tests/crawler/test_stock_list.py`

**Step 1: 寫失敗測試**

```python
# tests/crawler/test_stock_list.py
import pytest
from src.crawler.stock_list import get_twse_stock_list

def test_get_twse_stock_list_returns_list():
    """Should return list of stock codes"""
    stocks = get_twse_stock_list()
    assert isinstance(stocks, list)
    assert len(stocks) > 0
    assert all(isinstance(code, str) for code in stocks)
    # Taiwan stocks should have codes like '0050', '1101', etc.
    assert any(code in stocks for code in ['0050', '1101', '2330'])

def test_stock_code_format():
    """Stock codes should be 4-digit strings"""
    stocks = get_twse_stock_list()
    for code in stocks:
        assert len(code) == 4
        assert code.isdigit()
```

**Step 2: 運行測試驗證失敗**

```bash
pytest tests/crawler/test_stock_list.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'src.crawler.stock_list'`

**Step 3: 實現最小代碼**

```python
# src/crawler/stock_list.py
import requests
from typing import List

def get_twse_stock_list() -> List[str]:
    """
    獲取台灣證交所上市股票代號
    Uses Taiwan Stock Exchange official API
    """
    try:
        # TWSE 官方 API - 上市股票列表
        url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL"
        params = {'response': 'json', 'date': '20240101'}

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        stock_codes = []
        if 'data' in data:
            for item in data['data']:
                # Format: ['code', 'name', ...]
                stock_codes.append(item[0])

        return sorted(stock_codes)

    except Exception as e:
        print(f"Error fetching stock list: {e}")
        return []
```

**Step 4: 運行測試驗證通過**

```bash
pytest tests/crawler/test_stock_list.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/crawler/stock_list.py tests/crawler/test_stock_list.py
git commit -m "feat: add stock list fetcher from TWSE"
```

---

## Task 3: 設計 TDCC 爬蟲核心架構

**Files:**
- Create: `src/crawler/tdcc_scraper.py`
- Create: `tests/crawler/test_tdcc_scraper.py`

**Step 1: 寫失敗測試 - 爬蟲初始化**

```python
# tests/crawler/test_tdcc_scraper.py
import pytest
from src.crawler.tdcc_scraper import TDCCScraper

def test_tdcc_scraper_init():
    """Should initialize scraper with headless browser"""
    scraper = TDCCScraper()
    assert scraper is not None
    assert scraper.driver is not None

def test_tdcc_scraper_query_stock():
    """Should query TDCC website for a stock"""
    scraper = TDCCScraper()
    # 用台積電 (2330) 測試
    result = scraper.query_stock('2330')
    assert result is not None
    assert isinstance(result, list)
    assert len(result) > 0
    # 每筆紀錄應有日期、占比等字段
    assert 'date' in result[0]
    assert 'ratio_400_above' in result[0]
    scraper.close()
```

**Step 2: 運行測試驗證失敗**

```bash
pytest tests/crawler/test_tdcc_scraper.py::test_tdcc_scraper_init -v
```

Expected: FAIL - `ModuleNotFoundError`

**Step 3: 實現 Selenium 爬蟲架構**

```python
# src/crawler/tdcc_scraper.py
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from typing import List, Dict
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TDCCScraper:
    """爬蟲類 - 蒐集 TDCC 大戶持股數據"""

    def __init__(self):
        """初始化 Selenium WebDriver (headless)"""
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

        self.driver = webdriver.Chrome(options=options)
        self.base_url = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
        self.wait = WebDriverWait(self.driver, 10)

    def query_stock(self, stock_code: str) -> List[Dict]:
        """
        查詢單支股票的所有歷史數據

        Args:
            stock_code: 股票代號 (e.g., '2330')

        Returns:
            列表，包含日期、占比等數據
        """
        try:
            logger.info(f"Querying stock {stock_code}...")
            self.driver.get(self.base_url)

            # 等待頁面加載
            time.sleep(2)

            # 輸入股票代號
            stock_input = self.wait.until(
                EC.presence_of_element_located((By.ID, "txtStockNo"))
            )
            stock_input.clear()
            stock_input.send_keys(stock_code)

            # 點擊查詢按鈕
            query_btn = self.driver.find_element(By.ID, "btnQuery")
            query_btn.click()

            # 等待結果加載
            time.sleep(2)

            # 提取日期選單中所有可用日期
            date_dropdown = Select(self.driver.find_element(By.ID, "ddlYear"))
            dates = [option.get_attribute("value") for option in date_dropdown.options[1:]]

            all_data = []

            # 遍歷每個日期
            for date in dates:
                date_dropdown = Select(self.driver.find_element(By.ID, "ddlYear"))
                date_dropdown.select_by_value(date)
                time.sleep(1)

                # 提取該日期的數據
                try:
                    table = self.driver.find_element(By.ID, "gvStockInfo")
                    rows = table.find_elements(By.TAG_NAME, "tr")[1:]  # Skip header

                    for row in rows:
                        cols = row.find_elements(By.TAG_NAME, "td")
                        if len(cols) >= 2:
                            all_data.append({
                                'date': date,
                                'ratio_400_above': cols[1].text,
                                'stock_code': stock_code
                            })
                except Exception as e:
                    logger.warning(f"Error extracting data for date {date}: {e}")
                    continue

            logger.info(f"✓ Retrieved {len(all_data)} records for stock {stock_code}")
            return all_data

        except Exception as e:
            logger.error(f"Error querying stock {stock_code}: {e}")
            return []

    def close(self):
        """關閉瀏覽器"""
        self.driver.quit()
```

**Step 4: 運行測試驗證通過**

```bash
pytest tests/crawler/test_tdcc_scraper.py::test_tdcc_scraper_init -v
```

Expected: PASS (初始化成功)

**注：** `test_tdcc_scraper_query_stock` 會因網頁結構而需微調，待實際測試後優化

**Step 5: Commit**

```bash
git add src/crawler/tdcc_scraper.py tests/crawler/test_tdcc_scraper.py
git commit -m "feat: implement selenium-based tdcc scraper"
```

---

## 後續 Tasks（詳見實施階段）

- Task 4: 數據存儲與管理
- Task 5: 整合爬蟲與主程序
- Task 6: 分析框架 - 識別吃貨與飆股
- Task 7: 統計分析報告
- Task 8: 端到端測試與驗證
- Task 9: 日K線數據整合
