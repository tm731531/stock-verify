# ⚙️ 另一台機器要完成的事項

**目標**: 在另一台機器上部署 006208 SMA20/50 日線交易系統（永豐金 API + 定時執行）

**時間估計**: 30 分鐘

**難度**: ⭐ 簡單（只需配置，代碼已完成）

---

## 🎯 目標結果

```
每日 12:30 自動執行 SMA20/50 交易機器人
↓
取得 006208 K 線數據（永豐金 API）
↓
計算 SMA20/50 + ATR 指標
↓
產生進出場訊號
↓
記錄到 JSON/CSV 檔案
```

---

## ✅ 完成清單

### 第 1 部分：環境準備（5 分鐘）

```bash
# 1.1 複製代碼到工作目錄
git clone <repo_url> /path/to/sma_006208_trading
cd /path/to/sma_006208_trading

# 1.2 安裝依賴
pip3 install pandas numpy shioaji

# 1.3 建立必要目錄
mkdir -p data logs sma_006208_daily_bot/{configs,states,trades,logs}
```

**檢查**: `ls -la` 確認目錄結構

---

### 第 2 部分：API 認證配置（10 分鐘）

```bash
# 2.1 編輯配置檔
nano sma_006208_daily_bot/configs/global.json
```

**填入以下內容**:
```json
{
  "api_key": "填入永豐金 API_KEY",
  "secret_key": "填入永豐金 SECRET_KEY",
  "ca_path": "",
  "ca_passwd": "",
  "person_id": "填入身分證字號（可選）",
  "simulation": false,
  "enable_ordering": false,
  "poll_interval": 5,
  "symbol": "006208",
  "description": "台灣50 ETF (006208) 日線 SMA 市場制度系統"
}
```

**需要的三個資訊**:
- [ ] API_KEY （向永豐金取得）
- [ ] SECRET_KEY （向永豐金取得）
- [ ] 身分證字號 （自己的）

---

### 第 3 部分：測試連線（5 分鐘）

```bash
# 3.1 進入機器人目錄
cd sma_006208_daily_bot

# 3.2 測試連線
python3 main.py --status
```

**預期輸出**:
```
SMA 006208 日線系統 - 狀態
======================================================================
[全域設定]
  商品: 006208
  交易開關: 停用 (模擬模式)
  模擬模式: 否

[策略設定]
  SMA短期: 20 日
  SMA長期: 50 日
```

**如果失敗**: 檢查 API_KEY 和 SECRET_KEY 是否正確

---

### 第 4 部分：執行測試（5 分鐘）

```bash
# 4.1 確保模擬模式
python3 main.py --disable

# 4.2 執行一次測試
python3 main.py

# 4.3 檢查輸出
tail logs/sma_bot.log
```

**應該看到**:
```
[2026-02-28 12:30:00] SMA 006208 日線系統 - 開始執行
[2026-02-28 12:30:00] 市場訊號: BULL
[2026-02-28 12:30:00] 價格: $98.50
[2026-02-28 12:30:00] SMA20 (短線): $98.20
[2026-02-28 12:30:00] SMA50 (長線): $97.80
```

---

### 第 5 部分：設定定時執行（5 分鐘）

```bash
# 5.1 進入 scripts 目錄
cd /path/to/sma_006208_trading/scripts

# 5.2 自動配置（推薦）
bash setup_crontab.sh

# 5.3 驗證配置
crontab -l
```

**應該看到**:
```
# SMA006208 每日機器人 (台灣時間 12:30)
30 12 * * 1-5 /path/to/scripts/run_daily_bot.sh
```

---

### 第 6 部分：驗證定時任務（3 分鐘）

```bash
# 6.1 檢查 Crontab 已設置
crontab -l

# 6.2 檢查系統日誌
grep CRON /var/log/syslog | tail -10

# 6.3 監看日誌輸出（等待下一個 12:30，或手動執行測試）
bash /path/to/scripts/run_daily_bot.sh
tail logs/crontab_*.log
```

---

## 🚨 常見問題排查

### ❌ API 認證失敗
```bash
# 檢查 API_KEY 和 SECRET_KEY
cat sma_006208_daily_bot/configs/global.json | grep -E "api_key|secret_key"

# 確認是否為正確的字符串（不包含 "YOUR_" 開頭的佔位符）
```

### ❌ Crontab 無法執行
```bash
# 檢查腳本有執行權限
ls -la scripts/run_daily_bot.sh
# 應該看到 -rwxr-xr-x

# 手動執行測試
bash scripts/run_daily_bot.sh

# 檢查錯誤信息
tail logs/crontab_*.log
```

### ❌ 日誌中沒有資料
```bash
# 檢查 CSV 數據是否存在
ls -la data/006208_historical.csv

# 如果沒有，API 會自動下載
# 等待 API 取得數據後重試
```

---

## 📊 快速檢查表

在完成每個步驟後，勾選：

- [ ] **環境**：Python 3.7+、pandas、numpy、shioaji 已安裝
- [ ] **配置**：global.json 已填入 API_KEY、SECRET_KEY、身分證字號
- [ ] **連線**：`python3 main.py --status` 執行成功，顯示 SMA20/50
- [ ] **測試**：`python3 main.py` 執行成功，生成日誌檔案
- [ ] **Crontab**：`crontab -l` 顯示每日 12:30 執行的 job
- [ ] **驗證**：`grep CRON /var/log/syslog` 顯示成功執行記錄

---

## 🎯 下一步（可選）

完成上述步驟後，系統會每日 12:30 自動執行。

### 監控（可選）
```bash
# 實時監看日誌
tail -f logs/sma_bot.log
tail -f logs/crontab_*.log

# 查看交易記錄
cat sma_006208_daily_bot/trades/trades_*.json | jq .
```

### 切換到實盤（謹慎）
當確認邏輯無誤後：
```bash
# 1. 更新配置啟用實盤
nano sma_006208_daily_bot/configs/global.json
# 改: "enable_ordering": false → true

# 2. 測試（會進行模擬下單）
python3 sma_006208_daily_bot/main.py

# 3. 檢查日誌無誤後，Crontab 會自動執行實盤
```

---

## 📞 問題聯繫

如遇到問題，檢查以下文檔：
- `IMPLEMENTATION_GUIDE.md` - 完整系統說明
- `DEPLOYMENT_WITH_SHIOAJI.md` - API 詳細配置和故障排除
- `scripts/run_daily_bot.sh` - Crontab 執行腳本說明
- `scripts/setup_crontab.sh` - Crontab 配置工具說明

---

**預計完成時間**: 30 分鐘
**難度**: ⭐ 簡單（配置即可，代碼已完成）
**最後檢查**: 等待明天 12:30 看是否自動執行 ✅

