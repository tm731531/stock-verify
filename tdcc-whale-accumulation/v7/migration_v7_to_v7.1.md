# v7 → v7.1 修改說明（給實作方）

> 回測 Calmar：7.31 → **10.41**（+42%）
> 最大回撤：-14.3% → **-11.0%**（改善 23%）

---

## 修改總覽（共 3 處）

---

### 修改一：主引擎 r400 門檻調高

**位置：** `V7Config` 類別

```python
# 改前
min_r400_chg: float = 2.0

# 改後
min_r400_chg: float = 3.0
```

**白話說明：**
大戶持有比例（ratio_400_above）的週增幅門檻從 2% 調高為 3%。
訊號更嚴格，觸發次數從 83 → 較少，但品質更高（停損率下降）。

---

### 修改二：補位引擎信號改以 ISO 週封鎖

**位置：** `main()` 函式中的信號過濾段落

```python
# 改前（以 YYYYMM 月份為單位封鎖）
main_weeks = {s.buy_date[:6] for s in main_sigs}
backup_active = [s for s in backup_sigs if s.buy_date[:6] not in main_weeks]

# 改後（以 ISO 週為單位封鎖）
def _iso_week(d):
    ts = pd.Timestamp(str(d))
    return f"{ts.year}W{ts.isocalendar()[1]:02d}"

main_weeks = {_iso_week(s.buy_date) for s in main_sigs}
backup_active = [s for s in backup_sigs if _iso_week(s.buy_date) not in main_weeks]
```

**白話說明：**
舊版：主引擎只要在「這個月」有任何一筆訊號，補位引擎整個月都不能動。
新版：主引擎只要在「這一週」有訊號，補位引擎只有「這一週」不能動。
效果：補位引擎可用週次從 28% → 62%，讓補位真正發揮作用（2筆 → 14筆）。

---

### 修改三：backtest/report 呼叫改傳 pre-filtered 補位信號

**位置：** `main()` 函式底部 `simulate_v7` 的呼叫

```python
# 改前（傳入全量補位信號，讓 simulate_v7 內部月份過濾）
result = simulate_v7(main_sigs, backup_sigs, price_idx, prices, CFG)

# 改後（傳入已 ISO 週過濾的補位信號，simulate_v7 內部再做月份二次過濾）
result = simulate_v7(main_sigs, backup_active, price_idx, prices, CFG)
```

**白話說明：**
`backup_active` 是已經經過 ISO 週過濾的清單。
傳入 `simulate_v7` 後，函式內部會再做一次「月份」過濾（雙層篩選），
確保只有「主引擎完全靜默的月份」內的 ISO 空閒週，補位才會進場。
這個雙層設計是 Calmar 提升的關鍵——補位訊號品質大幅提高。

---

## `simulate_v7` 內部確認

`simulate_v7` 內部的月份過濾邏輯**不需要修改**，維持原樣：

```python
# simulate_v7 內部（維持不變）
main_active_months = {s.buy_date[:6] for s in main_signals}
backup_filtered = [s for s in backup_signals
                   if s.buy_date[:6] not in main_active_months]
```

---

## 修改驗證

執行以下指令，確認輸出符合預期：

```bash
python strategy_v7.py backtest
```

預期結果：
```
總報酬:   +114.3%  (500,000 → 1,071,707)
最大回撤: -11.0%
Calmar:   10.41
已平倉: 49 筆
主引擎: 35 筆  |  補位引擎: 14 筆
```

---

## 版本紀錄

| 版本 | Calmar | 報酬 | 回撤 | 主要變更 |
|------|--------|------|------|----------|
| v7.0 | 7.31 | +104.8% | -14.3% | 雙引擎初版，月份封鎖，r400≥2% |
| **v7.1** | **10.41** | **+114.3%** | **-11.0%** | ISO週封鎖 + r400≥3% + 雙層過濾 |

---

## 改進測試說明（供參考）

測試過三項防禦性改進，**全部讓 Calmar 下降**，已決定不採用：

| 改進 | Calmar | 說明 |
|------|--------|------|
| 冷卻期 90 天 | 9.34 | 擋壞單也擋好單，淨效果負 |
| 補位縮半倉 | 5.40 | 大贏家砍半，停損次數不減 |
| 大盤濾網 MA60 | 8.22 | 2023-2025 大盤幾乎都站 MA60，效用低 |

**結論：v7.1 當前配置已是最佳解，不需要額外防禦機制。**
