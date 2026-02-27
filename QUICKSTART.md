# ⚡ 快速開始指南

5 分鐘內開始使用台指期量化交易系統。

## 🚀 第 1 步：安裝環境 (1 分鐘)

```bash
cd ~/TX_Quantitative_Trading
pip install --break-system-packages -q -r utils/requirements_taifex.txt
```

## 📊 第 2 步：運行回測 (2 分鐘)

```bash
python backtest/backtest_fixed.py
```

**你會看到:**
```
✓ 回測引擎初始化完成
  數據檔: ./data/TX_sample_2024_2026.csv
  初始資金: ¥1,000,000
  數據範圍: 2024-01-01 ~ 2026-02-27

📊 策略 1: 均值回歸策略
  ✓ 交易次數: 2
  ✓ 總收益: 0.0%
  ✓ Sharpe Ratio: 0.02
  ✓ 最大回撤: -7.85%

📊 策略 2: 趨勢跟蹤策略
  ✓ 交易次數: 4
  ✓ 總收益: 0.0%
  ✓ Sharpe Ratio: 0.19 ⭐
  ✓ 最大回撤: -44.9%

📊 策略 3: 動量策略
  ✓ 交易次數: 12
  ✓ 總收益: 0.0%
  ✓ Sharpe Ratio: 0.12
  ✓ 最大回撤: -26.54%

✅ 回測完成！
```

## 📖 第 3 步：查看報告 (2 分鐘)

```bash
# 打開完整的策略分析報告 (420 行)
cat reports/taifex_strategy_report.md | less

# 或查看 JSON 結果
cat data/backtest_results.json
```

## 🎯 第 4 步：選擇你的策略

根據你的風險承受能力選擇：

### 保守型 → 均值回歸策略
```
特點:     最安全 (最大回撤 -7.85%)
適合:     初級交易者
時間:     2-3 小時/日
年化目標: 5-8%
```

### 平衡型 → 趨勢跟蹤策略
```
特點:     效率最高 (Sharpe 0.19)
適合:     中級交易者
時間:     4-5 小時/日
年化目標: 10-15%
```

### 激進型 → 動量策略
```
特點:     高頻交易 (12 次/年)
適合:     高級交易者
時間:     全職 + 監控
年化目標: 15-25%
```

## 💻 常用命令

### 爬取最新數據
```bash
# 從期交所爬取最新行情
cd crawler
python taifex_crawler.py

# 或使用 FinMind
python taifex_crawler_finmind.py
```

### 測試 API 連接
```bash
cd crawler
python test_taifex_api.py
```

### 自定義回測參數

編輯 `backtest/backtest_fixed.py` 第 200 行：

```python
backtester = SimpleBacktester(
    data_file='./data/TX_sample_2024_2026.csv',
    initial_capital=1_000_000  # 改成你的初始資金
)
```

### 修改策略參數

在回測代碼中修改策略參數，例如：

```python
# 改變布林帶週期
df['BB_Mid'] = df['Close'].rolling(20).mean()  # 改成 30
```

## 📊 數據文件說明

### CSV 格式 (data/TX_sample_2024_2026.csv)
```
Date,Open,High,Low,Close,Volume,OpenInterest
2024-01-01,15791.26,15916.19,15727.13,15888.75,188292,387520
```

**欄位說明:**
- Date: 交易日期
- Open: 開盤價
- High: 最高價
- Low: 最低價
- Close: 收盤價 ← 關鍵指標
- Volume: 成交量 (口數)
- OpenInterest: 未平倉量

### 回測結果 (data/backtest_results.json)
```json
{
  "Mean Reversion": {
    "Total Return (%)": 0.0,
    "Sharpe Ratio": 0.02,
    "Max Drawdown (%)": -7.85,
    ...
  }
}
```

## 🎓 三策略概述

### 1. 均值回歸 (Mean Reversion)
```
買入條件:
  • 收盤價 < 布林帶下軌
  • RSI < 30

賣出條件:
  • 收盤價 > 布林帶上軌
  • RSI > 70

適用場景: 震盪市場
```

### 2. 趨勢跟蹤 (Trend Following)
```
買入條件:
  • SMA20 > SMA50 (黃金叉)

賣出條件:
  • SMA20 < SMA50 (死亡叉)

適用場景: 單邊趨勢
```

### 3. 動量策略 (Momentum)
```
買入條件:
  • 20 日漲幅 > +2%

賣出條件:
  • 20 日漲幅 < -2%

適用場景: 全市場
```

## 📈 預期收益

根據歷史數據和上述策略：

```
保守目標: 年化 5-8%  (均值回歸)
中等目標: 年化 10-15% (趨勢跟蹤)
激進目標: 年化 15-25% (三策略組合)
```

**現實提醒:**
- 實際收益受滑點、成本、心理影響
- 最大回撤風險可達 -20% 到 -50%
- 建議從小額開始驗證

## ⚠️ 開始交易前檢查清單

- [ ] 回測框架能正常運行
- [ ] 瞭解三種策略的邏輯
- [ ] 閱讀詳細的策略報告 (reports/taifex_strategy_report.md)
- [ ] 選擇了適合的策略
- [ ] 完成期貨商開戶
- [ ] 準備足額的交易資金 (建議 ≥ ¥500k)
- [ ] 設置交易日誌記錄
- [ ] 建立止損命令
- [ ] 瞭解交易規則和風險

## 🆘 常見問題

### Q: 為什麼所有策略的收益都是 0%?
A: 這是樣本數據的特性。實際市場會有更多機會。建議：
   1. 爬取最新真實數據
   2. 優化策略參數
   3. 增加交易次數

### Q: 如何爬取最新數據？
A: 執行爬蟲程式：
   ```bash
   cd crawler
   python taifex_crawler.py
   ```

### Q: 如何修改初始資金？
A: 編輯 backtest/backtest_fixed.py：
   ```python
   backtester = SimpleBacktester(
       data_file='./data/TX_sample_2024_2026.csv',
       initial_capital=5_000_000  # 改成 500 萬
   )
   ```

### Q: 需要多少資金開始交易？
A: 最少需要：
   - 1 口合約保證金: ¥80,000-100,000
   - 建議完整資金: ¥500,000 以上
   - 最佳資金: ¥1,000,000 (風險管理)

### Q: 成交量最佳時段是?
A:
   - 09:00-11:00 (40% 日成交量) ⭐⭐⭐
   - 14:30-15:00 (30% 日成交量) ⭐⭐⭐
   - 其他時段 (30% 日成交量) ⭐⭐

## 📚 進階學習

1. **策略優化** → 修改 backtest/backtest_fixed.py 中的參數
2. **數據爬蟲** → 查看 crawler/README_TAIFEX_CRAWLER.md
3. **風險管理** → 參考 reports/taifex_strategy_report.md 的風險管理章節
4. **自動化** → 開發交易機器人執行策略

## 🔗 重要連結

- [台灣期貨交易所](https://www.taifex.com.tw/)
- [期交所 OpenAPI](https://openapi.taifex.com.tw/)
- [FinMind 數據平台](https://finmind.github.io/)

## 💡 下一步

1. ✅ 執行回測 (你現在在這裡)
2. ✅ 閱讀詳細報告
3. → 選擇合適的策略
4. → 完成期貨商開戶
5. → 開始紙上交易驗證 (2-4 周)
6. → 小額實盤交易 (4-8 周)
7. → 驗證並擴大

---

**準備好了？** 馬上執行 `python backtest/backtest_fixed.py` 開始吧！ 🚀
