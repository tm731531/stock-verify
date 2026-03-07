#!/bin/bash

# TDCC 爬蟲自動化運行腳本
# 用途：每週五下午自動更新 TDCC 大戶持股數據

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

# 確保在正確的目錄
cd "$PROJECT_DIR" || exit 1

# 設定日誌
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/crawler_$(date +%Y%m%d_%H%M%S).log"

# 運行爬蟲
echo "[$(date)] 開始執行 TDCC 爬蟲..." | tee -a "$LOG_FILE"

PYTHONPATH=src python3 src/crawler/main.py \
    --max-dates 10 \
    --delay 0.2 \
    --verbose >> "$LOG_FILE" 2>&1

RESULT=$?

if [ $RESULT -eq 0 ]; then
    echo "[$(date)] ✓ 爬蟲執行成功" | tee -a "$LOG_FILE"

    # 自動重跑 v7 SCAN 版本（如果有）
    echo "[$(date)] 開始重跑 v7 SCAN 版本..." | tee -a "$LOG_FILE"

    if [ -f "v7/fetch_tdcc.py" ]; then
        echo "[$(date)] ① 抓取 TDCC 資料..." | tee -a "$LOG_FILE"
        python3 v7/fetch_tdcc.py --force >> "$LOG_FILE" 2>&1
        echo "[$(date)] ✓ TDCC 資料抓取完成" | tee -a "$LOG_FILE"
    fi

    if [ -f "v7/scan_notify.py" ]; then
        echo "[$(date)] ② 掃描股票信號（算股號）..." | tee -a "$LOG_FILE"
        python3 v7/scan_notify.py >> "$LOG_FILE" 2>&1
        echo "[$(date)] ✓ 信號掃描完成" | tee -a "$LOG_FILE"
    fi
else
    echo "[$(date)] ✗ 爬蟲執行失敗（代碼 $RESULT）" | tee -a "$LOG_FILE"
    exit 1
fi

echo "[$(date)] 完成所有任務" | tee -a "$LOG_FILE"
