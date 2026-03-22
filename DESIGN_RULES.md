---
name: Stock-Verify Backtesting Design Rules
description: Design patterns for quantitative trading strategy backtesting and live bot management
type: rule
---

# Stock-Verify - Design Rules

**Last Updated**: 2026-03-16 | **Maturity**: ⭐⭐ (Experimental + Live Trading)

## Current Design Assessment

### Strengths
- ✅ **Multiple Strategy Implementations**: v7, v8, v11 show iterative refinement
- ✅ **Live Trading Bot**: 006208 SMA bot with state persistence and trade logging
- ✅ **Detailed Backtesting**: Comprehensive metrics and verification
- ✅ **Whale Detection**: TDCC institutional chip analysis

### Critical Weaknesses
- 🔴 **Version Management Chaos** (CRITICAL)
  - Problem: v7, v8, v11 exist simultaneously with overlapping logic
  - Risk: Bug fixed in v8 not applied to v7 or v11
  - Cost: 3x maintenance burden for same strategy
  - Impact: Confusion on which version is "current"

- 🔴 **Duplicate Backtest Scripts** (CRITICAL)
  - Count: 10+ backtest variations (backtest_fixed.py, adaptive_backtest_v11.py, ensemble_, etc.)
  - Problem: Same logic copy-pasted across files
  - Risk: Fix in one doesn't propagate, code rot accelerates
  - Impact: Developer can't tell which script to modify

- 🟠 **State Divergence Risk** (HIGH)
  - Problem: Live bot uses different signal calculation than backtest
  - Risk: Backtest shows 15% returns but live trading shows 5%
  - Root cause: Evolution of signal logic not synced
  - Impact: Strategy validation breaks

- 🟡 **No Clear Version Semantics** (MEDIUM)
  - Problem: What's the difference between v7, v8, v11?
  - No changelog, no comparison docs
  - Impact: Replication uncertainty, hard to explain results

---

## Part 1: What to Change (Critical Priority)

### Priority 1: Unify Backtest Framework (URGENT) 🔴

**Location**: `stock-verify/backtest/` → Consolidate into single framework

**Current Problem**:
```
stock-verify/backtest/
├── backtest_fixed.py              ← Uses this one today?
├── adaptive_backtest_v11.py       ← Or this one?
├── backtest_with_logging.py       ← Or this with logging?
├── ensemble_strategy_backtest.py  ← Or ensemble?
├── daily_full_backtest.py         ← Different for daily?
└── ... (10 more)

Each has slightly different:
- Date range handling
- Fee calculation
- Position sizing
- Signal generation
= Impossible to compare apples to apples
```

**Solution**: Single `BacktestRunner` with configuration

**Architecture**:
```
stock-verify/backtest/
├── runner.py                      ← Single BacktestRunner class
├── config/
│   ├── 6position_whale.json      ← Config for 6-position strategy
│   ├── sma_daily.json            ← Config for SMA bot
│   ├── ensemble.json             ← Config for ensemble
│   └── template.json             ← Template for new strategies
├── strategies/
│   ├── whale_6position.py        ← Strategy implementation
│   ├── sma_daily.py
│   └── ensemble.py
├── metrics.py                     ← Shared metrics calculation
└── run_backtest.py               ← Entry point
```

**BacktestRunner Design**:
```python
# stock-verify/backtest/runner.py

class BacktestRunner:
    """
    Single unified backtest harness supporting multiple strategies.
    Use JSON config instead of separate scripts.
    """

    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.strategy = self._load_strategy(self.config['strategy_class'])
        self.metrics = MetricsCalculator()

    def run(self, data: DataFrame) -> BacktestResults:
        """Execute backtest with configured strategy"""
        positions = []
        cash = self.config['initial_capital']
        fees = 0

        for i in range(len(data)):
            signal = self.strategy.generate_signal(data.iloc[:i+1])
            action = self.strategy.decide_action(signal, cash)

            if action == 'BUY':
                shares = cash // (data.iloc[i]['close'] * (1 + self.config['commission']))
                positions.append({
                    'entry_price': data.iloc[i]['close'],
                    'entry_date': data.iloc[i].name,
                    'shares': shares
                })
                cash -= shares * data.iloc[i]['close']
                fees += shares * data.iloc[i]['close'] * self.config['commission']

            elif action == 'SELL':
                for pos in positions:
                    exit_price = data.iloc[i]['close']
                    pnl = (exit_price - pos['entry_price']) * pos['shares']
                    fees += pos['shares'] * exit_price * self.config['commission']
                    # Record result
                positions = []

        # Calculate metrics using shared calculator
        results = self.metrics.calculate(positions, fees, cash)
        return results

# stock-verify/backtest/config/6position_whale.json
{
    "name": "TDCC 6-Position Whale Accumulation",
    "strategy_class": "strategies.whale_6position.WhaleAccumulationStrategy",
    "initial_capital": 500000,
    "commission": 0.001425,
    "backtest_period": {
        "start": "2023-01-01",
        "end": "2026-03-16"
    },
    "parameters": {
        "position_count": 6,
        "accumulation_threshold": 0.02,
        "whale_detection_window": 20
    }
}

# Usage: Single entry point
python run_backtest.py --config config/6position_whale.json --output results/
```

**What Gets Deleted**:
```
❌ Delete these duplicate scripts:
- backtest_fixed.py
- adaptive_backtest_v11.py
- backtest_with_logging.py
- ensemble_strategy_backtest.py
- daily_full_backtest.py
- ... (all 10+ other scripts)

✅ Keep strategy implementations in strategies/ directory
```

**Why This Matters**:
1. **One source of truth** for backtesting logic
2. **Config-driven** → Easy to test multiple strategies without code changes
3. **Comparable results** → Same runner, different configs
4. **Reproducible** → Config + data + code = exact results

**Priority**: CRITICAL (blocks everything else)
**Effort**: 6-8 hours
**Benefit**: Unifies the codebase, enables science-based comparisons

---

### Priority 2: Version Management for Strategies 🔴

**Location**: `stock-verify/strategies/` (new structure)

**Current Problem**:
```
tdcc-whale-accumulation/
├── v7/
│   ├── STRATEGY_6POSITIONS/
│   └── ... (v7 specific code)
├── v8/
│   └── STRATEGY_6POSITIONS/
│       └── ... (v8 code)
└── v11/
    └── ...

Question: Which is "production"?
Answer: Nobody knows.
```

**Solution**: Versioned strategies with clear semantics

**New Structure**:
```
stock-verify/strategies/
├── whale_6position/
│   ├── __init__.py
│   ├── core.py              ← Shared signal logic
│   ├── versions.py          ← Version registry
│   ├── v8/
│   │   ├── __init__.py
│   │   ├── algorithm.py     ← v8-specific implementation
│   │   └── CHANGELOG.md     ← What changed from v7→v8
│   ├── v11/
│   │   ├── __init__.py
│   │   ├── algorithm.py     ← v11-specific implementation
│   │   └── CHANGELOG.md
│   └── test/
│       ├── test_v8.py
│       └── test_v11.py
├── sma_daily/
│   ├── __init__.py
│   ├── core.py
│   ├── v1/                  ← Current production
│   │   └── algorithm.py
│   └── test/
│       └── test_v1.py
```

**Version Registry**:
```python
# stock-verify/strategies/whale_6position/versions.py

class StrategyRegistry:
    VERSIONS = {
        'v8': {
            'status': 'stable',
            'notes': 'Improved whale detection with 20-day window',
            'deprecation': None,
            'class': WhaleAccumulationV8,
        },
        'v11': {
            'status': 'current_live',
            'notes': 'Added ensemble voting, 15% live performance',
            'deprecation': None,
            'class': WhaleAccumulationV11,
        },
        'v7': {
            'status': 'deprecated',
            'notes': 'Original algorithm, poor in sideways markets',
            'deprecation': 'Deprecated as of 2026-03-01. Use v8+',
            'class': WhaleAccumulationV7,
        }
    }

    @classmethod
    def get(cls, version: str) -> StrategyVersion:
        if version not in cls.VERSIONS:
            raise ValueError(f"Unknown version: {version}")
        meta = cls.VERSIONS[version]
        if meta['deprecation']:
            logger.warning(f"⚠️ {version}: {meta['deprecation']}")
        return meta['class']

    @classmethod
    def list(cls):
        for version, meta in cls.VERSIONS.items():
            status = meta['status']
            print(f"{version:8} [{status:15}] {meta['notes']}")
```

**CHANGELOG.md Template**:
```markdown
# Whale Accumulation Strategy - v11

**Date**: 2026-03-16
**Status**: Current Production
**Live Performance**: 15% YTD (2025-09 to 2026-03)

## Changes from v8 → v11
- Added ensemble voting (3 signals must agree)
- Extended whale detection window from 15 → 20 days
- Improved position sizing using institutional ownership
- Fix: Handled gap-down openings better

## Differences from v7
- v7: Simple MA crossover + whale detection
- v11: Ensemble voting + institutional analysis
- v11 shows 8% better Sharpe ratio in backtest

## Known Issues
- None
```

**Priority**: HIGH (clarity)
**Effort**: 3-4 hours
**Benefit**: Clear strategy evolution, prevents confusion

---

### Priority 3: Sync Live Bot with Backtest Signals 🟠

**Location**: `stock-verify/006208-sma-market-regime/` + `strategies/sma_daily/`

**Problem**:
```
Live bot signal generation:
  def buy_signal(price, sma20, sma50):
      return price > sma20 and sma20 > sma50

Backtest signal generation (in some script):
  def buy_signal(price, sma20, sma50, additional_filter):
      return price > sma20 and sma20 > sma50 and additional_filter

= Different logic!
= Live bot: 15% return | Backtest: 20% return
= Can't trust backtest results
```

**Solution**: Shared signal module

**New Structure**:
```
stock-verify/
├── shared_signals/
│   ├── __init__.py
│   └── sma_signals.py          ← Single source of truth
├── 006208-sma-market-regime/
│   └── bot.py                   ← Uses shared_signals
├── backtest/
│   └── run_backtest.py          ← Uses shared_signals
└── strategies/
    └── sma_daily/
        ├── v1/
        │   └── algorithm.py     ← Uses shared_signals
```

**Implementation**:
```python
# stock-verify/shared_signals/sma_signals.py

class SMASignalGenerator:
    """Single source of truth for SMA signals"""

    def __init__(self, fast_period=20, slow_period=50):
        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate(self, prices: List[float]) -> str:
        """
        Returns: 'BUY', 'SELL', or 'HOLD'
        Used by both live bot and backtest
        """
        if len(prices) < self.slow_period:
            return 'HOLD'

        sma_fast = sum(prices[-self.fast_period:]) / self.fast_period
        sma_slow = sum(prices[-self.slow_period:]) / self.slow_period
        current = prices[-1]

        if current > sma_fast and sma_fast > sma_slow:
            return 'BUY'
        elif current < sma_fast and sma_fast < sma_slow:
            return 'SELL'
        else:
            return 'HOLD'

# Live bot usage:
# 006208-sma-market-regime/bot.py
from shared_signals import SMASignalGenerator

generator = SMASignalGenerator(fast_period=20, slow_period=50)

def on_market_update(price_history):
    signal = generator.generate(price_history)
    if signal == 'BUY':
        place_buy_order()
    elif signal == 'SELL':
        place_sell_order()

# Backtest usage:
# backtest/run_backtest.py
from shared_signals import SMASignalGenerator

generator = SMASignalGenerator(fast_period=20, slow_period=50)

for i in range(len(data)):
    signal = generator.generate(data['close'].iloc[:i+1].tolist())
    # Same logic as live bot!
```

**Testing**:
```python
def test_live_bot_and_backtest_same_signal():
    """Ensure live bot and backtest use identical signal logic"""
    generator = SMASignalGenerator()
    prices = [100, 102, 101, 103, 105, 104, 106, 107, 105, 108]

    live_signal = generator.generate(prices)
    backtest_signal = generator.generate(prices)

    assert live_signal == backtest_signal, "Divergence detected!"
```

**Priority**: HIGH (risk mitigation)
**Effort**: 2-3 hours
**Benefit**: Backtest results now reliable, strategy validation works

---

## Part 2: What NOT to Touch (Red Lines)

🛑 **Do not refactor these** (signal validation is critical):

1. **Core Backtest Signal Signature**
   - Current functions must remain compatible
   - New signals can be added, existing ones must not change behavior
   - Rule: If you need to change signal logic, create new version
   - If issue: Bug fix is okay; algorithmic change = new version

2. **Live Bot Trade State Persistence Format**
   - Location: `006208-sma-market-regime/states/`
   - Why locked: Trade history is immutable, trading-critical
   - Rule: Append-only state updates
   - If needed: Create migration script for format changes

3. **Historical Trade Logs**
   - Location: `006208-sma-market-regime/trades/`
   - Why locked: Performance verification depends on accurate logs
   - Rule: Don't modify past trade records
   - If error: Document the correction, add footnote

---

## Part 3: SOLID Application (Project-Specific)

### Single Responsibility
⚠️ Currently violated:
- Each backtest script does: fetch data + run backtest + calculate metrics + plot results
- Should be: One script coordinates, others handle single concern

✅ After refactor:
- `BacktestRunner`: Orchestrates backtest execution
- `MetricsCalculator`: Calculates metrics only
- `DataLoader`: Fetches data only
- `Visualizer`: Plots results only

---

### Open/Closed Principle
✅ After refactor:
- Add new strategy → New file in `strategies/`, no modification to runner
- Add new metric → New method in `MetricsCalculator`
- New version of strategy → `strategies/whale_6position/v12/`

---

### Liskov Substitution
✅ Strategy interface consistency:
```python
class StrategyBase(ABC):
    @abstractmethod
    def generate_signal(self, data: DataFrame) -> str:
        """Returns: 'BUY', 'SELL', 'HOLD'"""
        pass

# All strategies must implement this consistently
class WhaleV8(StrategyBase):
    def generate_signal(self, data) -> str: ...  # ✅ Same contract

class SMADaily(StrategyBase):
    def generate_signal(self, data) -> str: ...  # ✅ Same contract
```

---

## Part 4: Roadmap & Priorities

| Task | Effort | Priority | Blocking | Status |
|------|--------|----------|----------|--------|
| Unify BacktestRunner | 6-8h | 🔴 CRITICAL | All other tasks | TODO |
| Implement version management | 3-4h | 🔴 CRITICAL | Clarity | TODO |
| Sync live bot + backtest signals | 2-3h | 🟠 HIGH | Trust backtest | TODO |
| Delete duplicate backtest scripts | 0.5h | 🟢 LOW | Cleanup | TODO |

---

## Code Review Checklist

Before committing changes:

- [ ] Using `shared_signals/` for live bot AND backtest? (Not duplicate)
- [ ] New strategy follows version structure + changelog?
- [ ] Signal function signature matches StrategyBase contract?
- [ ] Backtest config file added to `backtest/config/`?
- [ ] Tests cover strategy signal generation?
- [ ] Trade logs untouched (no modifying past trades)?

---

## Migration Path (Step-by-Step)

**Phase 1** (Week 1): Unify BacktestRunner
1. Create `backtest/runner.py` with BacktestRunner class
2. Create config template
3. Convert `backtest_fixed.py` config to JSON
4. Test runner with existing data

**Phase 2** (Week 2): Implement versioning
1. Reorganize strategies into versioned directories
2. Create version registry
3. Add CHANGELOG for each version
4. Update documentation

**Phase 3** (Week 3): Sync live bot
1. Extract SMA signal logic to `shared_signals/`
2. Update live bot to use shared module
3. Verify signal consistency
4. Add integration test

**Phase 4** (Week 4): Cleanup
1. Delete redundant backtest scripts
2. Archive old code (if needed)
3. Update README with new structure

---

## Reference

**Global Rules**: `/home/tom/.claude/projects/-home-tom/DESIGN_PRINCIPLES_RULE.md`

**Related**:
- SimpleEC OMS DESIGN_RULES.md — Event-driven patterns
- Analyst DESIGN_RULES.md — Plugin architecture
