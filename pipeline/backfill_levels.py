# backfill_levels.py
# Calculates volume profile levels for all historical dates
# using bars already stored in es_trades database.
# Does NOT call the Databento API — reads from database only.

import os
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv
from datetime import date, timedelta
from zoneinfo import ZoneInfo

# Import transform functions
import sys
sys.path.insert(0, 'pipeline')
from transform import (calculate_volume_profile, filter_overnight,
                       filter_previous_day, filter_previous_week)

load_dotenv()
EASTERN = ZoneInfo("America/New_York")

DB_URL = f"postgresql://postgres:{os.getenv('PG_PASSWORD')}@localhost:5432/es_trading"
engine = create_engine(DB_URL)

def get_dates_needing_levels():
    """
    Returns all trade_dates that have bars in es_trades but
    do NOT yet have all three levels in volume_profile_levels.
    Skips dates that are already fully calculated.
    """
    query = """
        SELECT DISTINCT t.trade_date
        FROM es_trades t
        WHERE t.trade_date IS NOT NULL
        AND (
            SELECT COUNT(DISTINCT session_type)
            FROM volume_profile_levels v
            WHERE v.trade_date = t.trade_date
        ) < 3
        ORDER BY t.trade_date ASC
    """
    df = pd.read_sql(query, engine)
    return df['trade_date'].tolist()

def get_bars_for_date(trade_date):
    """
    Queries es_trades for all bars associated with a trade_date.
    Pulls a wider window to ensure all three session filters
    have enough data to work with.
    """
    # Get bars from 14 days before trade_date to cover previous week
    query = f"""
        SELECT timestamp, open, high, low, close, volume,
               session_type, session_date, trade_date
        FROM es_trades
        WHERE trade_date >= '{trade_date}'::date - INTERVAL '14 days'
        AND trade_date <= '{trade_date}'::date
        ORDER BY timestamp ASC
    """
    df = pd.read_sql(query, engine)

    if df.empty:
        return None

    # Convert timestamps to Eastern Time
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df['timestamp'] = df['timestamp'].dt.tz_convert(EASTERN)

    return df

def write_levels_to_db(levels_df):
    """
    Writes calculated levels to volume_profile_levels.
    Skips any session that already has levels for this date.
    """
    if levels_df is None or levels_df.empty:
        return 0

    rows_written = 0
    for _, row in levels_df.iterrows():
        # Check if this session already exists
        existing = pd.read_sql(
            f"""SELECT COUNT(*) as count FROM volume_profile_levels
                WHERE trade_date = '{row['trade_date']}'
                AND session_type = '{row['session_type']}'""",
            engine
        )
        if existing['count'].iloc[0] > 0:
            continue

        pd.DataFrame([row]).to_sql(
            'volume_profile_levels', engine,
            if_exists='append', index=False
        )
        rows_written += 1

    return rows_written

def calculate_levels_for_date(trade_date, bars_df):
    """
    Calculates all three session levels for a given trade_date
    using bars already in the database.
    Returns a DataFrame of levels or None.
    """
    if bars_df is None or bars_df.empty:
        return None

    trade_date_str = trade_date.isoformat() if hasattr(trade_date, 'isoformat') else trade_date
    results = []

    sessions = {
        'previous_overnight': filter_overnight,
        'previous_day':       filter_previous_day,
        'previous_week':      filter_previous_week,
    }

    for session_type, filter_func in sessions.items():
        try:
            session_bars = filter_func(bars_df, trade_date_str)
            if session_bars.empty:
                continue

            levels = calculate_volume_profile(session_bars)
            if levels:
                results.append({
                    'session_date': trade_date_str,
                    'trade_date':   trade_date_str,
                    'session_type': session_type,
                    'vah':          levels['vah'],
                    'poc':          levels['poc'],
                    'val':          levels['val'],
                    'total_volume': levels['total_volume']
                })
        except Exception as e:
            print(f"  Error calculating {session_type}: {e}")
            continue

    if not results:
        return None

    return pd.DataFrame(results)

def run_backfill():
    """
    Main backfill function. Processes all dates that need levels.
    """
    print("Starting historical levels backfill...")
    print("Reading bars from database — no API calls needed.\n")

    dates = get_dates_needing_levels()
    print(f"Found {len(dates)} dates needing levels calculation")

    total_written = 0
    processed = 0

    for trade_date in dates:
        # Get bars for this date and surrounding window
        bars_df = get_bars_for_date(trade_date)

        if bars_df is None:
            continue

        # Calculate levels
        levels_df = calculate_levels_for_date(trade_date, bars_df)

        if levels_df is None:
            continue

        # Write to database
        written = write_levels_to_db(levels_df)
        total_written += written
        processed += 1

        # Print progress every 50 dates
        if processed % 50 == 0:
            print(f"Processed {processed}/{len(dates)} dates — "
                  f"{total_written} level rows written so far")

    print(f"\nBackfill complete.")
    print(f"  Dates processed: {processed}")
    print(f"  Total level rows written: {total_written}")

if __name__ == "__main__":
    run_backfill()