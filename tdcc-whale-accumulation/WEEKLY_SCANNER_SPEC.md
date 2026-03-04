# 每週大戶吃貨訊號掃描器 — 設計規格書

## 目標

做一個**獨立的 Python 腳本**，每週六/日自動執行一次：
1. 抓最新兩週的 TDCC 大股東持股數據
2. 抓這些股票的最新收盤價
3. 跑策略篩選
4. 輸出結果通知我（不管有沒有訊號都要通知）

**不保留歷史資料**，每次跑完就丟掉。只需要當週和上週的數據來判斷。

---

## 系統架構

```
weekly_scanner.py          ← 唯一的主程式
├── 1. 抓 TDCC 數據 (最新 2 週)
├── 2. 抓股價 (訊號股的最新收盤)
├── 3. 策略篩選
├── 4. 輸出結果
└── (選用) 5. 通知 (LINE / Email / Telegram)
```

**不需要 database、不需要歷史資料、不需要 web framework。一個 .py 檔搞定。**

---

## Step 1: 抓 TDCC 大股東持股數據

### 資料來源

TDCC 集保中心網站：`https://www.tdcc.com.tw/portal/zh/smWeb/qryStock`

這是一個 POST 請求，需要：
1. 先 GET 頁面取得 CSRF token
2. POST 查詢指定日期的持股分散表

### 需要抓的日期

只需要**最新兩週**的 TDCC 統計日。TDCC 每週五統計，通常下週三~五公布。

日期格式：`YYYYMMDD`，例如 `20260226`、`20260213`

**怎麼知道最新的日期？** TDCC 網站有個下拉選單列出可用日期，先 GET 頁面解析出最新的兩個日期。

### 需要抓的欄位

對每一檔股票，從持股分散表取得：
- `stock_code`: 股票代碼
- `date`: TDCC 統計日
- `ratio_400_above`: 持股 400 張以上的人佔全部股東的持股比例 (%)
- `ratio_1000_above`: 持股 1000 張以上的人佔全部股東的持股比例 (%)
- `total_holders`: 總持有人數

### TDCC 的數據格式

TDCC 回傳的是一張分級距表（1-999股、1000-5000股...等級距的人數和持股比例）。你需要：
- 把「400 張以上」的所有級距的持股比例加總 = `ratio_400_above`
- 把「1000 張以上」的所有級距的持股比例加總 = `ratio_1000_above`
- 把所有級距的人數加總 = `total_holders`

注意：TDCC 的「張」= 1000 股，所以「400 張以上」= 第 15 級距以上（400,001 股以上）

### 範圍

需要查詢所有上市上櫃個股（約 2,300 檔）。每個日期 × 每檔股票 = 一次 POST 請求。

兩個日期 × 2,300 檔 = 約 4,600 次請求。建議延遲 0.3 秒，大約 25 分鐘完成。

**最佳化**：因為我們只需要股價 ≥ 300 的股票，可以先抓股價再只查高價股的 TDCC，減少請求數。但第一次跑不知道哪些 ≥ 300，所以第一次全抓，之後可以快取股票清單。

---

## Step 2: 抓股價

### 目的

取得訊號股（符合 TDCC 條件的股票）的**訊號日收盤價**，用來計算限價。

### 資料來源

- **上市 (TWSE)**：`https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=YYYYMM01&stockNo=XXXX`
  - 回傳該月的每日交易資料，取最後一天的收盤價

- **上櫃 (TPEX)**：`https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php?l=zh-tw&d=YYY/MM/DD&stkno=XXXX`
  - 民國年格式（2026 = 115）

### 怎麼判斷上市還是上櫃？

- 先試 TWSE，如果回傳 `stat != "OK"` 或沒有 `data`，就試 TPEX
- 或者用批次 API 一次抓全市場：
  - TWSE: `https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL` （只有當天）
  - TPEX: `https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&d=YYY/MM/DD`

### 只需要抓哪些股票的價格？

只需要抓 **Step 1 篩選後可能符合條件的股票**（例如 ratio 有上升的）。或者用批次 API 一次抓全市場收盤價更快。

---

## Step 3: 策略篩選

### 輸入

兩週的 TDCC 數據 + 股價。結構：

```python
# 每一筆是一個股票在某一週的數據
{
    'stock_code': '6789',
    'date': '20260226',         # 本週
    'ratio_400_above': 45.3,
    'ratio_1000_above': 38.2,
    'total_holders': 12500,
}
```

### 篩選邏輯

```python
def check_signal(this_week, last_week, price):
    """
    this_week, last_week: 同一檔股票的兩週 TDCC 數據
    price: 該股票的最新收盤價

    回傳: (是否通過, 各指標數值, 不通過原因)
    """

    # 條件 1: ratio 上升
    if this_week['ratio_400_above'] <= last_week['ratio_400_above']:
        return False, "ratio 未上升"

    # 條件 2: ratio 變化 >= 2%
    r400_chg = this_week['ratio_400_above'] - last_week['ratio_400_above']
    if r400_chg < 2.0:
        return False, f"ratio 變化 {r400_chg:.1f}% < 2%"

    # 條件 3: sync >= 50%
    r1000_chg = this_week['ratio_1000_above'] - last_week['ratio_1000_above']
    sync = r1000_chg / r400_chg if r400_chg > 0.01 else 0
    if sync < 0.5:
        return False, f"sync {sync:.0%} < 50%"

    # 條件 4: 持有人數下降 >= 2%
    holder_chg = (this_week['total_holders'] - last_week['total_holders']) / last_week['total_holders'] * 100
    if holder_chg > -2.0:
        return False, f"散戶變化 {holder_chg:+.1f}% > -2%"

    # 條件 5: 股價 >= 300
    if price < 300:
        return False, f"股價 {price:.0f} < 300"

    # 條件 6: 排除 ETF
    if this_week['stock_code'].startswith('00'):
        return False, "ETF"

    # 條件 7: 排除單週 ratio 變動 > 5%
    if abs(r400_chg) > 5.0:
        return False, f"單週變動 {r400_chg:.1f}% > 5% (特殊事件)"

    # 全部通過
    limit_price = price * 1.03
    return True, {
        'stock_code': this_week['stock_code'],
        'price': price,
        'limit_price': limit_price,
        'r400_chg': r400_chg,
        'r1000_chg': r1000_chg,
        'sync': sync,
        'holder_chg': holder_chg,
        'stop_loss': limit_price * 0.93,  # 假設用限價成交
    }
```

### 重要：兩週連升的判斷

因為我們只抓兩週數據，所以**只能判斷這兩週之間是否上升**。這等同於 `streak >= 1`（至少一週上升）。

如果要嚴格要求 `streak >= 2`（連續兩週上升），需要抓三週數據。**建議抓三週**，多一次 TDCC 查詢但訊號品質更好。

用三週的話：
```python
# week1 (最舊) → week2 → week3 (最新)
# 需要: week2 > week1 AND week3 > week2
streak_2 = (week3['ratio_400_above'] > week2['ratio_400_above']) and \
           (week2['ratio_400_above'] > week1['ratio_400_above'])
```

此時 ratio 變化和散戶變化用 week3 - week1（跨兩週的累計）。

---

## Step 4: 輸出結果

### 不管有沒有訊號都要輸出

```
========================================
TDCC 大戶吃貨掃描 — 2026/03/07
統計週: 20260226 vs 20260213
掃描: 2,316 檔 (排除 287 檔特殊事件)
========================================

✅ 符合條件: 4 檔

| 股票 | 收盤 | 限價(+3%) | 停損(-7%) | ratio↑ | sync | 散戶↓ |
|------|------|-----------|-----------|--------|------|-------|
| 6789 | 342  | 352       | 328       | +3.2%  | 93%  | -13%  |
| 6584 | 425  | 438       | 407       | +5.7%  | 74%  | -26%  |
| 3105 | 338  | 348       | 324       | +4.2%  | 79%  | -5%   |
| 1560 | 524  | 540       | 502       | +4.2%  | 119% | -8%   |

📋 操作:
- 下週一掛限價買入，每檔 125,000 元
- 5 天內成交就好，沒成交取消
- 成交後停損線 = 成交價 × 0.93
```

或者沒有訊號時：

```
========================================
TDCC 大戶吃貨掃描 — 2026/03/07
統計週: 20260226 vs 20260213
掃描: 2,316 檔 (排除 287 檔特殊事件)
========================================

❌ 本週無符合條件的訊號

接近通過的股票 (差一個條件):
| 股票 | 收盤 | ratio↑ | sync | 散戶  | 不通過原因      |
|------|------|--------|------|-------|----------------|
| 3529 | 2530 | +1.7%  | 64%  | -19%  | ratio 1.7%<2%  |
| 5234 | 424  | +3.2%  | 33%  | -22%  | sync 33%<50%   |
```

### 輸出格式

- 印到 terminal (stdout)
- 同時寫入一個 txt 或 json 檔，方便之後對帳

---

## Step 5 (選用): 通知

可以之後再加。先做到「跑腳本 → 看結果」就好。
之後可以接：
- LINE Notify
- Telegram Bot
- Email (SMTP)

---

## 技術限制和注意事項

1. **TDCC 網站有 CSRF token**：每次請求前要先 GET 頁面拿 token
2. **TDCC 請求延遲**：建議每次請求間隔 0.3 秒，避免被封
3. **TPEX 日期是民國年**：2026 年 = 民國 115 年
4. **零股交易**：300 元以上的股票 125K 只能買 300-400 股
5. **每週只跑一次**：不需要 daemon 或 cron（除非你要自動化）

---

## 依賴套件

```
requests          # HTTP 請求
beautifulsoup4    # 解析 TDCC 網頁 (如果需要)
```

不需要 pandas、numpy、sqlite。盡量用標準庫。

---

## 測試方式

```bash
python weekly_scanner.py
```

可以加參數指定日期測試：
```bash
python weekly_scanner.py --date 20260226  # 測試指定週次
```

---

## 檔案結構

```
weekly_scanner/
├── weekly_scanner.py      # 主程式 (唯一需要的檔案)
├── requirements.txt       # requests, beautifulsoup4
├── output/                # 輸出目錄
│   └── scan_20260307.txt  # 每次掃描的結果
└── README.md              # 說明
```
