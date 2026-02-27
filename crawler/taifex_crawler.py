#!/usr/bin/env python3
"""
台灣期貨交易所 (TAIFEX) 台指期 (TX) 數據爬蟲
直接調用期交所 OpenAPI 獲取歷史日線數據

功能:
- 爬取台指期日線 OHLCV + 未平倉量
- 支持日期範圍查詢
- 自動去重和數據驗證
- 存為 CSV 格式
"""

import requests
import pandas as pd
import json
from datetime import datetime, timedelta
import time
from pathlib import Path
import logging

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TAIFEXCrawler:
    """期交所 OpenAPI 爬蟲"""

    # 官方 API 端點
    BASE_URL = "https://openapi.taifex.com.tw/v1/DailyFutureMarketData"

    # 台指期期貨代碼
    TAIWAN_INDEX_FUTURES = "TX"  # 台指期 (大台)
    TAIWAN_INDEX_MICRO = "MTX"   # 小台

    def __init__(self, product_id=TAIWAN_INDEX_FUTURES, output_dir="./taifex_data"):
        """
        初始化爬蟲

        Args:
            product_id: 期貨代碼 ('TX' 大台 或 'MTX' 小台)
            output_dir: 數據輸出目錄
        """
        self.product_id = product_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def fetch_date(self, date_str: str) -> pd.DataFrame:
        """
        獲取單一日期的期貨數據

        Args:
            date_str: 日期字符串 'YYYY-MM-DD'

        Returns:
            DataFrame: 該日期的所有期貨合約數據
        """
        try:
            params = {
                'queryDate': date_str.replace('-', ''),  # YYYYMMDD 格式
                'productID': self.product_id
            }

            response = self.session.get(
                self.BASE_URL,
                params=params,
                timeout=10
            )
            response.raise_for_status()

            data = response.json()

            # 檢查是否有數據
            if 'data' not in data or not data['data']:
                logger.warning(f"No data found for {date_str}")
                return pd.DataFrame()

            # 轉換為 DataFrame
            df = pd.DataFrame(data['data'])

            # 添加日期列
            df['date'] = date_str

            logger.info(f"✓ {date_str}: 取得 {len(df)} 筆數據")

            return df

        except requests.exceptions.RequestException as e:
            logger.error(f"✗ API 請求失敗 {date_str}: {e}")
            return pd.DataFrame()
        except json.JSONDecodeError as e:
            logger.error(f"✗ JSON 解析失敗 {date_str}: {e}")
            return pd.DataFrame()

    def fetch_date_range(self, start_date: str, end_date: str, sleep_interval=0.5) -> pd.DataFrame:
        """
        獲取日期範圍內的數據

        Args:
            start_date: 開始日期 'YYYY-MM-DD'
            end_date: 結束日期 'YYYY-MM-DD'
            sleep_interval: 兩次請求間隔 (秒)，避免被 IP 封禁

        Returns:
            DataFrame: 合併後的歷史數據
        """
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')

        all_data = []
        current = start
        total_days = (end - start).days + 1

        logger.info(f"開始爬取 {self.product_id} 從 {start_date} 到 {end_date} ({total_days} 天)")

        while current <= end:
            date_str = current.strftime('%Y-%m-%d')

            # 跳過週末
            if current.weekday() < 5:  # Monday=0, Friday=4
                df = self.fetch_date(date_str)
                if not df.empty:
                    all_data.append(df)

            current += timedelta(days=1)
            time.sleep(sleep_interval)  # 避免 API 限流

        if not all_data:
            logger.warning("沒有取得任何數據")
            return pd.DataFrame()

        # 合併所有數據
        combined_df = pd.concat(all_data, ignore_index=True)
        logger.info(f"✓ 共取得 {len(combined_df)} 筆數據")

        return combined_df

    def clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        清理和標準化數據

        Args:
            df: 原始數據 DataFrame

        Returns:
            DataFrame: 清理後的數據
        """
        if df.empty:
            return df

        # 複製以避免修改原始數據
        df = df.copy()

        # 重新命名列以符合標準格式
        column_mapping = {
            'date': 'Date',
            'contract_month': 'ContractMonth',
            'open_price': 'Open',
            'high_price': 'High',
            'low_price': 'Low',
            'close_price': 'Close',
            'trading_volume': 'Volume',
            'open_interest': 'OpenInterest'
        }

        # 只重新命名存在的列
        existing_mapping = {k: v for k, v in column_mapping.items() if k in df.columns}
        df = df.rename(columns=existing_mapping)

        # 選擇關鍵列
        key_columns = ['Date', 'ContractMonth', 'Open', 'High', 'Low', 'Close', 'Volume', 'OpenInterest']
        available_columns = [col for col in key_columns if col in df.columns]
        df = df[available_columns]

        # 數據類型轉換
        numeric_columns = ['Open', 'High', 'Low', 'Close', 'Volume', 'OpenInterest']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df['Date'] = pd.to_datetime(df['Date'])

        # 去除 NaN 值
        df = df.dropna(subset=['Close'])

        # 按日期排序
        df = df.sort_values('Date').reset_index(drop=True)

        # 去重
        df = df.drop_duplicates(subset=['Date', 'ContractMonth'], keep='last')

        logger.info(f"✓ 數據清理完成: {len(df)} 筆記錄")

        return df

    def save_to_csv(self, df: pd.DataFrame, filename=None) -> str:
        """
        保存數據為 CSV 檔案

        Args:
            df: DataFrame
            filename: 文件名（可選）

        Returns:
            str: 保存的文件路徑
        """
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"taifex_{self.product_id}_{timestamp}.csv"

        filepath = self.output_dir / filename
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        logger.info(f"✓ 數據已保存: {filepath}")

        return str(filepath)

    def get_latest_contract(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        篩選最近期合約的數據（通常用於分析）

        Args:
            df: 完整數據 DataFrame

        Returns:
            DataFrame: 最近期合約的數據
        """
        if df.empty or 'ContractMonth' not in df.columns:
            return df

        # 獲取最新的合約月份
        latest_contract = df['ContractMonth'].max()
        filtered_df = df[df['ContractMonth'] == latest_contract].copy()

        logger.info(f"✓ 篩選最近期合約: {latest_contract} ({len(filtered_df)} 筆記錄)")

        return filtered_df


def main():
    """主程序"""

    # ========== 配置區域 ==========

    # 爬蟲參數
    PRODUCT_ID = "TX"  # 'TX' = 大台, 'MTX' = 小台
    START_DATE = "2024-01-01"  # 開始日期
    END_DATE = "2025-02-27"    # 結束日期
    OUTPUT_DIR = "./taifex_data"

    # ========== 執行爬蟲 ==========

    logger.info(f"初始化爬蟲... (產品: {PRODUCT_ID})")
    crawler = TAIFEXCrawler(product_id=PRODUCT_ID, output_dir=OUTPUT_DIR)

    # 獲取數據
    logger.info("=" * 60)
    logger.info("Step 1: 爬取期交所 OpenAPI 數據")
    logger.info("=" * 60)
    raw_data = crawler.fetch_date_range(START_DATE, END_DATE, sleep_interval=0.5)

    if raw_data.empty:
        logger.error("無法獲取數據，程式退出")
        return

    # 清理數據
    logger.info("\n" + "=" * 60)
    logger.info("Step 2: 數據清理和驗證")
    logger.info("=" * 60)
    cleaned_data = crawler.clean_data(raw_data)

    if cleaned_data.empty:
        logger.error("清理後無數據，程式退出")
        return

    # 保存全部數據
    logger.info("\n" + "=" * 60)
    logger.info("Step 3: 保存數據")
    logger.info("=" * 60)
    full_filepath = crawler.save_to_csv(cleaned_data, f"taifex_{PRODUCT_ID}_full.csv")

    # 篩選最近期合約
    logger.info("\n" + "=" * 60)
    logger.info("Step 4: 篩選最近期合約")
    logger.info("=" * 60)
    latest_contract_data = crawler.get_latest_contract(cleaned_data)
    if not latest_contract_data.empty:
        contract_filepath = crawler.save_to_csv(latest_contract_data, f"taifex_{PRODUCT_ID}_latest.csv")

    # 輸出統計信息
    logger.info("\n" + "=" * 60)
    logger.info("爬蟲完成！統計信息:")
    logger.info("=" * 60)
    logger.info(f"總記錄數: {len(cleaned_data)}")
    logger.info(f"日期範圍: {cleaned_data['Date'].min()} 到 {cleaned_data['Date'].max()}")
    logger.info(f"獨特合約: {cleaned_data['ContractMonth'].nunique()}")
    logger.info(f"輸出目錄: {OUTPUT_DIR}")

    # 顯示前幾行數據
    logger.info("\n數據樣本 (前5行):")
    logger.info("\n" + cleaned_data.head().to_string())

    return cleaned_data


if __name__ == "__main__":
    data = main()
