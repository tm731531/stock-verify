# V4 備位引擎 - 實施優化指南

**基於**: PATTERN_ANALYSIS_REPORT.md 的核心發現
**目標**: 將每週 40+ 信號篩選到 2-3 個高品質信號
**實施階段**: Phase 1 (立即) → Phase 2 (2週內) → Phase 3 (1月監控)

---

## Phase 1: 立即實施 - 價格篩選 (效果 +25-30%)

### 修改位置
**檔案**: `v7/scan_notify.py` (line 280-340)

### 修改內容

```python
# 現有代碼 (scan_backup_engine_v4)
def scan_backup_engine_v4(date_range=None):
    signals = []
    # ... 既有邏輯 ...

    if holder_decline_pct <= -5.0:  # 散戶↓≥5%
        if close_price > ma20 and close_price >= 50:
            # ⭐ 新增：價格篩選
            if 200 <= close_price <= 500:  # 🔴 加入這行
                signals.append({
                    'code': stock_code,
                    'engine': 'backup_v4',
                    'signal_date': current_date,
                    'holder_decline': holder_decline_pct,
                    'price': close_price,
                    'ma20': ma20,
                })

    return signals
```

### 預期效果
- 信號量: 2,700 → 800-900 (67% 減少)
- 勝率: 40.2% → 45-48% (篩選後品質提升)
- 每週進場: 40+ → 12-15 個

### 驗證步驟
```bash
# 測試掃描
python3 v7/scan_notify.py --test 20260322

# 檢查輸出訊號是否都在 200-500 元範圍
# 預期輸出: 信號數 12-15 個
```

---

## Phase 2: 進階篩選 - 散戶逃離幅度 (效果 +10-15%)

### 修改位置
**檔案**: `v7/scan_notify.py` (line 300-310)

### 修改內容

```python
# 進一步篩選逃離百分比
def scan_backup_engine_v4_filtered(date_range=None):
    signals = []
    # ... 既有邏輯 ...

    if holder_decline_pct <= -5.0:  # 散戶↓≥5%
        if close_price > ma20 and close_price >= 50:
            if 200 <= close_price <= 500:  # Phase 1
                # ⭐ Phase 2: 散戶逃離幅度篩選
                if -15.0 <= holder_decline_pct < -5.0:  # 適度逃離
                    signals.append({
                        'code': stock_code,
                        'engine': 'backup_v4_filtered',
                        'signal_date': current_date,
                        'holder_decline': holder_decline_pct,  # -15% ~ -5%
                        'price': close_price,
                        'ma20': ma20,
                        'price_ma20_gap': (close_price - ma20) / ma20 * 100,
                    })

    return signals
```

### 閾值說明
- **-5% ~ -10%**: 溫和逃離，確定性高 ✅ 優先
- **-10% ~ -15%**: 中等逃離，兼具確定性和獲利 ✅ 次選
- **< -15%**: 過度逃離，恐慌拋售，風險大 ❌ 排除
- **> -5%**: 基本無逃離，不符合條件 ❌ 排除

### 預期效果
- 信號量: 800-900 → 300-400 (55-60% 減少)
- 勝率: 45-48% → 48-52% (進一步提升)
- 每週進場: 12-15 → 5-8 個

---

## Phase 3: 週期篩選 - 進場時機確認 (效果 +5-10%)

### 修改位置
**檔案**: `v7/scan_notify.py` (line 320-370)

### 修改內容

```python
def run_backtest_v4_optimized(backup_sigs, max_positions=3, max_hold_days=90):
    """執行優化後的回測 - 加入進場時機確認"""

    # ... 既有進場邏輯 ...

    for sig in backup_sigs:
        sig_date = sig['signal_date']
        sig_date_obj = datetime.strptime(sig_date, '%Y%m%d')

        # ⭐ Phase 3: 信號日期 +3~7 天內確認進場
        earliest_entry = sig_date_obj + timedelta(days=3)
        latest_entry = sig_date_obj + timedelta(days=7)

        # 在這個時間窗口內查找價格
        for day_offset in range(3, 8):
            check_date = sig_date_obj + timedelta(days=day_offset)
            check_date_str = check_date.strftime('%Y%m%d')

            cursor.execute("""
                SELECT close_price FROM daily_prices
                WHERE stock_code = %s AND date = %s
            """, (sig['code'], check_date_str))

            price_row = cursor.fetchone()
            if price_row:
                check_price = float(price_row['close_price'])
                limit_price = float(sig['price']) * 1.05  # 信號日股價 × 1.05

                if check_price <= limit_price:
                    # ✅ 進場條件滿足
                    pending_orders[sig['code']] = {
                        'signal_date': sig_date,
                        'entry_date': check_date_str,
                        'entry_price': check_price,
                        'engine': 'backup_v4_filtered'
                    }
                    break  # 找到進場點，跳出
        else:
            # 7天內無進場機會
            pass

    return pending_orders
```

### 進場確認邏輯
1. 訊號日期: T
2. 確認窗口: T+3 ~ T+7 天
3. 條件: 當日收盤 ≤ 訊號日收盤 × 1.05
4. 首次滿足即進場，無需等待全部 7 天

### 預期效果
- 信號量: 300-400 → 最終進場 2-3 個/週 ✅
- 勝率: 48-52% → 50-55% (確認後進場品質最佳)
- 成功率: 提升 10-15%

---

## 完整實施時間表

| 階段 | 時間點 | 修改項目 | 預期訊號量 | 預期勝率 |
|------|--------|---------|-----------|---------|
| Phase 1 | 即日 | 價格篩選 200-500 | 12-15/週 | 45-48% |
| Phase 2 | 1週內 | 散戶逃離 -15~-5% | 5-8/週 | 48-52% |
| Phase 3 | 2週內 | 進場時機 +3~7天 | 2-3/週 | 50-55% |

---

## 測試與監控

### 每週檢查清單

```python
# test_v4_filtering.py
import pandas as pd

def validate_signals(signals, requirements):
    """驗證訊號是否符合篩選條件"""

    passed = 0
    failed = 0

    for sig in signals:
        price = sig['price']
        fled_pct = sig['holder_decline']
        ma20 = sig['ma20']

        # 檢查所有篩選條件
        checks = {
            '價格範圍': 200 <= price <= 500,
            '散戶逃離': -15 <= fled_pct <= -5,
            '站上MA20': price > ma20,
        }

        if all(checks.values()):
            passed += 1
        else:
            failed += 1
            print(f"❌ {sig['code']}: {checks}")

    print(f"✅ 通過: {passed}/{passed+failed} ({passed/(passed+failed)*100:.1f}%)")
    return passed, failed
```

### 監控指標 (每月檢查)

```
每月指標        目標值    預警值    應對
─────────────────────────────────
勝率            >50%     <45%     調整篩選條件
平均獲利/筆     >NT$20K  <NT$10K  檢查進場時機
月利潤          >NT$150K <NT$100K 審視市場狀況
最大回檔        <30%     >40%     考慮降低積極度
```

---

## 代碼修改優先順序

1️⃣ **立即做** (今天)
   - 加入價格篩選 200-500 元
   - 修改 scan_backup_engine_v4 第 330-331 行

2️⃣ **本週做** (2-3天)
   - 加入散戶逃離 -15~-5% 篩選
   - 修改 holder_decline_pct 檢查邏輯
   - 測試並驗證訊號量

3️⃣ **下週做** (5-7天)
   - 加入進場時機確認 (T+3~7天)
   - 修改進場邏輯
   - 全回測驗證新設定

---

## 風險控制

### 黑天鵝事件應對

**場景**: 市場崩跌 >10%
```
應對:
1. 暫停新進場 (保護現有部位)
2. 降低一半的進場頻率
3. 加嚴篩選條件 (例如: -10~-5% 只選 -5%)
4. 增加停損設定 (臨時改為 -15%)
```

**場景**: 單週訊號過多 (>10 個)
```
應對:
1. 優先選擇 「最大跌幅的前 3 個」
2. 避免「重複進場同一產業」
3. 優先進場 「逃離幅度 -10% 以內」(更穩定)
```

---

## 後續優化方向 (Phase 4+)

### 長期改進清單

- [ ] 加入產業分類篩選 (避免單一產業過度集中)
- [ ] 加入成交量確認 (放量下跌 vs 縮量下跌 差異)
- [ ] 動態調整 MA20 周期 (低波動股用 MA50, 高波動股用 MA10)
- [ ] 機構投資者動向追蹤 (三大法人同向即進)
- [ ] 情緒指標整合 (VIX 或恐慌指數)

---

## FAQ

**Q: 為什麼要篩選到 2-3 個信號?**
A: 資金限制。90天+3個配置 × NT$166,667 = NT$500K 本金，無法同時進場 40+ 個。

**Q: 為什麼不改成 200-300 元?**
A: 數據顯示 300-500 元勝率最高 (45.4%)，雖然數量較少，品質更佳。

**Q: 停損不改?**
A: 當前數據顯示停損全虧損，改為「到期出場」。如果後續遇黑天鵝，再臨時加回 -15% 停損。

**Q: 多頭市場是否要改配置?**
A: 建議多頭維持 90天+3個，空頭改為 42天+6個 (根據 2023 年數據)。

---

## 成功標準

實施優化後，預期在 **3 個月內** 達到：

- ✅ 每週精選 2-3 個高品質信號
- ✅ 月勝率 50%+
- ✅ 月獲利 NT$150K+ (NT$500K 本金的 30% 月報酬)
- ✅ 最大回檔 <30%
- ✅ 連續虧損月數 <2 個月

---

**最後更新**: 2026-03-22
**責任人**: tom
**審核狀態**: ✅ 待實施
