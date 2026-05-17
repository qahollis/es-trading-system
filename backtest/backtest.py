# backtest.py
# ES Futures Volume Profile Backtest Engine
# Includes S/R comparison baseline
#
# Entry rules:
# - Bar low must reach or go below level for long entries
# - Bar high must reach or go above level for short entries
# - Entry price = level price (limit order fill)
# - Entries only accepted between 6:30pm and 10pm Eastern
#
# Exit rules:
# - 16 ticks adverse = loss
# - 60 ticks favorable = win
# - Session end (9:30am next morning) = timeout

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
STOP_POINTS    = STOP_TICKS   * TICK_SIZE
TARGET_POINTS  = TARGET_TICKS * TICK_SIZE

ENTRY_WINDOW_START = 18.5   # 6:30pm Eastern
ENTRY_WINDOW_END   = 22.0   # 10:00pm Eastern
COOLDOWN_BARS      = 10

# ── Data Retrieval ─────────────────────────────────────────────────────────

def get_trading_dates():
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
    """Returns volume profile levels for a trade_date."""
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
    """Returns all price bars for a trade_date."""
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

def get_sr_levels_for_date(trade_date):
    """
    Calculates simple S/R levels for a trade_date.

    Previous day RTH high/low: from 9:30am-4pm ON trade_date.
    This session completes before our 6:30pm entry window — valid.

    Previous overnight high/low: from the PREVIOUS trade_date's
    overnight session (6pm to 9:30am). We must use the previous
    trade_date to avoid lookahead bias — the current overnight
    session has not completed when we start trading at 6:30pm.

    Returns dict: {level_name: price}
    """
    levels = {}

    # Previous day RTH: 9:30am to 4pm ON trade_date
    # Completes before our 6:30pm entry window -- no lookahead bias
    rth_query = f"""
        SELECT MAX(high) as rth_high, MIN(low) as rth_low
        FROM es_trades
        WHERE trade_date = '{trade_date}'
        AND timestamp AT TIME ZONE 'America/New_York' >= '{trade_date} 09:30:00'
        AND timestamp AT TIME ZONE 'America/New_York' < '{trade_date} 16:00:00'
    """
    rth_df = pd.read_sql(rth_query, engine)

    if not rth_df.empty and rth_df['rth_high'].iloc[0] is not None:
        levels['prev_day_high'] = float(rth_df['rth_high'].iloc[0])
        levels['prev_day_low']  = float(rth_df['rth_low'].iloc[0])

    # Previous overnight: must use PREVIOUS trade_date's overnight
    # to avoid lookahead bias
    # Previous overnight = 6pm previous_trade_date to 9:30am trade_date
    # These bars have trade_date = previous_trade_date in our database
    prev_date_query = f"""
        SELECT MAX(trade_date) as prev_date
        FROM es_trades
        WHERE trade_date < '{trade_date}'
    """
    prev_df = pd.read_sql(prev_date_query, engine)

    if not prev_df.empty and prev_df['prev_date'].iloc[0] is not None:
        prev_date = prev_df['prev_date'].iloc[0]

        overnight_query = f"""
            SELECT MAX(high) as on_high, MIN(low) as on_low
            FROM es_trades
            WHERE trade_date = '{prev_date}'
            AND (
                EXTRACT(HOUR FROM timestamp AT TIME ZONE 'America/New_York') >= 18
                OR EXTRACT(HOUR FROM timestamp AT TIME ZONE 'America/New_York') < 9
                OR (
                    EXTRACT(HOUR FROM timestamp AT TIME ZONE 'America/New_York') = 9
                    AND EXTRACT(MINUTE FROM timestamp AT TIME ZONE 'America/New_York') < 30
                )
            )
        """
        on_df = pd.read_sql(overnight_query, engine)

        if not on_df.empty and on_df['on_high'].iloc[0] is not None:
            levels['prev_overnight_high'] = float(on_df['on_high'].iloc[0])
            levels['prev_overnight_low']  = float(on_df['on_low'].iloc[0])

    return levels

def get_session_end(trade_date_str):
    """Returns 9:30am Eastern the morning after trade_date."""
    trade_date_dt = pd.Timestamp(trade_date_str)
    return pd.Timestamp(
        str(trade_date_dt.date() + pd.Timedelta(days=1)) + ' 09:30:00'
    ).tz_localize(EASTERN)

# ── Helper Functions ───────────────────────────────────────────────────────

def bar_touched_level(bar_high, bar_low, level_price):
    """
    Returns True if level_price falls within the bar's high-low range.
    Confirms price actually traded at the level during this bar.
    A limit order at the level would have filled.
    Works identically for both long and short entry detection.
    Formula: bar_low <= level_price <= bar_high
    """
    return bar_low <= level_price <= bar_high

def is_in_trading_window(timestamp):
    hour_decimal = timestamp.hour + timestamp.minute / 60
    return ENTRY_WINDOW_START <= hour_decimal <= ENTRY_WINDOW_END

def get_approach_direction(bars, touch_idx, lookback=3):
    if touch_idx < lookback:
        return 'neutral'
    start_price = float(bars.iloc[touch_idx - lookback]['close'])
    end_price   = float(bars.iloc[touch_idx]['close'])
    diff        = end_price - start_price
    if diff > TICK_SIZE:
        return 'bullish'
    elif diff < -TICK_SIZE:
        return 'bearish'
    else:
        return 'neutral'

def get_confluences(levels, touched_session, touched_type, level_price):
    confluence_tolerance = 4 * TICK_SIZE
    confluences = []
    for session_type, session_levels in levels.items():
        for level_type, lp in session_levels.items():
            if session_type == touched_session and level_type == touched_type:
                continue
            if abs(level_price - lp) <= confluence_tolerance:
                confluences.append(f"{session_type}_{level_type}")
    return confluences

def simulate_trade(bars, entry_idx, direction, session_end, entry_price):
    """
    Simulates a trade from entry_idx forward.
    Entry at level_price (limit order fill).
    Stop: 16 ticks adverse. Target: 60 ticks favorable.
    """
    mae_ticks = 0

    for i in range(entry_idx + 1, len(bars)):
        bar       = bars.iloc[i]
        bars_held = i - entry_idx
        bar_time  = bar['timestamp']
        bar_high  = float(bar['high'])
        bar_low   = float(bar['low'])

        if bar_time >= session_end:
            return {
                'outcome':  'timeout',
                'ticks':     0,
                'mae':       round(mae_ticks, 1),
                'bars_held': bars_held
            }

        if direction == 'long':
            adverse   = max(0, (entry_price - bar_low)  / TICK_SIZE)
            favorable = max(0, (bar_high - entry_price) / TICK_SIZE)
        else:
            adverse   = max(0, (bar_high - entry_price) / TICK_SIZE)
            favorable = max(0, (entry_price - bar_low)  / TICK_SIZE)

        mae_ticks = max(mae_ticks, adverse)

        if adverse >= STOP_TICKS:
            return {
                'outcome':  'loss',
                'ticks':    -STOP_TICKS,
                'mae':       float(STOP_TICKS),
                'bars_held': bars_held
            }

        if favorable >= TARGET_TICKS:
            return {
                'outcome':  'win',
                'ticks':     TARGET_TICKS,
                'mae':       round(mae_ticks, 1),
                'bars_held': bars_held
            }

    return {
        'outcome':  'timeout',
        'ticks':     0,
        'mae':       round(mae_ticks, 1),
        'bars_held': len(bars) - entry_idx
    }

# ── Volume Profile Backtest ────────────────────────────────────────────────

def run_backtest():
    """
    Main volume profile backtest.
    Scans for level touches within entry window.
    Enters at level price when bar range includes the level.
    """
    print("="*60)
    print("VOLUME PROFILE BACKTEST")
    print(f"Stop: {STOP_TICKS}t | Target: {TARGET_TICKS}t | Entry: level price")
    print(f"Window: 6:30pm-10:00pm | Session end: 9:30am")
    print("="*60)

    dates = get_trading_dates()
    print(f"\nProcessing {len(dates)} trading days...\n")

    all_trades   = []
    touch_counts = {}

    for date_idx, trade_date in enumerate(dates):
        trade_date_str = (trade_date.isoformat()
                          if hasattr(trade_date, 'isoformat')
                          else str(trade_date))

        levels      = get_levels_for_date(trade_date_str)
        bars        = get_bars_for_date(trade_date_str)
        session_end = get_session_end(trade_date_str)

        if not levels or bars is None or bars.empty:
            continue

        touch_counts = {}

        for bar_idx in range(len(bars)):
            bar       = bars.iloc[bar_idx]
            timestamp = bar['timestamp']

            if not is_in_trading_window(timestamp):
                continue

            bar_high = float(bar['high'])
            bar_low  = float(bar['low'])

            for session_type, session_levels in levels.items():
                for level_type, level_price in session_levels.items():

                    # Level must fall within bar high-low range
                    # Confirms price actually traded at the level
                    if not bar_touched_level(bar_high, bar_low, level_price):
                        continue

                    directions_to_test = []

                    # Long direction cooldown check
                    lkey = (trade_date_str, session_type, level_type, 'long')
                    last = touch_counts.get(lkey + ('idx',), -999)
                    if bar_idx - last >= COOLDOWN_BARS:
                        directions_to_test.append('long')
                        touch_counts[lkey] = touch_counts.get(lkey, 0) + 1
                        touch_counts[lkey + ('idx',)] = bar_idx

                    # Short direction cooldown check
                    skey = (trade_date_str, session_type, level_type, 'short')
                    last = touch_counts.get(skey + ('idx',), -999)
                    if bar_idx - last >= COOLDOWN_BARS:
                        directions_to_test.append('short')
                        touch_counts[skey] = touch_counts.get(skey, 0) + 1
                        touch_counts[skey + ('idx',)] = bar_idx

                    if not directions_to_test:
                        continue

                    approach    = get_approach_direction(bars, bar_idx)
                    confluences = get_confluences(
                        levels, session_type, level_type, level_price
                    )
                    touch_count = touch_counts.get(
                        (trade_date_str, session_type, level_type,
                         directions_to_test[0]), 1
                    )

                    for direction in directions_to_test:
                        result = simulate_trade(
                            bars, bar_idx, direction,
                            session_end, entry_price=level_price
                        )
                        all_trades.append({
                            'trade_date':       trade_date_str,
                            'timestamp':        timestamp,
                            'day_of_week':      timestamp.strftime('%A'),
                            'hour':             timestamp.hour,
                            'session_type':     session_type,
                            'level_type':       level_type,
                            'level_price':      level_price,
                            'entry_price':      level_price,
                            'touch_count':      touch_count,
                            'approach':         approach,
                            'direction':        direction,
                            'confluences':      (', '.join(confluences)
                                                 if confluences else 'none'),
                            'confluence_count': len(confluences),
                            'outcome':          result['outcome'],
                            'ticks':            result['ticks'],
                            'mae':              result['mae'],
                            'bars_held':        result['bars_held']
                        })

        if (date_idx + 1) % 50 == 0:
            print(f"Processed {date_idx+1}/{len(dates)} days — "
                  f"{len(all_trades)} records so far")

    print(f"\nVolume profile backtest complete. Total records: {len(all_trades)}")
    return pd.DataFrame(all_trades) if all_trades else None

# ── S/R Backtest ───────────────────────────────────────────────────────────

def run_sr_backtest():
    """
    Simple Support/Resistance backtest.
    Uses previous day RTH high/low and previous overnight high/low.
    Same entry/exit rules as volume profile backtest.
    Represents what a basic technical trader would use.
    """
    print("="*60)
    print("SIMPLE S/R BACKTEST")
    print(f"Stop: {STOP_TICKS}t | Target: {TARGET_TICKS}t | Entry: level price")
    print(f"Levels: Prev Day High/Low + Prev Overnight High/Low")
    print(f"Window: 6:30pm-10:00pm | Session end: 9:30am")
    print("="*60)

    dates = get_trading_dates()
    print(f"\nProcessing {len(dates)} trading days...\n")

    all_trades   = []
    touch_counts = {}

    for date_idx, trade_date in enumerate(dates):
        trade_date_str = (trade_date.isoformat()
                          if hasattr(trade_date, 'isoformat')
                          else str(trade_date))

        sr_levels   = get_sr_levels_for_date(trade_date_str)
        bars        = get_bars_for_date(trade_date_str)
        session_end = get_session_end(trade_date_str)

        if not sr_levels or bars is None or bars.empty:
            continue

        touch_counts = {}

        for bar_idx in range(len(bars)):
            bar       = bars.iloc[bar_idx]
            timestamp = bar['timestamp']

            if not is_in_trading_window(timestamp):
                continue

            bar_high = float(bar['high'])
            bar_low  = float(bar['low'])

            for level_name, level_price in sr_levels.items():

                # Level must fall within bar high-low range
                if not bar_touched_level(bar_high, bar_low, level_price):
                    continue

                directions_to_test = []

                # Long direction cooldown check
                lkey = (trade_date_str, level_name, 'long')
                last = touch_counts.get(lkey + ('idx',), -999)
                if bar_idx - last >= COOLDOWN_BARS:
                    directions_to_test.append('long')
                    touch_counts[lkey] = touch_counts.get(lkey, 0) + 1
                    touch_counts[lkey + ('idx',)] = bar_idx

                # Short direction cooldown check
                skey = (trade_date_str, level_name, 'short')
                last = touch_counts.get(skey + ('idx',), -999)
                if bar_idx - last >= COOLDOWN_BARS:
                    directions_to_test.append('short')
                    touch_counts[skey] = touch_counts.get(skey, 0) + 1
                    touch_counts[skey + ('idx',)] = bar_idx

                if not directions_to_test:
                    continue

                approach = get_approach_direction(bars, bar_idx)

                for direction in directions_to_test:
                    result = simulate_trade(
                        bars, bar_idx, direction,
                        session_end, entry_price=level_price
                    )
                    all_trades.append({
                        'trade_date':  trade_date_str,
                        'timestamp':   timestamp,
                        'day_of_week': timestamp.strftime('%A'),
                        'hour':        timestamp.hour,
                        'level_name':  level_name,
                        'level_price': level_price,
                        'entry_price': level_price,
                        'approach':    approach,
                        'direction':   direction,
                        'outcome':     result['outcome'],
                        'ticks':       result['ticks'],
                        'mae':         result['mae'],
                        'bars_held':   result['bars_held']
                    })

        if (date_idx + 1) % 50 == 0:
            print(f"Processed {date_idx+1}/{len(dates)} days — "
                  f"{len(all_trades)} records so far")

    print(f"\nS/R backtest complete. Total records: {len(all_trades)}")
    return pd.DataFrame(all_trades) if all_trades else None

# ── Results Analysis ───────────────────────────────────────────────────────

def analyze_results(df):
    """Ranked summary by setup type and direction. Min 20 samples."""
    if df is None or df.empty:
        return None
    completed = df[df['outcome'] != 'timeout'].copy()
    if completed.empty:
        return None
    grouped = completed.groupby(
        ['session_type', 'level_type', 'direction']
    ).agg(
        total_trades   = ('outcome', 'count'),
        wins           = ('outcome', lambda x: (x == 'win').sum()),
        avg_mae        = ('mae', 'mean'),
        avg_bars       = ('bars_held', 'mean'),
        avg_confluence = ('confluence_count', 'mean')
    ).reset_index()
    grouped['win_rate'] = (
        grouped['wins'] / grouped['total_trades'] * 100
    ).round(1)
    grouped['avg_mae']  = grouped['avg_mae'].round(1)
    grouped['avg_bars'] = grouped['avg_bars'].round(0)
    grouped = grouped[grouped['total_trades'] >= 20]
    grouped = grouped.sort_values('win_rate', ascending=False)
    return grouped

def analyze_sr_results(df):
    """Ranked summary for S/R backtest by level name and direction."""
    if df is None or df.empty:
        return None
    completed = df[df['outcome'] != 'timeout'].copy()
    if completed.empty:
        return None
    grouped = completed.groupby(
        ['level_name', 'direction']
    ).agg(
        total_trades = ('outcome', 'count'),
        wins         = ('outcome', lambda x: (x == 'win').sum()),
        avg_mae      = ('mae', 'mean'),
        avg_bars     = ('bars_held', 'mean'),
    ).reset_index()
    grouped['win_rate'] = (
        grouped['wins'] / grouped['total_trades'] * 100
    ).round(1)
    grouped['avg_mae']  = grouped['avg_mae'].round(1)
    grouped['avg_bars'] = grouped['avg_bars'].round(0)
    grouped = grouped[grouped['total_trades'] >= 20]
    grouped = grouped.sort_values('win_rate', ascending=False)
    return grouped

def analyze_confluence(df, tolerance_ticks=4):
    """
    Compares win rates by confluence count.
    tolerance_ticks: how close levels must be to count as confluent.
    """
    if df is None or df.empty:
        return None

    completed = df[df['outcome'] != 'timeout'].copy()

    # Recalculate confluence count using the specified tolerance
    # The raw data has confluence_count based on 4-tick tolerance
    # We need to recount from the confluences column which stores
    # the actual list of confluent levels found at 4-tick tolerance
    # For wider tolerances we need to rerun from raw level distances
    # So we use the stored confluence data as-is for the 4-tick case
    # and note that for other tolerances we need the full recalculation

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
    grouped['avg_mae'] = grouped['avg_mae'].round(1)
    grouped = grouped[grouped['total_trades'] >= 20]
    grouped = grouped.sort_values(['direction', 'confluence_count'])
    return grouped

def run_confluence_sweep(tolerances_ticks=[4, 6, 8, 10]):
    """
    Tests multiple confluence tolerances to find the optimal setting.
    For each tolerance reruns confluence calculation against all trades
    and measures the win rate gap between 0-confluence and 1-confluence.
    The optimal tolerance produces the largest gap.
    
    Only analyzes LONG entries with BEARISH approach on PREVIOUS DAY levels
    since these are our top 3 setups.
    """
    print("\n" + "="*60)
    print("CONFLUENCE TOLERANCE SWEEP")
    print("Testing tolerances:", tolerances_ticks, "ticks")
    print("Filter: previous_day levels, bearish approach, long only")
    print("="*60)

    # Load raw trades
    try:
        df = pd.read_csv('backtest/trades_raw.csv')
    except FileNotFoundError:
        print("trades_raw.csv not found. Run backtest first.")
        return None

    # Filter to our top 3 setups only
    filtered = df[
        (df['session_type'] == 'previous_day') &
        (df['approach'] == 'bearish') &
        (df['direction'] == 'long') &
        (df['outcome'] != 'timeout')
    ].copy()

    print(f"\nFiltered trades (PD bearish long): {len(filtered)}")
    print()

    # Get all trading dates and levels needed for recalculation
    dates = filtered['trade_date'].unique()

    results = []

    for tolerance_ticks in tolerances_ticks:
        tolerance_points = tolerance_ticks * 0.25

        # Recalculate confluence count for each trade
        # using the specified tolerance
        recalc_counts = []

        for _, trade in filtered.iterrows():
            trade_date = trade['trade_date']
            touched_session = trade['session_type']
            touched_type = trade['level_type']
            level_price = trade['level_price']

            # Get all levels for this date
            levels = get_levels_for_date(trade_date)
            if not levels:
                recalc_counts.append(0)
                continue

            # Count confluences at this tolerance
            count = 0
            for session_type, session_levels in levels.items():
                for level_type, lp in session_levels.items():
                    if session_type == touched_session and level_type == touched_type:
                        continue
                    if abs(level_price - lp) <= tolerance_points:
                        count += 1
            recalc_counts.append(count)

        filtered['recalc_confluence'] = recalc_counts

        # Calculate win rates by confluence count
        completed = filtered.copy()
        grouped = completed.groupby('recalc_confluence').agg(
            trades = ('outcome', 'count'),
            wins   = ('outcome', lambda x: (x == 'win').sum())
        ).reset_index()
        grouped['win_rate'] = (grouped['wins'] / grouped['trades'] * 100).round(1)
        grouped = grouped[grouped['trades'] >= 20]

        # Get 0-confluence and 1-confluence win rates
        zero_conf = grouped[grouped['recalc_confluence'] == 0]
        one_conf  = grouped[grouped['recalc_confluence'] == 1]
        two_conf  = grouped[grouped['recalc_confluence'] == 2]

        zero_wr = zero_conf['win_rate'].values[0] if len(zero_conf) > 0 else None
        one_wr  = one_conf['win_rate'].values[0]  if len(one_conf) > 0  else None
        two_wr  = two_conf['win_rate'].values[0]  if len(two_conf) > 0  else None

        zero_n = int(zero_conf['trades'].values[0]) if len(zero_conf) > 0 else 0
        one_n  = int(one_conf['trades'].values[0])  if len(one_conf) > 0  else 0
        two_n  = int(two_conf['trades'].values[0])  if len(two_conf) > 0  else 0

        gap = (one_wr - zero_wr) if (one_wr and zero_wr) else None

        results.append({
            'tolerance_ticks':  tolerance_ticks,
            'tolerance_points': tolerance_points,
            'zero_conf_wr':     zero_wr,
            'zero_conf_n':      zero_n,
            'one_conf_wr':      one_wr,
            'one_conf_n':       one_n,
            'two_conf_wr':      two_wr,
            'two_conf_n':       two_n,
            'gap_0_to_1':       gap
        })

        print(f"Tolerance: {tolerance_ticks} ticks ({tolerance_points} points)")
        print(f"  0 confluences: {zero_wr}% ({zero_n} trades)")
        print(f"  1 confluence:  {one_wr}% ({one_n} trades)")
        print(f"  2 confluences: {two_wr}% ({two_n} trades)")
        if gap:
            print(f"  Gap (0->1):    +{gap:.1f}%")
        print()

    # Summary table
    print("="*60)
    print("SUMMARY — Gap between 0-confluence and 1-confluence win rate")
    print("(Larger gap = better signal from confluence)")
    print("="*60)
    print(f"{'Tolerance':>12} {'0-conf%':>8} {'1-conf%':>8} {'Gap':>8} {'Optimal?':>10}")
    print("-"*50)

    best_gap = max([r['gap_0_to_1'] for r in results if r['gap_0_to_1'] is not None])

    for r in results:
        gap_str = f"+{r['gap_0_to_1']:.1f}%" if r['gap_0_to_1'] else "N/A"
        optimal = "<-- BEST" if r['gap_0_to_1'] == best_gap else ""
        zero_str = f"{r['zero_conf_wr']}%" if r['zero_conf_wr'] else "N/A"
        one_str  = f"{r['one_conf_wr']}%"  if r['one_conf_wr']  else "N/A"
        print(f"{r['tolerance_ticks']:>10}t {zero_str:>8} {one_str:>8} {gap_str:>8} {optimal:>10}")

    print()
    best = max(results, key=lambda x: x['gap_0_to_1'] if x['gap_0_to_1'] else 0)
    print(f"Recommended tolerance: {best['tolerance_ticks']} ticks ({best['tolerance_points']} points)")

    return results

def analyze_approach(df):
    """Win rates by approach direction and level type."""
    if df is None or df.empty:
        return None
    completed = df[df['outcome'] != 'timeout'].copy()
    grouped = completed.groupby(
        ['direction', 'approach', 'level_type']
    ).agg(
        total_trades = ('outcome', 'count'),
        wins         = ('outcome', lambda x: (x == 'win').sum()),
        avg_mae      = ('mae', 'mean')
    ).reset_index()
    grouped['win_rate'] = (
        grouped['wins'] / grouped['total_trades'] * 100
    ).round(1)
    grouped['avg_mae'] = grouped['avg_mae'].round(1)
    grouped = grouped[grouped['total_trades'] >= 20]
    grouped = grouped.sort_values('win_rate', ascending=False)
    return grouped

def analyze_by_day(df):
    """Win rates by day of week."""
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
    grouped = grouped[grouped['total_trades'] >= 10]
    grouped = grouped.sort_values('win_rate', ascending=False)
    return grouped

def print_summary(df, label):
    """Prints win/loss summary for any results dataframe."""
    completed = df[df['outcome'] != 'timeout']
    wins      = (completed['outcome'] == 'win').sum()
    losses    = (completed['outcome'] == 'loss').sum()
    timeouts  = (df['outcome'] == 'timeout').sum()
    overall   = wins / len(completed) * 100 if len(completed) > 0 else 0
    print(f"\n{label} SUMMARY:")
    print(f"  Total records:    {len(df)}")
    print(f"  Completed trades: {len(completed)}")
    print(f"  Wins:             {wins}")
    print(f"  Losses:           {losses}")
    print(f"  Timeouts:         {timeouts}")
    print(f"  Overall win rate: {overall:.1f}%")

# ── Entry Point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*60)
    print("CONFLUENCE TOLERANCE SWEEP")
    print("="*60)
    run_confluence_sweep(tolerances_ticks=[4, 6, 8, 10, 12])

    # ── Volume Profile Backtest ──
    vp_trades = run_backtest()

    if vp_trades is not None:
        vp_trades.to_csv('backtest/trades_raw.csv', index=False)
        print("Raw VP trades saved to backtest/trades_raw.csv")

        print("\n" + "="*60)
        print("VP RESULTS BY SETUP TYPE AND DIRECTION")
        print("="*60)
        results = analyze_results(vp_trades)
        if results is not None:
            print(results.to_string(index=False))

        print("\n" + "="*60)
        print("VP CONFLUENCE ANALYSIS")
        print("="*60)
        confluence = analyze_confluence(vp_trades)
        if confluence is not None:
            print(confluence.to_string(index=False))

        print("\n" + "="*60)
        print("VP APPROACH DIRECTION ANALYSIS")
        print("="*60)
        approach = analyze_approach(vp_trades)
        if approach is not None:
            print(approach.to_string(index=False))

        print("\n" + "="*60)
        print("VP DAY OF WEEK ANALYSIS")
        print("="*60)
        by_day = analyze_by_day(vp_trades)
        if by_day is not None:
            print(by_day.head(20).to_string(index=False))

        print_summary(vp_trades, "VOLUME PROFILE")

    # ── S/R Backtest ──
    print("\n\n" + "="*60)
    sr_trades = run_sr_backtest()

    if sr_trades is not None:
        sr_trades.to_csv('backtest/sr_trades_raw.csv', index=False)
        print("Raw S/R trades saved to backtest/sr_trades_raw.csv")

        print("\n" + "="*60)
        print("S/R RESULTS BY LEVEL AND DIRECTION")
        print("="*60)
        sr_results = analyze_sr_results(sr_trades)
        if sr_results is not None:
            print(sr_results.to_string(index=False))

        print_summary(sr_trades, "SIMPLE S/R")

    # ── Side by Side Comparison ──
    if vp_trades is not None and sr_trades is not None:
        vp_completed = vp_trades[vp_trades['outcome'] != 'timeout']
        sr_completed = sr_trades[sr_trades['outcome'] != 'timeout']

        vp_wr = (vp_completed['outcome'] == 'win').sum() / len(vp_completed) * 100
        sr_wr = (sr_completed['outcome'] == 'win').sum() / len(sr_completed) * 100

        print("\n" + "="*60)
        print("SIDE BY SIDE COMPARISON")
        print("="*60)
        print(f"  Volume Profile win rate: {vp_wr:.1f}%")
        print(f"  Simple S/R win rate:     {sr_wr:.1f}%")
        print(f"  VP edge over S/R:        {vp_wr - sr_wr:+.1f}%")
        print()
        if vp_wr - sr_wr > 5:
            print("  Volume profile adds meaningful edge over simple S/R")
        elif vp_wr - sr_wr > 2:
            print("  Volume profile adds modest edge over simple S/R")
        else:
            print("  Volume profile and simple S/R perform similarly")