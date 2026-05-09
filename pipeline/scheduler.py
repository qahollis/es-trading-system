# scheduler.py
# Runs the daily pipeline automatically at scheduled times
# 5:45pm Eastern — previous day and previous week levels
# 9:35am Eastern — previous overnight levels after session closes

import schedule
import time
import os
from datetime import datetime
from load import run_daily_pipeline

def job():
    """
    The job that runs at each scheduled time.
    Calls run_daily_pipeline() which handles all ETL steps.
    Wrapped in try/except so a failure does not stop the scheduler.
    """
    print(f"\nScheduler triggered at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        run_daily_pipeline()
    except Exception as e:
        print(f"Pipeline failed: {e}")
        print("Scheduler will continue running for next scheduled job.")

# Schedule the pipeline to run twice daily
# 17:45 = 5:45pm Eastern (use 24-hour format)
# 09:35 = 9:35am Eastern
schedule.every().day.at("17:45").do(job)
schedule.every().day.at("09:35").do(job)

print("Scheduler is running.")
print("Next runs scheduled for 9:35am and 5:45pm Eastern daily.")
print("Press Ctrl+C to stop.")

# Keep the scheduler alive — checks every 60 seconds for pending jobs
while True:
    schedule.run_pending()
    time.sleep(60)