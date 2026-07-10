# MünzApp

A Euro coin collection tracker built with Flask. Displays an interactive spreadsheet-style table of Euro coins by country and denomination, backed by an Excel file.

## Stack

- **Backend:** Python / Flask
- **Excel parsing:** openpyxl
- **Data:** `Date Run Mai2026.xlsx` (project root) + `muenzapp/data.json` (user overrides/edits)
- **Port:** 8081

## How to run

```bash
python muenzapp/app.py
```

The app loads the Excel file on startup (takes a few seconds), then serves on `http://0.0.0.0:8081`.

## Project structure

```
muenzapp/
  app.py        # Flask app — reads Excel, generates HTML, handles API routes
  data.json     # User overrides, cell types, mintage data, undo stack
Date Run Mai2026.xlsx  # Main coin data spreadsheet
```

## Features

- Interactive coin table with edit mode
- Right-click context menu to mark cells (have, NIFC, ✕, etc.)
- Undo support
- Add extension years per country
- Mintage data fetched from Google Sheets (Austria, Italy)
- Export to PDF or Excel

## User preferences

<!-- Add preferences here as needed -->
