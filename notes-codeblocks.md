# Code Blocks Reference
Building blocks for assembling Python scripts from scratch.
Think of these as puzzle pieces — combine them to build any script.

---

## Block 1 — Variable
**When to use:** Storing any value you will reference later.
**Template:**
name = value

**Real examples from this project:**
tick_size = 0.25
trade_date = "2026-04-17"
total_volume = 0
API_KEY = os.getenv("DATABENTO_API_KEY")

---

## Block 2 — Function
**When to use:** Any logic you will run more than once, or that
does one specific job clearly named.
**Template:**
def function_name(input):
    # do something with input
    result = input
    return result

**Real examples from this project:**
def get_yesterday():
    yesterday = date.today() - timedelta(days=1)
    return yesterday.isoformat()

def is_es_front_month(symbol):
    if pd.isna(symbol):
        return False
    return str(symbol).startswith('ES') and len(str(symbol)) == 4

---

## Block 3 — If Statement
**When to use:** Making a decision — do this OR do that based
on whether something is true.
**Template:**
if condition:
    # do this if true
else:
    # do this if false

**Real examples from this project:**
if df.empty:
    print("No data returned")
    return None

if df is None or df.empty:
    print("No data to transform.")
    return None

---

## Block 4 — For Loop
**When to use:** Doing the same operation on every item
in a list or every row in a dataset.
**Template:**
for item in collection:
    # do something with item

**Real examples from this project:**
for session_type, session_df in sessions.items():
    levels = calculate_volume_profile(session_df)

for i, filepath in enumerate(csv_files):
    rows = load_csv_to_db(filepath)

---

## Block 5 — Print Statement
**When to use:** Any time you want to see what is happening
inside your code. Use constantly while building and debugging.
**Template:**
print(f"Description: {variable}")

**Real examples from this project:**
print(f"Fetching ES data for {date_str}...")
print(f"  Raw rows received: {len(df)}")
print(f"  Processing {session_type}: {len(session_df)} bars")

---

## Block 6 — Try/Except (Error Handling)
**When to use:** Wrapping code that might fail — API calls,
file reads, database writes. Catches the error and handles
it gracefully instead of crashing.
**Template:**
try:
    # code that might fail
except Exception as e:
    print(f"Error: {e}")

**Real examples from this project:**
try:
    data = client.timeseries.get_range(...)
except Exception as e:
    print(f"Error fetching data: {e}")
    return None

---

## Block 7 — Import
**When to use:** At the top of every script. Loads the
libraries and tools your script needs.
**Template:**
import library_name
from library_name import specific_tool

**Real examples from this project:**
import pandas as pd
import databento as db
from datetime import datetime, timedelta, date
from dotenv import load_dotenv

---

## Block 8 — Database Query
**When to use:** Reading data from PostgreSQL into a DataFrame.
**Template:**
def get_data_from_db(engine, query):
    df = pd.read_sql(query, engine)
    if df.empty:
        return None
    return df

**Real example from this project:**
def get_session_bars(engine, start_date, end_date):
    query = f"""
        SELECT * FROM es_trades
        WHERE session_date >= '{start_date}'
        AND session_date <= '{end_date}'
    """
    df = pd.read_sql(query, engine)
    if df.empty:
        return None
    return df

## Block 9 — While Loop
**When to use:** When you need something to run continuously
until manually stopped. Different from a for loop which runs
a set number of times.
**Template:**
while True:
    do_something()
    time.sleep(60)  # wait 60 seconds before checking again

**Real example from this project:**
while True:
    schedule.run_pending()  # run any jobs that are due
    time.sleep(60)          # check again in 60 seconds

## Scheduler Pattern
import schedule
import time

def job():
    run_my_pipeline()

schedule.every().day.at("17:45").do(job)

while True:
    schedule.run_pending()
    time.sleep(60)

## Common Comparison Operators
= assignment (setting a value):     x = 5
== equality check (is it equal?):   if x == 5:
!= not equal:                       if x != 5:
>  greater than:                    if x > 0:
<  less than:                       if x < 10:
>= greater than or equal:           if x >= 5:
<= less than or equal:              if x <= 10:

---

## How to Assemble a Script

Every script follows this structure — fill in the blocks:

# 1. IMPORTS — what tools do I need?
import ...

# 2. CONFIGURATION — what settings does this script need?
API_KEY = ...
DB_URL = ...

# 3. FUNCTIONS — what are the reusable pieces of logic?
def do_something(input):
    ...
    return result

# 4. MAIN BLOCK — what runs when I execute this script?
if __name__ == "__main__":
    result = do_something(input)
    print(result)

    ## The 5 Framework Questions (In Code Order)

1. What tools do I need?
   → Imports (libraries, functions from other scripts)

2. What settings do those tools need?
   → Configuration (API keys, DB connections, fixed parameters,
     constants that do not change during the script's run)

3. What are the steps?
   → Functions (one function per step, each doing one job)

4. What could go wrong?
   → Error handling (try/except blocks, if df.empty checks,
     None guards, duplicate checks)

5. What is my output and how will I know it worked?
   → Return statements, database writes, print statements,
     validation queries

## Script Planning Template
Answer the framework before writing any code.
Answers become your script skeleton.

### Framework Answers
1. What tools do I need?
   imports:

2. What settings do those tools need?
   configuration:

3. What are the steps?
   functions needed:
   -
   -
   -

4. What could go wrong?
   error handling needed:
   -
   -

5. What is my output and how will I know it worked?
   output:
   validation:

---

### Script Skeleton (write this before any real code)

# ── Imports ────────────────────────────────────────────
# Q1: What tools do I need?


# ── Configuration ──────────────────────────────────────
# Q1 extended: What settings do those tools need?


# ── Functions ──────────────────────────────────────────
# Q3: What are the steps?

# def step_one(input):
#     """what this function does"""
#     # logic here
#     return output

# def step_two(input):
#     """what this function does"""
#     # try/except if this step could fail (Q4)
#     return output

# ── Main Block ─────────────────────────────────────────
# Q5: What is my output and how will I know it worked?

# if __name__ == "__main__":
#     result = step_one()
#     result = step_two(result)
#     print(f"Validation: {result}")  # confirm it worked

---

### Step 3 — Fill In the Blocks
Fill each section using your codeblocks as reference.
One function at a time. Test each function before moving
to the next.