# 軌道鞅 大實體K關卡假設驗證 (Step A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用統計檢定證明「日K大實體K的實體邊緣(紅底/黑頂)當支撐壓力,是否顯著贏過隨機價位」——純驗假設,不交易。

**Architecture:** 新目錄 `taiex-orbital-yang/`,Python 套件 `orbital_yang/` 拆四模組(data_loader / body_levels / hypothesis_test / report)+ 一支 `run_step_a.py` 串接掃 (N,k) 參數。核心原則「詭道」:所有計算只用實體 `open→close`,丟掉 `high`/`low`。

**Tech Stack:** Python 3.12, pandas, numpy, yfinance(刷新日線), pytest。

**Spec:** `docs/superpowers/specs/2026-06-15-orbital-yang-body-levels-design.md`

---

## File Structure

| 檔案 | 職責 |
|---|---|
| `taiex-orbital-yang/orbital_yang/__init__.py` | 套件標記 |
| `taiex-orbital-yang/orbital_yang/data_loader.py` | 載入/刷新日線 OHLC |
| `taiex-orbital-yang/orbital_yang/body_levels.py` | body 計算、大實體K 判定、紅底/黑頂關卡 |
| `taiex-orbital-yang/orbital_yang/hypothesis_test.py` | touch/react 統計 + 隨機價位對照 |
| `taiex-orbital-yang/orbital_yang/report.py` | 彙整各 (N,k) 結果輸出 |
| `taiex-orbital-yang/run_step_a.py` | 串接:載資料→掃參數→出報告 |
| `taiex-orbital-yang/pytest.ini` | pytest pythonpath 設定 |
| `taiex-orbital-yang/tests/test_*.py` | 單元測試(含兩個詭道測試) |

導入慣例:`from orbital_yang.body_levels import detect_levels`(套件名用底線,目錄名用連字號,靠 `pytest.ini` 的 `pythonpath = .`)。

---

## Task 0: 專案骨架 + venv + 依賴

**Files:**
- Create: `taiex-orbital-yang/orbital_yang/__init__.py` (空檔)
- Create: `taiex-orbital-yang/tests/__init__.py` (空檔)
- Create: `taiex-orbital-yang/pytest.ini`
- Create: `taiex-orbital-yang/requirements.txt`

- [ ] **Step 1: 建目錄與 venv,裝依賴**

```bash
cd /home/tom/stock-verify/taiex-orbital-yang 2>/dev/null || mkdir -p /home/tom/stock-verify/taiex-orbital-yang
cd /home/tom/stock-verify/taiex-orbital-yang
mkdir -p orbital_yang tests data
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q pandas numpy yfinance pytest
```

- [ ] **Step 2: 建空套件檔與設定檔**

`taiex-orbital-yang/orbital_yang/__init__.py`: 空檔
`taiex-orbital-yang/tests/__init__.py`: 空檔

`taiex-orbital-yang/requirements.txt`:
```
pandas
numpy
yfinance
pytest
```

`taiex-orbital-yang/pytest.ini`:
```ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 3: 冒煙測試 pytest 可跑**

Run: `cd /home/tom/stock-verify/taiex-orbital-yang && ./venv/bin/pytest -q`
Expected: `no tests ran`(exit 5)— 代表 pytest 正常、只是還沒測試。

- [ ] **Step 4: Commit**

```bash
cd /home/tom/stock-verify
printf '%s\n' 'venv/' '__pycache__/' '*.pyc' '.pytest_cache/' > taiex-orbital-yang/.gitignore
git add taiex-orbital-yang/orbital_yang/__init__.py taiex-orbital-yang/tests/__init__.py taiex-orbital-yang/pytest.ini taiex-orbital-yang/requirements.txt taiex-orbital-yang/.gitignore
git commit -m "chore: scaffold taiex-orbital-yang Step A project"
```

---

## Task 1: data_loader — 載入 yfinance 格式日線 OHLC

`TWII_daily.csv` 是 yfinance 匯出格式:第一列欄名 `Price,Close,High,Low,Open,Volume`,第二列是 `Ticker,^TWII,...` 雜訊列,第三列起才是資料(首欄為日期)。

**Files:**
- Create: `taiex-orbital-yang/orbital_yang/data_loader.py`
- Test: `taiex-orbital-yang/tests/test_data_loader.py`

- [ ] **Step 1: 寫失敗測試**

`taiex-orbital-yang/tests/test_data_loader.py`:
```python
import pandas as pd
from orbital_yang.data_loader import load_daily


def _write_yf_csv(path):
    path.write_text(
        "Price,Close,High,Low,Open,Volume\n"
        "Ticker,^TWII,^TWII,^TWII,^TWII,^TWII\n"
        "2026-01-02,100.0,110.0,90.0,95.0,1000\n"
        "2026-01-03,105.0,108.0,101.0,100.0,1200\n"
    )


def test_load_daily_parses_yfinance_format(tmp_path):
    csv = tmp_path / "twii.csv"
    _write_yf_csv(csv)
    df = load_daily(str(csv))

    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    # 'Ticker' 雜訊列必須被丟掉
    assert (df["open"] == 95.0).iloc[0]
    assert df["close"].iloc[1] == 105.0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /home/tom/stock-verify/taiex-orbital-yang && ./venv/bin/pytest tests/test_data_loader.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'orbital_yang.data_loader'`

- [ ] **Step 3: 實作 data_loader**

`taiex-orbital-yang/orbital_yang/data_loader.py`:
```python
"""載入/刷新大盤日線 OHLC (yfinance ^TWII 格式)。"""
import pandas as pd

_COLS = ["open", "high", "low", "close", "volume"]


def load_daily(csv_path: str) -> pd.DataFrame:
    """讀 yfinance 匯出的日線 CSV,回傳乾淨 DataFrame。

    欄位: date, open, high, low, close, volume(date 為 datetime,已依日期排序)。
    """
    raw = pd.read_csv(csv_path)
    first = raw.columns[0]
    # yfinance 匯出第一列資料其實是 'Ticker' 雜訊列,丟掉
    raw = raw[raw[first].astype(str) != "Ticker"].copy()
    raw = raw.rename(columns={first: "date"})
    raw.columns = [str(c).lower() for c in raw.columns]
    raw["date"] = pd.to_datetime(raw["date"])
    for c in _COLS:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    raw = (
        raw.dropna(subset=["open", "close"])
        .sort_values("date")
        .reset_index(drop=True)
    )
    return raw[["date"] + _COLS]


def refresh_daily(csv_path: str, ticker: str = "^TWII", period: str = "5y") -> pd.DataFrame:
    """用 yfinance 抓最新日線寫入 csv_path,並回傳 load_daily 結果。"""
    import yfinance as yf

    df = yf.download(ticker, period=period, auto_adjust=False, progress=False)
    df = df.reset_index()
    df.to_csv(csv_path, index=False)
    return load_daily(csv_path)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd /home/tom/stock-verify/taiex-orbital-yang && ./venv/bin/pytest tests/test_data_loader.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/tom/stock-verify
git add taiex-orbital-yang/orbital_yang/data_loader.py taiex-orbital-yang/tests/test_data_loader.py
git commit -m "feat(orbital-yang): data_loader for yfinance daily OHLC"
```

---

## Task 2: body_levels — body 計算 + 大實體K 判定(含詭道測試)

**Files:**
- Create: `taiex-orbital-yang/orbital_yang/body_levels.py`
- Test: `taiex-orbital-yang/tests/test_body_levels.py`

- [ ] **Step 1: 寫失敗測試(含兩個詭道測試)**

`taiex-orbital-yang/tests/test_body_levels.py`:
```python
import pandas as pd
from orbital_yang.body_levels import body, detect_big_bodies, detect_levels


def _df(rows):
    """rows: list of (open, high, low, close)。日期自動產生,volume 固定。"""
    dates = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [1000] * len(rows),
        }
    )


def test_body_ignores_wicks():
    df = _df([(100, 999, 1, 110)])  # 巨大上下影線, 實體=10
    assert body(df).iloc[0] == 10


def test_kuidao_open_low_close_flat_counts_as_big_red():
    """詭道測試1: 開低收平盤 = 大實體紅K, 必須被判為大紅K -> support。"""
    rows = [(100, 101, 99, 100.5)] * 20          # 20 根小實體 (body=0.5)
    rows.append((90, 100.2, 89, 100))            # 開低(90)收平盤(100), 大實體紅K body=10
    df = _df(rows)
    levels = detect_levels(df, n=20, k=2.0)
    assert len(levels) == 1
    assert levels[0].kind == "support"
    assert levels[0].price == 90      # 紅底 = 大紅K開盤價


def test_kuidao_long_doji_wick_not_big():
    """詭道測試2: 長十字影線(實體極小)不可被判為大K。"""
    rows = [(100, 101, 99, 100.5)] * 20          # body=0.5
    rows.append((100, 200, 10, 100.3))           # 影線巨大但實體=0.3
    df = _df(rows)
    levels = detect_levels(df, n=20, k=2.0)
    assert len(levels) == 0


def test_big_black_makes_resistance():
    rows = [(100, 101, 99, 100.5)] * 20
    rows.append((110, 111, 99, 100))             # 大黑K body=10, 開盤110
    df = _df(rows)
    levels = detect_levels(df, n=20, k=2.0)
    assert len(levels) == 1
    assert levels[0].kind == "resistance"
    assert levels[0].price == 110     # 黑頂 = 大黑K開盤價
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /home/tom/stock-verify/taiex-orbital-yang && ./venv/bin/pytest tests/test_body_levels.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'orbital_yang.body_levels'`

- [ ] **Step 3: 實作 body_levels**

`taiex-orbital-yang/orbital_yang/body_levels.py`:
```python
"""詭道原則: 只算實體 open->close, 丟棄 high/low。

大實體K -> 實體邊緣作為支撐/壓力關卡:
  大紅K(收>開) -> 紅底 = 開盤價 (support)
  大黑K(收<開) -> 黑頂 = 開盤價 (resistance)
"""
from dataclasses import dataclass
import pandas as pd


@dataclass
class Level:
    idx: int        # 形成關卡的 K 棒索引
    date: object    # 該 K 棒日期
    price: float    # 關卡價(大實體K 的開盤價)
    kind: str       # 'support' (紅底) 或 'resistance' (黑頂)


def body(df: pd.DataFrame) -> pd.Series:
    """實體大小 = |close - open|(不含影線)。"""
    return (df["close"] - df["open"]).abs()


def detect_big_bodies(df: pd.DataFrame, n: int, k: float) -> pd.Series:
    """布林 Series: body[i] > 前 n 根 body 的中位數 × k。

    前 n 根不足者為 False(rolling 產生 NaN, 比較後為 False)。
    """
    b = body(df)
    med = b.shift(1).rolling(n).median()
    return (b > med * k).fillna(False)


def detect_levels(df: pd.DataFrame, n: int, k: float) -> list:
    """回傳所有大實體K 形成的紅底/黑頂關卡。"""
    big = detect_big_bodies(df, n, k)
    levels = []
    for i in range(len(df)):
        if not bool(big.iloc[i]):
            continue
        o = float(df["open"].iloc[i])
        c = float(df["close"].iloc[i])
        if c > o:
            levels.append(Level(i, df["date"].iloc[i], o, "support"))
        elif c < o:
            levels.append(Level(i, df["date"].iloc[i], o, "resistance"))
    return levels
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd /home/tom/stock-verify/taiex-orbital-yang && ./venv/bin/pytest tests/test_body_levels.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/tom/stock-verify
git add taiex-orbital-yang/orbital_yang/body_levels.py taiex-orbital-yang/tests/test_body_levels.py
git commit -m "feat(orbital-yang): body-only big-candle level detection (詭道)"
```

---

## Task 3: hypothesis_test — touch/react 統計 + 隨機價位對照

**Files:**
- Create: `taiex-orbital-yang/orbital_yang/hypothesis_test.py`
- Test: `taiex-orbital-yang/tests/test_hypothesis_test.py`

判定規則(只看實體):
- **touch**: 關卡形成後某根 `j`,其實體區間 `[min(o,c), max(o,c)]` 與 `[L-ε, L+ε]` 相交。
- **support react**: touch 後 `W` 根內,某根 `close - L ≥ R`(反彈成功);若期間先出現 `close ≤ L-ε` 則失敗(跌破)。
- **resistance react**: 對稱(`L - close ≥ R` 成功;先 `close ≥ L+ε` 則失敗)。

- [ ] **Step 1: 寫失敗測試**

`taiex-orbital-yang/tests/test_hypothesis_test.py`:
```python
import pandas as pd
from orbital_yang.body_levels import Level
from orbital_yang.hypothesis_test import TestParams, evaluate_levels, random_control


def _df(closes, opens=None):
    n = len(closes)
    opens = opens or closes
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": [max(o, c) for o, c in zip(opens, closes)],
            "low": [min(o, c) for o, c in zip(opens, closes)],
            "close": closes,
            "volume": [1000] * n,
        }
    )


def test_support_bounce_is_react_success():
    # 關卡 L=100 形成於 idx0; 之後跌到觸碰 100 再彈到 >=105
    df = _df([100, 103, 100, 102, 106, 108])
    level = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="support")
    params = TestParams(epsilon=0.5, window=4, reaction=5.0)
    stats = evaluate_levels(df, [level], params)
    assert stats.n_touch == 1
    assert stats.n_react == 1
    assert stats.react_rate == 1.0


def test_support_breakdown_is_not_react():
    # 觸碰 100 後直接跌破到 94(< L-eps), 不算反彈成功
    df = _df([100, 101, 100, 96, 94, 93])
    level = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="support")
    params = TestParams(epsilon=0.5, window=4, reaction=5.0)
    stats = evaluate_levels(df, [level], params)
    assert stats.n_touch == 1
    assert stats.n_react == 0
    assert stats.react_rate == 0.0


def test_random_control_is_reproducible():
    df = _df([100, 102, 101, 103, 99, 104, 100, 105])
    level = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="support")
    params = TestParams(epsilon=0.5, window=4, reaction=5.0)
    a = random_control(df, [level], params, n_sets=10, seed=42)
    b = random_control(df, [level], params, n_sets=10, seed=42)
    assert a.react_rate == b.react_rate     # 固定種子可重現
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /home/tom/stock-verify/taiex-orbital-yang && ./venv/bin/pytest tests/test_hypothesis_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'orbital_yang.hypothesis_test'`

- [ ] **Step 3: 實作 hypothesis_test**

`taiex-orbital-yang/orbital_yang/hypothesis_test.py`:
```python
"""假設檢定: 大實體K關卡的支撐/壓力反應率, 對照隨機價位。"""
from dataclasses import dataclass
import numpy as np

from .body_levels import Level


@dataclass
class TestParams:
    epsilon: float    # 碰觸容忍(點)
    window: int       # 反應觀察窗(根)
    reaction: float   # 視為反彈/受阻所需幅度(點)


@dataclass
class Stats:
    n_levels: int
    n_touch: int
    n_react: int
    react_rate: float       # n_react / n_touch (touch=0 時為 0.0)
    avg_reaction: float     # 反彈成功者平均幅度


def _react_one(o, c, lo_body, hi_body, level: Level, params: TestParams):
    """回傳 (touched: bool, reacted: bool, magnitude: float)。"""
    L = level.price
    n = len(c)
    for j in range(level.idx + 1, n):
        if lo_body[j] <= L + params.epsilon and hi_body[j] >= L - params.epsilon:
            end = min(n, j + 1 + params.window)
            if level.kind == "support":
                for t in range(j + 1, end):
                    if c[t] <= L - params.epsilon:
                        return (True, False, 0.0)
                    if c[t] - L >= params.reaction:
                        return (True, True, c[t] - L)
            else:  # resistance
                for t in range(j + 1, end):
                    if c[t] >= L + params.epsilon:
                        return (True, False, 0.0)
                    if L - c[t] >= params.reaction:
                        return (True, True, L - c[t])
            return (True, False, 0.0)
    return (False, False, 0.0)


def evaluate_levels(df, levels, params: TestParams) -> Stats:
    o = df["open"].to_numpy(float)
    c = df["close"].to_numpy(float)
    lo_body = np.minimum(o, c)
    hi_body = np.maximum(o, c)

    n_touch = n_react = 0
    mags = []
    for lv in levels:
        touched, reacted, mag = _react_one(o, c, lo_body, hi_body, lv, params)
        if touched:
            n_touch += 1
        if reacted:
            n_react += 1
            mags.append(mag)
    rate = (n_react / n_touch) if n_touch else 0.0
    avg = float(np.mean(mags)) if mags else 0.0
    return Stats(len(levels), n_touch, n_react, rate, avg)


def random_control(df, levels, params: TestParams, n_sets: int, seed: int) -> Stats:
    """生成與真關卡同數量/同 kind 分佈、但價位隨機的假關卡, 聚合 n_sets 次結果。

    隨機價位於 [收盤最小, 收盤最大] 均勻抽樣; 形成索引取真關卡的索引(對齊)。
    """
    rng = np.random.default_rng(seed)
    c = df["close"].to_numpy(float)
    lo, hi = float(c.min()), float(c.max())

    tot_touch = tot_react = 0
    mags = []
    for _ in range(n_sets):
        fake = []
        for lv in levels:
            price = float(rng.uniform(lo, hi))
            fake.append(Level(lv.idx, lv.date, price, lv.kind))
        s = evaluate_levels(df, fake, params)
        tot_touch += s.n_touch
        tot_react += s.n_react
        if s.avg_reaction:
            mags.append(s.avg_reaction)
    rate = (tot_react / tot_touch) if tot_touch else 0.0
    avg = float(np.mean(mags)) if mags else 0.0
    return Stats(len(levels) * n_sets, tot_touch, tot_react, rate, avg)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd /home/tom/stock-verify/taiex-orbital-yang && ./venv/bin/pytest tests/test_hypothesis_test.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/tom/stock-verify
git add taiex-orbital-yang/orbital_yang/hypothesis_test.py taiex-orbital-yang/tests/test_hypothesis_test.py
git commit -m "feat(orbital-yang): touch/react hypothesis test + random-price control"
```

---

## Task 4: report — 彙整 (N,k) 網格結果

**Files:**
- Create: `taiex-orbital-yang/orbital_yang/report.py`
- Test: `taiex-orbital-yang/tests/test_report.py`

- [ ] **Step 1: 寫失敗測試**

`taiex-orbital-yang/tests/test_report.py`:
```python
from orbital_yang.hypothesis_test import Stats
from orbital_yang.report import render_markdown


def test_render_markdown_contains_grid_and_edge():
    rows = [
        {"n": 20, "k": 2.0, "real": Stats(5, 4, 3, 0.75, 8.0),
         "control": Stats(50, 40, 12, 0.30, 6.0)},
    ]
    md = render_markdown(rows)
    assert "| N | k |" in md
    assert "20" in md and "2.0" in md
    assert "0.75" in md and "0.30" in md
    # edge = 真實 react 率 - 對照 react 率
    assert "0.45" in md
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /home/tom/stock-verify/taiex-orbital-yang && ./venv/bin/pytest tests/test_report.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'orbital_yang.report'`

- [ ] **Step 3: 實作 report**

`taiex-orbital-yang/orbital_yang/report.py`:
```python
"""把各 (N,k) 的真實 vs 隨機對照結果彙整成 Markdown 報告。"""


def render_markdown(rows: list) -> str:
    """rows: list of dict, 每個含 n, k, real(Stats), control(Stats)。"""
    lines = [
        "# 軌道鞅大實體K關卡 — 假設檢定結果 (Step A)",
        "",
        "| N | k | 關卡數 | 碰觸 | 真實反應率 | 隨機反應率 | edge(真-隨) | 真實平均幅度 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        real = r["real"]
        ctrl = r["control"]
        edge = real.react_rate - ctrl.react_rate
        lines.append(
            f"| {r['n']} | {r['k']:.1f} | {real.n_levels} | {real.n_touch} "
            f"| {real.react_rate:.2f} | {ctrl.react_rate:.2f} | {edge:.2f} "
            f"| {real.avg_reaction:.1f} |"
        )
    lines += [
        "",
        "> edge > 0 且穩定 → 地基成立(大實體K邊緣確實優於隨機價位)。",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd /home/tom/stock-verify/taiex-orbital-yang && ./venv/bin/pytest tests/test_report.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/tom/stock-verify
git add taiex-orbital-yang/orbital_yang/report.py taiex-orbital-yang/tests/test_report.py
git commit -m "feat(orbital-yang): markdown report for (N,k) grid"
```

---

## Task 5: run_step_a.py — 串接 + 跑真實資料

**Files:**
- Create: `taiex-orbital-yang/run_step_a.py`
- Data: 複製/刷新 `taiex-orbital-yang/data/TWII_daily.csv`

- [ ] **Step 1: 準備資料(複製現成,失敗才刷新)**

```bash
cd /home/tom/stock-verify/taiex-orbital-yang
cp /home/tom/shioaji-trading/data/TWII_daily.csv data/TWII_daily.csv
./venv/bin/python -c "from orbital_yang.data_loader import load_daily; d=load_daily('data/TWII_daily.csv'); print(len(d), d['date'].min(), d['date'].max())"
```
Expected: 印出根數與日期區間(現成檔到 2026-01-30)。
> 註: 資料只到 2026-01,要刷新到當日可改跑
> `./venv/bin/python -c "from orbital_yang.data_loader import refresh_daily; refresh_daily('data/TWII_daily.csv')"`
> (需連外抓 yfinance;先用現成檔讓流程跑通,刷新失敗不阻塞。)

- [ ] **Step 2: 寫 run_step_a.py**

`taiex-orbital-yang/run_step_a.py`:
```python
"""Step A 主流程: 載日線 -> 掃 (N,k) -> 真實 vs 隨機對照 -> 出報告。"""
from pathlib import Path

from orbital_yang.data_loader import load_daily
from orbital_yang.body_levels import detect_levels
from orbital_yang.hypothesis_test import TestParams, evaluate_levels, random_control
from orbital_yang.report import render_markdown

DATA = Path(__file__).parent / "data" / "TWII_daily.csv"
OUT = Path(__file__).parent / "reports" / "step_a_result.md"

N_GRID = [10, 20, 40]
K_GRID = [1.5, 2.0, 2.5, 3.0]
PARAMS = TestParams(epsilon=30.0, window=10, reaction=100.0)  # 點數;指數級距
CONTROL_SETS = 50
SEED = 42


def main():
    df = load_daily(str(DATA))
    print(f"資料: {len(df)} 根, {df['date'].min().date()} ~ {df['date'].max().date()}")

    rows = []
    for n in N_GRID:
        for k in K_GRID:
            levels = detect_levels(df, n=n, k=k)
            real = evaluate_levels(df, levels, PARAMS)
            ctrl = random_control(df, levels, PARAMS, n_sets=CONTROL_SETS, seed=SEED)
            rows.append({"n": n, "k": k, "real": real, "control": ctrl})
            print(f"N={n} k={k}: 關卡{real.n_levels} 碰{real.n_touch} "
                  f"真{real.react_rate:.2f} 隨{ctrl.react_rate:.2f}")

    md = render_markdown(rows)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print(f"\n報告寫入 {OUT}")
    print(md)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 跑真實資料**

Run: `cd /home/tom/stock-verify/taiex-orbital-yang && ./venv/bin/python run_step_a.py`
Expected: 印出每組 (N,k) 的真實/隨機反應率,並寫出 `reports/step_a_result.md`。**先確認流程跑完不報錯**;數字解讀留給人看(edge 是否穩定 > 0)。

- [ ] **Step 4: 全測試綠燈**

Run: `cd /home/tom/stock-verify/taiex-orbital-yang && ./venv/bin/pytest -q`
Expected: PASS (全部, 約 10 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/tom/stock-verify
git add taiex-orbital-yang/run_step_a.py taiex-orbital-yang/data/TWII_daily.csv taiex-orbital-yang/reports/step_a_result.md
git commit -m "feat(orbital-yang): Step A runner over (N,k) grid + first result"
```

---

## Task 6: 結果判讀與下一步(人工檢查點)

- [ ] **Step 1: 看 `reports/step_a_result.md`**,判斷:
  - 真實反應率是否**穩定**高於隨機反應率(edge > 0,且非單一 (N,k) 僥倖)?
  - 碰觸樣本數是否足夠(太少則結論不可靠)?
- [ ] **Step 2: 回報 Tom 做決策**(此處可能觸發 decision-server):
  - **地基成立** → 進 Step 2(疊進出場規則 / 期貨日K 忠實版 A')。
  - **地基不成立** → 檢討定義(ε/W/R、紅底黑頂取邊緣方式)或直接止損此假設。

---

## Self-Review

- **Spec coverage**: §1 目標→Task6 判讀;§2 詭道→Task2 只用 open/close + 兩個詭道測試;§3 資料→Task1/Task5;§4 量化定義→Task2;§5 假設檢定(對照A)→Task3;§6 模組結構→Task1-4 對齊;§7 單元測試→各 Task 的 test;§8 路線圖→Task6 出口。涵蓋完整。
- **Placeholder scan**: 無 TBD/TODO;每個 code step 有完整程式碼。`refresh_daily` 為實際實作非佔位。
- **Type consistency**: `Level(idx,date,price,kind)`、`TestParams(epsilon,window,reaction)`、`Stats(n_levels,n_touch,n_react,react_rate,avg_reaction)` 跨 Task 一致;`detect_levels(df,n,k)`、`evaluate_levels(df,levels,params)`、`random_control(df,levels,params,n_sets,seed)`、`render_markdown(rows)` 簽名前後一致。
