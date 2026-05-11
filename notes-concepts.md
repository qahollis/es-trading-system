# Data Engineering Concepts Reference

## Core Concepts

### Pipeline
A series of automated steps that moves data from one place to another 
while transforming it along the way. Like an NFL play — once you build 
it, it runs the same way every time without you on the field.

### ETL
Extract, Transform, Load — the three steps every data pipeline follows.
- **Extract** — pull raw data from a source (Databento API)
- **Transform** — process it into something useful (calculate VAH/POC/VAL)
- **Load** — write the finished output to a destination (PostgreSQL)

### API (Application Programming Interface)
A door a company opens so other software can request their data 
programmatically. Instead of visiting a website manually, your code 
sends a request and gets data back automatically.

### DataFrame
Pandas' core data structure — think of it as a spreadsheet in memory. 
Columns are named, rows are indexed, and you can filter, transform, 
and aggregate with a single line of code.

### Database
A structured place to store and query data. Like Excel but stores 
millions of rows, multiple programs can read it simultaneously, and 
you can query it in milliseconds with SQL.

### Schema
The structure of a database — defines what tables exist, what columns 
each table has, and what data types each column accepts. Like designing 
the column headers of a spreadsheet before entering any data.

### Primary Key
A column that uniquely identifies every row in a table. No two rows 
can share the same value. Like a jersey number — every player has one 
and no two players share the same number.

### Virtual Environment
An isolated Python installation specific to one project. Every project 
gets its own set of libraries so they never conflict with each other. 
Like a dedicated locker room for each sport a player is on.

### Library / Package
Pre-built tools written by other engineers that you import and use. 
Instead of building tools from scratch you download proven ones. Like 
going to Lowe's instead of forging your own hammer.

### Scheduler
A system that runs your pipeline automatically at a set time without 
you doing anything. Like setting a DVR — you configure it once and it 
records every day automatically.

### Volume Profile
A frequency distribution of traded volume across price levels over a 
defined time period. The POC is the price where the most contracts 
traded. The Value Area contains 70% of all volume. Like a shot chart 
in basketball — the POC is the spot on the floor where the most shots 
were taken.

### OHLCV
Open, High, Low, Close, Volume — the five pieces of data describing 
what happened during one time period on a price chart. Every candle 
on your chart is built from these five numbers.

### POC (Point of Control)
The price level with the highest volume traded during a session. Acts 
as a magnet — price tends to return to where the most business was done.

### VAH (Value Area High)
The top price boundary of the Value Area — the range containing 70% 
of session volume.

### VAL (Value Area Low)
The bottom price boundary of the Value Area.

### Continuous Contract
A stitched-together futures price series that rolls from one expiring 
contract to the next. Used for historical backtesting so you have one 
clean price series instead of gaps between contract months.

### Front Month Contract
The nearest-to-expiration futures contract that is actively traded. 
ES contracts use codes: H (March), M (June), U (September), Z (December).

### UTC (Coordinated Universal Time)
The global time standard. Financial data is often stored in UTC to 
avoid timezone confusion. Your pipeline converts UTC to Eastern Time 
to match your session windows.

## Data Types in PostgreSQL
- `SERIAL` — auto-incrementing integer (used for ID columns)
- `TIMESTAMPTZ` — timestamp with timezone information
- `NUMERIC(10,2)` — decimal number with up to 10 digits and 2 decimal places (use for price data — never use FLOAT for financial data)
- `INTEGER` — whole number (used for volume)
- `VARCHAR(20)` — text up to 20 characters
- `DATE` — date only, no time component
- `NOT NULL` — field is required, cannot be empty

## How to Think Through Writing a Script
1. What is my input?      (files, API data, database query)
2. What is my output?     (database rows, CSV, printed result)
3. What are the steps?    (plain English first, always)
4. What could go wrong?   (empty files, wrong format, bad data)
5. How will I know it worked? (print statements, row counts)

### .gitignore
A file that tells git which files and folders to never track or upload.
Always create this before your first commit. Critical for keeping 
passwords, API keys, and large data files off GitHub.

### Separation of Concerns
A design principle where each script or function does exactly one thing.
Extract.py fetches data. Transform.py calculates levels. Load.py writes 
to the database. Keeping these separate makes each piece easier to 
debug, test, and reuse independently.

### Hardcoding vs Dynamic Values
Never hardcode dates, file paths, or values that change over time into 
your scripts. Calculate them programmatically so the script works 
correctly every time it runs without modification.

### Row Count Assertion
A data quality check that verifies a dataset contains an expected 
number of rows. If a pipeline pulls significantly fewer rows than 
expected it may indicate missing data, an API issue, or a session 
boundary problem. Used professionally in dbt tests and pipeline 
monitoring.

### Using the Right Data Source
Not all data needs to come from the same place. New data comes from 
the API. Historical data comes from the database. A well-designed 
pipeline uses each source for what it is best suited for — APIs for 
fresh data, databases for stored historical data.

### How Engineers Find Functions They Don't Know
1. Know what you want to accomplish in plain English
2. Search: "pandas [what you want to do]" or "python [what you want to do]"
3. Read the first 2-3 results and find the pattern
4. Adapt the example to your specific situation
Common searches used in this project:
- "pandas read sql database"
- "pandas write dataframe to postgresql"
- "python convert timezone pandas"
- "databento get historical data python"

## How to Know What Goes in Parentheses
Every function has a signature that defines its inputs:

def function_name(required_input, optional_input=default_value):

- Required inputs: must be provided or Python throws an error
- Optional inputs: have a default value, can be skipped
- To find what a function needs: search "pandas read_sql documentation"
  or hover over the function name in VS Code — it shows a tooltip
  with the full signature

Example — pd.read_sql needs:
1. sql: the query string
2. con: the database connection (engine)
These are required. Everything else is optional.

### Database Engine (SQLAlchemy)
The engine is a database connection object — like a key card that 
gives your Python code access to PostgreSQL. Created once at the 
top of a script and passed to any function that needs database access.

engine = create_engine("postgresql://username:password@host:port/database")

The connection string format:
- postgresql:// — database type
- username:password — your credentials  
- localhost — server address (your machine for local databases)
- 5432 — default PostgreSQL port
- /database_name — which database to connect to

### Logging vs Print
print() — outputs to terminal only, disappears when terminal closes.
logging — outputs to terminal AND writes to a persistent log file.
Use print() while building and debugging.
Replace with logging when the pipeline is ready for production.

Log levels (in order of severity):
- logging.info()    — normal operational messages
- logging.warning() — something unexpected but not critical
- logging.error()   — something failed

Setup pattern (goes at top of every script):
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('logs/pipeline.log'),
        logging.StreamHandler()
    ]
)

### Trade Date vs Session Date (Futures)
session_date — the calendar date a bar physically occurred on
trade_date — the trading session the bar belongs to

Rule for ES futures:
- 6:00pm to 11:59pm → trade_date = same calendar date (overnight opens)
- 12:00am to 9:29am → trade_date = previous calendar date (still in overnight)
- 9:30am to 5:00pm → trade_date = same calendar date (RTH session)

Example:
Bar at 2:00am April 17 → session_date=April 17, trade_date=April 16
Bar at 2:00pm April 17 → session_date=April 17, trade_date=April 17

### Pipeline Orchestration Tools
Orchestration = scheduling and managing when pipeline steps run,
in what order, and what to do when something fails.

schedule library — simple Python scheduler for single scripts.
Good for: one script, runs once a day, local machine.
Used in: Project 1 daily pipeline.

Apache Airflow — enterprise orchestration platform.
Good for: multiple dependent tasks, complex schedules, 
production environments, team visibility into pipeline health.
Used in: Project 2 backtest engine.

Rule of thumb: use the simplest tool that solves the problem.
Adding Airflow complexity to a simple daily script is like 
hiring an NFL coaching staff to run a backyard pickup game.

### Backtesting
Running a trading strategy against historical data to measure its
performance before risking real money. A backtest answers:
"If I had followed these rules over the past 5 years, what would
have happened?"

Key metrics every backtest should output:
- Win rate: % of trades that hit target before stop
- Sample size: number of trades — must be large enough to be
  statistically meaningful (minimum 30, ideally 100+)
- Average MAE: how far price went against entry on winning trades
  (tells you if your stop is correctly sized)
- Average time to target: how long winning trades took to develop
- Expectancy: (win rate × avg winner) - (loss rate × avg loser)
  Must be positive for a strategy to be profitable long term

### Confluence
When two or more levels from different sessions align at or near
the same price. Example: Previous Day VAL at 5234.75 and Previous
Overnight POC at 5235.00 — these are stacked within 1 tick.
Confluence setups tend to produce stronger reactions because more
traders are watching the same level.

### Parameter Sensitivity Testing
Testing a backtest with different parameter values to see how 
sensitive the results are to your choices. Example: testing 
1-tick, 2-tick, and 3-tick entry tolerances to see which 
produces the most consistent win rate.

If results change dramatically with small parameter changes 
the strategy is fragile. If results are stable across a range 
of parameters the edge is more robust.

### Entry Tolerance (Backtesting)
The number of ticks price must come within a level to count 
as a setup. Set too tight — misses valid setups. Set too wide 
— includes noise. 2 ticks is a reasonable starting point for 
ES futures volume profile trading.

### Trade Direction at Volume Profile Levels
Simple rule (starting point):
- VAH touch → short (rejection from top of value area)
- POC touch → long (bounce from most accepted price)
- VAL touch → long (bounce from bottom of value area)

Limitation: direction should also consider broader market 
context — a POC in a downtrend may be a short entry not long.
Add directional context analysis as a backtest refinement.

