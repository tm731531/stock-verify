"""Data storage manager for TDCC shareholding data (CSV + SQLite)."""

import logging
import os
import sqlite3
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

CSV_FILENAME = "tdcc_data.csv"
DB_FILENAME = "tdcc_holdings.db"
RECORD_COLUMNS = ["stock_code", "date", "ratio_400_above", "ratio_1000_above", "total_holders"]

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS holdings (
    stock_code TEXT NOT NULL,
    date TEXT NOT NULL,
    ratio_400_above REAL,
    ratio_1000_above REAL,
    total_holders INTEGER,
    PRIMARY KEY (stock_code, date)
)
"""


class DataManager:
    """Manage TDCC data persistence in CSV and SQLite."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.csv_path = os.path.join(data_dir, CSV_FILENAME)
        self.db_path = os.path.join(data_dir, DB_FILENAME)
        os.makedirs(data_dir, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
        conn.close()

    def save_records(self, records: List[Dict]) -> int:
        """
        Save records to both CSV and SQLite, deduplicating by (stock_code, date).

        Returns number of new records saved.
        """
        if not records:
            return 0

        new_df = pd.DataFrame(records)[RECORD_COLUMNS]

        # --- SQLite (upsert) ---
        conn = sqlite3.connect(self.db_path)
        new_count = 0
        for _, row in new_df.iterrows():
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO holdings (stock_code, date, ratio_400_above, ratio_1000_above, total_holders) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (row["stock_code"], row["date"], row["ratio_400_above"], row["ratio_1000_above"], int(row["total_holders"])),
                )
                new_count += conn.total_changes
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        conn.close()

        # --- CSV (read-merge-write) ---
        if os.path.exists(self.csv_path):
            existing_df = pd.read_csv(self.csv_path, dtype={"stock_code": str, "date": str})
            merged = pd.concat([existing_df, new_df], ignore_index=True)
            merged = merged.drop_duplicates(subset=["stock_code", "date"], keep="last")
        else:
            merged = new_df

        merged = merged.sort_values(["stock_code", "date"]).reset_index(drop=True)
        merged.to_csv(self.csv_path, index=False)

        saved = len(merged) - (len(pd.read_csv(self.csv_path)) if os.path.exists(self.csv_path) else 0)
        logger.info(f"Saved {len(new_df)} records ({new_count} new)")
        return new_count

    def query(
        self,
        stock_code: Optional[str] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> List[Dict]:
        """Query holdings data from SQLite."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        sql = "SELECT * FROM holdings WHERE 1=1"
        params = []

        if stock_code:
            sql += " AND stock_code = ?"
            params.append(stock_code)
        if date_start:
            sql += " AND date >= ?"
            params.append(date_start)
        if date_end:
            sql += " AND date <= ?"
            params.append(date_end)

        sql += " ORDER BY date ASC"

        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_scraped_stocks(self) -> List[str]:
        """Get list of stock codes that have been scraped."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT DISTINCT stock_code FROM holdings ORDER BY stock_code").fetchall()
        conn.close()
        return [r[0] for r in rows]

    def get_latest_date(self, stock_code: str) -> Optional[str]:
        """Get the most recent date for a given stock."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT MAX(date) FROM holdings WHERE stock_code = ?",
            (stock_code,),
        ).fetchone()
        conn.close()
        return row[0] if row and row[0] else None
