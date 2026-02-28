#!/bin/bash

################################################################################
# SMA006208 日線交易機器人 - Crontab 執行腳本
################################################################################
#
# 用途: 每日 12:30 台灣時間執行 SMA20/50 交易系統
#
# 部署步驟:
#   1. 編輯此檔案，設置 BOT_DIR 和 LOG_DIR
#   2. chmod +x run_daily_bot.sh
#   3. crontab -e
#   4. 加入: 30 12 * * 1-5 /path/to/run_daily_bot.sh
#
# 檢查執行:
#   crontab -l                    # 檢查 crontab 配置
#   tail -f logs/crontab_*.log   # 監看日誌
#
################################################################################

# ============================================================================
# 配置區 - 請根據實際環境修改
# ============================================================================

# 機器人工作目錄
BOT_DIR="/home/user/sma_006208_trading/sma_006208_daily_bot"

# 日誌目錄
LOG_DIR="/home/user/sma_006208_trading/logs"

# Python 執行檔
PYTHON_CMD="python3"

# ============================================================================
# 執行邏輯 - 一般不需修改
# ============================================================================

# 生成帶時間戳的日誌檔名
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/crontab_${TIMESTAMP}.log"

# 確保日誌目錄存在
mkdir -p "$LOG_DIR"

# ============================================================================
# 執行日誌記錄函數
# ============================================================================

log_message() {
    local level=$1
    local message=$2
    local datetime=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${datetime}] [${level}] ${message}" | tee -a "$LOG_FILE"
}

# ============================================================================
# 主程式執行
# ============================================================================

log_message "INFO" "================================"
log_message "INFO" "SMA006208 日線機器人 - 開始執行"
log_message "INFO" "================================"

# 檢查工作目錄是否存在
if [ ! -d "$BOT_DIR" ]; then
    log_message "ERROR" "工作目錄不存在: $BOT_DIR"
    exit 1
fi

log_message "INFO" "工作目錄: $BOT_DIR"
log_message "INFO" "日誌檔案: $LOG_FILE"

# 進入工作目錄
cd "$BOT_DIR" || exit 1
log_message "INFO" "✅ 進入工作目錄"

# 檢查是否有足夠的磁盤空間（至少 100MB）
available_space=$(df /home | tail -1 | awk '{print $4}')
if [ "$available_space" -lt 102400 ]; then
    log_message "WARN" "磁盤空間不足 (剩餘: ${available_space}KB)"
fi

# 執行機器人
log_message "INFO" "執行機器人..."
$PYTHON_CMD main.py >> "$LOG_FILE" 2>&1
exit_code=$?

# ============================================================================
# 執行結果處理
# ============================================================================

if [ $exit_code -eq 0 ]; then
    log_message "INFO" "✅ 執行成功"
    log_message "INFO" "================================"
    exit 0
else
    log_message "ERROR" "❌ 執行失敗 (exit code: $exit_code)"
    log_message "ERROR" "请检查 main.py 的错误信息"
    log_message "INFO" "================================"
    exit $exit_code
fi
