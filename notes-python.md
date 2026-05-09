# Python Reference

## Project Setup
```python
# Always activate virtual environment before working
.\venv\Scripts\activate

# Install a library
pip install libraryname

# Check installed libraries
pip list
```

## Imports Used in This Project
```python
import os                          # access environment variables
import pandas as pd                # data manipulation
import requests                    # make API/HTTP calls
from datetime import datetime, timedelta  # date math
from dotenv import load_dotenv     # load .env file
from sqlalchemy import create_engine     # connect to PostgreSQL
from pathlib import Path           # handle file paths cleanly
```

## Loading Environment Variables
```python
from dotenv import load_dotenv
import os

load_dotenv()                           # reads your .env file
API_KEY = os.getenv("MY_API_KEY")      # retrieves a specific key
```

## Connecting to PostgreSQL
```python
from sqlalchemy import create_engine

DB_URL = "postgresql://postgres:PASSWORD@localhost:5432/es_trading"
engine = create_engine(DB_URL)
```

## Reading a CSV into a DataFrame
```python
import pandas as pd

df = pd.read_csv("filepath.csv")
print(df.head())        # shows first 5 rows
print(len(df))          # shows row count
df.printSchema          # shows column names and types (PySpark)
df.dtypes               # shows column types (Pandas)
```

## Filtering a DataFrame
```python
# Keep only rows where symbol starts with ES
df = df[df['symbol'].str.startswith('ES')]

# Keep only rows where volume is greater than 0
df = df[df['volume'] > 0]

# Apply a custom function to filter
df = df[df['symbol'].apply(my_function)]
```

## Converting Timestamps
```python
# Convert UTC string to datetime
df['timestamp'] = pd.to_datetime(df['ts_event'], utc=True)

# Convert UTC to Eastern Time
df['timestamp'] = df['timestamp'].dt.tz_convert('America/New_York')

# Extract just the date from a timestamp
df['session_date'] = df['timestamp'].dt.date
```

## Writing a DataFrame to PostgreSQL
```python
df.to_sql('table_name', engine, if_exists='append', index=False)
# if_exists options:
# 'append' — adds rows to existing table
# 'replace' — drops table and recreates it
# 'fail' — throws error if table exists
```

## Defining a Function
```python
def my_function(parameter):
    """
    Docstring — explains what the function does.
    Always indent code inside the function with 4 spaces.
    """
    result = parameter * 2
    return result
```

## Looping Through Files in a Folder
```python
from pathlib import Path

folder = Path("data/my_folder")
for filepath in sorted(folder.iterdir()):
    print(filepath.name)
```

## Error Handling
```python
try:
    # code that might fail
    df = pd.read_csv(filepath)
except Exception as e:
    # what to do if it fails
    print(f"Error: {e}")
```

## f-strings (formatted strings)
```python
name = "Quentin"
count = 1558
print(f"Hello {name}, processing {count} files")
# Output: Hello Quentin, processing 1558 files
```

## If __name__ == "__main__"
```python
# This block only runs when you execute the file directly
# It does NOT run when the file is imported by another script
if __name__ == "__main__":
    run_backfill()
```

## File Paths
- Use forward slashes `/` in Python code — works on all operating systems
- Use backslashes `\` in PowerShell terminal commands
- Use `r"C:\path\to\file"` (raw string) when you must use backslashes in Python