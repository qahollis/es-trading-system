# backfill_levels.py
# Calculates and stores volume profile levels for a range of historical dates
# Run this once to populate the volume_profile_levels table
# before running the backtest

from datetime import date, timedelta
from load import run_daily_pipeline

start = date(2024, 1, 2)
end   = date(2026, 4, 30)

current = start
total_days = 0

while current <= end:
    if current.weekday() < 5:
        print(f"\n{'='*40}")
        run_daily_pipeline(current.isoformat())
        total_days += 1
    current += timedelta(days=1)

print(f"\nLevels backfill complete. Processed {total_days} trading days.")