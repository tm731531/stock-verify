# 006208 SMA20/50 交易系統 - 實現指南

**版本**: 1.0
**日期**: 2026-02-28
**狀態**: 準備跨機實現

---

## 📋 目錄

1. [核心目標](#核心目標)
2. [為什麼選擇 SMA20/50](#為什麼選擇-sma2050)
3. [系統架構](#系統架構)
4. [環境準備](#環境準備)
5. [實現步驟](#實現步驟)
6. [關鍵配置](#關鍵配置)
7. [驗證清單](#驗證清單)
8. [常見問題](#常見問題)

---

## 核心目標

為台灣50 ETF (006208) 實現一個自動化的日線 SMA20/50 交易系統：

- ✅ 每日自動檢測進出場訊號
- ✅ 使用動態 SMA 參數（可快速調整）
- ✅ 記錄完整的交易日誌和績效統計
- ✅ 提供日線機器人架構（支持 Crontab）

---

## 為什麼選擇 SMA20/50

### 量化對比（2020-2026年回測）

| 指標 | SMA50/200 | SMA20/50 | 改進 |
|------|-----------|----------|------|
| **已實現獲利** | $131,745 | $299,874 | **+139%** 💰 |
| **報酬率** | 61.90% | 71.85% | +9.95% |
| **進場次數** | 5 次 | 15 次 | 更多機會 |
| **勝率** | 60% | 57% | 可接受 |
| **交易速度** | 慢（50日）| 快（20日）| ⚡ 快速反應 |
| **平均獲利** | $21,887 | $21,420 | 一致 |

### 結論
- **更多現金流**：SMA20/50 產生更多已實現獲利
- **更快反應**：適合主動交易，避免長期套牢
- **相同品質**：勝率和平均獲利維持一致

---

## 系統架構

### 整體流程

```
歷史數據 (CSV)
    ↓
[SMA 計算] → SMA20, SMA50, ATR, ATR_MA
    ↓
[訊號檢測] ← 進場: SMA20 > SMA50 + ATR ≤ MA×1.3
         ← 出場: SMA20 < SMA50 或 警訊止損
    ↓
[交易執行] → 記錄進出場、計算 P&L
    ↓
[日誌記錄] → JSON/CSV 文件 + 日線摘要
```

### 核心邏輯

```python
# 進場條件（黃金交叉 + 波動率正常）
進場 = (SMA20 > SMA50) AND (ATR ≤ ATR_MA × 1.3)

# 出場條件 1：死亡交叉
出場1 = SMA20 < SMA50

# 出場條件 2：警訊止損
出場2 = (ATR > ATR_MA × 1.5) AND (日跌幅 < -3%)
```

---

## 環境準備

### 系統需求

```bash
# 檢查 Python 版本（需要 3.7+）
python3 --version

# 檢查必要的包
pip3 list | grep -E "pandas|numpy"
```

### 安裝依賴

```bash
pip3 install pandas numpy
# 可選：用於實時數據
pip3 install shioaji
```

### 目錄結構

```
stock-verify/006208-sma-market-regime/
├── data/
│   └── 006208_historical.csv          # 歷史數據（必需）
├── backtest_sma_optimized.py          # 回測引擎
├── TRADING_LOG_SMA20_50_FINAL.md      # 交易日誌範例
└── sma_006208_daily_bot/
    ├── configs/
    │   ├── global.json                # 全域設定（自動生成）
    │   └── sma_strategy.json          # 策略設定（自動生成）
    ├── states/
    │   └── sma_bot_state.json         # 當前狀態（自動生成）
    ├── trades/
    │   ├── trades_YYYYMMDD.json       # 交易記錄
    │   └── signals_YYYYMMDD.json      # 訊號記錄
    ├── logs/
    │   └── sma_bot.log                # 執行日誌
    ├── config_manager.py              # 配置管理
    ├── sma_market_regime.py           # 核心策略
    ├── trade_logger.py                # 交易記錄
    └── main.py                        # 日線入口
```

---

## 實現步驟

### Step 1: 準備歷史數據

需要 CSV 檔案：`data/006208_historical.csv`

**格式要求**:
```
Date,Open,High,Low,Close,Volume
2020-01-02,47.60,47.75,47.55,47.60,5600000
2020-01-03,47.65,47.90,47.60,47.80,6200000
...
```

**最低要求**：至少 50+ 個交易日（用於計算 SMA50）

### Step 2: 實現回測引擎

**檔案**: `backtest_sma_optimized.py`

核心功能：
- 載入 CSV 數據
- 計算 SMA20、SMA50、ATR、ATR_MA
- 模擬交易（$100k 固定額、最多 $300k 倉位）
- 輸出已實現獲利統計

**預期結果**：$299,874 已實現獲利（+71.85%）

### Step 3: 實現日線機器人

#### 3a. config_manager.py

```python
class ConfigManager:
    def _load_strategy_config(self):
        default = {
            "sma_short": 20,      # 關鍵參數
            "sma_long": 50,       # 關鍵參數
            "atr_period": 14,
            "atr_ma_period": 20,
            "volatility_threshold_multiplier": 1.5,
            "entry_volatility_threshold": 1.3,
            # ... 其他配置
        }
```

**特點**: 所有 SMA 參數從配置檔讀取，支持動態調整

#### 3b. sma_market_regime.py

```python
class SMAMarketRegime:
    def calculate_indicators(self, df):
        # 使用動態列名
        df[f'SMA_{self.sma_short}'] = df['Close'].rolling(self.sma_short).mean()
        df[f'SMA_{self.sma_long}'] = df['Close'].rolling(self.sma_long).mean()
        # ATR 計算...
        return df

    def detect_regime(self, last_row):
        # 進場/出場/警訊 判斷
        if sma_short > sma_long:
            signal = "entry"
        elif sma_short < sma_long:
            signal = "hold"
        # ...
```

**特點**:
- 動態 SMA 列名（支持任意週期組合）
- 返回 market_status dict（包含 sma50/sma200 向後相容鍵）

#### 3c. trade_logger.py

```python
class TradeLogger:
    def log_entry(self, entry_price, signal_reason):
        # 記錄進場訊號到 JSON/CSV

    def log_exit(self, exit_price, entry_price, pnl):
        # 記錄出場訊號和損益

    def print_summary(self):
        # 印出日線摘要
```

#### 3d. main.py

```python
class SMA006208Bot:
    def run_once(self):
        # 1. 檢查市場交易時間
        # 2. 載入最新數據
        # 3. 計算訊號
        # 4. 執行交易邏輯
        # 5. 記錄到日誌

if __name__ == "__main__":
    bot = SMA006208Bot()
    bot.run_once()
```

**命令選項**:
```bash
python main.py                 # 日線執行
python main.py --status        # 顯示狀態
python main.py --enable        # 啟用實際下單
python main.py --disable       # 停用下單（模擬模式）
python main.py --reset         # 重置狀態
```

### Step 4: 設定 Crontab（可選）

```bash
# 編輯 crontab
crontab -e

# 每日 12:30 執行（台灣時間）
30 12 * * 1-5 cd /path/to/sma_006208_daily_bot && python3 main.py >> /tmp/sma_bot.log 2>&1
```

---

## 關鍵配置

### strategy_config.json

```json
{
  "sma_short": 20,                          // 短期 SMA（進場/出場判斷）
  "sma_long": 50,                           // 長期 SMA（趨勢判斷）
  "atr_period": 14,                         // ATR 計算週期
  "atr_ma_period": 20,                      // ATR 均線週期
  "volatility_threshold_multiplier": 1.5,   // 警訊閾值（ATR > MA × 1.5）
  "daily_drop_threshold": -0.03,            // 單日跌幅閾值（-3%）
  "entry_volatility_threshold": 1.3,        // 進場波動率閾值（ATR ≤ MA × 1.3）
  "max_trades_per_day": 1,                  // 每日最多交易次數
  "warning_action": "reduce"                // 警訊時動作（reduce/hold/exit）
}
```

### 快速調整指南

| 要求 | 調整參數 | 影響 |
|------|---------|------|
| 進場更頻繁 | ↓ `sma_short` | 反應更快，信號更多 |
| 進場更保守 | ↑ `sma_short` | 反應變慢，信號減少 |
| 波動率篩選更嚴 | ↑ `entry_volatility_threshold` | 進場更謹慎 |
| 波動率篩選更鬆 | ↓ `entry_volatility_threshold` | 進場更激進 |

---

## 驗證清單

### 前置檢查
- [ ] CSV 檔案存在且有 50+ 個交易日
- [ ] Python 3.7+ 已安裝
- [ ] pandas、numpy 已安裝

### 代碼實現檢查
- [ ] config_manager.py 設定為 `sma_short=20, sma_long=50`
- [ ] sma_market_regime.py 使用動態 SMA 列名（`f'SMA_{self.sma_short}'`）
- [ ] main.py 可正確呼叫 `get_market_status()`
- [ ] trade_logger.py 正確記錄進出場

### 功能驗證
- [ ] `backtest_sma_optimized.py` 執行無錯誤
- [ ] 輸出已實現獲利 ≥ $299,874
- [ ] `python3 main.py --status` 可顯示配置
- [ ] 日誌檔案正確生成

### 部署檢查
- [ ] Crontab 已配置（如需要）
- [ ] 日線執行正確（測試一次）
- [ ] 狀態檔案可正確保存和讀取

---

## 常見問題

### Q1: SMA 值為什麼是 NaN？
**A**: SMA20 需要 20 個交易日才有值，SMA50 需要 50 天。檢查 CSV 數據是否足夠。

### Q2: 如何調整 SMA 參數？
**A**: 編輯 `config_manager.py` 中的 `_load_strategy_config()` 方法，修改 `sma_short` 和 `sma_long`。配置會在首次執行時自動生成。

### Q3: 怎樣重置交易狀態？
**A**: 執行 `python3 main.py --reset` 刪除狀態檔案。

### Q4: 日誌檔案在哪裡？
**A**:
- 交易記錄：`sma_006208_daily_bot/trades/trades_YYYYMMDD.json`
- 訊號記錄：`sma_006208_daily_bot/signals_YYYYMMDD.json`
- 執行日誌：`sma_006208_daily_bot/logs/sma_bot.log`

### Q5: 如何從 SMA50/200 切換到 SMA20/50？
**A**: 只需修改配置檔中的 `sma_short` 和 `sma_long` 值。代碼會自動使用新的 SMA 計算。

### Q6: 可以同時運行多個 SMA 組合嗎？
**A**: 可以，建立不同的配置檔案和狀態檔案目錄。

---

## 效能預期

### 回測結果（2020-2026）
- **初始資本**: $500,000
- **已實現獲利**: $299,874
- **總報酬率**: +71.85%
- **出場勝率**: 57% (8/14)
- **平均獲利**: $21,420 per exit
- **最大獲利**: $115,934
- **最大虧損**: -$24,493

### 交易統計
- **進場次數**: 15
- **加倀次數**: 30
- **出場次數**: 14
- **警訊止損**: 6
- **死亡交叉**: 8

---

## 參考資料

### 相關檔案
- `backtest_sma_optimized.py` - 完整回測實現
- `TRADING_LOG_SMA20_50_FINAL.md` - 14 個交易周期的詳細記錄
- `backtest_sma_comparison.py` - SMA 組合對比分析

### 關鍵觀點
1. **SMA20/50 比 SMA50/200 好 139%**（已實現現金流）
2. **使用最高價進場**更保守但更現實
3. **ATR 波動率篩選**避免在波動期進場
4. **完整狀態管理**支持日線連續運行

---

## 支持和問題

如遇到實現問題：

1. **檢查數據**: CSV 是否有足夠的歷史數據
2. **檢查邏輯**: SMA 計算和訊號判斷是否正確
3. **檢查配置**: 所有參數是否按照 SMA20/50 設定
4. **檢查日誌**: 查看 `logs/sma_bot.log` 瞭解詳細執行流程

---

**最後更新**: 2026-02-28
**版本**: 1.0 Release Candidate
**狀態**: ✅ 準備跨機實現
