# SQL Reference

## PostgreSQL Connection
```bash
psql -U postgres          # connect as postgres user
\c es_trading             # switch to es_trading database
\dt                       # list all tables
\d tablename              # describe a table's columns
\q                        # quit
```

## Database and Table Creation
```sql
-- Create a database
CREATE DATABASE es_trading;

-- Create a table
CREATE TABLE volume_profile_levels (
    id            SERIAL PRIMARY KEY,
    session_date  DATE NOT NULL,
    session_type  VARCHAR(20) NOT NULL,
    vah           NUMERIC(10,2),
    poc           NUMERIC(10,2),
    val           NUMERIC(10,2),
    total_volume  INTEGER,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
```

## Basic Queries
```sql
-- Select all rows
SELECT * FROM volume_profile_levels;

-- Select specific columns
SELECT session_date, session_type, vah, poc, val
FROM volume_profile_levels;

-- Filter rows
SELECT * FROM volume_profile_levels
WHERE session_type = 'overnight';

-- Sort results
SELECT * FROM volume_profile_levels
ORDER BY session_date DESC;

-- Limit results
SELECT * FROM volume_profile_levels
ORDER BY session_date DESC
LIMIT 10;
```

## Useful Queries for This Project
```sql
-- Check how many rows are in a table
SELECT COUNT(*) FROM es_trades;

-- Check most recent data loaded
SELECT MAX(session_date) FROM es_trades;

-- Check oldest data loaded
SELECT MIN(session_date) FROM es_trades;

-- See levels for a specific date
SELECT * FROM volume_profile_levels
WHERE session_date = '2026-04-07'
ORDER BY session_type;

-- Check row counts by session type
SELECT session_type, COUNT(*)
FROM volume_profile_levels
GROUP BY session_type;
```

## Data Types
| Type | Use For | Example |
|---|---|---|
| SERIAL | Auto-increment IDs | 1, 2, 3... |
| TIMESTAMPTZ | Timestamps with timezone | 2026-04-07 18:00:00-05:00 |
| NUMERIC(10,2) | Price data | 5234.75 |
| INTEGER | Whole numbers | 1558 |
| VARCHAR(20) | Short text | 'overnight' |
| DATE | Date only | 2026-04-07 |
| BOOLEAN | True/False | TRUE |

## Important Rules
- Always end SQL statements with a semicolon `;`
- PostgreSQL commands starting with `\` are psql shortcuts, not SQL
- Use single quotes for text values: `WHERE type = 'overnight'`
- NUMERIC is safer than FLOAT for financial data — no rounding errors