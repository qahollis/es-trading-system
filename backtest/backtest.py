# backtest.py
# ES Futures Volume Profile Backtest Engine
# Tests ALL level touches with BOTH long and short entries
# independently — lets the data determine which direction wins
# at each level type under which conditions.
#
# Entry rules:
# - Price comes within 2 ticks of any volume profile level
# - Both long AND short entries recorded for every touch
# - Entries only accepted between 6:30pm and 10pm Eastern
#
# Exit rules (from entry price):
# - 16 ticks adverse = loss
# - 60 ticks favorable = win
# - End of session data = timeout

import os
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from dotenv import load_dotenv
from datetime import date
from zoneinfo import ZoneInfo

load_dotenv()
EASTERN = ZoneInfo("America/New_York")

DB_URL = f"postgresql://postgres:{os.getenv('PG_PASSWORD')}@localhost:5432/es_trading"
engine = create_engine(DB_URL)

# ── Strategy Parameters ────────────────────────────────────────────────────
TICK_SIZE      = 0.25
STOP_TICKS     = 16
TARGET_TICKS   = 60
TOUCH_TICKS    = 2
STOP_POINTS    = STOP_TICKS   * TICK_SIZE   # 4.00 points
TARGET_POINTS  = TARGET_TICKS * TICK_SIZE   # 15.00 points
TOUCH_POINTS   = TOUCH_TICKS  * TICK_SIZE   # 0.50 points

# Trading window — entries only accepted in this window
ENTRY_WINDOW_START = 18.5   # 6:30pm Eastern (18 + 30/60)
ENTRY_WINDOW_END   = 22.0   # 10:00pm Eastern

# ── Data Retrieval ─────────────────────────────────────────────────────────

def get_trading_dates():
    """
    Returns all trade_dates that have both levels and bars.
    These are the dates the backtest will process.
    """
    query = """
        SELECT DISTINCT v.trade_date
        FROM volume_profile_levels v
        INNER JOIN es_trades t ON t.trade_date = v.trade_date
        WHERE v.trade_date >= '2024-01-02'
        ORDER BY v.trade_date ASC
    """
    df = pd.read_sql(query, engine)
    return df['trade_date'].tolist()

def get_levels_for_date(trade_date):
    """
    Returns all volume profile levels for a given trade_date.
    Structure: {session_type: {vah, poc, val}}
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
    Returns all price bars for a given trade_date sorted by timestamp.
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
    df = df.reset_index(drop=True)
    return df

# ── Helper Functions ───────────────────────────────────────────────────────

def price_touched_level(price, level):
    """Returns True if price came within TOUCH_POINTS of a level."""
    return abs(price - level) <= TOUCH_POINTS

def is_in_trading_window(timestamp):
    """
    Returns True if timestamp falls within 6:30pm to 10pm Eastern.
    Entries are only valid during this window.
    """
    hour_decimal = timestamp.hour + timestamp.minute / 60
    return ENTRY_WINDOW_START <= hour_decimal <= ENTRY_WINDOW_END

def get_approach_direction(bars, touch_idx, lookback=3):
    """
    Determines the direction price was traveling into the level touch.
    Compares close price lookback bars before touch to close at touch.
    Returns 'bullish', 'bearish', or 'neutral'.
    """
    if touch_idx < lookback:
        return 'neutral'

    start_price = bars.iloc[touch_idx - lookback]['close']
    end_price   = bars.iloc[touch_idx]['close']
    diff        = end_price - start_price

    if diff > TICK_SIZE:
        return 'bullish'
    elif diff < -TICK_SIZE:
        return 'bearish'
    else:
        return 'neutral'

def get_confluences(levels, touched_session, touched_type, touch_price):
    """
    Returns list of other levels within 4 ticks of the touch price.
    Example output: ['previous_day_poc', 'previous_week_val']
    """
    confluence_tolerance = 4 * TICK_SIZE
    confluences = []

    for session_type, session_levels in levels.items():
        for level_type, level_price in session_levels.items():
            if session_type == touched_session and level_type == touched_type:
                continue
            if abs(touch_price - level_price) <= confluence_tolerance:
                confluences.append(f"{session_type}_{level_type}")

    return confluences

def simulate_trade(bars, entry_idx, direction):
    """
    Simulates a trade from entry_idx forward.
    Runs until stop hit, target hit, or end of session data.
    No time limit — trade runs as long as data exists.

    Returns dict with outcome, mae, bars_held.
    """
    entry_price = float(bars.iloc[entry_idx]['close'])
    mae_ticks   = 0

    for i in range(entry_idx + 1, len(bars)):
        bar        = bars.iloc[i]
        bars_held  = i - entry_idx
        bar_high   = float(bar['high'])
        bar_low    = float(bar['low'])

        if direction == 'long':
            adverse   = (entry_price - bar_low)  / TICK_SIZE
            favorable = (bar_high - entry_price) / TICK_SIZE
        else:  # short
            adverse   = (bar_high - entry_price) / TICK_SIZE
            favorable = (entry_price - bar_low)  / TICK_SIZE

        mae_ticks = max(mae_ticks, adverse)

        # Check stop first (conservative assumption)
        if adverse >= STOP_TICKS:
            return {
                'outcome':    'loss',
                'ticks':      -STOP_TICKS,
                'mae':        round(mae_ticks, 1),
                'bars_held':  bars_held
            }

        # Check target
        if favorable >= TARGET_TICKS:
            return {
                'outcome':    'win',
                'ticks':      TARGET_TICKS,
                'mae':        round(mae_ticks, 1),
                'bars_held':  bars_held
            }

    # End of session data reached
    return {
        'outcome':    'timeout',
        'ticks':      0,
        'mae':        round(mae_ticks, 1),
        'bars_held':  len(bars) - entry_idx
    }

# ── Main Backtest Engine ───────────────────────────────────────────────────

def run_backtest():
    """
    Main backtest function. For every trading day:
    1. Gets levels from volume_profile_levels
    2. Gets price bars from es_trades
    3. Scans for level touches within the trading window
    4. For each touch simulates BOTH long and short entries
    5. Records all results
    """
    print("="*60)
    print("ES FUTURES VOLUME PROFILE BACKTEST")
    print(f"Stop: {STOP_TICKS} ticks | Target: {TARGET_TICKS} ticks")
    print(f"Entry window: 6:30pm - 10:00pm Eastern")
    print(f"Direction: Both long and short tested independently")
    print("="*60)

    dates = get_trading_dates()
    print(f"\nProcessing {len(dates)} trading days...\n")

    all_trades  = []
    # Track touch count per level per session
    # Key: (trade_date, session_type, level_type)
    touch_counts = {}

    for date_idx, trade_date in enumerate(dates):

        trade_date_str = trade_date.isoformat() if hasattr(trade_date, 'isoformat') else str(trade_date)

        levels = get_levels_for_date(trade_date_str)
        bars   = get_bars_for_date(trade_date_str)

        if not levels or bars is None or bars.empty:
            continue

        # Reset touch counts for this date
        touch_counts = {}

        # Scan each bar
        for bar_idx in range(len(bars)):
            bar       = bars.iloc[bar_idx]
            timestamp = bar['timestamp']

            # Only accept entries within trading window
            if not is_in_trading_window(timestamp):
                continue

            touch_price = float(bar['close'])

            # Check every level
            for session_type, session_levels in levels.items():
                for level_type, level_price in session_levels.items():

                    if not price_touched_level(touch_price, level_price):
                        continue

                    # Increment touch count for this level
                    level_key = (trade_date_str, session_type, level_type)
                    touch_counts[level_key] = touch_counts.get(level_key, 0) + 1
                    touch_count = touch_counts[level_key]

                    # Get context
                    approach     = get_approach_direction(bars, bar_idx)
                    confluences  = get_confluences(
                        levels, session_type, level_type, touch_price
                    )

                    # Simulate BOTH directions independently
                    for direction in ['long', 'short']:
                        result = simulate_trade(bars, bar_idx, direction)

                        all_trades.append({
                            'trade_date':       trade_date_str,
                            'timestamp':        timestamp,
                            'day_of_week':      timestamp.strftime('%A'),
                            'hour':             timestamp.hour,
                            'session_type':     session_type,
                            'level_type':       level_type,
                            'level_price':      level_price,
                            'touch_price':      touch_price,
                            'touch_count':      touch_count,
                            'approach':         approach,
                            'direction':        direction,
                            'confluences':      ', '.join(confluences) if confluences else 'none',
                            'confluence_count': len(confluences),
                            'outcome':          result['outcome'],
                            'ticks':            result['ticks'],
                            'mae':              result['mae'],
                            'bars_held':        result['bars_held']
                        })

        if (date_idx + 1) % 50 == 0:
            print(f"Processed {date_idx + 1}/{len(dates)} days — "
                  f"{len(all_trades)} trade records so far")

    print(f"\nBacktest complete. Total records: {len(all_trades)}")
    return pd.DataFrame(all_trades) if all_trades else None

# ── Results Analysis ───────────────────────────────────────────────────────

def analyze_results(df):
    """
    Produces a ranked summary of results by setup type and direction.
    Filters out timeouts for win rate calculation.
    Minimum 20 samples required to include a setup in results.
    """
    if df is None or df.empty:
        print("No trades to analyze.")
        return None

    # Filter out timeouts
    completed = df[df['outcome'] != 'timeout'].copy()

    if completed.empty:
        print("No completed trades.")
        return None

    # Group by session, level type, and direction
    grouped = completed.groupby(
        ['session_type', 'level_type', 'direction']
    ).agg(
        total_trades    = ('outcome', 'count'),
        wins            = ('outcome', lambda x: (x == 'win').sum()),
        avg_mae         = ('mae', 'mean'),
        avg_bars        = ('bars_held', 'mean'),
        avg_confluence  = ('confluence_count', 'mean')
    ).reset_index()

    grouped['win_rate'] = (
        grouped['wins'] / grouped['total_trades'] * 100
    ).round(1)
    grouped['avg_mae']  = grouped['avg_mae'].round(1)
    grouped['avg_bars'] = grouped['avg_bars'].round(0)

    # Only include setups with enough samples
    grouped = grouped[grouped['total_trades'] >= 20]

    # Sort by win rate
    grouped = grouped.sort_values('win_rate', ascending=False)

    return grouped

def analyze_by_day(df):
    """
    Breaks down win rates by day of week for each setup.
    Helps identify if certain setups work better on specific days.
    """
    if df is None or df.empty:
        return None

    completed = df[df['outcome'] != 'timeout'].copy()

    grouped = completed.groupby(
        ['day_of_week', 'session_type', 'level_type', 'direction']
    ).agg(
        total_trades = ('outcome', 'count'),
        wins         = ('outcome', lambda x: (x == 'win').sum()),
    ).reset_index()

    grouped['win_rate'] = (
        grouped['wins'] / grouped['total_trades'] * 100
    ).round(1)

    # Only setups with 10+ samples per day
    grouped = grouped[grouped['total_trades'] >= 10]
    grouped = grouped.sort_values('win_rate', ascending=False)

    return grouped

def analyze_confluence(df):
    """
    Compares win rates for single level touches vs confluence touches.
    Shows whether stacked levels produce better results.
    """
    if df is None or df.empty:
        return None

    completed = df[df['outcome'] != 'timeout'].copy()

    grouped = completed.groupby(
        ['direction', 'confluence_count']
    ).agg(
        total_trades = ('outcome', 'count'),
        wins         = ('outcome', lambda x: (x == 'win').sum()),
        avg_mae      = ('mae', 'mean')
    ).reset_index()

    grouped['win_rate'] = (
        grouped['wins'] / grouped['total_trades'] * 100
    ).round(1)
    grouped['avg_mae']  = grouped['avg_mae'].round(1)
    grouped           = grouped[grouped['total_trades'] >= 20]
    grouped           = grouped.sort_values(
        ['direction', 'confluence_count']
    )

    return grouped

# ── Entry Point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Run the backtest
    trades = run_backtest()

    if trades is not None:
        # Save raw results
        trades.to_csv('backtest/trades_raw.csv', index=False)
        print(f"Raw trades saved to backtest/trades_raw.csv")

        print("\n" + "="*60)
        print("RESULTS BY SETUP TYPE AND DIRECTION")
        print("="*60)
        results = analyze_results(trades)
        if results is not None:
            print(results.to_string(index=False))

        print("\n" + "="*60)
        print("CONFLUENCE ANALYSIS")
        print("="*60)
        confluence = analyze_confluence(trades)
        if confluence is not None:
            print(confluence.to_string(index=False))

        print("\n" + "="*60)
        print("DAY OF WEEK ANALYSIS")
        print("="*60)
        by_day = analyze_by_day(trades)
        if by_day is not None:
            print(by_day.head(20).to_string(index=False))

        # Summary stats
        completed = trades[trades['outcome'] != 'timeout']
        print(f"\n{'='*60}")
        print(f"SUMMARY")
        print(f"{'='*60}")
        print(f"Total records:    {len(trades)}")
        print(f"Completed trades: {len(completed)}")
        print(f"Wins:             {(completed['outcome'] == 'win').sum()}")
        print(f"Losses:           {(completed['outcome'] == 'loss').sum()}")
        print(f"Timeouts:         {(trades['outcome'] == 'timeout').sum()}")
        if len(completed) > 0:
            overall_wr = (completed['outcome'] == 'win').sum() / len(completed) * 100
            print(f"Overall win rate: {overall_wr:.1f}%")