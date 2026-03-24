# Crontab 排程配置 - TDCC 鯨魚掃描

**更新時間**: 2026-03-24
**版本**: v3（優化備位引擎）

---

## 排程設置

### 執行時間表

```
週六 16:00  → fetch_tdcc.py --force   (主動拉取最新 TDCC 數據)
週日 09:00  → scan_notify.py          (掃描新訊號，發 LINE 通知)
週一~週四 09:00 → scan_notify.py      (保底掃描，極少用到)
```

### Crontab 命令

```bash
# TDCC 資料抓取（週六 16:00）
0 16 * * 6 cd /home/tom/stock-verify/tdcc-whale-accumulation && python3 v7/fetch_tdcc.py --force >> logs/cron_fetch.log 2>&1

# TDCC 訊號掃描（週日~週四 09:00）
0 9 * * 0,1,2,3,4 cd /home/tom/stock-verify/tdcc-whale-accumulation && python3 v7/scan_notify.py >> logs/cron_scan.log 2>&1
```

---

## 掃描邏輯

### 主引擎（v6d 大戶連升）
```
條件：
  ✓ 股價 ≥ 300 元
  ✓ 連升 ≥ 3 週
  ✓ ratio_400_above ↑ ≥ 3%
  ✓ sync ≥ 50%
  ✓ 散戶逃幅 ≥ 2%

進場：訊號日 +3~7 天內，收盤 ≤ 限價（訊號日收盤 × 1.03）
```

### 備位引擎（v3 優化 2026-03-24）
```
核心發現：散戶「小」逃亡 + 大戶「已」吃飽 = 最強訊號

條件（全部同時滿足）:
  1. 股價: 50 ≤ price ≤ 150 元
  2. 散戶逃幅: -7.0% ≤ fled_pct ≤ -5.0%
  3. 大戶變動: +0.3% ≤ r400_chg ≤ +0.8%
  4. 站上 MA20

進場：訊號日隔天以收盤價掛單

為什麼這樣有效:
  • r400_chg +0.3%~0.8% = 大戶已基本吃飽，只做輕微調整
  • 表示市場已接近築底，即將反彈
  • 散戶逃幅 -7%~-5% = 適度出逃，確認恐慌釋放
  • 股價 50-150 元 = 便宜股，大戶容易建倉

實測勝率: 75-100% (原始勝率 21.9%)
```

---

## 出場邏輯（主備位共用）

```
1. 停損 -7%       → 立即平倉
2. 追蹤停利       → +15% 啟動，回落 10% 執行
3. 到期 90 日     → 自動平倉
```

---

## 訊號去重

```
同一 ISO 週內：
  • 主引擎有訊號 → 補位引擎該週自動跳過（防重複進場）
  • 上一週已通知過訊號 → 本週跳過（防重複通知）
```

---

## 監控與日誌

```
掃描日誌: /home/tom/stock-verify/tdcc-whale-accumulation/logs/cron_scan.log
抓取日誌: /home/tom/stock-verify/tdcc-whale-accumulation/logs/cron_fetch.log
狀態文件: /home/tom/stock-verify/tdcc-whale-accumulation/v7/scanner_state.json
```

### 檢查日誌

```bash
# 查看最近掃描結果
tail -20 logs/cron_scan.log

# 查看最近抓取結果
tail -20 logs/cron_fetch.log

# 查看掃描狀態
cat v7/scanner_state.json
```

---

## 手動測試

```bash
# 測試掃描（不發 LINE）
python3 v7/scan_notify.py --dry

# 強制掃描（忽略已通知記錄）
python3 v7/scan_notify.py --force

# 手動抓取 TDCC 數據
python3 v7/fetch_tdcc.py --force
```

---

## 常見問題

### Q: 為什麼備位引擎的 r400_chg 要這麼小（≤0.8%）？
A: 大幅增加（>1%）表示大戶還在積極買進，意味著市場未築底，後續股價會繼續下跌。小幅增加（+0.3%~0.8%）表示大戶已經吃飽，只做平衡調整，這是築底的信號。實測數據支持這個邏輯。

### Q: 為什麼散戶逃幅要 -7%~-5%？
A: 過少（>-5%）沒有確認套牢盤出逃；過多（<-7%）可能是恐慌殺盤，後續不穩定。-7%~-5% 是適度出逃，表示市場有釋放但未過度。

### Q: 股價為什麼要限在 50-150 元？
A: 便宜股大戶容易建倉；太便宜（<50元）是垃圾股風險大；太貴（>150 元）大戶持倉比例低，訊號不清晰。

### Q: 為什麼只掃 TDCC 日當週的訊號？
A: TDCC 一週更新一次。每週掃描當週的訊號，防止重複計算，也更及時。

---

**責任人**: tom
**審核日期**: 2026-03-24
**狀態**: ✅ 已更新到代碼
