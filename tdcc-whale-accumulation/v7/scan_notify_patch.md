# scan_notify.py 修改說明

## 說明

兩邊差異過大，請直接以 **`scan_notify_v2.py`** 為基準重做。
你需要做的是：把裡面的**資料層**替換成你自己的實作，其餘邏輯保持不動。

---

## 需要比對 / 替換的部分

### 1. 路徑設定
```python
BASE_DIR     = Path(__file__).parent
DB_PATH      = BASE_DIR.parent / 'data' / 'tdcc_holdings.db'
CONFIG_PATH  = BASE_DIR / 'scanner_config.json'
STATE_PATH   = BASE_DIR / 'scanner_state.json'
FETCH_SCRIPT = BASE_DIR / 'fetch_tdcc.py'
```
確認 DB 路徑、config、state、抓取腳本路徑是否相同。

---

### 2. 資料表結構

`load_stock_data()` 對應的 SQL：
```sql
SELECT stock_code, date, ratio_400_above, ratio_1000_above, total_holders
FROM holdings
ORDER BY stock_code, date
```
欄位順序 index：`[0]=stock_code, [1]=date, [2]=ratio_400_above, [3]=ratio_1000_above, [4]=total_holders`

`load_price_data()` 對應的 SQL：
```sql
SELECT stock_code, date, close_price
FROM daily_prices
```

---

### 3. Norway 探測（若你有不同實作可替換）
```python
def norway_latest_date(sample='3443') -> str:
    # 抓 norway.twsthr.info 判斷最新 TDCC 日期
    ...
```

---

### 4. 抓取驅動
```python
def try_fetch() -> bool:
    # 呼叫 fetch_tdcc.py
    ...
```

---

## 邏輯說明（不要動）

| 模組 | 說明 |
|------|------|
| `scan_main_signals()` | 主引擎：連升≥3週 + 大戶↑≥3% + 同步≥50% + 散戶↓≥2% + 股價≥300，用 cummax 永久排除異常股 |
| `scan_backup_signals()` | 補位引擎：4週持有人↓≥5% + 站上MA20 + 股價≥50，只用 TDCC 當天收盤，不查未來 |
| `build_message()` | 主引擎有訊號 → 只發主引擎；無訊號 → 補位前5名 |
| 通知去重 | 以主引擎 `signal_date` 為準，存在 `scanner_state.json` |

---

## 通知樣式

### 主引擎有訊號時
```
🐋 TDCC 鯨魚掃描｜03/06
最新資料：2026/02/26

🎯 主引擎 3 個（TDCC 2026/02/26）
訊號日後跳過2天，第3天起觀察收盤≤限價，隔天掛單（最多等5天）

【6584】連升3週｜大戶+5.7%｜同步73.5%
  收盤 425 → 限價 ≤ 437.8 → 停損 ≤ 407.2
  大戶比例 79.02%｜散戶-26.0%

🛑 停損＝限價×0.93｜停利：+15%啟動，回落10%出場｜最長90天
```

### 主引擎無訊號時（補位頂上）
```
🐋 TDCC 鯨魚掃描｜03/06
最新資料：2026/02/26

📌 補位引擎 前5（散戶出逃最多，共69個，TDCC 2026/02/26）
TDCC日後第5個交易日收盤買入

【3167】散戶跑-35.3%｜持有人12,697
  TDCC收盤 297.0｜TDCC後第5個交易日買入

🛑 停損＝限價×0.93｜停利：+15%啟動，回落10%出場｜最長90天
```

---

## 參考檔案

完整版本：`v7/scan_notify_v2.py`
