# 📑 項目完整索引

快速導航到項目中的各個部分。

## 🎯 從這裡開始

### 新手用戶
1. **5 分鐘快速開始** → 閱讀 [QUICKSTART.md](QUICKSTART.md)
2. **執行回測** → 運行 `python backtest/backtest_fixed.py`
3. **瞭解策略** → 閱讀 [reports/taifex_strategy_report.md](reports/taifex_strategy_report.md)
4. **選擇策略** → 決定使用哪個策略開始

### 進階用戶
1. **瞭解系統架構** → 閱讀 [README.md](README.md)
2. **爬蟲使用** → 查看 [crawler/README_TAIFEX_CRAWLER.md](crawler/README_TAIFEX_CRAWLER.md)
3. **參數優化** → 編輯 [backtest/backtest_fixed.py](backtest/backtest_fixed.py)
4. **自動化交易** → 開發自己的交易機器人

---

## 📂 完整文件清單

### 📄 文檔 (Start Here!)
| 文件 | 說明 | 時間 |
|------|------|------|
| [QUICKSTART.md](QUICKSTART.md) | ⚡ 5 分鐘快速開始 | 5 min |
| [README.md](README.md) | 📖 完整項目說明 | 15 min |
| [INDEX.md](INDEX.md) | 📑 你在這裡 | 3 min |
| [config.yaml](config.yaml) | ⚙️ 項目配置文件 | 5 min |

### 🐍 Python 程式碼

#### backtest/ (回測模組) ⭐
| 文件 | 說明 | 行數 | 用途 |
|------|------|------|------|
| [backtest_fixed.py](backtest/backtest_fixed.py) | ⭐ 推薦使用 | 320 | 執行三策略回測 |
| [quantitative_backtest.py](backtest/quantitative_backtest.py) | 高級模組 | 1300+ | 複雜回測場景 |

**快速運行:**
```bash
cd ~/TX_Quantitative_Trading
python backtest/backtest_fixed.py
```

#### crawler/ (數據爬蟲)
| 文件 | 說明 | 行數 | 用途 |
|------|------|------|------|
| [taifex_crawler.py](crawler/taifex_crawler.py) | 期交所爬蟲 | 1300+ | 爬取官方數據 |
| [taifex_crawler_finmind.py](crawler/taifex_crawler_finmind.py) | FinMind 爬蟲 | 300+ | 爬取 FinMind 數據 |
| [test_taifex_api.py](crawler/test_taifex_api.py) | API 測試 | 150+ | 測試連接 |
| [README_TAIFEX_CRAWLER.md](crawler/README_TAIFEX_CRAWLER.md) | 爬蟲指南 | 300+ | 詳細文檔 |

**快速測試:**
```bash
cd ~/TX_Quantitative_Trading/crawler
python test_taifex_api.py
```

### 📊 數據文件 (data/)

| 文件 | 說明 | 大小 | 記錄數 |
|------|------|------|--------|
| [TX_sample_2024_2026.csv](data/TX_sample_2024_2026.csv) | 歷史行情數據 | 34 KB | 565 |
| [backtest_results.json](data/backtest_results.json) | 回測結果 | 1 KB | 3 策略 |

### 📈 報告文件 (reports/)

| 文件 | 說明 | 行數 | 內容 |
|------|------|------|------|
| [taifex_strategy_report.md](reports/taifex_strategy_report.md) | 完整策略分析 | 420 | 詳細策略指南 + 風險管理 + 實施計畫 |

**內容大綱:**
- 執行摘要
- 三策略詳細分析
- 風險管理框架
- 季節性策略配置
- 成本分析
- 實施 4 週計畫
- 預期收益估算

### ⚙️ 配置文件 (utils/)

| 文件 | 說明 | 用途 |
|------|------|------|
| [requirements_taifex.txt](utils/requirements_taifex.txt) | Python 依賴 | pip install |
| [config.yaml](config.yaml) | 項目配置 | 策略參數設置 |

---

## 🔄 工作流程

### 方案 A: 初級交易者 (風險最低)

```
1. 閱讀文檔 (20 min)
   ├─ QUICKSTART.md
   └─ reports/taifex_strategy_report.md 的策略章節

2. 運行回測 (5 min)
   └─ python backtest/backtest_fixed.py

3. 選擇策略 (10 min)
   └─ 選擇: 均值回歸 (最安全)

4. 開始實行 (4 周)
   ├─ 第 1-2 周: 紙上交易
   └─ 第 3-4 周: 開始實盤
```

### 方案 B: 中級交易者 (效率導向)

```
1. 深入研究 (45 min)
   ├─ README.md (完整系統)
   ├─ reports/taifex_strategy_report.md (深度分析)
   └─ config.yaml (參數理解)

2. 運行回測與優化 (15 min)
   ├─ python backtest/backtest_fixed.py
   └─ 修改參數重新回測

3. 選擇策略 (15 min)
   └─ 選擇: 趨勢跟蹤 (效率最高)

4. 開始實行 (8 周)
   ├─ 第 1-2 周: 紙上交易 + 參數驗證
   ├─ 第 3-4 周: 小額實盤
   ├─ 第 5-8 周: 驗證與擴大
   └─ 第 9+ 周: 優化自動化
```

### 方案 C: 高級交易者 (全自動)

```
1. 系統理解 (60 min)
   ├─ 研究所有代碼
   ├─ 分析回測邏輯
   └─ 理解數據流程

2. 自定義開發 (多天)
   ├─ 新增策略
   ├─ 參數優化
   ├─ 機器學習集成
   └─ 自動化交易機器人

3. 實施部署 (多周)
   ├─ 完整回測
   ├─ 紙上交易驗證
   ├─ 實盤部署
   └─ 持續監控與優化
```

---

## 🎯 快速命令速查

### 基本操作
```bash
# 進入項目目錄
cd ~/TX_Quantitative_Trading

# 安裝依賴
pip install --break-system-packages -q -r utils/requirements_taifex.txt

# 執行回測
python backtest/backtest_fixed.py

# 查看報告
cat reports/taifex_strategy_report.md | less
```

### 數據爬蟲
```bash
# 進入爬蟲目錄
cd crawler

# 測試 API
python test_taifex_api.py

# 爬取期交所數據
python taifex_crawler.py

# 爬取 FinMind 數據
python taifex_crawler_finmind.py
```

### 回測優化
```bash
# 修改初始資金
nano backtest/backtest_fixed.py  # 編輯第 200 行

# 修改策略參數
nano backtest/backtest_fixed.py  # 編輯策略函數

# 查看結果
cat data/backtest_results.json | python -m json.tool
```

---

## 📚 學習順序建議

### 第 1 天 (理論)
- [ ] 閱讀 QUICKSTART.md (5 min)
- [ ] 運行回測看結果 (5 min)
- [ ] 閱讀三策略邏輯 (15 min)
- [ ] 決定選擇哪個策略 (5 min)

### 第 2 天 (實踐)
- [ ] 詳讀選中策略的完整說明 (30 min)
- [ ] 理解風險管理框架 (20 min)
- [ ] 開始紙上交易模擬 (30 min)
- [ ] 記錄進出點位 (10 min)

### 第 3-4 周 (驗證)
- [ ] 持續紙上交易 (每日)
- [ ] 評估滑點影響 (每周)
- [ ] 優化進出規則 (每周)
- [ ] 準備實盤資金 (周末)

### 第 5-8 周 (實盤)
- [ ] 小額實盤交易 (1 口合約)
- [ ] 嚴格記錄日誌 (每日)
- [ ] 評估實際執行難度 (每周)
- [ ] 決定是否擴大倉位 (每周)

---

## 🔗 快速連結

### 官方資源
- [台灣期貨交易所](https://www.taifex.com.tw/)
- [期交所 OpenAPI](https://openapi.taifex.com.tw/)
- [FinMind 數據平台](https://finmind.github.io/)

### 期貨商
- [群益期貨](https://www.quamtrade.com)
- [統一期貨](https://www.unifutures.com.tw)
- [永豐期貨](https://www.yuanta.com.tw)

### 學習資源
- 台指期合約規格
- 期貨風險管理指南
- 量化交易理論

---

## 📞 常見問題快速連結

| 問題 | 答案位置 |
|------|---------|
| 如何開始? | [QUICKSTART.md](QUICKSTART.md) |
| 三策略是什麼? | [reports/taifex_strategy_report.md](reports/taifex_strategy_report.md) |
| 如何爬取數據? | [crawler/README_TAIFEX_CRAWLER.md](crawler/README_TAIFEX_CRAWLER.md) |
| 風險管理怎麼做? | [reports/taifex_strategy_report.md](reports/taifex_strategy_report.md) 的風險管理章節 |
| 如何修改參數? | [README.md](README.md) 的進階功能部分 |
| 預期收益多少? | [reports/taifex_strategy_report.md](reports/taifex_strategy_report.md) 的預期收益部分 |

---

## ✅ 檢查清單

按順序完成以下項目：

- [ ] 閱讀 QUICKSTART.md
- [ ] 安裝 Python 依賴
- [ ] 運行回測程式
- [ ] 查看回測結果
- [ ] 閱讀策略報告
- [ ] 選擇合適的策略
- [ ] 理解風險管理框架
- [ ] 開始紙上交易
- [ ] 完成期貨商開戶
- [ ] 開始實盤交易

---

## 📊 項目統計

```
總文件數:     13 個
代碼行數:     2000+ 行
文檔行數:     1000+ 行
數據記錄:     565 個交易日
策略數:       3 種
回測時間:     2024-01-01 ~ 2026-02-27

項目大小:     184 KB
主要語言:     Python 3
配置文件:     YAML
數據格式:     CSV, JSON
```

---

## 🎓 推薦閱讀順序

1. **必讀** (40 min)
   - [ ] QUICKSTART.md
   - [ ] 回測結果
   - [ ] 三策略概述

2. **重要** (60 min)
   - [ ] 選中策略的完整說明
   - [ ] 風險管理框架
   - [ ] 成本分析

3. **進階** (可選)
   - [ ] 完整 README.md
   - [ ] 爬蟲文檔
   - [ ] 配置文件說明

---

**項目位置:** `/home/tom/TX_Quantitative_Trading`

**立即開始:** `python backtest/backtest_fixed.py` 🚀

祝你交易順利！
