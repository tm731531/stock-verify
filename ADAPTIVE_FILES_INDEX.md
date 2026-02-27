# 自適應交易系統 - 文件索引

**更新日期**: 2026-02-27
**系統版本**: 1.0
**狀態**: ✓ 完成上線

---

## 快速導航

### 我想...

- **了解系統整體** → `/ADAPTIVE_SYSTEM_README.md` (15分鐘)
- **看詳細回測報告** → `/reports/adaptive_backtest_report.md` (30分鐘)
- **對比策略性能** → `/reports/ADAPTIVE_VS_SINGLE_COMPARISON.md` (20分鐘)
- **快速查詢信息** → `/QUICKREF_ADAPTIVE_SYSTEM.md` (5分鐘)
- **運行回測** → `python3 backtest/adaptive_backtest.py` (1分鐘)
- **查看交易記錄** → `cat data/adaptive_trades.csv` (1分鐘)
- **檢查日誌數據** → `cat data/adaptive_backtest_log.csv` (10分鐘)
- **修改系統參數** → 編輯 `backtest/adaptive_backtest.py` 的 `MarketEnvironmentDetector`

---

## 文件結構

```
/home/tom/TX_Quantitative_Trading/
│
├─ 【主要文檔】
│  ├─ ADAPTIVE_SYSTEM_README.md ..................... 系統完整說明書
│  ├─ QUICKREF_ADAPTIVE_SYSTEM.md .................. 快速參考指南
│  └─ ADAPTIVE_FILES_INDEX.md ...................... 本文件
│
├─ 【代碼】
│  └─ backtest/
│     ├─ adaptive_backtest.py ...................... 核心系統 (508行)
│     └─ comparison_backtest.py ................... 對比分析 (250+行)
│
├─ 【數據】
│  └─ data/
│     ├─ TX_full_2019_2026.csv ................... 原始K線數據
│     ├─ adaptive_backtest_log.csv ............... 每日回測日誌 ⭐
│     └─ adaptive_trades.csv ..................... 交易記錄 ⭐
│
└─ 【報告】
   └─ reports/
      ├─ adaptive_backtest_report.md ............ 詳細回測報告 ⭐
      └─ ADAPTIVE_VS_SINGLE_COMPARISON.md .... 對比分析報告 ⭐
```

⭐ = 關鍵文件

---

## 文件詳解

### 【核心代碼】

#### `backtest/adaptive_backtest.py` (508行)
**用途**: 自適應回測系統的核心實現
**內容**:
- `MarketEnvironmentDetector`: 環境檢測器
  - `detect_environment()`: 判斷當前市場狀態
  - 使用: 價格位置、趨勢強度、成交量、下跌天數、動量 5個信號
  
- `AdaptiveStrategyEngine`: 策略引擎
  - `get_sma_trend_signal()`: SMA趨勢策略 (BULL)
  - `get_mean_reversion_signal()`: 均值回歸策略 (BEAR)
  - `get_breakout_signal()`: 高低突破策略 (RANGE)
  - `get_signal()`: 主入口函數
  
- `AdaptiveBacktester`: 回測器
  - `backtest()`: 執行完整回測
  - 生成日誌和交易記錄
  
- `RolloverManager`: 換倉管理
  - 計算換倉成本 (¥6,100 per roll)

**運行方式**:
```bash
python3 backtest/adaptive_backtest.py
```

**輸出**:
- Console: 統計信息、環境分布、策略表現
- `data/adaptive_backtest_log.csv`: 1,682行日誌
- `data/adaptive_trades.csv`: 8筆交易記錄

---

#### `backtest/comparison_backtest.py` (250+行)
**用途**: 對比分析回測
**內容**:
- `SimpleBacktester`: 簡化回測器
  - `backtest_sma_trend()`: 純SMA趨勢
  - `backtest_mean_reversion()`: 純均值回歸
  - `backtest_breakout()`: 純高低突破
  - `backtest_hodl()`: HODL買持策略

**運行方式**:
```bash
python3 backtest/comparison_backtest.py
```

**輸出**: 5種策略的績效對比表

---

### 【數據文件】

#### `data/TX_full_2019_2026.csv` (136KB)
**用途**: 原始K線數據
**內容**: 1,732行
**欄位**: Date, Open, High, Low, Close, Volume
**日期範圍**: 2019-01-02 ~ 2026-02-26

**使用**: 作為回測的輸入數據

---

#### `data/adaptive_backtest_log.csv` (103KB) ⭐⭐⭐
**用途**: 每日詳細回測日誌
**內容**: 1,682行 + 表頭
**欄位**:
| 欄位 | 說明 |
|------|------|
| Date | 交易日期 |
| Close | 收盤價 |
| Environment | 當前環境 (BULL/BEAR/RANGE/NEUTRAL) |
| Strategy | 當前策略名稱 |
| Signal | 信號值 (1=買/0=無/-1=賣) |
| Position | 倉位狀態 (0=空倉/1=持倉) |
| PortfolioValue | 組合總價值 |

**用途**: 驗證每日判斷和交易邏輯

**查看方式**:
```bash
# 查看前50行
head -50 data/adaptive_backtest_log.csv

# 查看最後100行
tail -100 data/adaptive_backtest_log.csv

# 查看特定環境的記錄
grep "BULL" data/adaptive_backtest_log.csv | wc -l

# 統計環境分布
cut -d',' -f3 data/adaptive_backtest_log.csv | tail -n +2 | sort | uniq -c
```

---

#### `data/adaptive_trades.csv` (1.3KB) ⭐⭐⭐
**用途**: 完整交易記錄
**內容**: 9行 (8筆完成 + 1筆未平倉)
**欄位**:
| 欄位 | 說明 |
|------|------|
| entry_date | 進場日期 |
| entry_price | 進場價格 |
| entry_environment | 進場時的環境 |
| entry_strategy | 進場時的策略 |
| exit_date | 出場日期 |
| exit_price | 出場價格 |
| profit_pct | 收益百分比 |
| profit_points | 收益點數 |
| days_held | 持倉天數 |
| exit_environment | 出場時的環境 |
| exit_strategy | 出場時的策略 |

**用途**: 分析每筆交易的邏輯和績效

**查看方式**:
```bash
cat data/adaptive_trades.csv

# 用 Excel 或 pandas 查看
python3
import pandas as pd
df = pd.read_csv('data/adaptive_trades.csv')
print(df[['entry_date', 'entry_strategy', 'profit_pct', 'days_held']])
```

---

### 【報告文件】

#### `reports/adaptive_backtest_report.md` (16KB) ⭐⭐⭐
**用途**: 完整的回測詳細報告
**內容** (~500行):
1. 執行摘要
2. 市場環境分析
   - 環境分布統計
   - 環境判斷邏輯
3. 策略配置
   - 環境↔策略映射
   - 策略詳細說明
4. 回測結果詳析
   - 各環境下的策略表現
   - 總體績效分析
5. 對比分析
   - 設計對比
   - 預期收益對比
6. 交易日誌摘要 (前100天示例)
7. 系統特性評估 (優勢/劣勢)
8. 數據完整性驗證
9. 結論和建議

**推薦閱讀**: 完整理解回測結果

---

#### `reports/ADAPTIVE_VS_SINGLE_COMPARISON.md` (12KB) ⭐⭐⭐
**用途**: 與單一策略的對比分析
**內容** (~400行):
1. 總體排名表
2. 深度對比分析
   - 年化收益對比
   - Sharpe比率對比
   - 最大回撤對比
3. 策略特性對比
4. 各策略優劣評估
   - SMA趨勢
   - 均值回歸
   - 高低突破
   - 自適應系統
   - HODL買持
5. 環境匹配度分析
6. 實用建議
7. 2019-2026特殊性分析
8. 反事實分析 (如果是2008年)
9. 結論

**推薦閱讀**: 了解系統相對性能

---

### 【文檔文件】

#### `ADAPTIVE_SYSTEM_README.md` (15KB)
**用途**: 系統完整說明書
**內容**:
- 核心簡介
- 回測結果一覽
- 與其他策略的對比
- 系統架構 (代碼結構、回測流程)
- 完整交易紀錄
- 文件架構
- 快速使用方式
- 關鍵參數
- 重要發現 (環境分布、大行情、BEAR身份、風險控制)
- 改進空間 (短期/中期/長期)
- 實盤應用指南
- 最後的話 (系統本質、推薦場景)

**推薦閱讀**: 快速全面了解

---

#### `QUICKREF_ADAPTIVE_SYSTEM.md` (9KB)
**用途**: 快速參考指南
**內容**:
1. 快速執行
2. 文件索引
3. 核心績效指標 (一頁紙摘要)
4. 環境檢測一覽表
5. 環境↔策略映射 (代碼片段)
6. 八大交易記錄 (表格)
7. 策略對比排名
8. 核心設計原則 (無未來信息、每日判斷、交易記錄)
9. 改進建議 (短期/長期)
10. 日誌查看方式
11. 常見問題 (FAQ)
12. 性能統計
13. 快速開始 (5分鐘指南)
14. 相關文件索引

**推薦閱讀**: 快速查找信息

---

#### `ADAPTIVE_FILES_INDEX.md` (本文件)
**用途**: 文件導航和索引
**內容**: 完整的文件結構和使用指南

---

## 核心績效數據速查

### 環境分布
```
BULL (牛市)     : 613天 (36.4%)
BEAR (空頭)     : 312天 (18.5%)
NEUTRAL (不確定): 757天 (45.0%)
RANGE (震盪)    : 0天   (0.0%)
```

### 交易統計
```
總交易: 8次
勝率: 62.5% (5/8)
平均持倉: 138天
最大持倉: 721天 (交易6)
最短持倉: 44天 (交易1)
```

### 績效指標
```
總收益    : +33.24%
年化收益  : +4.75%
Sharpe    : 0.3134
最大回撤  : -53.44%
```

### 策略表現
```
BULL環境 (SMA趨勢)    : 1交易, 平均+34.40%, 勝率100%
BEAR環境 (均值回歸)   : 7交易, 平均+8.56%, 勝率57%
RANGE環境 (高低突破)  : 0交易, 機會0
NEUTRAL (空倉)       : 757天, 無風險
```

---

## 常見使用案例

### 案例1: 我想驗證回測結果
1. 打開 `data/adaptive_trades.csv` 查看交易記錄
2. 打開 `data/adaptive_backtest_log.csv` 查看日誌
3. 找到交易進場日期，驗證環境判斷
4. 計算進場和出場的利潤百分比

### 案例2: 我想修改環境判斷參數
1. 編輯 `backtest/adaptive_backtest.py`
2. 找到 `MarketEnvironmentDetector.detect_environment()` 函數
3. 修改以下參數:
   - `trend_strength = (high_30 - low_30) / low_30` 的0.05閾值
   - `momentum_20 > 0.02` 的0.02閾值
   - `down_days >= 3` 的3天閾值
4. 重新運行: `python3 backtest/adaptive_backtest.py`

### 案例3: 我想添加新策略
1. 在 `AdaptiveStrategyEngine` 類中添加新方法:
```python
@staticmethod
def get_my_new_strategy_signal(df, current_idx):
    # 實現新策略邏輯
    return signal
```

2. 在 `get_signal()` 函數中添加條件:
```python
elif environment == 'MY_NEW_ENV':
    return get_my_new_strategy_signal(df, current_idx), '我的新策略'
```

3. 在 `MarketEnvironmentDetector.detect_environment()` 中返回新環境

### 案例4: 我想查看特定時期的交易
1. 打開 `data/adaptive_backtest_log.csv`
2. 過濾特定日期範圍
3. 查看 Signal 欄是否有 1 或 -1 (進場或出場)
4. 查看 Position 欄確認持倉狀態

---

## 數據驗證清單

在使用系統前，請確認:

- [ ] `data/TX_full_2019_2026.csv` 存在且有 1,732 行
- [ ] `data/adaptive_backtest_log.csv` 存在且有 1,682 行
- [ ] `data/adaptive_trades.csv` 存在且有 9 行
- [ ] `backtest/adaptive_backtest.py` 可正常運行
- [ ] 執行後 Console 輸出環境分布統計
- [ ] 交易記錄中有 2 筆大行情 (+34.40% 和 +55.24%)

---

## 更新和改進

最後修改日期: 2026-02-27
系統版本: 1.0
穩定性: ✓ 生產就緒

### 已知限制
- 年化收益低於 HODL (4.75% vs 33.63%)
- 無止損機制，最大回撤 -53%
- NEUTRAL 環境比例過高 (45%)

### 計劃改進
- v1.1: 加入止損機制
- v1.2: 動態倉位管理
- v1.3: 機器學習優化

---

**祝您使用愉快！**

如有問題，請參閱:
1. `/QUICKREF_ADAPTIVE_SYSTEM.md` 的 FAQ 部分
2. `/reports/adaptive_backtest_report.md` 的常見問題章節
3. `/ADAPTIVE_SYSTEM_README.md` 的完整說明

