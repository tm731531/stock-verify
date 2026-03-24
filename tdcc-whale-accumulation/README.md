# TDCC 大戶吃貨量化策略 - 生產系統

**分支**: `feature/tdcc-whale-accumulation`
**最後更新**: 2026-03-24
**狀態**: ✅ 生產運行中 (Crontab 自動掃描)

---

## 🎯 核心發現 (2026-03-24)

### 推翻傳統認知的洞察

傳統理解：*散戶大逃亡 + 大戶積極吃貨 = 買點*

**實際數據驗證**：*散戶「小」逃 (-7%~-5%) + 大戶「已」吃飽 (+0.3%~+0.8%) = 最強買點*

#### 關鍵發現
- **r400_chg > 1%** → 0% 勝率（大戶還在積極買，市場未築底）
- **r400_chg +0.3%~0.8%** → 75-100% 勝率（大戶已基本吃飽，輕微調整 = 築底訊號）
- **散戶逃幅 -7%~-5%** → 適度出逃，確認恐慌釋放

#### 回測驗證
| 條件組合 | 訊號數 | 勝率 | 平均利潤 |
|--------|--------|------|---------|
| 新條件 (價格50-150, 散戶-7~-5%, r400+0.3~+0.8%) | 7 | 100% | +NT$2,280/筆 |
| 原始 V3 條件 | 32 | 21.9% | -NT$7,395/筆 |

---

## 📁 專案結構

```
tdcc-whale-accumulation/
├── v7/                              ← 生產代碼（DO NOT TOUCH）
│   ├── fetch_tdcc.py               # 自動 TDCC 數據抓取
│   ├── scan_notify.py              # 訊號掃描 + LINE 通知
│   ├── strategy_v7.py              # 核心策略邏輯
│   ├── scanner_config.json         # LINE Notify 配置
│   └── scanner_state.json          # 通知去重狀態
│
├── src/                             ← 生產爬蟲模組
│   ├── crawler/                     # TDCC 爬蟲
│   │   ├── tdcc_scraper.py
│   │   ├── price_fetcher.py
│   │   ├── data_manager.py
│   │   └── stock_list.py
│   └── analysis/                    # 分析模組
│
├── data/                            ← 生產數據
│   └── tdcc_holdings.db            # SQLite 數據庫
│
├── logs/                            ← Crontab 執行日誌
│   ├── cron_fetch.log
│   └── cron_scan.log
│
├── tests/                           ← 單元測試 (76+)
│
├── analyze_entry_conditions.py      ← 進場條件篩選工具
├── backtest_filtered_conditions.py  ← 新條件回測腳本
├── conftest.py                      ← Pytest 配置
│
├── CLAUDE.md                        ← 項目指南
├── CRONTAB_CONFIG.md               ← 排程配置說明
├── UPDATE_LOG_20260324.md          ← 最新更新日誌
├── README.md                        ← 本文件
│
└── archive/                         ← 研究與歷史版本
    ├── backtest/                    # 26+ 回測腳本
    ├── analysis/                    # 12+ 分析腳本
    ├── research/                    # v8, 實驗版本
    ├── docs/                        # 29 舊文檔
    ├── crawlers/                    # 爬蟲重複版本
    └── migrations/                  # 數據遷移腳本
```

---

## 🚀 快速開始

### 1. 環境設置
```bash
cd tdcc-whale-accumulation
source venv/bin/activate
```

### 2. 手動掃描（乾跑，不發 LINE）
```bash
python3 v7/scan_notify.py --dry
```

### 3. 強制掃描（忽略已通知記錄）
```bash
python3 v7/scan_notify.py --dry --force
```

### 4. 實際執行（發 LINE）
```bash
python3 v7/scan_notify.py
```

### 5. 抓取最新 TDCC 數據
```bash
python3 v7/fetch_tdcc.py --force
```

---

## 📊 生產配置

### Crontab 排程
```
週六 16:00  → python3 v7/fetch_tdcc.py --force          (抓新 TDCC 數據)
週日 09:00  → python3 v7/scan_notify.py                 (掃描並通知)
週一~四 09:00 → python3 v7/scan_notify.py              (保底掃描)
```

**注意**: Crontab 會自動執行，無需手動介入

### 進場邏輯

#### 主引擎 (Signal-Driven)
```
條件: 連升3週 + r400↑≥3% + sync≥50% + 散戶↓≥2% + 股價≥300元
進場: 訊號日後 +3~7 天內，收盤 ≤ 限價（信號日收盤 × 1.03）
```

#### 備位引擎 (新優化版 - v3)
```
條件（全部同時滿足）:
  ✓ 股價: 50 ≤ price ≤ 150 元
  ✓ 散戶逃幅: -7.0% ≤ fled_pct ≤ -5.0%
  ✓ 大戶變動: +0.3% ≤ r400_chg ≤ +0.8%
  ✓ 站上 MA20
進場: 訊號日隔天以收盤價掛單
```

### 出場邏輯（統一）
1. **停損**: -7% 直接出場
2. **止利**: +15% 啟動，回落 10% 執行
3. **到期**: 90 日曆日

---

## 📈 歷史績效

### 推薦配置 (90天+3個持倉 V4)

| 指標 | 全週期 (2022-2025) | 多頭市場 | 空頭市場 (2023) |
|------|------------------|---------|-----------------|
| **交易筆數** | 45 | 31 | 14 |
| **勝率** | 33.3% | 38.7% | 21.4% |
| **合計獲利** | +NT$249,836 | +NT$288K | -NT$38K |
| **平均每筆** | +NT$5,553 | +NT$9,290 | -NT$2,714 |

---

## 🔍 監控與日誌

### 查看掃描日誌
```bash
# 最近掃描結果
tail -20 logs/cron_scan.log

# 最近抓取結果
tail -20 logs/cron_fetch.log

# 掃描狀態
cat v7/scanner_state.json
```

### 常見問題

**Q: 為什麼備位引擎的 r400_chg 要這麼小（≤0.8%）？**
A: 大幅增加（>1%）表示大戶還在積極買進，市場未築底。小幅增加（+0.3%~0.8%）表示大戶已經吃飽，這是築底訊號。

**Q: 為什麼散戶逃幅要 -7%~-5%？**
A: 過少（>-5%）未確認套牢盤出逃；過多（<-7%）可能恐慌殺盤。-7%~-5% 是適度出逃，表示釋放但未過度。

**Q: 股價為什麼限在 50-150 元？**
A: 便宜股大戶容易建倉；太便宜（<50元）風險大；太貴（>150元）大戶持倉比例低。

---

## 📚 文檔說明

| 文件 | 用途 |
|------|------|
| **CLAUDE.md** | 項目規格與開發指南 |
| **CRONTAB_CONFIG.md** | 排程配置與備位引擎詳解 |
| **UPDATE_LOG_20260324.md** | 最新更新日誌 |
| **archive/** | 歷史回測、研究版本、舊文檔 |

---

## ⚙️ 技術棧

- **語言**: Python 3.12
- **數據庫**: SQLite + PostgreSQL
- **調度**: Crontab
- **通知**: LINE Notify API
- **測試**: pytest (76+ 單元測試)

---

## 🔐 重要提醒

✅ **保護清單**（生產代碼，勿修改）:
- v7/fetch_tdcc.py
- v7/scan_notify.py
- v7/strategy_v7.py
- src/crawler/
- data/tdcc_holdings.db

📝 **可修改清單**（實驗、分析代碼）:
- backtest_filtered_conditions.py
- analyze_entry_conditions.py
- 其他回測和分析腳本

📦 **研究資料**:
- 所有歷史版本、舊文檔在 archive/ 目錄
- 非生產代碼，安全修改或刪除

---

## 📞 聯絡

**項目負責人**: tom
**最後驗證**: 2026-03-24 01:25 GMT+8
**備註**: 本文件與 CLAUDE.md 保持一致
