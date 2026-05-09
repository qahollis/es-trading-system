# extract.py
# Fetches ES futures OHLCV data from Databento API
# Captures the full trading day — 6pm Eastern to 5pm Eastern next day
# Returns a clean pandas DataFrame ready for the transform step

import os
import pandas as pd
import databento as db
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("DATABENTO_API_KEY")

EASTERN = ZoneInfo("America/New_York")

def get_yesterday():
    """
    Calculates yesterday's date dynamically.
    Never hardcode dates — this ensures the script works correctly
    every time it runs without manual changes.
    """
    yesterday = date.today() - timedelta(days=1)
    return yesterday.isoformat()

def get_session_window(date_str):
    """
    Calculates the correct start and end times for a given trading date.
    Handles the full ES futures trading day:
    - Start: 6pm Eastern the previous calendar day
    - End: 5pm Eastern on date_str (Friday close)

    Returns start and end as ISO format strings with timezone info.
    """
    trade_date = date.fromisoformat(date_str)

    # Start: 6pm Eastern the previous calendar day
    start_dt = datetime(
        trade_date.year,
        trade_date.month,
        trade_date.day,
        hour=18,
        minute=0,
        second=0,
        tzinfo=EASTERN
    ) - timedelta(days=1)

    # End: 5pm Eastern on the trade date
    end_dt = datetime(
        trade_date.year,
        trade_date.month,
        trade_date.day,
        hour=17,
        minute=0,
        second=0,
        tzinfo=EASTERN
    )

    return start_dt.isoformat(), end_dt.isoformat()

def fetch_es_data(date_str=None):
    """
    Fetches 1-minute ES futures bars from Databento for a given date.
    If no date provided, defaults to yesterday.
    Captures full trading day — 6pm Eastern to 5pm Eastern.
    Returns a clean DataFrame or None if no data available.
    """
    # Use yesterday if no date specified
    if date_str is None:
        date_str = get_yesterday()

    start, end = get_session_window(date_str)

    print(f"Fetching ES data for {date_str}...")
    print(f"  Window: {start} to {end}")

    try:
        # Initialize Databento client
        client = db.Historical(API_KEY)

        # Request 1-minute OHLCV bars for ES continuous contract
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            symbols=["ES.c.0"],
            schema="ohlcv-1m",
            start=start,
            end=end,
            stype_in="continuous",
        )

        # Convert to pandas DataFrame
        df = data.to_df()

        # Check if any data was returned
        if df.empty:
            print(f"No data returned for {date_str} — market may have been closed.")
            return None

        print(f"  Raw rows received: {len(df)}")

        # Convert timestamp index to Eastern Time
        df.index = pd.to_datetime(df.index, utc=True)
        df.index = df.index.tz_convert(EASTERN)
        df = df.reset_index()

        # Rename timestamp column
        df = df.rename(columns={df.columns[0]: 'timestamp'})

     # Add session_date — calendar date of each bar
        df['session_date'] = df['timestamp'].dt.date

        # Add trade_date — the trading session each bar belongs to
        # Rule: bars between midnight and 9:30am belong to previous calendar date
        # because they fall inside the overnight session that opened the evening before
        def assign_trade_date(ts):
            hour = ts.hour
            minute = ts.minute
            if hour < 9 or (hour == 9 and minute < 30):
                # Midnight to 9:29am — belongs to previous day's session
                return (ts - pd.Timedelta(days=1)).date()
            else:
                # 9:30am onwards — belongs to current calendar date
                return ts.date()

        df['trade_date'] = df['timestamp'].apply(assign_trade_date)
        df['session_type'] = None

        # Select only the columns we need
        df = df[['timestamp', 'open', 'high', 'low', 'close',
                 'volume', 'session_type', 'session_date', 'trade_date']]
        # Convert volume to standard integer — Databento returns uint64
        # which PostgreSQL does not support
        df['volume'] = df['volume'].astype('int64')

        print(f"  Clean rows ready for transform: {len(df)}")
        return df

    except Exception as e:
        print(f"Error fetching data for {date_str}: {e}")
        return None

if __name__ == "__main__":
    # Test: fetch a known trading day
    df = fetch_es_data()
    if df is not None:
        print("\nSample data:")
        print(df.head())
        print(f"\nDate range in data:")
        print(f"  First bar: {df['timestamp'].min()}")
        print(f"  Last bar:  {df['timestamp'].max()}")
        print(f"  Total rows: {len(df)}")