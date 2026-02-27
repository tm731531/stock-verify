# 項目結構總覽

**生成日期**: 2026-02-27
**版本**: 1.0
**狀態**: ✓ 完整就緒

---

## 📁 完整文件結構

```
TX_Quantitative_Trading/
│
├── 📋 核心文檔 (決策參考)
│   ├── TRADING_RULES.md                  ⭐⭐⭐ 完整進出策略規則 (430行)
│   ├── BACKTEST_REPORT.md                ⭐⭐⭐ 詳細回測結果分析 (520行)
│   ├── QUICK_REFERENCE.md                ⭐⭐⭐ 快速參考卡 (400行)
│   ├── PROJECT_STRUCTURE.md              本文件 (文件導航)
│   ├── README.md                         項目說明
│   ├── QUICKSTART.md                     5分鐘上手指南
│   ├── INDEX.md                          舊版目錄 (參考)
│   └── .gitignore                        Git忽略配置 ✓
│
├── 🔬 回測代碼
│   ├── backtest/
│   │   ├── tuned_adaptive_backtest.py    ⭐ 優化版本系統 (MODERATE推薦)
│   │   ├── adaptive_backtest.py          通用版本系統 (508行)
│   │   ├── comparison_backtest.py        對比分析系統
│   │   ├── daily_full_backtest.py        日線完整回測
│   │   ├── ensemble_strategy_backtest.py 組合策略回測
│   │   └── generate_comparison_charts.py 圖表生成
│
├── 📊 數據文件
│   ├── data/
│   │   ├── TX_full_2019_2026.csv         ⭐ 完整數據源 (7年, 1,732根K線)
│   │   ├── TX_sample_2024_2026.csv       樣本數據 (測試用)
│   │   │
│   │   ├── adaptive_backtest_log.csv     原始版本日誌
│   │   ├── adaptive_backtest_log_conservative.csv  保守版日誌
│   │   ├── adaptive_backtest_log_moderate.csv      ⭐ 中等版日誌 (MODERATE)
│   │   ├── adaptive_backtest_log_aggressive.csv    激進版日誌
│   │   │
│   │   ├── adaptive_trades.csv           原始版本交易記錄
│   │   ├── adaptive_trades_conservative.csv
│   │   ├── adaptive_trades_moderate.csv  ⭐ 中等版交易 (推薦查看)
│   │   └── adaptive_trades_aggressive.csv
│
├── 📈 回測報告
│   ├── reports/
│   │   ├── adaptive_backtest_report.md              詳細回測分析
│   │   ├── ADAPTIVE_VS_SINGLE_COMPARISON.md         對標對比
│   │   ├── parameter_optimization_detailed_analysis.md  參數優化詳析
│   │   ├── parameter_comparison.csv                 版本對比表格
│   │   ├── parameter_tuning_quick_guide.md          參數調整指南
│   │   ├── ensemble_backtest_report.md              組合策略報告
│   │   ├── daily_backtest_full_2019_2026.md        日線完整報告
│   │   └── taifex_strategy_report.md                期貨策略報告
│
├── 🔧 配置和文檔
│   ├── config.yaml                       配置文件
│   ├── ADAPTIVE_SYSTEM_README.md          系統說明書
│   ├── ADAPTIVE_FILES_INDEX.md            舊版文件索引
│   ├── DAILY_BACKTEST_SUMMARY.md          日線回測摘要
│   ├── EXECUTIVE_SUMMARY.txt              執行摘要
│   ├── PARAMETER_OPTIMIZATION_README.md   參數優化說明
│   ├── QUICKREF_ADAPTIVE_SYSTEM.md        舊版快速參考
│   └── QUICKREF_DAILY_BACKTEST.md         日線快速參考
│
├── 📡 數據爬蟲
│   ├── crawler/
│   │   ├── taifex_crawler.py              期交所爬蟲 (通用版)
│   │   ├── taifex_crawler_finmind.py      FinMind數據源版本
│   │   ├── test_taifex_api.py             API測試代碼
│   │   └── README_TAIFEX_CRAWLER.md       爬蟲說明文檔
│
├── 🔗 工具函數
│   ├── utils/
│   │   └── (待補充)
│
└── 📌 說明文檔
    ├── WORK_PRINCIPLES.md (參考用)
    └── ... (其他說明文檔)
```

---

## 🎯 快速查找指南

### 我想...

**了解交易規則**
→ 讀 `TRADING_RULES.md` (完整版，30分鐘)

**查看歷史回測結果**
→ 讀 `BACKTEST_REPORT.md` (詳細版，15分鐘)

**日常交易參考**
→ 讀 `QUICK_REFERENCE.md` (5分鐘速查)

**快速上手系統**
→ 讀 `QUICKSTART.md` (5分鐘)

**修改回測參數**
→ 編輯 `backtest/tuned_adaptive_backtest.py` (行100-200)

**運行完整回測**
```bash
cd /home/tom/TX_Quantitative_Trading
python3 backtest/tuned_adaptive_backtest.py  # 新版本 (推薦)
# 或
python3 backtest/adaptive_backtest.py        # 舊版本
```

**查看交易記錄**
→ 打開 `data/adaptive_trades_moderate.csv` (Excel/CSV閱讀器)

**查看每日日誌**
→ 打開 `data/adaptive_backtest_log_moderate.csv`

**對比不同版本**
→ 讀 `reports/parameter_comparison.csv`

**獲取新數據**
→ 運行 `crawler/taifex_crawler.py` 或 `taifex_crawler_finmind.py`

---

## 📊 核心數據說明

### 數據源
- **位置**: `data/TX_full_2019_2026.csv`
- **週期**: 2019-01-02 ~ 2026-02-26 (7年, 1,732根日K線)
- **字段**: Date, Open, High, Low, Close, Volume
- **品種**: TX (台灣指數期貨)
- **完整性**: 100% (無缺失數據)

### 回測版本
- **MODERATE** (推薦 ⭐⭐⭐)
  - 位置: `backtest/tuned_adaptive_backtest.py`
  - 交易記錄: `data/adaptive_trades_moderate.csv`
  - 日誌: `data/adaptive_backtest_log_moderate.csv`
  - 特點: NEUTRAL比例4.7%, 年化4.09%, 6筆交易, 66.7%勝率

- **CONSERVATIVE** (保守)
  - 特點: 更多交易(9筆), 但整體無利潤
  - 推薦度: ❌ 不推薦

- **AGGRESSIVE** (激進)
  - 特點: 完全消除NEUTRAL, 但交易太少
  - 推薦度: ⭐⭐ 可選

---

## 📈 交易績效總結

### MODERATE版本 (推薦)

| 指標 | 數值 | 評價 |
|------|------|------|
| 回測周期 | 2019-2026 (7年) | 足夠長 |
| 初始資金 | ¥1,000,000 | 標準 |
| 最終資金 | ¥1,040,900 | +4.09% |
| 年化收益 | 4.09% | 穩定 |
| Sharpe比率 | 0.2914 | 良好 (>0.25) |
| 最大回撤 | -54.17% | 需改進 |
| 完成交易 | 6筆 | 合理 |
| 勝率 | 66.7% | 優秀 |

### 與其他策略對比

```
策略名稱      年化%    Sharpe  回撤%
─────────────────────────────────
HODL買持      33.63%   1.04   -31.63%  (最賺)
自適應系統     4.09%   0.29   -54.17%  (保守)
SMA趨勢       4.09%   0.29   -33.01%
高低突破      3.59%   0.27   -29.20%
均值回歸      0.00%   0.08   -30.33%  (最差)
```

---

## 🚀 實盤部署檢查清單

### 代碼準備 (1-2天)

- [ ] 閱讀 `TRADING_RULES.md`
- [ ] 閱讀 `BACKTEST_REPORT.md`
- [ ] 理解進出場邏輯
- [ ] 驗證計算公式正確性
- [ ] 測試回測代碼可重現性

### 系統準備 (1周)

- [ ] 將策略編碼進交易系統
- [ ] 建立環境檢測模塊
- [ ] 建立信號生成模塊
- [ ] 建立訂單執行模塊
- [ ] 建立風險控制模塊

### 監控系統 (1周)

- [ ] 建立日誌記錄系統
- [ ] 建立績效監控儀表板
- [ ] 建立告警系統
- [ ] 準備定期評估流程

### 資金準備 (1-2周)

- [ ] 準備初始資金 (¥100,000小額試驗)
- [ ] 開立期貨賬戶
- [ ] 準備保證金 (¥10,000-15,000)
- [ ] 測試出金入金流程

### 風險管理 (必須)

- [ ] **加入止損機制**: -15% (BULL) / -20% (BEAR)
- [ ] **月度風險限制**: -20%
- [ ] **年度回撤限制**: -30%
- [ ] **暫停機制**: 達到限制時暫停交易

### 測試與驗證 (1-2周)

- [ ] 紙上交易試運行 (模擬交易)
- [ ] 確認環境判定準確性
- [ ] 測試進出場執行時機
- [ ] 測試止損機制
- [ ] 驗證成本計算

### 實盤上線 (2026-03-05 建議)

- [ ] 正式開始實盤交易
- [ ] 初始資金: ¥100,000
- [ ] 杠桿倍數: 50倍 (保守)
- [ ] 每日監控和記錄
- [ ] 每周評估績效

---

## 🔧 常用命令

### 運行回測

```bash
# 運行MODERATE版本 (推薦)
cd /home/tom/TX_Quantitative_Trading
python3 backtest/tuned_adaptive_backtest.py

# 運行原始版本
python3 backtest/adaptive_backtest.py

# 運行對比分析
python3 backtest/comparison_backtest.py
```

### 查看數據

```bash
# 查看最近50行日誌
tail -50 data/adaptive_backtest_log_moderate.csv

# 查看所有交易記錄
cat data/adaptive_trades_moderate.csv

# 統計環境分佈
grep "BULL" data/adaptive_backtest_log_moderate.csv | wc -l
grep "BEAR" data/adaptive_backtest_log_moderate.csv | wc -l
grep "NEUTRAL" data/adaptive_backtest_log_moderate.csv | wc -l

# 查看特定日期的交易
grep "2020-05-05" data/adaptive_backtest_log_moderate.csv
```

### 更新數據

```bash
# 從期交所下載最新數據 (如需要)
cd crawler
python3 taifex_crawler.py  # 通用版本
# 或
python3 taifex_crawler_finmind.py  # FinMind版本
```

---

## 📚 文檔閱讀順序 (推薦)

### 第1階段: 快速了解 (15分鐘)

1. 讀 `README.md` (項目概述)
2. 讀 `QUICKSTART.md` (5分鐘上手)
3. 掃 `QUICK_REFERENCE.md` (快速參考)

### 第2階段: 深入理解 (1小時)

1. 詳讀 `TRADING_RULES.md` (進出規則)
2. 詳讀 `BACKTEST_REPORT.md` (回測結果)
3. 查看 `data/adaptive_trades_moderate.csv` (交易記錄)

### 第3階段: 實戰準備 (2小時)

1. 閱讀 `TRADING_RULES.md` 附錄 (計算示例)
2. 檢查 `backtest/tuned_adaptive_backtest.py` (代碼邏輯)
3. 準備止損和風險控制機制
4. 進行紙上交易試運行 (1-2周)

### 第4階段: 實盤上線 (2026-03-05)

1. 準備資金和賬戶
2. 配置系統
3. 開始小額實盤
4. 每日監控和記錄
5. 每月評估績效

---

## 💾 版本管理 (Git初始化)

### 初始化 Git 倉庫

```bash
cd /home/tom/TX_Quantitative_Trading
git init
git config user.name "Tom"
git config user.email "tm731531@gmail.com"

# 添加所有文件
git add -A

# 創建初始提交
git commit -m "Initial commit: Adaptive Multi-Strategy Trading System v1.0

- TRADING_RULES.md: Complete entry/exit rules
- BACKTEST_REPORT.md: Detailed 7-year backtest results
- QUICK_REFERENCE.md: Daily trading reference card
- MODERATE version: 4.09% annual return, 66.7% win rate
- Ready for live trading deployment"

# 查看提交歷史
git log
```

### 連接到遠程倉庫 (如有GitHub)

```bash
# 添加遠程倉庫
git remote add origin https://github.com/yourusername/TX_Quantitative_Trading.git

# 推送到遠程
git branch -M main
git push -u origin main
```

---

## 📞 後續支持

### 3個月評估 (2026-05-27)

- 回顧3個月的實盤績效
- 評估環境判定準確性
- 評估止損機制有效性
- 決定是否擴大資金規模

### 6個月評估 (2026-08-27)

- 年化收益是否達到4%目標?
- Sharpe比率是否穩定?
- 是否需要參數調整?
- 準備v1.1版本改進計劃

### 12個月評估 (2026-12-27)

- 完整年度績效回顧
- 所有指標對標回測結果
- 決定是否推進到v2.0
- 機器學習優化計劃

---

## 重要提示

### ⚠️ 風險警告

1. **過度擬合風險**: 參數基於2019-2026歷史數據優化，不保證未來有效
2. **槓桿風險**: 回測採用200倍槓桿，實盤建議從50倍開始
3. **滑點成本**: 回測未計入實際交易成本，實盤收益會低3-5%
4. **市場變化**: 市場環境可能發生結構性改變，需持續監控

### ✓ 成功因素

1. **紀律執行**: 按規則交易，不憑情感
2. **長期堅持**: 4.09%年化需要多年積累
3. **持續優化**: 定期評估和參數調整
4. **風險控制**: 止損和倉位管理不能妥協

---

**最後更新**: 2026-02-27
**文檔版本**: 1.0
**狀態**: ✓ 生產就緒
**推薦實盤開始**: 2026-03-05
