# WEEKLY_SCANNER_SPEC 修正清單

原始規格書有幾個地方需要修正，請按照這份文件更新。

---

## 修正 1：抓 4 週數據（不是 2 週）

**原文（錯誤）：**
> 抓最新兩週的 TDCC 大股東持股數據
> 不保留歷史資料，每次跑完就丟掉。只需要當週和上週的數據來判斷。

**修正：**
需要抓**最新 4 週**的 TDCC 數據。因為策略要求連續 3 週上升，需要 4 個時間點才能判斷 3 個差值。

```
week1 (最舊) → week2 → week3 → week4 (最新)
判斷: week2 > week1 AND week3 > week2 AND week4 > week3
```

4 個日期 × 2,300 檔 = 約 9,200 次請求。延遲 0.3 秒，約 50 分鐘。

---

## 修正 2：篩選邏輯完整重寫

**原文的 `check_signal` 只比較 2 週，要改成 4 週。** 把原文的整個 `check_signal` 函數換成：

```python
def check_signal(week1, week2, week3, week4, price):
    """
    week1~week4: 同一檔股票的連續 4 週 TDCC 數據 (week1 最舊)
    每一週的格式: {'stock_code': '6789', 'date': '20260226',
                   'ratio_400_above': 45.3, 'ratio_1000_above': 38.2,
                   'total_holders': 12500}
    price: 該股票在 week4 的收盤價

    回傳: (通過, 指標字典 or 不通過原因)
    """
    code = week4['stock_code']

    # 條件 6: 排除 ETF
    if code.startswith('00'):
        return False, 'ETF'

    # 條件 1: 連續 3 週上升 (week2>week1, week3>week2, week4>week3)
    if week2['ratio_400_above'] <= week1['ratio_400_above']:
        return False, '第1→2週未上升'
    if week3['ratio_400_above'] <= week2['ratio_400_above']:
        return False, '第2→3週未上升'
    if week4['ratio_400_above'] <= week3['ratio_400_above']:
        return False, '第3→4週未上升'

    # 條件 2: 累計 ratio 變化 >= 2% (從 week1 到 week4)
    r400_chg = week4['ratio_400_above'] - week1['ratio_400_above']
    if r400_chg < 2.0:
        return False, f'ratio 累計 {r400_chg:.1f}% < 2%'

    # 條件 7: 排除單週 ratio 變動 > 5% (任何一週)
    for wa, wb in [(week1, week2), (week2, week3), (week3, week4)]:
        diff = abs(wb['ratio_400_above'] - wa['ratio_400_above'])
        if diff > 5.0:
            return False, f'單週變動 {diff:.1f}% > 5% (特殊事件)'

    # 條件 3: sync >= 50%
    r1000_chg = week4['ratio_1000_above'] - week1['ratio_1000_above']
    sync = r1000_chg / r400_chg if r400_chg > 0.01 else 0
    if sync < 0.5:
        return False, f'sync {sync:.0%} < 50%'

    # 條件 4: 持有人數下降 >= 2% (從 week1 到 week4)
    holder_chg = (week4['total_holders'] - week1['total_holders']) / week1['total_holders'] * 100
    if holder_chg > -2.0:
        return False, f'散戶變化 {holder_chg:+.1f}% > -2%'

    # 條件 5: 股價 >= 300
    if price < 300:
        return False, f'股價 {price:.0f} < 300'

    # 全部通過
    limit_price = price * 1.03
    return True, {
        'stock_code': code,
        'price': price,
        'limit_price': round(limit_price, 1),
        'stop_loss': round(limit_price * 0.93, 1),
        'r400_chg': round(r400_chg, 2),
        'r1000_chg': round(r1000_chg, 2),
        'sync': round(sync, 3),
        'holder_chg': round(holder_chg, 1),
        'streak': 3,  # 至少 3 週, 可能更多
    }
```

---

## 修正 3：ratio 和散戶變化的計算範圍

**原文（錯誤）：**
> 此時 ratio 變化和散戶變化用 week3 - week1（跨兩週的累計）

**修正：**
用 **week4 - week1**（跨三週的累計）。因為是 4 個時間點、3 個週間差值。

```
ratio 變化 = week4.ratio_400_above - week1.ratio_400_above  (3 週累計)
散戶變化   = (week4.total_holders - week1.total_holders) / week1.total_holders * 100
sync       = (week4.ratio_1000_above - week1.ratio_1000_above) / ratio 變化
```

---

## 修正 4：特殊事件排除改用 point-in-time

**原文：**
> 排除單週 ratio 變動 > 5%

**修正：** 不只檢查這 4 週的變動。如果這檔股票在**歷史上任何一週**曾經有過 >5% 的單週變動，就永遠排除。

```python
# 每一週都要檢查: 這檔股票截至目前是否曾經出過事
for wa, wb in [(week1, week2), (week2, week3), (week3, week4)]:
    if abs(wb['ratio_400_above'] - wa['ratio_400_above']) > 5.0:
        # 排除, 而且這檔股票之後的週次也全部排除
```

如果只跑一次（不保留歷史），這 4 週的檢查已經夠用。但如果要更嚴格，可以多抓幾週來檢查。

---

## 修正 5：輸出增加「連升週數」

輸出表格加一欄 `連升`，顯示實際連續上升了幾週（可能是 3、4、5...）：

```
| 股票 | 收盤 | 限價 | 停損 | 連升 | ratio↑ | sync | 散戶↓ |
|------|------|------|------|------|--------|------|-------|
| 6446 | 724  | 746  | 693  | 6週  | +3.5%  | 68%  | -16%  |
```

計算方式：從 week4 往回數，連續幾週都比前一週高。最少 3 週（否則不會通過）。

---

## 修正 6：出場規則補充

原文沒有提到出場規則的細節。補充：

```
持有中每天收盤檢查:
  1. 停損: 跌破成交價 × 0.93 (-7%) → 隔天開盤賣
  2. 停利: 漲超過 15% 後啟動 trailing stop
           從最高價回落 10% → 隔天開盤賣
           (注意: 漲不到 15% 就不啟動, 只有停損保護)
  3. 到期: 持有 90 天 → 不管賺賠都賣
```

---

## 修正 7：需要抓的日期是 4 個不是 2 個

**原文：**
> 怎麼知道最新的日期？ TDCC 網站有個下拉選單列出可用日期，先 GET 頁面解析出最新的兩個日期。

**修正：**
解析出最新的 **4 個**日期。

---

## 修正 8：範圍估算更新

**原文：**
> 兩個日期 × 2,300 檔 = 約 4,600 次請求

**修正：**
4 個日期 × 2,300 檔 = 約 **9,200** 次請求。延遲 0.3 秒，約 **50 分鐘**。

**最佳化建議（可選）：** 先抓最新 1 週的全市場數據判斷哪些股票 ratio 有在升，只對「有在升」的股票回抓前 3 週。這樣可以把請求數降到 4,000-5,000 次。

---

## 完整策略參數（最終版）

```
訊號條件:
  1. 連續 ≥ 3 週 ratio_400_above 每週都上升
  2. 累計 ratio 變化 ≥ 2% (week4 - week1)
  3. sync = (week4.r1000 - week1.r1000) / (week4.r400 - week1.r400) ≥ 50%
  4. 散戶人數變化 = (week4.holders - week1.holders) / week1.holders ≤ -2%
  5. 股價 ≥ 300 元
  6. 排除 ETF (股號 00 開頭)
  7. 排除歷史上任何一週有 >5% ratio 單週變動的股票

進場:
  8. 限價 = 訊號日收盤 × 1.03
  9. 掛單後 5 個交易日窗口
  10. 每檔 125,000 TWD
  11. 最多同時 4 檔
  12. 每週最多 2 檔

出場:
  13. 停損: 成交價 × 0.93 (-7%)
  14. 停利: 漲 15% 後啟動, 從最高價回落 10%
  15. 到期: 90 天
```
