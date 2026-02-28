# 永豐金 API 整合 & 定時腳本部署指南

**版本**: 1.0
**日期**: 2026-02-28
**環境**: 永豐金 Shioaji API + Linux Crontab

---

## 📋 目錄

1. [環境設置](#環境設置)
2. [Shioaji 集成](#shioaji-集成)
3. [定時腳本配置](#定時腳本配置)
4. [生產部署檢查清單](#生產部署檢查清單)
5. [監控和維護](#監控和維護)

---

## 環境設置

### 前置要求

```bash
# 檢查 Python 版本
python3 --version  # 需要 3.7+

# 安裝依賴
pip3 install pandas numpy shioaji
```

### 目錄結構（參考）

```
/home/user/sma_006208_trading/
├── data/
│   └── 006208_historical.csv              # 初始歷史數據（首次執行時同步）
├── sma_006208_daily_bot/
│   ├── configs/
│   │   ├── global.json
│   │   └── sma_strategy.json
│   ├── states/
│   │   └── sma_bot_state.json
│   ├── trades/
│   │   ├── trades_YYYYMMDD.json
│   │   └── signals_YYYYMMDD.json
│   ├── logs/
│   │   └── sma_bot.log
│   ├── config_manager.py
│   ├── sma_market_regime.py
│   ├── trade_logger.py
│   └── main.py
├── scripts/
│   ├── run_daily_bot.sh                   # 定時執行腳本
│   └── setup_crontab.sh                   # Crontab 初始化腳本
├── IMPLEMENTATION_GUIDE.md
└── DEPLOYMENT_WITH_SHIOAJI.md
```

---

## Shioaji 集成

### Step 1: 修改 main.py 的數據源

在 `main.py` 中，修改 `get_latest_data()` 函數以優先使用 Shioaji API：

```python
def fetch_data_from_api(config: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """從永豐金 Shioaji API 取得即時數據"""
    try:
        import shioaji as sj
    except ImportError:
        logger.warning("shioaji 未安裝，跳過 API 資料取得")
        return None

    try:
        # 初始化 API（模擬模式）
        api = sj.Shioaji(simulation=config.get('simulation', True))

        # 使用配置的認證資訊
        api_key = config.get('api_key')
        secret_key = config.get('secret_key')

        if api_key == "YOUR_API_KEY" or not api_key:
            logger.warning("API 認證資訊未設定")
            return None

        # 登入
        api.login(api_key=api_key, secret_key=secret_key)
        logger.info("✅ 永豐金 API 登入成功")

        # 取得 006208 K 線數據
        symbol = config.get('symbol', '006208')
        contract = api.Contracts.Stocks[symbol]

        # 取得最近 100 天數據（用於計算 SMA50）
        today = datetime.now()
        start_date = (today - timedelta(days=100)).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')

        kbars = api.kbars(contract, start=start_date, end=end_date)

        if kbars is not None and not kbars.empty:
            df = pd.DataFrame({
                'Date': kbars.index,
                'Open': kbars['open'].values,
                'High': kbars['high'].values,
                'Low': kbars['low'].values,
                'Close': kbars['close'].values,
                'Volume': kbars['volume'].values
            })
            df.set_index('Date', inplace=True)

            api.logout()
            logger.info(f"✅ 取得 {len(df)} 根 K 線數據")
            return df

        api.logout()
        logger.warning("無法從 API 取得數據，嘗試使用 CSV 備用")
        return None

    except Exception as e:
        logger.error(f"❌ Shioaji API 錯誤: {e}")
        return None
```

### Step 2: 配置認證資訊

編輯 `sma_006208_daily_bot/configs/global.json`：

```json
{
  "api_key": "YOUR_API_KEY",           // 從永豐金取得
  "secret_key": "YOUR_SECRET_KEY",     // 從永豐金取得
  "ca_path": "/path/to/ca.pem",        // 憑證路徑（如需要）
  "ca_passwd": "your_password",        // 憑證密碼（如需要）
  "person_id": "YOUR_ID",              // 身分證字號
  "simulation": false,                 // false = 實盤, true = 模擬
  "enable_ordering": false,            // false = 模擬下單, true = 實際下單
  "poll_interval": 5,
  "symbol": "006208",
  "description": "台灣50 ETF (006208) 日線 SMA 市場制度系統"
}
```

### Step 3: 測試 API 連線

```bash
cd sma_006208_daily_bot
python3 main.py --status
```

預期輸出：
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
  波動率閾值: 1.5x

[當前狀態]
  倉位: 無倉位
  進場價格: $0.00
  進場日期: 無
  今日交易數: 0
```

---

## 定時腳本配置

### Step 1: 建立 Crontab 執行腳本

**檔案**: `scripts/run_daily_bot.sh`

```bash
#!/bin/bash

# SMA006208 日線機器人 - Crontab 執行腳本
# 每日 12:30 執行

# 設定變數
BOT_DIR="/path/to/sma_006208_trading/sma_006208_daily_bot"
LOG_DIR="/path/to/sma_006208_trading/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/crontab_${TIMESTAMP}.log"

# 確保日誌目錄存在
mkdir -p "$LOG_DIR"

# 記錄執行時間
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 開始執行 SMA006208 日線機器人" >> "$LOG_FILE"

# 進入工作目錄
cd "$BOT_DIR" || exit 1

# 執行機器人
python3 main.py >> "$LOG_FILE" 2>&1

# 檢查執行結果
if [ $? -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 執行成功" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 執行失敗 (exit code: $?)" >> "$LOG_FILE"
fi

exit 0
```

### Step 2: 設置 Crontab

```bash
# 編輯 crontab
crontab -e

# 加入以下行
# 每日 12:30 執行（台灣時間，週一到週五）
30 12 * * 1-5 /path/to/sma_006208_trading/scripts/run_daily_bot.sh

# 或使用以下行確保時區正確
30 12 * * 1-5 export TZ=Asia/Taipei && /path/to/sma_006208_trading/scripts/run_daily_bot.sh
```

### Step 3: 驗證 Crontab 設置

```bash
# 檢查當前的 crontab 設置
crontab -l

# 檢查 crontab 日誌（系統日誌）
grep CRON /var/log/syslog          # Debian/Ubuntu
grep CRON /var/log/messages         # CentOS/RHEL
```

### Step 4: 測試定時執行

```bash
# 手動執行腳本測試
bash /path/to/sma_006208_trading/scripts/run_daily_bot.sh

# 檢查日誌
tail -f /path/to/sma_006208_trading/logs/crontab_*.log
```

---

## 生產部署檢查清單

### 前置設置
- [ ] Python 3.7+ 已安裝
- [ ] 依賴包已安裝（pandas, numpy, shioaji）
- [ ] 永豐金 API 認證資訊已取得
- [ ] 目錄結構已建立
- [ ] CSV 歷史數據已準備（至少 50+ 交易日）

### Shioaji 整合
- [ ] API 認證資訊已配置到 global.json
- [ ] `python3 main.py --status` 可正確運行
- [ ] API 登入測試成功
- [ ] 數據可正確從 API 取得

### 定時腳本
- [ ] `scripts/run_daily_bot.sh` 已建立且可執行
  ```bash
  chmod +x /path/to/scripts/run_daily_bot.sh
  ```
- [ ] 手動測試腳本成功
- [ ] Crontab 已配置
- [ ] Crontab 日誌出現成功執行記錄

### 模擬到實盤
- [ ] 模擬模式下運行至少 1-2 周，驗證信號合理
- [ ] 檢查交易日誌和信號記錄
- [ ] 確認沒有代碼錯誤或邏輯問題
- [ ] 準備好實盤認證資訊
- [ ] 更新 `simulation: false` 和 `enable_ordering: false` → `true`
- [ ] 再次用模擬下單測試
- [ ] 最後啟用 `enable_ordering: true`

### 監控設置
- [ ] 日誌目錄有足夠的磁盤空間
- [ ] 日誌輪轉策略已配置（防止日誌檔案過大）
- [ ] 監控腳本已設置（可選）

---

## 監控和維護

### 日誌監控

```bash
# 實時監控最新日誌
tail -f /path/to/logs/sma_bot.log

# 查看最近的 Crontab 執行
tail -20 /path/to/logs/crontab_*.log

# 搜尋錯誤
grep -i "error\|❌\|failed" /path/to/logs/sma_bot.log
```

### 日誌輪轉（防止磁盤滿）

**檔案**: `/etc/logrotate.d/sma_bot`

```bash
/path/to/sma_006208_trading/logs/sma_bot.log {
    daily                    # 每天輪轉
    rotate 30               # 保留 30 個備份
    compress                # 壓縮舊日誌
    delaycompress           # 延遲壓縮
    missingok               # 檔案不存在不報錯
    notifempty              # 空檔案不輪轉
}
```

### 定期檢查清單

**每日檢查**:
- [ ] 機器人是否正常執行（檢查日誌）
- [ ] 是否有新的進出場信號
- [ ] 是否有警訊或錯誤

**每周檢查**:
- [ ] 交易績效是否符合預期
- [ ] 是否需要調整 SMA 參數
- [ ] Crontab 是否持續運行

**每月檢查**:
- [ ] 回測結果與實盤績效對比
- [ ] 日誌檔案大小和磁盤使用情況
- [ ] API 連接穩定性

---

## 故障排除

### 問題 1: Crontab 未執行

**症狀**: 預定時間未執行機器人

**檢查步驟**:
```bash
# 1. 確認 crontab 已配置
crontab -l

# 2. 檢查 crontab 服務是否運行
sudo systemctl status cron

# 3. 檢查系統日誌
grep CRON /var/log/syslog | tail -20

# 4. 檢查檔案權限
ls -la /path/to/scripts/run_daily_bot.sh
# 應該有執行權限 (x)
```

**解決方案**:
```bash
# 重新設置執行權限
chmod +x /path/to/scripts/run_daily_bot.sh

# 重啟 crontab 服務
sudo systemctl restart cron
```

### 問題 2: API 認證失敗

**症狀**: 日誌顯示 "API 登入失敗"

**檢查步驟**:
```bash
# 1. 檢查認證資訊
cat sma_006208_daily_bot/configs/global.json | grep api_key

# 2. 測試 API 連線
python3 -c "import shioaji; print('✅ Shioaji 已安裝')"

# 3. 手動測試登入
python3 << 'EOF'
import shioaji as sj
api = sj.Shioaji(simulation=False)
api.login(api_key="YOUR_KEY", secret_key="YOUR_SECRET")
print("✅ 登入成功")
api.logout()
EOF
```

**解決方案**:
- 驗證 API 密鑰是否有效（與永豐金聯繫）
- 檢查 API 限額是否用盡
- 確認網絡連接正常

### 問題 3: 數據丟失或不完整

**症狀**: K 線數據為空或不足

**檢查步驟**:
```bash
# 1. 檢查 CSV 檔案
head -5 data/006208_historical.csv
wc -l data/006208_historical.csv

# 2. 檢查 API 數據
python3 << 'EOF'
import pandas as pd
df = pd.read_csv('data/006208_historical.csv')
print(f"數據行數: {len(df)}")
print(f"日期範圍: {df['Date'].min()} ~ {df['Date'].max()}")
EOF
```

**解決方案**:
- 確保 CSV 檔案有至少 50+ 個交易日
- 檢查網絡連接
- 等待市場開盤時間重試

---

## 進階配置

### 多機器部署

如果在多台機器上部署，可以使用配置同步：

```bash
# 機器 A（主機器）
git clone <repo> /path/to/sma_006208_trading
cd /path/to/sma_006208_trading

# 機器 B（備機器）
git clone <repo> /path/to/sma_006208_trading
cd /path/to/sma_006208_trading
# 從主機器複製配置
scp user@machine_a:/path/to/configs/* ./sma_006208_daily_bot/configs/
```

### 備份策略

```bash
# 每日備份交易記錄
0 13 * * 1-5 tar -czf /backup/sma_trades_$(date +\%Y\%m\%d).tar.gz \
  /path/to/sma_006208_trading/sma_006208_daily_bot/trades/

# 每周備份配置
0 0 * * 0 tar -czf /backup/sma_config_$(date +\%Y\%m\%d).tar.gz \
  /path/to/sma_006208_trading/sma_006208_daily_bot/configs/
```

---

## 關鍵指標監控

每日應監控以下指標：

| 指標 | 預期值 | 檢查點 |
|------|--------|--------|
| **機器人執行** | 每日 1 次 | Crontab 日誌 |
| **API 連線** | 成功 | logs/sma_bot.log |
| **信號產生** | 視市場 | trades/signals_*.json |
| **錯誤數** | 0 | grep "error" logs/ |
| **磁盤使用** | < 80% | df -h |

---

## 聯絡方式和支持

### 常見問題快速解答

| 問題 | 解決方案 |
|------|--------|
| API 無法連接 | 檢查 API_KEY/SECRET，確認網絡 |
| Crontab 未執行 | 檢查權限，確認時間設置 |
| 日誌檔案過大 | 配置 logrotate 輪轉 |
| 信號不產生 | 檢查市場是否開盤，數據是否足夠 |

### 緊急操作

```bash
# 立即停止機器人（編輯 crontab）
crontab -e
# 註解掉執行行或設置狀態為禁用
python3 main.py --disable

# 重置系統狀態
python3 main.py --reset

# 恢復運行
python3 main.py --enable
crontab -e
# 取消註解或重新啟用
```

---

**最後更新**: 2026-02-28
**版本**: 1.0 Production Ready
**狀態**: ✅ 準備永豐金 API 部署
