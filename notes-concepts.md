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