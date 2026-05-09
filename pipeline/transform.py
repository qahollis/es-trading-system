# transform.py
# Calculates VAH, POC, and VAL for each session window
# Input: clean DataFrame of OHLCV bars from extract.py
# Output: DataFrame of volume profile levels ready for database storage

import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

# ── Session Window Definitions ──────────────────────────────────────────────
# These match your exact trading session definitions

def filter_overnight(df, trade_date):
    """
    Previous Overnight session: 6pm Eastern the day before trade_date
    to 9:30am Eastern on trade_date.

    When sitting down to trade on April 22 evening, the reference
    overnight session is the completed April 21 overnight
    (6pm April 21 to 9:30am April 22).

    The live developing session is tracked separately on the chart
    and is never stored by this pipeline.
    """
    trade_dt = pd.Timestamp(trade_date, tz=EASTERN)
    start = (trade_dt - pd.Timedelta(days=1)).replace(hour=18, minute=0)
    end   = trade_dt.replace(hour=9, minute=30)
    return df[(df['timestamp'] >= start) & (df['timestamp'] < end)]

def filter_previous_day(df, trade_date):
    """
    Previous Day RTH: 9:30am to 4pm Eastern on trade_date.
    When you sit down to trade the April 17 overnight session at 6:30pm,
    your Previous Day levels come from April 17 RTH (9:30am-4pm same day).
    """
    start = pd.Timestamp(trade_date, tz=EASTERN).replace(hour=9, minute=30)
    end   = pd.Timestamp(trade_date, tz=EASTERN).replace(hour=16, minute=0)
    return df[(df['timestamp'] >= start) & (df['timestamp'] < end)]

def filter_previous_week(df, trade_date):
    """
    Previous Week: Sunday 6pm to Friday 5pm of the most recently
    completed week.
    Example: trade_date any day in week of April 13-19 →
    returns bars from Sunday April 6 6pm to Friday April 11 5pm.
    """
    ref = pd.Timestamp(trade_date, tz=EASTERN)

    # Find the most recent Friday that is fully completed
    # weekday(): Monday=0, Tuesday=1, Wednesday=2, Thursday=3,
    #            Friday=4, Saturday=5, Sunday=6
    days_since_monday = ref.weekday()

    # Find this week's Monday then go back to get last week's Friday
    this_monday = ref - pd.Timedelta(days=days_since_monday)
    last_friday = this_monday - pd.Timedelta(days=3)
    last_sunday = last_friday - pd.Timedelta(days=5)

    start = last_sunday.replace(hour=18, minute=0)
    end   = last_friday.replace(hour=17, minute=0)

    return df[(df['timestamp'] >= start) & (df['timestamp'] < end)]

# ── Volume Profile Calculator ────────────────────────────────────────────────

def calculate_volume_profile(df, tick_size=0.25):
    """
    Calculates VAH, POC, and VAL from a DataFrame of OHLCV bars.

    How it works:
    1. Round each bar's close price to the nearest tick
    2. Sum all volume traded at each price level
    3. Find the price with most volume — that is the POC
    4. Expand outward from POC until 70% of volume is captured
    5. The range covered is the Value Area — top is VAH, bottom is VAL

    tick_size=0.25 because one ES tick = $12.50 (0.25 index points)
    """
    if df is None or df.empty:
        return None

    df = df.copy()

    # Round close price to nearest tick to create price buckets
    df['price_bucket'] = (df['close'] / tick_size).round() * tick_size

    # Sum volume at each price bucket — this builds the profile
    profile = df.groupby('price_bucket')['volume'].sum().sort_index()

    if profile.empty:
        return None

    total_volume = profile.sum()
    target_volume = total_volume * 0.70  # Value Area = 70% of total volume

    # POC = price level with the highest volume
    poc = float(profile.idxmax())

    # Expand outward from POC to find Value Area boundaries
    prices = profile.index.tolist()
    poc_idx = prices.index(poc)
    upper = poc_idx
    lower = poc_idx
    accumulated = float(profile[poc])

    while accumulated < target_volume:
        upper_vol = float(profile[prices[upper + 1]]) if upper + 1 < len(prices) else 0
        lower_vol = float(profile[prices[lower - 1]]) if lower - 1 >= 0 else 0

        if upper_vol >= lower_vol and upper + 1 < len(prices):
            upper += 1
            accumulated += upper_vol
        elif lower - 1 >= 0:
            lower -= 1
            accumulated += lower_vol
        else:
            break

    return {
        'poc': round(poc, 2),
        'vah': round(float(prices[upper]), 2),
        'val': round(float(prices[lower]), 2),
        'total_volume': int(total_volume)
    }

# ── Main Transform Function ──────────────────────────────────────────────────

def transform(df, trade_date):
    """
    Takes a full day DataFrame from extract.py and calculates
    volume profile levels for all three session windows.

    Returns a DataFrame with one row per session type containing
    VAH, POC, VAL, and total volume — ready for database storage.
    """
    if df is None or df.empty:
        print("No data to transform.")
        return None

    # Ensure timestamps are timezone-aware Eastern Time
    if df['timestamp'].dt.tz is None:
        df['timestamp'] = df['timestamp'].dt.tz_localize(EASTERN)
    else:
        df['timestamp'] = df['timestamp'].dt.tz_convert(EASTERN)

    # Define the three session windows to calculate
    sessions = {
        'previous_overnight': filter_overnight(df, trade_date),
        'previous_day':       filter_previous_day(df, trade_date),
        'previous_week':      filter_previous_week(df, trade_date),
    }

    results = []

    for session_type, session_df in sessions.items():
        print(f"  Processing {session_type}: {len(session_df)} bars")

        levels = calculate_volume_profile(session_df)

        if levels:
            results.append({
                'session_date': trade_date,
                'session_type': session_type,
                'vah':          levels['vah'],
                'poc':          levels['poc'],
                'val':          levels['val'],
                'total_volume': levels['total_volume']
            })
            print(f"    VAH: {levels['vah']}  POC: {levels['poc']}  VAL: {levels['val']}")
        else:
            print(f"    No levels calculated — insufficient data")

    if not results:
        print("No levels calculated for any session.")
        return None

    return pd.DataFrame(results)


if __name__ == "__main__":
    # Test overnight filter only — previous day and week
    # require database queries handled by load.py
    import sys
    sys.path.insert(0, 'pipeline')
    from extract import fetch_es_data

    print("Running overnight filter test for 2026-04-16...")
    raw_df = fetch_es_data("2026-04-16")
    if raw_df is not None:
        # Test overnight filter specifically
        overnight_bars = filter_overnight(raw_df, "2026-04-16")
        print(f"Overnight bars: {len(overnight_bars)}")
        if not overnight_bars.empty:
            print(f"First bar: {overnight_bars['timestamp'].min()}")
            print(f"Last bar:  {overnight_bars['timestamp'].max()}")

        # Test previous day filter
        prev_day_bars = filter_previous_day(raw_df, "2026-04-16")
        print(f"Previous day bars: {len(prev_day_bars)}")
        if not prev_day_bars.empty:
            print(f"First bar: {prev_day_bars['timestamp'].min()}")
            print(f"Last bar:  {prev_day_bars['timestamp'].max()}")