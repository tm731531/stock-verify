"""
006208 SMA 日線系統 - 交易記錄器
================================
記錄所有交易、訊號和狀態變化
"""

import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class TradeLogger:
    """交易記錄器"""

    def __init__(self, trades_dir: Path, logs_dir: Path):
        self.trades_dir = trades_dir
        self.logs_dir = logs_dir

        self.trades_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        # 交易檔案
        today = datetime.now().strftime('%Y%m%d')
        self.trades_file = trades_dir / f"trades_{today}.json"
        self.trades_csv = trades_dir / f"trades_{today}.csv"

        # 信號檔案
        self.signals_file = trades_dir / f"signals_{today}.json"

    def log_entry(self, entry_price: float, entry_type: str,
                  signal_reason: str, position_size: int = 1):
        """記錄進場訊號"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "entry",
            "action": entry_type,  # "long"
            "price": entry_price,
            "position_size": position_size,
            "signal_reason": signal_reason
        }

        self._append_trade(entry)
        self._append_signal(entry)

    def log_exit(self, exit_price: float, entry_price: float,
                 exit_reason: str, position_size: int = 1, entry_type: str = "long"):
        """記錄出場訊號"""
        pnl = (exit_price - entry_price) * position_size if entry_type == "long" else (entry_price - exit_price) * position_size
        pnl_pct = (pnl / entry_price / position_size) * 100 if entry_price > 0 else 0

        exit_log = {
            "timestamp": datetime.now().isoformat(),
            "type": "exit",
            "action": entry_type,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "position_size": position_size,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "exit_reason": exit_reason
        }

        self._append_trade(exit_log)
        self._append_signal(exit_log)

    def log_warning(self, price: float, atr: float, atr_ma: float,
                    daily_ret: float, action: str = "reduce"):
        """記錄空頭警訊"""
        warning = {
            "timestamp": datetime.now().isoformat(),
            "type": "warning",
            "signal": "volatility_explosion",
            "price": price,
            "atr": atr,
            "atr_ma": atr_ma,
            "daily_return": daily_ret,
            "action": action,
            "description": f"波動爆炸: ATR {atr/atr_ma:.1f}x + 跌幅 {daily_ret*100:.1f}%"
        }

        self._append_signal(warning)

    def log_signal(self, signal_type: str, price: float,
                   sma50: float, sma200: float, details: Dict[str, Any]):
        """記錄市場訊號"""
        signal = {
            "timestamp": datetime.now().isoformat(),
            "type": "market_signal",
            "signal": signal_type,  # "bull", "bear", "entry", "warning"
            "price": price,
            "sma50": sma50,
            "sma200": sma200,
            "details": details
        }

        self._append_signal(signal)

    def log_state_change(self, old_state: Dict[str, Any],
                        new_state: Dict[str, Any], reason: str):
        """記錄狀態變化"""
        change = {
            "timestamp": datetime.now().isoformat(),
            "type": "state_change",
            "reason": reason,
            "old_state": old_state,
            "new_state": new_state
        }

        self._append_signal(change)

    def _append_trade(self, trade: Dict[str, Any]):
        """附加交易記錄"""
        trades = self._read_trades()
        trades.append(trade)

        with open(self.trades_file, 'w', encoding='utf-8') as f:
            json.dump(trades, f, indent=2, ensure_ascii=False)

        # 同時寫入 CSV
        self._write_csv_trade(trade)

    def _append_signal(self, signal: Dict[str, Any]):
        """附加信號記錄"""
        signals = self._read_signals()
        signals.append(signal)

        with open(self.signals_file, 'w', encoding='utf-8') as f:
            json.dump(signals, f, indent=2, ensure_ascii=False)

    def _read_trades(self) -> list:
        """讀取所有交易"""
        if not self.trades_file.exists():
            return []

        try:
            with open(self.trades_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []

    def _read_signals(self) -> list:
        """讀取所有信號"""
        if not self.signals_file.exists():
            return []

        try:
            with open(self.signals_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []

    def _write_csv_trade(self, trade: Dict[str, Any]):
        """將交易記錄為 CSV"""
        file_exists = self.trades_csv.exists()

        with open(self.trades_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'timestamp', 'type', 'action', 'price', 'entry_price',
                'exit_price', 'position_size', 'pnl', 'pnl_pct', 'reason'
            ])

            if not file_exists:
                writer.writeheader()

            row = {
                'timestamp': trade.get('timestamp'),
                'type': trade.get('type'),
                'action': trade.get('action'),
                'price': trade.get('price'),
                'entry_price': trade.get('entry_price'),
                'exit_price': trade.get('exit_price'),
                'position_size': trade.get('position_size'),
                'pnl': trade.get('pnl'),
                'pnl_pct': trade.get('pnl_pct'),
                'reason': trade.get('signal_reason') or trade.get('exit_reason')
            }

            writer.writerow(row)

    def get_today_summary(self) -> Dict[str, Any]:
        """取得今日摘要"""
        trades = self._read_trades()
        signals = self._read_signals()

        entries = [t for t in trades if t.get('type') == 'entry']
        exits = [t for t in trades if t.get('type') == 'exit']
        warnings = [s for s in signals if s.get('type') == 'warning']

        total_pnl = sum(t.get('pnl', 0) for t in exits)
        winning_trades = len([t for t in exits if t.get('pnl', 0) > 0])
        losing_trades = len([t for t in exits if t.get('pnl', 0) < 0])

        return {
            "date": datetime.now().strftime('%Y-%m-%d'),
            "total_trades": len(entries),
            "entries": len(entries),
            "exits": len(exits),
            "warnings": len(warnings),
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "total_pnl": total_pnl,
            "win_rate": (winning_trades / len(exits) * 100) if exits else 0
        }

    def print_summary(self):
        """印出今日摘要"""
        summary = self.get_today_summary()

        print("\n" + "=" * 60)
        print(f"交易摘要 - {summary['date']}")
        print("=" * 60)
        print(f"總交易數: {summary['total_trades']}")
        print(f"進場: {summary['entries']} | 出場: {summary['exits']}")
        print(f"警訊: {summary['warnings']}")
        print(f"勝率: {summary['winning_trades']}/{summary['exits']} ({summary['win_rate']:.1f}%)")
        print(f"今日損益: {summary['total_pnl']:+.0f}")
        print("=" * 60 + "\n")
