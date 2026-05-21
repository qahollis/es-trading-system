# load.py
# Orchestrates the full daily ETL pipeline
# 1. Fetches yesterday's raw bars from Databento (extract)
# 2. Writes raw bars to es_trades table
# 3. Queries database for previous day and previous week bars
# 4. Calculates VAH/POC/VAL for all three sessions (transform)
# 5. Writes levels to volume_profile_levels table

import os
import pandas as pd
from datetime import date, timedelta
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from extract import fetch_es_data
from transform import transform, calculate_volume_profile
from transform import filter_overnight, filter_previous_day, filter_previous_week

load_dotenv()

# Database connection
DB_URL = f"postgresql://postgres:{os.getenv('PG_PASSWORD')}@localhost:5432/es_trading"
engine = create_engine(DB_URL)

def get_bars_from_db(start_date, end_date):
    """
    Queries es_trades table for bars within a trade_date range.
    Uses trade_date (not session_date) so session boundaries are
    respected correctly — overnight bars that cross midnight are
    grouped with the correct trading session.
    """
    query = f"""
        SELECT timestamp, open, high, low, close, volume,
               session_type, session_date, trade_date
        FROM es_trades
        WHERE trade_date >= '{start_date}'
        AND trade_date <= '{end_date}'
        ORDER BY timestamp ASC
    """
    df = pd.read_sql(query, engine)

    if df.empty:
        return None

    # Ensure timestamps are timezone-aware Eastern Time
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df['timestamp'] = df['timestamp'].dt.tz_convert(EASTERN)

    return df

def write_bars_to_db(df):
    """
    Writes new daily bars to es_trades table.
    Checks for existing data first to avoid duplicates.
    """
    if df is None or df.empty:
        print("No bars to write.")
        return 0

    # Check if data for this trade_date already exists
    # Use trade_date column max value to identify the session
    if 'trade_date' in df.columns:
        sample_date = df['trade_date'].max()
    else:
        sample_date = df['session_date'].iloc[0]

    existing = pd.read_sql(
        f"SELECT COUNT(*) as count FROM es_trades WHERE trade_date = '{sample_date}'",
        engine
    )

    if existing['count'].iloc[0] > 0:
        print(f"  Bars for trade_date {sample_date} already exist — skipping to avoid duplicates.")
        return 0

    df.to_sql('es_trades', engine, if_exists='append', index=False)
    print(f"  Written {len(df)} bars to es_trades")
    return len(df)

def write_levels_to_db(levels_df):
    """
    Writes calculated volume profile levels to volume_profile_levels table.
    Checks for existing levels first to avoid duplicates.
    """
    if levels_df is None or levels_df.empty:
        print("No levels to write.")
        return 0

    rows_written = 0

    for _, row in levels_df.iterrows():
        # Check if this session's levels already exist
        existing = pd.read_sql(
            f"""SELECT COUNT(*) as count FROM volume_profile_levels
                WHERE session_date = '{row['session_date']}'
                AND session_type = '{row['session_type']}'""",
            engine
        )

        if existing['count'].iloc[0] > 0:
            print(f"  Levels for {row['session_date']} {row['session_type']} already exist — skipping.")
            continue

        # Write this session's levels
        row_df = pd.DataFrame([row])
        row_df.to_sql('volume_profile_levels', engine, if_exists='append', index=False)
        rows_written += 1
        print(f"  Written {row['session_type']} levels: VAH={row['vah']} POC={row['poc']} VAL={row['val']}")

    return rows_written

def run_daily_pipeline(trade_date=None):
    """
    Runs the complete daily ETL pipeline for a given trade date.
    If no date provided, defaults to yesterday.

    Steps:
    1. Fetch bars from Databento for trade_date
    2. Write new bars to database
    3. Calculate overnight levels from new bars
    4. Query database for previous day bars (same trade_date)
    5. Query database for previous week bars (14 day lookback)
    6. Calculate previous day and previous week levels
    7. Write all levels to database
    """
    from transform import (filter_overnight, filter_previous_day,
                           filter_previous_week, calculate_volume_profile)
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")

    # Default to yesterday
    if trade_date is None:
        trade_date = (date.today() - timedelta(days=1)).isoformat()

    print("Pipeline starting...")
    print(f"\n{'='*50}")
    print(f"Running daily pipeline for {trade_date}")
    print(f"{'='*50}")

    # ── Step 1: Fetch new bars from Databento ──
    print("\nStep 1: Fetching new bars from Databento...")
    new_bars = fetch_es_data(trade_date)

    if new_bars is None:
        print("No new data available. Pipeline complete.")
        return

    # ── Step 2: Write new bars to database ──
    print("\nStep 2: Writing new bars to database...")
    write_bars_to_db(new_bars)

    # ── Step 3: Calculate overnight levels from new bars ──
    print("\nStep 3: Calculating overnight levels...")

    # Ensure timestamps are timezone aware
    if new_bars['timestamp'].dt.tz is None:
        new_bars['timestamp'] = new_bars['timestamp'].dt.tz_localize(EASTERN)
    else:
        new_bars['timestamp'] = new_bars['timestamp'].dt.tz_convert(EASTERN)

    overnight_bars = filter_overnight(new_bars, trade_date)
    print(f"  Overnight bars found: {len(overnight_bars)}")

    overnight_levels = None
    if not overnight_bars.empty:
        levels = calculate_volume_profile(overnight_bars)
        if levels:
            overnight_levels = pd.DataFrame([{
                'session_date': trade_date,
                'trade_date':   trade_date,
                'session_type': 'previous_overnight',
                **levels
            }])
            print(f"  Overnight — VAH: {levels['vah']}  POC: {levels['poc']}  VAL: {levels['val']}")
        else:
            print("  Overnight — insufficient data for level calculation")
    else:
        print("  No overnight bars found in new data")

    # ── Step 4: Query database for previous day bars ──
    # Previous day RTH = 9:30am to 4pm on trade_date (same day)
    print("\nStep 4: Querying database for previous day bars...")
    prev_day_bars = get_bars_from_db(trade_date, trade_date)
    if prev_day_bars is not None:
        print(f"  Previous day bars found: {len(prev_day_bars)}")
    else:
        print("  No previous day bars found in database")

    # ── Step 5: Query database for previous week bars ──
    # Go back 14 days to ensure full previous week is captured
    print("\nStep 5: Querying database for previous week bars...")
    prev_week_start = (date.fromisoformat(trade_date) - timedelta(days=14)).isoformat()
    prev_week_bars = get_bars_from_db(prev_week_start, trade_date)
    if prev_week_bars is not None:
        print(f"  Previous week bars found: {len(prev_week_bars)}")
    else:
        print("  No previous week bars found in database")

    # ── Step 6: Calculate previous day and previous week levels ──
    print("\nStep 6: Calculating all session levels...")
    all_levels = []

    # Add overnight levels if calculated
    if overnight_levels is not None:
        all_levels.append(overnight_levels)

    # Previous day levels
    if prev_day_bars is not None:
        pd_filtered = filter_previous_day(prev_day_bars, trade_date)
        print(f"  Previous day filtered bars: {len(pd_filtered)}")
        pd_levels = calculate_volume_profile(pd_filtered)
        if pd_levels:
            all_levels.append(pd.DataFrame([{
                'session_date': trade_date,
                'trade_date':   trade_date,
                'session_type': 'previous_day',
                **pd_levels
            }]))
            print(f"  Previous day — VAH: {pd_levels['vah']}  POC: {pd_levels['poc']}  VAL: {pd_levels['val']}")
        else:
            print("  Previous day — insufficient data for level calculation")

    # Previous week levels
    if prev_week_bars is not None:
        pw_filtered = filter_previous_week(prev_week_bars, trade_date)
        print(f"  Previous week filtered bars: {len(pw_filtered)}")
        pw_levels = calculate_volume_profile(pw_filtered)
        if pw_levels:
            all_levels.append(pd.DataFrame([{
                'session_date': trade_date,
                'trade_date':   trade_date,
                'session_type': 'previous_week',
                **pw_levels
            }]))
            print(f"  Previous week — VAH: {pw_levels['vah']}  POC: {pw_levels['poc']}  VAL: {pw_levels['val']}")
        else:
            print("  Previous week — insufficient data for level calculation")

    # ── Step 7: Write all levels to database ──
    print("\nStep 7: Writing levels to database...")
    if all_levels:
        combined_levels = pd.concat(all_levels, ignore_index=True)
        write_levels_to_db(combined_levels)
    else:
        print("  No levels to write.")

    print(f"\nPipeline complete for {trade_date}")


if __name__ == "__main__":
    run_daily_pipeline()