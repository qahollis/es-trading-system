# Terminal Commands Reference

## Navigation
- `cd foldername` — Change Directory. Moves you into a folder. Think of it like double-clicking a folder in File Explorer except you stay in the terminal.
- `cd ..` — Moves you one level up. If you are in `pipeline` this takes you back to `es-trading-system`.
- `ls` — List. Shows everything in your current folder — files and subfolders. Your equivalent of opening a folder in File Explorer and seeing what is inside.
- `ls filename` — checks a file in your current folder
- `ls subfolder\filename` — checks a file inside a subfolder
- `ls subfolder` — lists all contents of a subfolder
- `pwd` — Print Working Directory. Shows you exactly where you currently are in the folder structure. Useful when you are lost.
- `code .` — opens VS Code in the current terminal folder

## File and Folder Management
- `mkdir foldername` — Make Directory. Creates a new folder.
- `move source destination` — Moves a file or folder from one location to another.
- `Remove-Item filename` — Deletes a file. Add `-Force` to override protection. Add `-Recurse` to delete a folder and everything inside it.
- `copy source destination` — Copies a file without removing the original.
- `type filename` — Prints the contents of a file directly in the terminal. Useful for quickly checking what is inside a small file like your `.env`.
`New-Item filename` - Creates a new empty file in the current directory
`New-Item filename1, filename2` - Creates multiple new files at once

## Python
- `python filename.py` — Runs a Python script.
- `python` — Opens an interactive Python session where you can type Python code line by line.
- `exit()` — Exits the interactive Python session.
- `pip install libraryname` — Downloads and installs a Python library into your active environment.
- `pip list` — Shows all libraries currently installed in your active environment.

## Virtual Environment
- `.\venv\Scripts\activate` — Activates your virtual environment. Always run this first when opening a new terminal session.
- `deactivate` — Exits the virtual environment and returns to global Python.

## PostgreSQL
- `psql -U postgres` — Connects to PostgreSQL as the postgres user.
- `\dt` — List Tables. Shows all tables in the current database.
- `\l` — List all databases.
- `\c databasename` — Connect to a specific database.
- `\q` — Quit psql.

## Git / GitHub
- `git add .` — stages all changed files for commit
- `git status` — shows what is staged and what is not
- `git commit -m "message"` — saves a snapshot with a description
- `git push` — uploads commits to GitHub
- `git pull` — downloads latest changes from GitHub to local machine
- `git log` — shows commit history
- `git branch` — shows current branch

## Typical End of Session Workflow
1. git add .
2. git status  (confirm what is being committed)
3. git commit -m "description of what you built"
4. git push