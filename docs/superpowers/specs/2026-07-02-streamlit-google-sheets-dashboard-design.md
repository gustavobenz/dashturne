# Streamlit Google Sheets Dashboard Design

## Goal

Build a Streamlit dashboard that reads a Google Sheets worksheet named `Dados` through a Service Account, converts it to a Pandas DataFrame, and renders metrics, filters, charts, and a detailed data table. The app must be deployable on Render Starter without storing credentials in the repository.

## Required Files

- `app.py`: Streamlit application, Google Sheets integration, data normalization, validation, filters, metrics, charts, and error handling.
- `requirements.txt`: Python dependencies needed by Streamlit, Pandas, and the Google Sheets API client.
- `.gitignore`: Python, Streamlit, local environment, and secret files ignored by Git.
- `README.md`: Setup, local run, Google Cloud, Render, GitHub, and deploy instructions.
- `render.yaml`: Render Blueprint service configuration.

## Data Source

The app reads these environment variables:

- `GOOGLE_SERVICE_ACCOUNT_JSON`: full Service Account JSON as a string.
- `GOOGLE_SPREADSHEET_ID`: target Google Spreadsheet ID.

The app connects to the spreadsheet through Google Sheets API v4 and reads all values from the worksheet range `Dados`. The first row is treated as the header.

## Data Contract

Required columns:

- `data`
- `categoria`
- `descricao`
- `valor`

Optional filter columns:

- `item`
- `oferta`
- `metodo_pagamento`
- `cidade`

The dashboard must keep working when optional filter columns are absent. Required columns missing from the sheet are a blocking validation error shown in the UI.

## Data Normalization

- `data` is converted with `pd.to_datetime(..., errors="coerce", dayfirst=True)`.
- `valor` is converted to number with support for common Brazilian decimal formatting such as `1.234,56`.
- Rows with invalid `data` or `valor` remain visible in the detailed table, but they are excluded from date and numeric aggregations where Pandas naturally ignores missing values.
- Empty sheets, missing headers, and all-empty data bodies are treated as "planilha sem dados".

## Interface

The sidebar contains:

- Manual update button that clears Streamlit cache.
- Date range filter derived from valid values in `data`.
- Optional multiselect filters for `item`, `oferta`, `metodo_pagamento`, and `cidade` when the columns exist.
- A category multiselect for `categoria`.

The main dashboard contains:

- Total records after filters.
- Sum of `valor` after filters.
- Bar chart grouped by `categoria`.
- Line chart grouped by `data`.
- Detailed filtered table.

The UI should be clean, responsive, and use Streamlit's native layout primitives.

## Cache

The Google Sheets read function uses `st.cache_data` to avoid unnecessary API calls. The manual update button clears the cache and reruns the app.

## Error Handling

The UI must show clear messages for:

- Missing environment variables.
- Invalid Service Account JSON.
- Invalid credentials or Google API authentication failure.
- Spreadsheet unavailable or inaccessible.
- Worksheet `Dados` missing.
- Spreadsheet with no usable rows.
- Required columns absent.

## Deployment

Render uses the command:

```bash
streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
```

Secrets are configured only as Render environment variables. The repository must not contain the Service Account JSON, `.env`, or local Streamlit secrets files.

## Constraints

- Keep implementation in a single `app.py` because this is a small deployable dashboard.
- Use reusable functions and type hints.
- Use objective comments only where they clarify non-obvious parsing or API behavior.
- Do not add authentication or database storage; the app only reads Google Sheets.
