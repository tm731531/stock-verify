# scan_notify.py 修改建議

## 背景

strategy_v7.py 已確認雙引擎邏輯，scan_notify.py 需補上**補位引擎掃描**並更新 LINE 通知格式。

---

## 一、新增常數（檔案頂部常數區）

在現有常數之後加入：

```python
# ── 補位引擎參數 ──
FLEE_LOOKBACK_WEEKS = 4      # 回望幾週
FLEE_MIN_PCT        = -5.0   # 持有人至少跌幾%
MIN_PRICE_BACKUP    = 50.0   # 補位引擎最低股價
BACKUP_MA_PERIOD    = 20     # 需站上幾日均線
BACKUP_ENTRY_DAYS   = 5      # TDCC 公布後第幾個交易日買入
BACKUP_TOP_N        = 5      # LINE 通知最多顯示幾個補位訊號
```

---

## 二、新增函式：`scan_backup_signals`

在 `scan_signals()` 函式之後新增：

```python
def scan_backup_signals(conn, tdcc_date: str) -> list[dict]:
    """
    補位引擎：散戶出逃 + 站上 MA20
    條件：4週持有人↓≥5% + 股價站上MA20 + 股價≥50
    進場：TDCC日後第5個交易日收盤價
    只掃最新 TDCC 週的訊號
    """
    import numpy as np

    # 載入持倉資料
    rows = conn.execute(
        'SELECT stock_code, date, total_holders '
        'FROM holdings ORDER BY stock_code, date'
    ).fetchall()
    stock_data = defaultdict(list)
    for r in rows:
        stock_data[r[0]].append(r)

    # 載入每日收盤價
    price_rows = conn.execute(
        'SELECT stock_code, date, close_price FROM daily_prices ORDER BY stock_code, date'
    ).fetchall()
    price_data = defaultdict(list)
    for r in price_rows:
        price_data[r[0]].append((r[1], float(r[2])))

    tdcc_week = iso_week_key(tdcc_date)
    signals = []

    for code, grp in stock_data.items():
        if code.startswith('00'):
            continue
        # 去重（同週保留最後一筆）
        grp = dedupe_by_week(grp)
        if len(grp) < FLEE_LOOKBACK_WEEKS + 1:
            continue
        # 最後一筆必須是最新 TDCC 週
        if iso_week_key(grp[-1][1]) != tdcc_week:
            continue

        holders = [x[2] for x in grp]
        i = len(grp) - 1
        h_now, h_bef = holders[i], holders[i - FLEE_LOOKBACK_WEEKS]
        if h_bef <= 0:
            continue
        flee = (h_now - h_bef) / h_bef * 100
        if flee > FLEE_MIN_PCT:
            continue

        # 找 TDCC 日的每日收盤
        pdates = price_data.get(code, [])
        if not pdates:
            continue
        date_list = [p[0] for p in pdates]
        close_list = [p[1] for p in pdates]

        # 找 TDCC 日 index
        tdcc_day = grp[-1][1]
        try:
            pi = next(k for k, d in enumerate(date_list) if d >= tdcc_day)
        except StopIteration:
            continue
        if pi >= len(date_list):
            continue
        cp = close_list[pi]
        if cp < MIN_PRICE_BACKUP:
            continue

        # 站上 MA20
        if pi >= BACKUP_MA_PERIOD:
            ma20 = sum(close_list[pi - BACKUP_MA_PERIOD:pi]) / BACKUP_MA_PERIOD
            if cp < ma20:
                continue
        else:
            continue  # 資料不夠算 MA20

        # 買入：第5個交易日收盤
        if pi + BACKUP_ENTRY_DAYS >= len(date_list):
            continue
        buy_date  = date_list[pi + BACKUP_ENTRY_DAYS]
        buy_price = close_list[pi + BACKUP_ENTRY_DAYS]
        if buy_price <= 0:
            continue

        signals.append({
            'signal_date': tdcc_date,
            'code':        code,
            'flee_pct':    round(flee, 1),
            'holders_now': h_now,
            'tdcc_close':  round(cp, 1),
            'buy_date':    buy_date,
            'buy_price':   round(buy_price, 1),
        })

    # 散戶跑幅最大的優先（負值愈小愈跑）
    return sorted(signals, key=lambda x: x['flee_pct'])
```

---

## 三、修改 `build_message`

將現有函式替換為：

```python
def build_message(main_signals: list[dict], backup_signals: list[dict],
                  db_date: str, signal_date: str) -> str:
    today  = date.today().strftime('%m/%d')
    db_str = f"{db_date[:4]}/{db_date[4:6]}/{db_date[6:]}"
    lines  = [f'\n🐋 TDCC 鯨魚掃描｜{today}', f'最新資料：{db_str}']

    sd = f"{signal_date[:4]}/{signal_date[4:6]}/{signal_date[6:]}"

    # ── 主引擎 ──
    if main_signals:
        lines += ['', f'🎯 主引擎 {len(main_signals)} 個（TDCC {sd}）',
                  '訊號日後跳過2天，第3天起觀察收盤≤限價，隔天掛單（最多等5天）', '']
        for s in main_signals:
            lines += [
                f"【{s['code']}】連升{s['streak']}週｜大戶+{s['r400_chg']}%｜同步{s['sync']}%",
                f"  收盤 {s['price']:.0f} → 限價 ≤ {s['limit_price']:.1f} → 停損 ≤ {s['stop_loss']:.1f}",
                f"  大戶比例 {s['r400_now']}%｜散戶{s['holder_chg']:+.1f}%",
                '',
            ]
    else:
        lines += ['', '🎯 主引擎：本週無訊號', '']

    # ── 補位引擎 ──
    if backup_signals:
        top = backup_signals[:BACKUP_TOP_N]
        lines += [f'📌 補位引擎 前{len(top)}（散戶出逃最多，共{len(backup_signals)}個）',
                  f'TDCC日後第5個交易日收盤買入', '']
        for s in top:
            lines += [
                f"【{s['code']}】散戶跑{s['flee_pct']:+.1f}%｜持有人{s['holders_now']:,}",
                f"  參考買入 {s['buy_price']:.1f}（{s['buy_date']}收盤）",
                '',
            ]
    else:
        lines += ['📌 補位引擎：本週無訊號', '']

    lines.append('🛑 停損＝限價×0.93｜停利：+15%啟動，回落10%出場｜最長90天')
    return '\n'.join(lines)
```

---

## 四、修改 `main()` 中的掃描與通知呼叫

找到這段（步驟3和步驟4）：

```python
    # ── 3. 掃描訊號 ─────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    signals, signal_date = scan_signals(conn)
    conn.close()
    print(f'[scan] 訊號日: {signal_date}｜訊號數: {len(signals)}')

    # ── 4. 發 LINE ──────────────────────────────────────
    msg  = build_message(signals, db_date, signal_date)
```

替換為：

```python
    # ── 3. 掃描訊號 ─────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    main_signals, signal_date = scan_signals(conn)
    backup_signals = scan_backup_signals(conn, signal_date) if signal_date else []
    conn.close()
    print(f'[scan] 訊號日: {signal_date}｜主引擎: {len(main_signals)}｜補位: {len(backup_signals)}')

    # ── 4. 發 LINE ──────────────────────────────────────
    msg  = build_message(main_signals, backup_signals, db_date, signal_date)
```

---

## 五、修改已通知判斷（步驟1）

找到：

```python
        _, current_signal_date = scan_signals(conn)
```

替換為（同時把變數名對齊）：

```python
        _, current_signal_date = scan_signals(conn)
        # 補位引擎不影響通知去重邏輯，只看主引擎 signal_date
```

不需要其他修改，邏輯不變。

---

## 修改摘要

| 項目 | 動作 |
|------|------|
| 新增常數 6 個 | `FLEE_*`, `BACKUP_*` |
| 新增函式 | `scan_backup_signals()` |
| 修改函式 | `build_message()` 接收兩個訊號列表 |
| 修改 `main()` | 步驟3掃兩個引擎，步驟4傳兩個列表 |
| 通知去重 | 不變，仍以主引擎 signal_date 為準 |
