# backtest.py
# Scans 5 years of ES futures data to find which volume profile
# level combinations produce 60+ tick moves before a 16 tick stop
#
# Research question: which setups give us the best edge?

import os
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from dotenv import load_dotenv
from datetime import date, timedelta
from zoneinfo import ZoneInfo

load_dotenv()
EASTERN = ZoneInfo("America/New_York")

DB_URL = f"postgresql://postgres:{os.getenv('PG_PASSWORD')}@localhost:5432/es_trading"
engine = create_engine(DB_URL)

# ── Strategy Parameters ────────────────────────────────────────────────────
TICK_SIZE     = 0.25          # ES tick size in index points
STOP_TICKS    = 16            # Fixed stop loss in ticks
TARGET_TICKS  = 60            # Profit target in ticks
TOUCH_TICKS   = 2             # How close price must come to trigger entry
STOP_POINTS   = STOP_TICKS   * TICK_SIZE   # 4.00 index points
TARGET_POINTS = TARGET_TICKS * TICK_SIZE   # 15.00 index points
TOUCH_POINTS  = TOUCH_TICKS  * TICK_SIZE   # 0.50 index points

# ── Helper Functions ───────────────────────────────────────────────────────

def price_touched_level(price, level, tolerance=TOUCH_POINTS):
    """
    Returns True if price came within tolerance of a level.
    Default tolerance is 2 ticks (0.50 index points).
    """
    return abs(price - level) <= tolerance

def get_levels_for_date(trade_date):
    """
    Queries the database for all three session levels for a given trade_date.
    Returns a dictionary of {session_type: {vah, poc, val}} or empty dict.
    """
    query = f"""
        SELECT session_type, vah, poc, val
        FROM volume_profile_levels
        WHERE trade_date = '{trade_date}'
    """
    df = pd.read_sql(query, engine)

    if df.empty:
        return {}

    levels = {}
    for _, row in df.iterrows():
        levels[row['session_type']] = {
            'vah': float(row['vah']),
            'poc': float(row['poc']),
            'val': float(row['val'])
        }
    return levels

def get_bars_for_date(trade_date):
    """
    Queries the database for all price bars for a given trade_date.
    Returns DataFrame of bars sorted by timestamp.
    """
    query = f"""
        SELECT timestamp, open, high, low, close, volume
        FROM es_trades
        WHERE trade_date = '{trade_date}'
        ORDER BY timestamp ASC
    """
    df = pd.read_sql(query, engine)

    if df.empty:
        return None

    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df['timestamp'] = df['timestamp'].dt.tz_convert(EASTERN)

    return df

def simulate_trade(bars, entry_idx, direction):
    """
    Simulates a trade starting at entry_idx bar.
    direction: 'long' (expecting price to go up)
               'short' (expecting price to go down)

    Returns dict with:
    - outcome: 'win', 'loss', or 'timeout'
    - ticks: how many ticks price moved in our favor at exit
    - mae: maximum adverse excursion in ticks (worst point against us)
    - bars_held: how many bars the trade lasted
    """
    entry_price = bars.iloc[entry_idx]['close']
    mae_points = 0

    for i in range(entry_idx + 1, len(bars)):
        bar = bars.iloc[i]
        bars_held = i - entry_idx

        if direction == 'long':
            # How far did price go against us (down)?
            adverse = entry_price - bar['low']
            # How far did price go in our favor (up)?
            favorable = bar['high'] - entry_price

        else:  # short
            # How far did price go against us (up)?
            adverse = bar['high'] - entry_price
            # How far did price go in our favor (down)?
            favorable = entry_price - bar['low']

        # Track worst point against us
        mae_points = max(mae_points, adverse)

        # Check if stop was hit
        if adverse >= STOP_POINTS:
            return {
                'outcome': 'loss',
                'ticks': -STOP_TICKS,
                'mae': round(mae_points / TICK_SIZE, 1),
                'bars_held': bars_held
            }

        # Check if target was hit
        if favorable >= TARGET_POINTS:
            return {
                'outcome': 'win',
                'ticks': TARGET_TICKS,
                'mae': round(mae_points / TICK_SIZE, 1),
                'bars_held': bars_held
            }

    # Neither stop nor target hit before data ended
    return {
        'outcome': 'timeout',
        'ticks': 0,
        'mae': round(mae_points / TICK_SIZE, 1),
        'bars_held': len(bars) - entry_idx
    }

def find_confluences(levels, touched_session, touched_level_type, touch_price):
    """
    Checks if any other levels are within 4 ticks of the touched level.
    Returns a list of confluence descriptions.
    Example: ['previous_day_poc', 'previous_week_val']
    """
    confluences = []
    confluence_tolerance = 4 * TICK_SIZE  # 1 point

    for session_type, session_levels in levels.items():
        for level_type, level_price in session_levels.items():
            # Skip the level we already touched
            if session_type == touched_session and level_type == touched_level_type:
                continue
            if abs(touch_price - level_price) <= confluence_tolerance:
                confluences.append(f"{session_type}_{level_type}")

    return confluences

def run_backtest(start_date=None, end_date=None):
    """
    Main backtest function. Scans all trading days between start_date
    and end_date looking for volume profile level touches and simulating
    trades with our fixed stop and target parameters.

    Returns a DataFrame of all trades found.
    """
    if start_date is None:
        start_date = "2021-04-06"
    if end_date is None:
        end_date = date.today().isoformat()

    print(f"\nRunning backtest: {start_date} to {end_date}")
    print(f"Parameters: {STOP_TICKS} tick stop / {TARGET_TICKS} tick target")
    print(f"Touch tolerance: {TOUCH_TICKS} ticks\n")

    # Get all unique trade_dates that have both levels and bars
    dates_query = f"""
        SELECT DISTINCT trade_date
        FROM volume_profile_levels
        WHERE trade_date >= '{start_date}'
        AND trade_date <= '{end_date}'
        ORDER BY trade_date ASC
    """
    dates_df = pd.read_sql(dates_query, engine)

    if dates_df.empty:
        print("No dates with calculated levels found.")
        print("Run load.py to calculate levels before backtesting.")
        return None

    print(f"Found {len(dates_df)} trading days with levels")

    all_trades = []
    dates_processed = 0

    for _, date_row in dates_df.iterrows():
        trade_date = date_row['trade_date'].isoformat()

        # Get levels and bars for this date
        levels = get_levels_for_date(trade_date)
        bars   = get_bars_for_date(trade_date)

        if not levels or bars is None:
            continue

        dates_processed += 1

        # Scan each bar looking for level touches
        for i, bar in bars.iterrows():
            bar_idx = bars.index.get_loc(i)

            # Skip last 60 bars — not enough room for trade to develop
            if bar_idx >= len(bars) - 60:
                break

            touch_price = bar['close']

            # Check every level across all three sessions
            for session_type, session_levels in levels.items():
                for level_type, level_price in session_levels.items():

                    if price_touched_level(touch_price, level_price):

                        # Determine trade direction
                        # VAL and POC touches — expect bounce up (long)
                        # VAH touches — expect rejection down (short)
                        if level_type == 'vah':
                            direction = 'short'
                        else:
                            direction = 'long'

                        # Find any confluences
                        confluences = find_confluences(
                            levels, session_type, level_type, touch_price
                        )

                        # Simulate the trade
                        result = simulate_trade(bars, bar_idx, direction)

                        # Record the trade
                        all_trades.append({
                            'trade_date':    trade_date,
                            'timestamp':     bar['timestamp'],
                            'session_type':  session_type,
                            'level_type':    level_type,
                            'level_price':   level_price,
                            'touch_price':   touch_price,
                            'direction':     direction,
                            'confluences':   ', '.join(confluences) if confluences else 'none',
                            'confluence_count': len(confluences),
                            'outcome':       result['outcome'],
                            'ticks':         result['ticks'],
                            'mae':           result['mae'],
                            'bars_held':     result['bars_held']
                        })

        if dates_processed % 10 == 0:
            print(f"Processed {dates_processed} days — {len(all_trades)} setups found so far")

    print(f"\nBacktest complete.")
    print(f"  Days processed: {dates_processed}")
    print(f"  Total setups found: {len(all_trades)}")

    if not all_trades:
        return None

    return pd.DataFrame(all_trades)

def analyze_results(trades_df):
    """
    Takes the raw trades DataFrame and produces a ranked summary
    showing which setups have the best win rate and edge.
    """
    if trades_df is None or trades_df.empty:
        print("No trades to analyze.")
        return None

    # Filter out timeouts for win rate calculation
    completed = trades_df[trades_df['outcome'] != 'timeout']

    if completed.empty:
        print("No completed trades found.")
        return None

    # Group by session type and level type
    grouped = completed.groupby(['session_type', 'level_type']).agg(
        total_trades    = ('outcome', 'count'),
        wins            = ('outcome', lambda x: (x == 'win').sum()),
        avg_mae         = ('mae', 'mean'),
        avg_bars_held   = ('bars_held', 'mean'),
        confluence_avg  = ('confluence_count', 'mean')
    ).reset_index()

    grouped['win_rate'] = (grouped['wins'] / grouped['total_trades'] * 100).round(1)
    grouped['avg_mae']  = grouped['avg_mae'].round(1)
    grouped['avg_bars_held'] = grouped['avg_bars_held'].round(0)

    # Sort by win rate descending
    grouped = grouped.sort_values('win_rate', ascending=False)

    return grouped

if __name__ == "__main__":
    # Run backtest on dates we have levels for
    # Start small — just the dates we have calculated levels for
    trades = run_backtest()

    if trades is not None:
        print("\n" + "="*60)
        print("RESULTS BY SETUP TYPE")
        print("="*60)
        results = analyze_results(trades)
        if results is not None:
            print(results.to_string(index=False))

        print(f"\nTotal trades recorded: {len(trades)}")
        print(f"Win trades: {(trades['outcome'] == 'win').sum()}")
        print(f"Loss trades: {(trades['outcome'] == 'loss').sum()}")
        print(f"Timeout trades: {(trades['outcome'] == 'timeout').sum()}")

        # Save results to CSV for further analysis
        trades.to_csv('backtest/trades_raw.csv', index=False)
        print(f"\nRaw trades saved to backtest/trades_raw.csv")