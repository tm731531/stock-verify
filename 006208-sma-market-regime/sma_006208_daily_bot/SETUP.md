# 快速安裝指南

## 5 分鐘快速開始

### 步驟 1: 進入目錄

```bash
cd /home/tom/shioaji-trading/working/sma_006208_daily_bot
```

### 步驟 2: 安裝依賴

```bash
pip install pandas numpy shioaji
```

### 步驟 3: 初始化設定

```bash
# 首次執行會自動建立 configs/global.json 和 configs/sma_strategy.json
python main.py --status
```

### 步驟 4: 設定 API (可選)

編輯 `configs/global.json`:

```json
{
  "api_key": "YOUR_ACTUAL_API_KEY",
  "secret_key": "YOUR_ACTUAL_SECRET_KEY",
  "simulation": false,  // 改為 false 使用實際 API
  "enable_ordering": false,  // 先用模擬模式測試
  "symbol": "0050"
}
```

### 步驟 5: 測試執行

```bash
# 模擬模式測試 (不會下單)
python main.py

# 應該看到類似輸出:
# [INFO] SMA 006208 日線系統 - 開始執行
# [INFO] 市場訊號: BULL
# ...
```

### 步驟 6: 設定 Crontab

```bash
# 編輯 crontab
crontab -e

# 添加這一行 (每日 12:30 執行)
30 12 * * 1-5 cd /home/tom/shioaji-trading/working/sma_006208_daily_bot && python main.py >> /tmp/sma_cron.log 2>&1
```

### 步驟 7: 啟用實盤 (可選)

```bash
# 先驗證 1-2 週後，確認邏輯無誤
python main.py --enable

# 之後可隨時停用回到模擬
python main.py --disable
```

---

## 日常操作

### 每日查看

```bash
# 查看今日交易記錄
cat trades/trades_$(date +%Y%m%d).json

# 查看系統狀態
python main.py --status

# 查看執行日誌
tail -20 logs/sma_bot.log
```

### 週間檢查

```bash
# 查看過去 5 天的交易
ls -ltr trades/trades_*.json | tail -5

# 計算週損益
# (手動計算或寫個 Python 腳本)
```

### 參數調整

如果要改變 SMA 參數:

```bash
# 編輯配置
nano configs/sma_strategy.json

# 改變例如:
# "sma_short": 20    (改為 20)
# "sma_long": 60     (改為 60)

# 然後重新執行
python main.py --status
```

---

## 常見設定組合

### 配置 A: 完全自動化 (推薦)

```json
// configs/global.json
{
  "simulation": false,      // 使用實際 API
  "enable_ordering": false  // 先模擬 1-2 週
}

// configs/sma_strategy.json
{
  "max_trades_per_day": 1,     // 每日最多 1 筆
  "warning_action": "reduce",  // 警訊時減倉
  "warning_reduction_pct": 0.5 // 減倉 50%
}
```

### 配置 B: 保守型 (風險最低)

```json
// 增加 SMA 週期 (更晚進場，更晚出場)
{
  "sma_short": 60,
  "sma_long": 250
}
```

### 配置 C: 激進型 (交易更頻繁)

```json
// 減少 SMA 週期，提高波動率敏感度
{
  "sma_short": 20,
  "sma_long": 50,
  "volatility_threshold_multiplier": 1.2
}
```

---

## 故障檢查清單

- [ ] 目錄權限正確: `ls -la` 檢查
- [ ] 依賴已安裝: `python -c "import pandas, numpy"`
- [ ] Crontab 設定: `crontab -l` 看到條目
- [ ] 日誌可寫入: `touch logs/test.log`
- [ ] 配置檔存在: `ls configs/`
- [ ] 第一次執行成功: `python main.py --status` 無錯誤

---

## 進階設定

### 多個策略參數測試

為了測試不同參數，可以建立多份配置:

```bash
# 建立測試版本
cp configs/sma_strategy.json configs/sma_strategy_v2.json

# 修改 v2 版本的參數
nano configs/sma_strategy_v2.json

# 建立 main_v2.py 使用 v2 配置
# 同時運行兩個版本比較結果
```

### 發送通知 (郵件/Slack)

編輯 `main.py`，在 `run_once()` 中添加:

```python
# 進場時發送郵件通知
if market_status['signal'] == 'entry':
    send_email_notification(...)  # 自行實現
    send_slack_notification(...)   # 自行實現
```

### 整合 Discord Webhook

```python
import requests

def notify_discord(message):
    webhook_url = "YOUR_DISCORD_WEBHOOK"
    requests.post(webhook_url, json={"content": message})

# 在交易發生時呼叫:
notify_discord(f"進場: ${market_status['close']:.2f}")
```

---

## 備份和還原

### 備份交易記錄

```bash
# 備份所有交易
mkdir -p /tmp/sma_backup
cp -r trades logs /tmp/sma_backup/

# 或上傳到雲端
aws s3 sync trades/ s3://my-bucket/sma_trades/
```

### 還原狀態

```bash
# 如果需要重新開始
python main.py --reset

# 或手動清除
rm states/sma_bot_state.json
```

---

## 監控工具建議

### 1. Log Viewer (本地查看)
```bash
tail -f logs/sma_bot.log | grep -E "進場|出場|警訊"
```

### 2. Crontab 檢查
```bash
# 檢查過去 24 小時的執行記錄
cat /var/log/syslog | grep CRON | tail -20
```

### 3. 簡單 Dashboard (Python)
```python
import json
from datetime import datetime

def show_dashboard():
    with open('states/sma_bot_state.json') as f:
        state = json.load(f)

    print(f"倉位: {['無', '持多', '持空'][state['position']+1]}")
    print(f"進場價: ${state['entry_price']}")
    print(f"今日交易: {state['trade_count']}")
```

---

## 完成清單

- [ ] 已安裝依賴
- [ ] 已初始化設定 (配置檔已建立)
- [ ] 已測試執行 (模擬模式)
- [ ] 已設定 Crontab
- [ ] 已驗證 Crontab 執行
- [ ] 已查看交易記錄格式
- [ ] 準備好啟用實盤 (可選)

---

**現在你的 SMA 006208 日線系統已經準備好了！** 🚀

有問題？執行 `python main.py --status` 查看狀態。
