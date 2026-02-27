# 006208 SMA 日線系統

**完全獨立的交易機器人 - 每日 12:30 自動運行**

## 🎯 系統概述

這是一個針對台灣50 ETF (006208) 日K線的自動交易系統，基於簡單但有效的 SMA 市場制度檢測。

**架構**: 參考 `unified_strategy_bot`，但完全獨立為日線股票交易

### 核心特性

- ✅ **3 條規則系統**: 波動率警訊、空頭確認、進場訊號
- ✅ **完全自動化**: Crontab 每日 12:30 執行一次
- ✅ **狀態持久化**: 位置、進場價格、交易計數等自動保存
- ✅ **詳細記錄**: 所有訊號、交易、狀態變化都有記錄
- ✅ **模擬/實盤切換**: 可輕鬆在測試和實盤之間切換

---

## 📂 目錄結構

```
sma_006208_daily_bot/
├── README.md                    (本檔案)
├── main.py                      (主程式，Crontab 執行)
├── config_manager.py            (設定管理)
├── trade_logger.py              (交易記錄)
├── sma_market_regime.py         (SMA 策略實現)
├── configs/                     (設定檔)
│   ├── global.json              (全域設定)
│   └── sma_strategy.json        (策略參數)
├── states/                      (狀態持久化)
│   └── sma_bot_state.json       (當前倉位和交易狀態)
├── trades/                      (交易記錄)
│   ├── trades_YYYYMMDD.json     (每日交易記錄)
│   ├── trades_YYYYMMDD.csv      (CSV 格式)
│   └── signals_YYYYMMDD.json    (市場訊號記錄)
├── logs/                        (執行日誌)
│   └── sma_bot.log              (主日誌檔)
└── data/                        (歷史資料)
    └── 006208_historical.csv    (K 線資料)
```

---

## 🚀 快速開始

### 1. 安裝依賴

```bash
pip install pandas numpy shioaji
```

### 2. 設定配置

**全域設定** (`configs/global.json`):
```json
{
  "api_key": "YOUR_API_KEY",
  "secret_key": "YOUR_SECRET_KEY",
  "simulation": true,
  "enable_ordering": false,
  "symbol": "0050"
}
```

**策略設定** (`configs/sma_strategy.json`):
```json
{
  "sma_short": 50,
  "sma_long": 200,
  "atr_period": 14,
  "atr_ma_period": 20,
  "volatility_threshold_multiplier": 1.5,
  "daily_drop_threshold": -0.03,
  "max_trades_per_day": 1,
  "enable_ordering": false
}
```

### 3. 測試執行

```bash
# 模擬模式 (無實際下單)
python main.py

# 查看狀態
python main.py --status

# 啟用實盤交易
python main.py --enable

# 重置系統狀態
python main.py --reset
```

### 4. 設定 Crontab (每日 12:30 執行)

```bash
# 編輯 crontab
crontab -e

# 添加以下行:
30 12 * * 1-5 cd /home/tom/shioaji-trading/working/sma_006208_daily_bot && python main.py >> /tmp/sma_cron.log 2>&1
```

**說明**:
- `30 12` = 每天 12:30
- `* * 1-5` = 週一到週五（交易日）
- `python main.py` = 執行主程式

### 5. 驗證執行

```bash
# 檢查 Crontab 日誌
tail -f /tmp/sma_cron.log

# 檢查系統日誌
tail -f logs/sma_bot.log

# 檢查今日交易記錄
cat trades/trades_$(date +%Y%m%d).json

# 查看系統狀態
python main.py --status
```

---

## 📊 三條規則詳解

### 規則 1️⃣ - 波動率爆炸警訊 ⚠️

**觸發條件**:
- ATR (波動率) > 其移動平均的 1.5 倍
- 單日收盤跌幅 > 3%

**執行動作**:
- 如果已持倉: 減倉 50% 保護資本
- 記錄警訊訊號

**歷史驗證**: ✅ 2022 年大空頭準確預警

### 規則 2️⃣ - 空頭確認 📉

**觸發條件**:
- 50 日 SMA < 200 日 SMA (死亡交叉)

**執行動作**:
- 持有現有倉位或保持現金
- 不進場新倉位

**目的**: 確認你在下跌趨勢中

### 規則 3️⃣ - 進場訊號 🚀

**觸發條件**:
- 50 日 SMA > 200 日 SMA (黃金交叉)
- 波動率開始回到正常 (ATR < MA × 1.3)

**執行動作**:
- 進場買進 (長倉)
- 記錄進場訊號

**目的**: 在上升趨勢確認時進場

---

## 💾 狀態管理

系統自動保存以下狀態 (`states/sma_bot_state.json`):

```json
{
  "position": 1,              // 0: 無倉位, 1: 持多, -1: 持空
  "entry_price": 125.50,      // 進場價格
  "entry_date": "2026-02-28", // 進場日期
  "trade_count": 1,           // 今日交易數
  "position_reduction": false // 是否已減倉
}
```

### 日期變更自動重置

每當日期變更時，以下計數器自動重置:
- `trade_count` → 0 (每日限制重新計算)
- `position_reduction` → false (新一天新機會)

---

## 📝 交易記錄

### JSON 格式 (`trades/trades_YYYYMMDD.json`)

進場記錄:
```json
{
  "timestamp": "2026-02-28T12:30:45.123456",
  "type": "entry",
  "action": "long",
  "price": 125.50,
  "signal_reason": "黃金交叉 + 波動正常"
}
```

出場記錄:
```json
{
  "timestamp": "2026-02-28T12:30:50.123456",
  "type": "exit",
  "action": "long",
  "entry_price": 125.50,
  "exit_price": 126.00,
  "pnl": 50,
  "pnl_pct": 0.4,
  "exit_reason": "死亡交叉"
}
```

### CSV 格式 (`trades/trades_YYYYMMDD.csv`)

便於在 Excel 中分析:
```
timestamp,type,action,price,entry_price,exit_price,pnl,pnl_pct,reason
2026-02-28T12:30:45,entry,long,125.50,,,,,黃金交叉
2026-02-28T12:30:50,exit,long,,125.50,126.00,50.0,0.4,死亡交叉
```

### 訊號記錄 (`trades/signals_YYYYMMDD.json`)

所有市場訊號:
```json
{
  "timestamp": "2026-02-28T12:30:45",
  "type": "market_signal",
  "signal": "bull",
  "sma50": 125.30,
  "sma200": 123.50,
  "details": {...}
}
```

---

## 🔧 設定參數說明

### 全域設定 (global.json)

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `api_key` | Shioaji API Key | "YOUR_API_KEY" |
| `secret_key` | Shioaji Secret Key | "YOUR_SECRET_KEY" |
| `simulation` | 是否為模擬模式 | true |
| `enable_ordering` | 是否實際下單 | false |
| `symbol` | 交易商品代碼 | "0050" |

### 策略設定 (sma_strategy.json)

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `sma_short` | 短期 SMA 日數 | 50 |
| `sma_long` | 長期 SMA 日數 | 200 |
| `atr_period` | ATR 計算週期 | 14 |
| `atr_ma_period` | ATR 移動平均週期 | 20 |
| `volatility_threshold_multiplier` | 波動率警訊倍數 | 1.5 |
| `daily_drop_threshold` | 單日跌幅閾值 | -0.03 |
| `entry_volatility_threshold` | 進場時波動率 | 1.3 |
| `max_trades_per_day` | 每日最多交易數 | 1 |
| `warning_action` | 警訊時動作 | "reduce" |
| `warning_reduction_pct` | 減倉百分比 | 0.5 |

---

## 📋 命令列選項

```bash
# 執行一次檢查 (Crontab 用)
python main.py

# 顯示系統狀態
python main.py --status

# 啟用實盤交易
python main.py --enable

# 停用實盤 (回到模擬模式)
python main.py --disable

# 重置所有狀態
python main.py --reset
```

---

## 🐛 故障排除

### 常見問題

**Q: 為什麼沒有下單?**
A: 檢查 `enable_ordering` 是否為 false (模擬模式)。執行 `python main.py --enable` 啟用。

**Q: 為什麼 Crontab 沒有執行?**
A:
1. 檢查 Crontab 設定: `crontab -l`
2. 檢查權限: `which python`
3. 檢查日誌: `tail -f /tmp/sma_cron.log`

**Q: 如何查看交易歷史?**
A:
```bash
# 查看 JSON 格式
cat trades/trades_20260228.json

# 查看 CSV 格式 (用 Excel 開啟)
open trades/trades_20260228.csv
```

**Q: 如何改變 SMA 參數?**
A: 編輯 `configs/sma_strategy.json`，改變 `sma_short` 和 `sma_long` 後重新執行。

---

## 📈 監控和報告

### 每日執行報告

每次執行會在 `logs/sma_bot.log` 中記錄:
```
2026-02-28 12:30:45 [INFO] SMA 006208 日線系統 - 開始執行
2026-02-28 12:30:45 [INFO] 市場訊號: BULL
2026-02-28 12:30:45 [INFO]   價格: $125.50
2026-02-28 12:30:45 [INFO]   SMA50: $125.30
2026-02-28 12:30:45 [INFO]   SMA200: $123.50
2026-02-28 12:30:46 [INFO] 交易摘要 - 2026-02-28
================================================
交易摘要 - 2026-02-28
================================================
總交易數: 1
進場: 1 | 出場: 0
警訊: 0
勝率: 0/0 (0.0%)
今日損益: 0
================================================
```

### 週報告

可用 Python 生成週報告:
```python
import json
from datetime import datetime, timedelta

# 讀取過去 5 天的交易
trades = []
for i in range(5):
    date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
    # ... 讀取 trades_{date}.json
```

---

## 🔐 安全建議

1. **API Key**: 不要將真實的 API Key 提交到 Git
   - 使用環境變數: `export SHIOAJI_API_KEY=xxx`
   - 或在 `configs/global.json` 中設定

2. **模擬模式**: 建議先在模擬模式下運行 2-4 週驗證邏輯

3. **交易日限制**: 系統自動只在交易日 (週一-週五) 執行

4. **日誌保護**: 日誌檔包含交易資訊，請保護好 `logs/` 目錄

---

## 📞 支援

- 檢查日誌: `tail -f logs/sma_bot.log`
- 檢查狀態: `python main.py --status`
- 查看交易: `cat trades/trades_$(date +%Y%m%d).json`

---

**作者**: Claude Code AI
**日期**: 2026-02-28
**版本**: 1.0
**參考架構**: unified_strategy_bot (台指期系統)
