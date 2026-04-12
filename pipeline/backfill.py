# backfill.py
# Loads all historical Databento CSV files into PostgreSQL
# Handles multiple ES contract symbols and filters to front month only

import os
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# Update with your PostgreSQL password
DB_URL = "postgresql://postgres:96ForestHillsDrive!@localhost:5432/es_trading"
engine = create_engine(DB_URL)

# Path to your Databento data folder
DATA_FOLDER = Path(r"C:\Users\qholl\Documents\es-trading-system\data\GLBX-20260407-TMQTEXNLNW")

def is_es_front_month(symbol):
    """
    Returns True if the symbol is an ES futures contract.
    Filters out options, spreads, and other instruments.
    Example valid symbols: ESM1, ESU2, ESH3, ESZ4
    """
    if pd.isna(symbol):
        return False
    symbol = str(symbol).strip()
    return symbol.startswith('ES') and len(symbol) == 4

def load_csv_to_db(filepath):
    """
    Reads one Databento daily CSV file and loads it into PostgreSQL.
    Returns number of rows loaded.
    """
    try:
        df = pd.read_csv(filepath)

        # Filter to ES front month contracts only
        df = df[df['symbol'].apply(is_es_front_month)].copy()

        if df.empty:
            return 0

        # Select only the columns we need
        df = df[['ts_event', 'open', 'high', 'low', 'close', 'volume', 'symbol']]

        # Convert timestamp from UTC string to datetime
        df['timestamp'] = pd.to_datetime(df['ts_event'], utc=True)

        # Convert to Eastern Time to match your session windows
        df['timestamp'] = df['timestamp'].dt.tz_convert('America/New_York')

        # Add session_date column
        df['session_date'] = df['timestamp'].dt.date

        # Add placeholder session_type — calculated in transform step
        df['session_type'] = None

        # Final column selection matching database schema
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume', 'session_type', 'session_date']]

        # Write to PostgreSQL
        df.to_sql('es_trades', engine, if_exists='append', index=False)

        return len(df)

    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        import traceback
        traceback.print_exc()
        return 0
def run_backfill():
    """
    Loops through all CSV files in the data folder and loads them
    into PostgreSQL. Skips non-CSV files automatically.
    """
    # Get all CSV files sorted by date
    csv_files = sorted([
        f for f in DATA_FOLDER.iterdir()
        if 'ohlcv' in f.name
    ])

    print(f"Found {len(csv_files)} files to process")

    if len(csv_files) == 0:
        print("No files found. Check your DATA_FOLDER path.")
        return

    total_rows = 0

    for i, filepath in enumerate(csv_files):
        rows = load_csv_to_db(filepath)
        total_rows += rows

        # Print progress every 50 files
        if (i + 1) % 50 == 0:
            print(f"Processed {i + 1}/{len(csv_files)} files — {total_rows:,} rows loaded so far")

    print(f"\nBackfill complete. Total rows loaded: {total_rows:,}")

if __name__ == "__main__":
    run_backfill()