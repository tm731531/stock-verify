# 期交所台指期爬蟲使用指南

## 🚀 快速開始

### 1. 安裝依賴
```bash
pip install -r requirements_taifex.txt
```

### 2. 執行爬蟲
```bash
python taifex_crawler.py
```

---

## 📋 配置說明

編輯 `taifex_crawler.py` 的主程序配置區：

```python
# ========== 配置區域 ==========

PRODUCT_ID = "TX"          # 'TX' = 大台, 'MTX' = 小台
START_DATE = "2024-01-01"  # 開始日期
END_DATE = "2025-02-27"    # 結束日期
OUTPUT_DIR = "./taifex_data"
```

### 期貨代碼
- **TX** - 台指期貨 (Taiwan Index Futures) - 大台
- **MTX** - 台指期貨微型 (Micro Taiwan Index Futures) - 小台
- 可自由替換其他期貨代碼 (如: GC=黃金, CL=原油等)

---

## 📊 功能特性

### ✅ 已實現功能
1. **OpenAPI 直接調用** - 無第三方庫依賴，直接調用期交所官方API
2. **日期範圍爬蟲** - 支持指定起迄日期自動迴圈爬取
3. **自動跳過週末** - 不會浪費 API 請求在無交易日
4. **API 限流保護** - 內置 0.5 秒延遲，避免被 IP 封禁
5. **數據清理** - 自動去除 NaN、去重、排序
6. **去重機制** - 同日期同合約只保留最新數據
7. **CSV 輸出** - UTF-8 編碼，支援中文
8. **詳細日誌** - 實時顯示進度和錯誤信息
9. **最新合約篩選** - 自動提取最近期合約用於分析

### 📁 輸出文件
爬蟲會生成兩個 CSV 檔案在 `taifex_data/` 目錄：

1. **taifex_TX_full.csv** - 全部合約的完整數據
2. **taifex_TX_latest.csv** - 僅最新期合約的數據（推薦用於技術分析）

### 📊 CSV 格式
```
Date,ContractMonth,Open,High,Low,Close,Volume,OpenInterest
2024-01-01,202401,15800,15850,15790,15830,120000,500000
2024-01-02,202401,15830,15900,15820,15890,125000,510000
```

---

## ⚡ 使用範例

### 範例 1: 爬取過去一年大台數據
```python
crawler = TAIFEXCrawler(product_id="TX", output_dir="./data")
data = crawler.fetch_date_range("2024-01-01", "2025-02-27")
cleaned = crawler.clean_data(data)
crawler.save_to_csv(cleaned, "tx_2024_2025.csv")
```

### 範例 2: 爬取小台最近三個月數據
```python
from datetime import datetime, timedelta

end_date = datetime.now().strftime('%Y-%m-%d')
start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')

crawler = TAIFEXCrawler(product_id="MTX")
data = crawler.fetch_date_range(start_date, end_date)
latest = crawler.get_latest_contract(data)
crawler.save_to_csv(latest, "mtx_3months.csv")
```

### 範例 3: 單日查詢
```python
crawler = TAIFEXCrawler()
data = crawler.fetch_date("2025-02-27")
print(data)
```

---

## 🔧 進階配置

### 調整 API 限流
```python
# 減少延遲 (速度快但風險高)
data = crawler.fetch_date_range("2024-01-01", "2025-02-27", sleep_interval=0.2)

# 增加延遲 (更保險)
data = crawler.fetch_date_range("2024-01-01", "2025-02-27", sleep_interval=1.0)
```

### 自定義輸出
```python
# 只保留特定合約
def filter_by_contract(df, contract_month):
    return df[df['ContractMonth'] == contract_month]

latest_only = filter_by_contract(cleaned_data, '202502')
crawler.save_to_csv(latest_only, "tx_202502.csv")
```

---

## ⚠️ 常見問題

### Q1: 收到 API 錯誤？
**原因**: 期交所 API 有限流保護
**解決**: 增加 sleep_interval 參數
```python
data = crawler.fetch_date_range("2024-01-01", "2025-02-27", sleep_interval=1.0)
```

### Q2: 某些日期沒有數據？
**原因**: 期貨市場休市日 (連假、股市休市)
**解決**: 正常現象，爬蟲會自動跳過週末

### Q3: 數據不完整？
**原因**: 可能是 API 伺服器問題或網路中斷
**解決**: 檢查日誌訊息，重新執行，或降低時間範圍

### Q4: 數據量很小？
**原因**: 期交所只保留近期數據，太舊的日期可能沒有
**解決**: 檢查期交所官方網站確認數據可用性

---

## 📈 下一步：進行回測

數據爬取完成後，可用於：
1. **技術分析** - 移動平均、RSI、MACD 等
2. **量化回測** - backtrader、zipline 框架
3. **策略開發** - 均值回歸、趨勢跟蹤、高頻交易
4. **風險管理** - 計算 Sharpe Ratio、Max Drawdown

---

## 📞 期交所 OpenAPI 文檔
官方文檔: https://openapi.taifex.com.tw/

**Note**: 本爬蟲調用的是公開 API，遵守期交所使用條款。
