#!/bin/bash

# 監視爬蟲進度，完成後自動運行 v7 SCAN
# 用法：nohup bash monitor_and_run_v7.sh &

PROJECT_DIR="/home/tom/stock-verify/tdcc-whale-accumulation"
TASK_ID="bhx53g8tg"  # 當前爬蟲任務

echo "[$(date)] 開始監視爬蟲..." | tee -a "$PROJECT_DIR/logs/monitor.log"

# 檢查爬蟲是否還在運行（最多等待 2 小時）
MAX_WAIT_MINUTES=120
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT_MINUTES ]; do
    # 嘗試檢查爬蟲狀態
    TASK_STATUS=$(cd /tmp && ls -la /*${TASK_ID}* 2>/dev/null | wc -l)

    if [ $TASK_STATUS -eq 0 ]; then
        echo "[$(date)] ✓ 爬蟲任務已完成" | tee -a "$PROJECT_DIR/logs/monitor.log"
        break
    fi

    echo "[$(date)] 爬蟲還在運行中... (已等待 ${ELAPSED} 分鐘)" | tee -a "$PROJECT_DIR/logs/monitor.log"
    sleep 60
    ELAPSED=$((ELAPSED + 1))
done

# 驗證數據更新
echo "[$(date)] 驗證數據更新..." | tee -a "$PROJECT_DIR/logs/monitor.log"

python3 << 'PYTHON_EOF'
import psycopg2
from datetime import datetime

conn = psycopg2.connect(host='localhost', port=5432, dbname='tdcc', user='tdcc', password='tdcc1234')
cursor = conn.cursor()

cursor.execute("SELECT MAX(date) FROM holdings")
max_date = cursor.fetchone()[0]

print(f"[{datetime.now()}] TDCC 最新日期: {max_date}")

if str(max_date) >= '20260306':
    print(f"[{datetime.now()}] ✓ 數據已更新到最新")
    exit(0)
else:
    print(f"[{datetime.now()}] ⚠️ 數據未更新到預期日期")
    exit(1)

conn.close()
PYTHON_EOF

# 運行 v7 SCAN 版本（1. 抓 TDCC 資料）
echo "[$(date)] 開始運行 v7 SCAN 版本..." | tee -a "$PROJECT_DIR/logs/monitor.log"

cd "$PROJECT_DIR" || exit 1

if [ -f "v7/fetch_tdcc.py" ]; then
    echo "[$(date)] ① 抓取 TDCC 資料..." | tee -a "$PROJECT_DIR/logs/monitor.log"
    python3 v7/fetch_tdcc.py --force >> "$PROJECT_DIR/logs/v7_fetch_tdcc.log" 2>&1
    RESULT=$?

    if [ $RESULT -eq 0 ] || [ $RESULT -eq 1 ]; then
        echo "[$(date)] ✓ TDCC 資料抓取完成 (代碼 $RESULT)" | tee -a "$PROJECT_DIR/logs/monitor.log"
    else
        echo "[$(date)] ✗ TDCC 資料抓取失敗 (代碼 $RESULT)" | tee -a "$PROJECT_DIR/logs/monitor.log"
        exit 1
    fi
fi

# 運行信號掃描（2. 算股號、識別信號）
if [ -f "v7/scan_notify.py" ]; then
    echo "[$(date)] ② 掃描股票信號..." | tee -a "$PROJECT_DIR/logs/monitor.log"
    python3 v7/scan_notify.py >> "$PROJECT_DIR/logs/v7_scan_signals.log" 2>&1
    RESULT=$?

    if [ $RESULT -eq 0 ]; then
        echo "[$(date)] ✓ 信號掃描完成" | tee -a "$PROJECT_DIR/logs/monitor.log"
    else
        echo "[$(date)] ⚠️  信號掃描完成 (代碼 $RESULT)" | tee -a "$PROJECT_DIR/logs/monitor.log"
    fi
fi

echo "[$(date)] ====== 完成所有自動化任務 ======" | tee -a "$PROJECT_DIR/logs/monitor.log"
echo "[$(date)] 請檢查以下日誌文件：" | tee -a "$PROJECT_DIR/logs/monitor.log"
echo "  - 爬蟲日誌: $PROJECT_DIR/logs/*.log" | tee -a "$PROJECT_DIR/logs/monitor.log"
echo "  - v7 SCAN: $PROJECT_DIR/logs/v7_scan.log" | tee -a "$PROJECT_DIR/logs/monitor.log"
