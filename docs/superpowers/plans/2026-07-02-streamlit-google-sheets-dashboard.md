# Streamlit Google Sheets Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deployable Streamlit dashboard that reads Google Sheets data with a Service Account and renders filters, metrics, charts, and a detailed table.

**Architecture:** The app stays in one focused `app.py` with reusable functions for configuration, Google Sheets access, DataFrame normalization, validation, filtering, and rendering. `st.cache_data` wraps the sheet fetch, and the manual refresh button clears the cache. Render deployment uses environment variables for secrets and a Blueprint file for the web service.

**Tech Stack:** Python, Streamlit, Pandas, Google API Python Client, Google Auth, Render Starter.

---

## File Structure

- Create `app.py`: Streamlit app and all dashboard logic.
- Create `requirements.txt`: runtime dependencies.
- Create `.gitignore`: local, cache, virtualenv, and secret exclusions.
- Create `README.md`: setup and deployment guide.
- Create `render.yaml`: Render service command and environment placeholders.

### Task 1: Project Dependency And Ignore Files

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`

- [ ] **Step 1: Create dependencies**

Write `requirements.txt`:

```txt
streamlit>=1.36,<2
pandas>=2.2,<3
google-api-python-client>=2.137,<3
google-auth>=2.32,<3
```

- [ ] **Step 2: Create ignored files**

Write `.gitignore`:

```gitignore
__pycache__/
*.py[cod]
*.pyo
*.pyd
.Python
.venv/
venv/
env/
.env
.env.*
!.env.example
.streamlit/secrets.toml
.streamlit/config.toml
*.log
.pytest_cache/
.mypy_cache/
.ruff_cache/
.DS_Store
Thumbs.db
```

- [ ] **Step 3: Verify file creation**

Run:

```bash
python -m pip --version
```

Expected: command prints the installed pip version, confirming Python is available for the next tasks.

### Task 2: Core Streamlit App

**Files:**
- Create: `app.py`

- [ ] **Step 1: Write app structure, imports, constants, and custom exception**

Create `app.py` with imports, constants, and `DashboardError`:

```python
from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd
import streamlit as st
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


SHEET_NAME = "Dados"
REQUIRED_COLUMNS = {"data", "categoria", "descricao", "valor"}
OPTIONAL_FILTER_COLUMNS = ("item", "oferta", "metodo_pagamento", "cidade")
SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)


class DashboardError(Exception):
    """Expected user-facing dashboard error."""
```

- [ ] **Step 2: Add environment and credential helpers**

Append:

```python
def get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise DashboardError(f"Variavel de ambiente obrigatoria ausente: {name}.")
    return value


def load_service_account_credentials() -> Credentials:
    raw_credentials = get_required_env("GOOGLE_SERVICE_ACCOUNT_JSON")
    try:
        credentials_info: dict[str, Any] = json.loads(raw_credentials)
    except json.JSONDecodeError as exc:
        raise DashboardError(
            "GOOGLE_SERVICE_ACCOUNT_JSON nao contem um JSON valido."
        ) from exc

    try:
        return Credentials.from_service_account_info(
            credentials_info,
            scopes=list(SCOPES),
        )
    except (ValueError, TypeError, GoogleAuthError) as exc:
        raise DashboardError(
            "Credenciais da Service Account invalidas ou incompletas."
        ) from exc
```

- [ ] **Step 3: Add cached Google Sheets fetch**

Append:

```python
@st.cache_data(ttl=600, show_spinner="Carregando dados do Google Sheets...")
def fetch_sheet_values(spreadsheet_id: str, credentials_json: str) -> list[list[str]]:
    try:
        credentials_info: dict[str, Any] = json.loads(credentials_json)
        credentials = Credentials.from_service_account_info(
            credentials_info,
            scopes=list(SCOPES),
        )
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        response = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=SHEET_NAME)
            .execute()
        )
    except json.JSONDecodeError as exc:
        raise DashboardError(
            "GOOGLE_SERVICE_ACCOUNT_JSON nao contem um JSON valido."
        ) from exc
    except (ValueError, TypeError, GoogleAuthError) as exc:
        raise DashboardError(
            "Credenciais da Service Account invalidas ou incompletas."
        ) from exc
    except HttpError as exc:
        status = getattr(exc.resp, "status", None)
        if status == 404:
            raise DashboardError(
                "Planilha indisponivel, ID incorreto ou aba 'Dados' inexistente."
            ) from exc
        if status in {401, 403}:
            raise DashboardError(
                "Acesso negado. Verifique credenciais e compartilhamento da planilha."
            ) from exc
        raise DashboardError("Erro ao consultar a Google Sheets API.") from exc
    except Exception as exc:
        raise DashboardError("Planilha indisponivel no momento.") from exc

    values = response.get("values", [])
    if not values or len(values) < 2:
        raise DashboardError("Planilha sem dados na aba 'Dados'.")
    return values
```

- [ ] **Step 4: Add DataFrame conversion and validation**

Append:

```python
def normalize_column_name(column: object) -> str:
    return str(column).strip().lower()


def parse_brazilian_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None

    text = str(value).strip()
    if not text:
        return None

    text = text.replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def values_to_dataframe(values: list[list[str]]) -> pd.DataFrame:
    if not values or len(values) < 2:
        raise DashboardError("Planilha sem dados na aba 'Dados'.")

    headers = [normalize_column_name(column) for column in values[0]]
    rows = values[1:]
    if not any(headers) or not rows:
        raise DashboardError("Planilha sem dados na aba 'Dados'.")

    dataframe = pd.DataFrame(rows, columns=headers)
    dataframe = dataframe.dropna(how="all")
    if dataframe.empty:
        raise DashboardError("Planilha sem dados na aba 'Dados'.")

    missing_columns = REQUIRED_COLUMNS.difference(dataframe.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise DashboardError(f"Colunas obrigatorias ausentes: {missing}.")

    dataframe["data"] = pd.to_datetime(
        dataframe["data"],
        errors="coerce",
        dayfirst=True,
    )
    dataframe["valor"] = dataframe["valor"].apply(parse_brazilian_number)
    dataframe["valor"] = pd.to_numeric(dataframe["valor"], errors="coerce")

    return dataframe
```

- [ ] **Step 5: Add filtering helpers**

Append:

```python
def sorted_options(dataframe: pd.DataFrame, column: str) -> list[str]:
    if column not in dataframe.columns:
        return []
    values = dataframe[column].dropna().astype(str).str.strip()
    return sorted(value for value in values.unique() if value)


def apply_multiselect_filter(
    dataframe: pd.DataFrame,
    column: str,
    selected_values: list[str],
) -> pd.DataFrame:
    if not selected_values or column not in dataframe.columns:
        return dataframe
    return dataframe[dataframe[column].astype(str).isin(selected_values)]
```

- [ ] **Step 6: Add sidebar filters and dashboard rendering**

Append:

```python
def render_filters(dataframe: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filtros")

    valid_dates = dataframe["data"].dropna()
    filtered = dataframe.copy()

    if not valid_dates.empty:
        min_date = valid_dates.min().date()
        max_date = valid_dates.max().date()
        date_range = st.sidebar.date_input(
            "Periodo",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
            filtered = filtered[
                (filtered["data"].dt.date >= start_date)
                & (filtered["data"].dt.date <= end_date)
            ]

    category_options = sorted_options(dataframe, "categoria")
    selected_categories = st.sidebar.multiselect(
        "Categoria",
        options=category_options,
        default=[],
    )
    filtered = apply_multiselect_filter(filtered, "categoria", selected_categories)

    for column in OPTIONAL_FILTER_COLUMNS:
        if column in dataframe.columns:
            selected = st.sidebar.multiselect(
                column.replace("_", " ").title(),
                options=sorted_options(dataframe, column),
                default=[],
            )
            filtered = apply_multiselect_filter(filtered, column, selected)

    return filtered


def render_metrics(dataframe: pd.DataFrame) -> None:
    total_records = len(dataframe)
    total_value = dataframe["valor"].sum(skipna=True)

    col_records, col_value = st.columns(2)
    col_records.metric("Total de registros", f"{total_records:,}".replace(",", "."))
    col_value.metric("Soma de valores", f"R$ {total_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))


def render_charts(dataframe: pd.DataFrame) -> None:
    st.subheader("Valor por categoria")
    category_chart = (
        dataframe.dropna(subset=["valor"])
        .groupby("categoria", as_index=True)["valor"]
        .sum()
        .sort_values(ascending=False)
    )
    st.bar_chart(category_chart)

    st.subheader("Valor por data")
    line_chart = (
        dataframe.dropna(subset=["data", "valor"])
        .assign(data=lambda frame: frame["data"].dt.date)
        .groupby("data", as_index=True)["valor"]
        .sum()
        .sort_index()
    )
    st.line_chart(line_chart)


def render_table(dataframe: pd.DataFrame) -> None:
    st.subheader("Dados detalhados")
    display_dataframe = dataframe.copy()
    display_dataframe["data"] = display_dataframe["data"].dt.strftime("%d/%m/%Y")
    st.dataframe(display_dataframe, use_container_width=True, hide_index=True)
```

- [ ] **Step 7: Add main function**

Append:

```python
def load_dataframe() -> pd.DataFrame:
    spreadsheet_id = get_required_env("GOOGLE_SPREADSHEET_ID")
    credentials_json = get_required_env("GOOGLE_SERVICE_ACCOUNT_JSON")
    values = fetch_sheet_values(spreadsheet_id, credentials_json)
    return values_to_dataframe(values)


def main() -> None:
    st.set_page_config(
        page_title="Dashboard Google Sheets",
        page_icon="📊",
        layout="wide",
    )
    st.title("Dashboard Google Sheets")

    if st.sidebar.button("Atualizar dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    try:
        dataframe = load_dataframe()
    except DashboardError as exc:
        st.error(str(exc))
        st.stop()

    filtered_dataframe = render_filters(dataframe)

    if filtered_dataframe.empty:
        st.warning("Nenhum registro encontrado para os filtros selecionados.")
        st.stop()

    render_metrics(filtered_dataframe)
    render_charts(filtered_dataframe)
    render_table(filtered_dataframe)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run syntax verification**

Run:

```bash
python -m py_compile app.py
```

Expected: command exits successfully without output.

### Task 3: Render Configuration

**Files:**
- Create: `render.yaml`

- [ ] **Step 1: Create Render Blueprint**

Write `render.yaml`:

```yaml
services:
  - type: web
    name: streamlit-google-sheets-dashboard
    runtime: python
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
    envVars:
      - key: GOOGLE_SERVICE_ACCOUNT_JSON
        sync: false
      - key: GOOGLE_SPREADSHEET_ID
        sync: false
```

- [ ] **Step 2: Verify YAML file exists**

Run:

```bash
python -c "from pathlib import Path; assert Path('render.yaml').exists(); print('render.yaml ok')"
```

Expected: prints `render.yaml ok`.

### Task 4: README Documentation

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

Write `README.md` with sections covering:

```markdown
# Dashboard Streamlit com Google Sheets

Dashboard web em Python que conecta ao Google Sheets com Service Account, carrega a aba `Dados` em um DataFrame do Pandas e exibe filtros, metricas, graficos e tabela detalhada.

## Stack

- Python
- Streamlit
- Pandas
- Google Sheets API
- Render Starter

## Colunas da planilha

A aba `Dados` deve conter, no minimo:

- `data`
- `categoria`
- `descricao`
- `valor`

Filtros opcionais aparecem automaticamente se estas colunas existirem:

- `item`
- `oferta`
- `metodo_pagamento`
- `cidade`

## Variaveis de ambiente

- `GOOGLE_SERVICE_ACCOUNT_JSON`: JSON completo da Service Account.
- `GOOGLE_SPREADSHEET_ID`: ID da planilha.

Nunca salve credenciais no codigo, no GitHub, em `.env` commitado ou em `secrets.toml`.

## Rodar localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```

Configure as variaveis de ambiente antes de iniciar o app.

## Criar a Service Account no Google Cloud

1. Acesse https://console.cloud.google.com/.
2. Crie ou selecione um projeto.
3. Acesse IAM e administrador > Contas de servico.
4. Clique em Criar conta de servico.
5. Informe nome e descricao.
6. Conclua a criacao.
7. Abra a conta criada, acesse Chaves e crie uma chave JSON.
8. Copie o conteudo completo do arquivo JSON para usar na variavel `GOOGLE_SERVICE_ACCOUNT_JSON`.

## Ativar a Google Sheets API

1. No Google Cloud Console, abra APIs e servicos > Biblioteca.
2. Pesquise por Google Sheets API.
3. Abra o resultado e clique em Ativar.

## Compartilhar a planilha com a Service Account

1. Abra o JSON da Service Account.
2. Copie o valor de `client_email`.
3. Abra a planilha no Google Sheets.
4. Clique em Compartilhar.
5. Adicione o `client_email` como Leitor.
6. Confirme o compartilhamento.

## Configurar variaveis no Render

1. No Render, abra o servico web.
2. Acesse Environment.
3. Adicione `GOOGLE_SPREADSHEET_ID` com o ID da planilha.
4. Adicione `GOOGLE_SERVICE_ACCOUNT_JSON` com o JSON completo em uma unica variavel.
5. Salve as alteracoes.

## Conectar o projeto ao GitHub

1. Crie um repositorio no GitHub.
2. Inicialize Git localmente, se necessario:

```bash
git init
git add .
git commit -m "feat: add streamlit google sheets dashboard"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
git push -u origin main
```

## Deploy no Render Starter

1. No Render, clique em New > Web Service.
2. Conecte sua conta GitHub.
3. Selecione o repositorio do projeto.
4. Escolha o plano Starter.
5. Use o comando de build:

```bash
pip install -r requirements.txt
```

6. Use o comando de start:

```bash
streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
```

7. Configure as variaveis de ambiente.
8. Clique em Deploy Web Service.

Tambem e possivel usar o `render.yaml` como Blueprint.
```

- [ ] **Step 2: Verify README exists**

Run:

```bash
python -c "from pathlib import Path; assert Path('README.md').exists(); print('README.md ok')"
```

Expected: prints `README.md ok`.

### Task 5: Final Verification

**Files:**
- Verify: `app.py`
- Verify: `requirements.txt`
- Verify: `.gitignore`
- Verify: `README.md`
- Verify: `render.yaml`

- [ ] **Step 1: Compile Python**

Run:

```bash
python -m py_compile app.py
```

Expected: command exits successfully without output.

- [ ] **Step 2: Confirm required files**

Run:

```bash
python -c "from pathlib import Path; files=['app.py','requirements.txt','.gitignore','README.md','render.yaml']; missing=[f for f in files if not Path(f).exists()]; assert not missing, missing; print('all files ok')"
```

Expected: prints `all files ok`.

- [ ] **Step 3: Commit if repository exists**

Run:

```bash
git status --short
```

Expected: if this is a Git repository, command prints changed files and the worker should commit. If this is not a Git repository, record that no commit was made because Git is not initialized.

## Self-Review

- Spec coverage: all requested files, Google Sheets Service Account access, environment variables, cache, manual refresh, filters, metrics, charts, detailed table, conversion, error handling, and Render deployment are covered.
- Placeholder scan: no task contains deferred implementation placeholders.
- Type consistency: helper names and constants are consistent across tasks.
