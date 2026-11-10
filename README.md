# CensusTrack

CensusTrack is a desktop dashboard for managing census enumeration districts,
enumeration blocks, and household survey records. It uses Python's built-in
Tkinter GUI toolkit and a local SQLite database.

## Features

- View combined census records and browse each of the three database tables.
- Add a census entry, creating its district when needed, a new enumeration
	block, and a household record in one transaction.
- Delete districts, blocks, or individual records. Deleting a district or
	block cascades to its dependent rows.
- Review district, block, and record totals in the dashboard.
- Validate submitted fields and numeric values, and check SQLite database and
	foreign-key integrity at startup.
- Create a sample dataset automatically when all three tables are empty.

## Database Schema

The application creates `censustrack.db` beside `censustrack.py` on first run.
Its schema consists of:

### `survey_districts`

- Columns: `district_id` (primary key), `district_name` (unique), `contact_email`
- Parent table for enumeration blocks.

### `enumeration_blocks`

- Columns: `block_id` (primary key), `district_id`, `block_identifier`, `enumeration_date`
- `district_id` references `survey_districts.district_id` with cascading deletes.

### `household_records`

- Columns: `record_id` (primary key), `block_id`, `record_type`, `recorded_value`
- `block_id` references `enumeration_blocks.block_id` with cascading deletes.

Foreign-key enforcement is enabled for application connections. The interface
validates recorded values as finite, non-negative numbers before saving them.

## Requirements

- Python 3
- Tkinter and SQLite support for that Python installation (both are commonly
	included with Python; some Linux distributions package Tkinter separately)
- A graphical desktop session to display the application window

No third-party Python packages are required.

## Run

From the project directory, run:

```bash
python3 censustrack.py
```

The database is created in the project directory if it does not exist. Keep
`censustrack.db` to preserve application data; it is generated locally and is
excluded from Git by the project `.gitignore`.
