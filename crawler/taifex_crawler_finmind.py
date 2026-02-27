#!/usr/bin/env python3
"""
使用 FinMind 爬取台指期歷史數據
FinMind 是台灣最大的免費金融數據庫，由國家高速網路中心贊助

功能:
- 爬取台指期日線 OHLCV + 其他技術指標
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


class FinMindCrawler:
    """FinMind 爬蟲 - 台灣期貨數據"""

    # FinMind 官方 API
    BASE_URL = "https://api.finmindtrade.com/api/v4/data"

    # 台指期期貨代碼
    PRODUCTS = {
        'TX': '台指期 (大台)',
        'MTX': '台指期微型 (小台)',
        'GC': '黃金期貨',
        'CL': '原油期貨'
    }

    def __init__(self, product_id='TX', output_dir="./taifex_data"):
        """
        初始化爬蟲

        Args:
            product_id: 期貨代碼
            output_dir: 數據輸出目錄
        """
        self.product_id = product_id
        self.product_name = self.PRODUCTS.get(product_id, product_id)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def fetch_date_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        從 FinMind 取得日期範圍內的期貨數據

        Args:
            start_date: 開始日期 'YYYY-MM-DD'
            end_date: 結束日期 'YYYY-MM-DD'

        Returns:
            DataFrame: 歷史數據
        """
        try:
            logger.info(f"從 FinMind 取得 {self.product_name} ({self.product_id})")
            logger.info(f"日期範圍: {start_date} 到 {end_date}")

            # FinMind API 參數
            params = {
                'dataset': 'TaiwanFuturesDailyClose',  # 台灣期貨日線
                'data_id': self.product_id,             # 期貨代碼
                'start_date': start_date.replace('-', ''),  # YYYYMMDD
                'end_date': end_date.replace('-', ''),      # YYYYMMDD
            }

            print(f"📡 API 請求...")
            print(f"   URL: {self.BASE_URL}")
            print(f"   Params: {params}\n")

            response = self.session.get(
                self.BASE_URL,
                params=params,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()

            # 檢查響應
            if data['status'] != 200:
                logger.error(f"API 返回錯誤: {data.get('message', 'Unknown error')}")
                return pd.DataFrame()

            if not data['data']:
                logger.warning(f"沒有找到 {self.product_id} 的數據")
                return pd.DataFrame()

            # 轉換為 DataFrame
            df = pd.DataFrame(data['data'])
            logger.info(f"✓ 成功取得 {len(df)} 筆數據")

            return df

        except requests.exceptions.RequestException as e:
            logger.error(f"✗ API 請求失敗: {e}")
            return pd.DataFrame()
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"✗ 數據解析失敗: {e}")
            return pd.DataFrame()

    def clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        清理和標準化數據

        Args:
            df: 原始數據

        Returns:
            DataFrame: 清理後的數據
        """
        if df.empty:
            return df

        df = df.copy()

        # FinMind 返回的列名通常是: date, open, high, low, close, volume
        column_mapping = {
            'date': 'Date',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }

        # 重新命名
        df = df.rename(columns=column_mapping)

        # 選擇關鍵列
        key_columns = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        available_columns = [col for col in key_columns if col in df.columns]
        df = df[available_columns]

        # 數據類型轉換
        numeric_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df['Date'] = pd.to_datetime(df['Date'])

        # 去除 NaN
        df = df.dropna(subset=['Close'])

        # 排序
        df = df.sort_values('Date').reset_index(drop=True)

        # 去重
        df = df.drop_duplicates(subset=['Date'], keep='last')

        logger.info(f"✓ 數據清理完成: {len(df)} 筆記錄")
        logger.info(f"  日期範圍: {df['Date'].min()} 到 {df['Date'].max()}")

        return df

    def save_to_csv(self, df: pd.DataFrame, filename=None) -> str:
        """
        保存數據為 CSV

        Args:
            df: DataFrame
            filename: 文件名

        Returns:
            str: 文件路徑
        """
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"finmind_{self.product_id}_{timestamp}.csv"

        filepath = self.output_dir / filename
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        logger.info(f"✓ 數據已保存: {filepath}")

        return str(filepath)

    def get_stats(self, df: pd.DataFrame):
        """統計數據"""
        if df.empty:
            return

        logger.info("\n" + "=" * 60)
        logger.info("📊 數據統計")
        logger.info("=" * 60)

        # 基本統計
        logger.info(f"總記錄數: {len(df)}")
        logger.info(f"日期範圍: {df['Date'].min().date()} 到 {df['Date'].max().date()}")
        logger.info(f"交易日數: {len(df)}")

        # 價格統計
        logger.info(f"\n價格統計:")
        logger.info(f"  開盤: ¥{df['Open'].min():.2f} - ¥{df['Open'].max():.2f}")
        logger.info(f"  最高: ¥{df['High'].max():.2f}")
        logger.info(f"  最低: ¥{df['Low'].min():.2f}")
        logger.info(f"  收盤: ¥{df['Close'].mean():.2f} (平均)")

        # 成交量統計
        if 'Volume' in df.columns:
            logger.info(f"\n成交量統計:")
            logger.info(f"  總量: {df['Volume'].sum():,.0f}")
            logger.info(f"  平均: {df['Volume'].mean():,.0f}")
            logger.info(f"  最高: {df['Volume'].max():,.0f}")

        # 顯示最新 5 筆數據
        logger.info(f"\n最新 5 筆數據:")
        for idx, row in df.tail(5).iterrows():
            logger.info(f"  {row['Date'].date()} | O:{row['Open']:.2f} H:{row['High']:.2f} L:{row['Low']:.2f} C:{row['Close']:.2f} V:{row['Volume']:.0f}")


def main():
    """主程序"""

    # ========== 配置 ==========
    PRODUCT_ID = "TX"          # 'TX'=大台, 'MTX'=小台
    START_DATE = "2023-01-01"  # 開始日期 (FinMind 有回溯數據)
    END_DATE = "2026-02-27"    # 結束日期
    OUTPUT_DIR = "./taifex_data"

    # ========== 執行 ==========

    logger.info("=" * 60)
    logger.info(f"🚀 FinMind 期貨數據爬蟲")
    logger.info("=" * 60)

    crawler = FinMindCrawler(product_id=PRODUCT_ID, output_dir=OUTPUT_DIR)

    # 第一步：爬取數據
    logger.info("\n" + "=" * 60)
    logger.info("Step 1: 從 FinMind 爬取數據")
    logger.info("=" * 60 + "\n")

    raw_data = crawler.fetch_date_range(START_DATE, END_DATE)

    if raw_data.empty:
        logger.error("❌ 無法取得數據，程式結束")
        return None

    # 第二步：清理數據
    logger.info("\n" + "=" * 60)
    logger.info("Step 2: 數據清理")
    logger.info("=" * 60)

    cleaned_data = crawler.clean_data(raw_data)

    if cleaned_data.empty:
        logger.error("❌ 清理後無數據")
        return None

    # 第三步：保存數據
    logger.info("\n" + "=" * 60)
    logger.info("Step 3: 保存數據")
    logger.info("=" * 60 + "\n")

    filepath = crawler.save_to_csv(cleaned_data, f"finmind_{PRODUCT_ID}_full.csv")

    # 第四步：統計
    crawler.get_stats(cleaned_data)

    logger.info("\n" + "=" * 60)
    logger.info("✅ 爬蟲完成！")
    logger.info("=" * 60)
    logger.info(f"輸出檔案: {filepath}")

    return cleaned_data


if __name__ == "__main__":
    data = main()
