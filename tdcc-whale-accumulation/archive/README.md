# Archive 目錄說明

本目錄存放研究、實驗、歷史版本的代碼和文檔，不是生產代碼。

**最後整理**: 2026-03-24

---

## 目錄結構

### 📊 `/backtest/` - 回測腳本集合 (26+ 文件)
歷史上用於驗證不同版本的回測代碼。

| 腳本名稱 | 用途 | 版本 |
|--------|------|------|
| `backtest_6weeks_*.py` | 6週配置回測 | v3-v4 |
| `backtest_90day_*.py` | 90天配置回測 | v3-v4 |
| `backtest_v3_compare.py` | V3 條件對比 | v3 |
| `backtest_v4_continuous_down.py` | V4 持續下降 | v4 |
| `backtest_all_versions.py` | 全版本對比 | 實驗 |
| `realistic_backtest.py` | 真實進場模擬 | 實驗 |

**何時使用**:
- 如果需要重新驗證某個版本的表現
- 對比不同參數組合
- 歷史回顧

### 📈 `/analysis/` - 分析腳本 (12+ 文件)
用於發掘策略模式和參數優化的分析代碼。

| 腳本名稱 | 用途 |
|--------|------|
| `analyze_ratio_400*.py` | 大戶持股比率分析 |
| `analyze_trading_patterns.py` | 交易模式分析 |
| `event_study_latency.py` | 事件延遲分析 |
| `sync_prices.py` | 價格同步處理 |
| `run_full_analysis.py` | 端到端分析流程 |
| `compare_3m.py` | 3個月對比分析 |
| `generate_comparison_charts.py` | 圖表生成 |

**何時使用**:
- 需要深入分析特定因子時
- 開發新特性前的數據探索
- 績效診斷

### 🔬 `/research/` - 實驗版本 (10+ 文件)

#### `v8/` - v8 實驗版本 (已停用)
- `v8/backtest_*.py` - v8 回測代碼
- `v8/strategy_*.py` - v8 策略邏輯

#### 歷史報告
- `2026-03-08-STRICT_COMPLIANCE/` - 3/8 完整性檢查版本
- `2026-03-08-V7.1-ANALYSIS/` - 3/8 V7.1 分析報告
- `回測報告/` - 詳細回測結果檔案

#### 其他實驗
- `STRATEGY_6POSITIONS/` - 6 個持倉實驗

**何時使用**:
- 參考舊版本邏輯
- 歷史問題排查
- 實驗想法原型

### 📚 `/docs/` - 舊文檔 (29 個文件)

#### 版本比較文檔
- `COMPARISON_V3_VS_V4.md` - V3 vs V4 詳細對比
- `COMPREHENSIVE_VERSION_COMPARISON.md` - 全面版本對比
- `V7_VS_6WEEKS_COMPARISON.md` - V7 vs 6週對比

#### 分析報告
- `PATTERN_ANALYSIS_REPORT.md` - 交易模式分析
- `REALISTIC_BACKTEST_SUMMARY.md` - 真實回測總結
- `V7_SPECIAL_EVENT_ANALYSIS.md` - V7 特殊事件分析
- `v7_STRATEGY_ARTICLE.md` - V7 策略文章

#### 技術報告
- `DATA_AUTHENTICITY_REPORT.md` - 數據真實性報告
- `EXPERT_REVIEW_ACTUAL_TRADES.md` - 專家審核
- `CODE_REVIEW_REQUEST.md` - 代碼審查要求
- `DUAL_ENGINE_BACKTEST_REPORT.md` - 雙引擎回測報告

#### 配置與說明
- `PostgreSQL_真實42day_vs_90day_對比.md` - PostgreSQL 對比
- `statistical_summary.md` - 統計摘要
- `STRATEGY_PLAN.md` - 策略計劃
- `WEEKLY_SCANNER_SPEC.md` - 週掃描器規格
- `WEEKLY_SCANNER_ERRATA.md` - 週掃描器勘誤
- `42day_vs_90day_comparison.md` - 42天 vs 90天對比

#### 版本特定文檔
- `v71_42day_backtest_result.md` - v71 42天結果
- `v71_vs_v72_final_comparison.md` - v71 vs v72 對比
- `2026-03-08-COMPLIANCE_FIX.md` - 3/8 合規修復
- `2026-03-08-TRADING_RECORDS.md` - 3/8 交易記錄

**何時使用**:
- 查詢歷史決策背景
- 理解版本演進過程
- 參考舊方案

### 🛠️ `/crawlers/` - 爬蟲重複版本 (5 個文件)
- `crawl_all_prices.py` - 全價格爬蟲
- `crawl_norway_*.py` - 挪威數據爬蟲
- `run_51w_and_backtest.py` - 51週爬取 + 回測

**何時使用**:
- 需要特定資料源爬蟲時參考
- 不推薦在生產環境使用

**生產爬蟲**在 `src/crawler/` 中管理

### 🔄 `/migrations/` - 數據遷移腳本 (4 個文件)
- `migrate_to_pg.py` - 遷移到 PostgreSQL
- `migrate_ohlcv_*.py` - OHLCV 數據遷移
- `upgrade_sqlite_schema.py` - SQLite 升級

**何時使用**:
- 數據庫升級時參考
- 不推薦直接執行，會修改生產數據

**警告**: 應首先備份生產數據庫

---

## 清理策略

### 安全刪除 ✅
可以安全刪除以節省空間:
- 所有 CSV 結果文件（可重新生成）
- 重複的回測腳本（保留一份參考即可）
- 已驗證的實驗代碼

### 保留 ⚠️
應該保留以供參考:
- 主要版本的回測代碼（v3, v4）
- 重要的分析腳本
- 版本比較文檔
- 特殊事件分析

### 遷移到更新系統 🚀
如果有類似功能要進入生產:
1. 複製到 `v7/` 或 `src/` 中
2. 通過測試驗證
3. 更新 CLAUDE.md 和 README.md
4. 在 git 中明確記錄遷移

---

## 查找文件

### 按功能查找
| 需求 | 位置 |
|------|------|
| 回測 V3 表現 | `backtest/backtest_v3_compare.py` |
| 回測 V4 表現 | `backtest/backtest_v4_continuous_down.py` |
| 查詢 V3 vs V4 對比 | `docs/COMPARISON_V3_VS_V4.md` |
| 分析大戶持股比率 | `analysis/analyze_ratio_400*.py` |
| v8 實驗版本 | `research/v8/` |
| 數據庫遷移 | `migrations/` |

### 按日期查找
- **2026-03-08** - `research/2026-03-08-*/` 目錄
- **2026-03-22** - `backtest/backtest_v*_*.py` 最新版

---

## 統計概況

| 類別 | 文件數 | 總大小 | 最後更新 |
|------|--------|--------|----------|
| 回測腳本 | 26 | ~250KB | 2026-03-23 |
| 分析腳本 | 12 | ~180KB | 2026-03-23 |
| 研究版本 | 10+ | ~500KB | 2026-03-08 |
| 舊文檔 | 29 | ~300KB | 2026-03-08 |
| 爬蟲 | 5 | ~100KB | 2026-03-06 |
| 遷移 | 4 | ~80KB | 2026-03-09 |

**總計**: ~1.4MB 歷史檔案

---

## 最佳實踐

### 不要做 ❌
- 直接修改 archive 中的生產代碼並期望它自動在生產環境運行
- 在 archive 中測試新功能（應該在 main 目錄新建）
- 使用 archive 中的爬蟲代碼而不知道有更新版本

### 應該做 ✅
- 查詢歷史決策時參考 archive 中的文檔
- 實驗新想法時在 main 目錄新建臨時腳本
- 如果要用 archive 中的代碼，先複製並驗證
- 定期檢查 archive 是否有需要優化的內容

---

**維護者**: tom
**上次整理**: 2026-03-24
**建議**: 每季度檢查一次 archive，考慮是否有內容可以歸檔或刪除
