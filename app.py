from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from typing import Any

import pandas as pd
import streamlit as st
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


DEFAULT_SPREADSHEET_ID = "1ogY8-8jjibTWu1PKcPyKHofoOEL9Hn4RLJUssG2IXao"
DEFAULT_SHEET_NAME = "Sheet1"
REQUIRED_COLUMNS = {"data_de_criacao", "descricao", "valor"}
OPTIONAL_FILTER_COLUMNS = ("item", "oferta", "metodo_pagamento", "cidade")
SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)
STATUS_COLUMN = "status"
APPROVED_STATUS = "approved"
CITY_SOURCE_COLUMN = "item"
CITY_PATTERN = re.compile(r"turn[eê]\s+seven\s+(.+)$", re.IGNORECASE)
COLUMN_ALIASES = {
    "data_criacao": "data_de_criacao",
    "created_at": "data_de_criacao",
    "valor": "valor",
    "preco": "valor",
    "descricao": "descricao",
    "descricao_do_item": "descricao",
    "item": "item",
    "oferta": "oferta",
    "metodo_de_pagamento": "metodo_pagamento",
    "forma_de_pagamento": "metodo_pagamento",
    "cidade": "cidade",
}
DERIVED_COLUMNS = {
    "descricao": ("item", "oferta"),
}


class DashboardError(Exception):
    """Expected user-facing dashboard error."""


def get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise DashboardError(f"Variavel de ambiente obrigatoria ausente: {name}.")
    return value


def get_optional_env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def get_service_account_json() -> str:
    env_credentials = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if env_credentials:
        return env_credentials

    local_credentials_path = "google-credentials.json"
    if os.path.exists(local_credentials_path):
        with open(local_credentials_path, encoding="utf-8") as credentials_file:
            return credentials_file.read()

    raise DashboardError(
        "Variavel de ambiente obrigatoria ausente: GOOGLE_SERVICE_ACCOUNT_JSON. "
        "Para rodar localmente, mantenha google-credentials.json na pasta do projeto."
    )


def load_service_account_credentials(credentials_json: str) -> Credentials:
    try:
        credentials_info: dict[str, Any] = json.loads(credentials_json)
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


@st.cache_data(ttl=600, show_spinner="Carregando dados do Google Sheets...")
def fetch_sheet_values(
    spreadsheet_id: str,
    credentials_json: str,
    sheet_name: str,
) -> list[list[str]]:
    credentials = load_service_account_credentials(credentials_json)

    try:
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        response = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=sheet_name)
            .execute()
        )
    except HttpError as exc:
        status = getattr(exc.resp, "status", None)
        if status in {400, 404}:
            raise DashboardError(
                f"Planilha indisponivel, ID incorreto ou aba '{sheet_name}' inexistente."
            ) from exc
        if status in {401, 403}:
            raise DashboardError(
                "Acesso negado. Verifique credenciais e compartilhamento da planilha."
            ) from exc
        raise DashboardError("Erro ao consultar a Google Sheets API.") from exc
    except GoogleAuthError as exc:
        raise DashboardError(
            "Credenciais da Service Account invalidas ou incompletas."
        ) from exc
    except Exception as exc:
        raise DashboardError("Planilha indisponivel no momento.") from exc

    values = response.get("values", [])
    if not values or len(values) < 2:
        raise DashboardError(f"Planilha sem dados na aba '{sheet_name}'.")
    return values


def normalize_column_name(column: object) -> str:
    text = str(column).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return COLUMN_ALIASES.get(text, text)


def parse_brazilian_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None

    text = str(value).strip()
    if not text:
        return None

    text = re.sub(r"[^\d,.\-]", "", text)
    if not text or text in {"-", ",", "."}:
        return None

    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif "." in text:
        parts = text.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            text = "".join(parts)

    try:
        return float(text)
    except ValueError:
        return None


def add_derived_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    for target, sources in DERIVED_COLUMNS.items():
        if target in dataframe.columns:
            continue
        for source in sources:
            if source in dataframe.columns:
                dataframe[target] = dataframe[source]
                break
    return dataframe


def extract_city_from_item(text: object) -> str | None:
    if text is None or pd.isna(text):
        return None

    match = CITY_PATTERN.search(str(text))
    if not match:
        return None

    city = match.group(1).strip()
    return city or None


def derive_city_column(dataframe: pd.DataFrame) -> pd.DataFrame:
    if CITY_SOURCE_COLUMN in dataframe.columns:
        dataframe["cidade"] = dataframe[CITY_SOURCE_COLUMN].apply(extract_city_from_item)
    return dataframe


def filter_approved_status(dataframe: pd.DataFrame) -> pd.DataFrame:
    if STATUS_COLUMN not in dataframe.columns:
        return dataframe

    status_values = dataframe[STATUS_COLUMN].fillna("").astype(str).str.strip().str.lower()
    return dataframe[status_values == APPROVED_STATUS]


def values_to_dataframe(values: list[list[str]]) -> pd.DataFrame:
    if not values or len(values) < 2:
        raise DashboardError(f"Planilha sem dados na aba '{DEFAULT_SHEET_NAME}'.")

    headers = [normalize_column_name(column) for column in values[0]]
    if not any(headers):
        raise DashboardError(f"Planilha sem dados na aba '{DEFAULT_SHEET_NAME}'.")
    if any(not header for header in headers):
        raise DashboardError("Cabecalhos em branco nao sao permitidos.")

    duplicate_headers = sorted(
        {header for header in headers if headers.count(header) > 1}
    )
    if duplicate_headers:
        duplicates = ", ".join(duplicate_headers)
        raise DashboardError(f"Cabecalhos duplicados: {duplicates}.")

    rows = [row[: len(headers)] + [""] * max(len(headers) - len(row), 0) for row in values[1:]]
    if not rows:
        raise DashboardError(f"Planilha sem dados na aba '{DEFAULT_SHEET_NAME}'.")

    dataframe = pd.DataFrame(rows, columns=headers)
    dataframe = dataframe.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all")
    if dataframe.empty:
        raise DashboardError(f"Planilha sem dados na aba '{DEFAULT_SHEET_NAME}'.")

    dataframe = add_derived_columns(dataframe)
    dataframe = derive_city_column(dataframe)
    missing_columns = REQUIRED_COLUMNS.difference(dataframe.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise DashboardError(f"Colunas obrigatorias ausentes: {missing}.")

    dataframe["data"] = pd.to_datetime(
        dataframe["data_de_criacao"],
        errors="coerce",
        dayfirst=True,
        format="mixed",
    )
    dataframe["valor"] = dataframe["valor"].apply(parse_brazilian_number)
    dataframe["valor"] = pd.to_numeric(dataframe["valor"], errors="coerce")
    dataframe = filter_approved_status(dataframe)
    if dataframe.empty:
        raise DashboardError("Nenhum registro com status aprovado encontrado.")

    return dataframe


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

    values = dataframe[column].fillna("").astype(str).str.strip()
    return dataframe[values.isin(selected_values)]


def render_filters(dataframe: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filtros")
    filtered = dataframe.copy()

    valid_dates = dataframe["data"].dropna()
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
            if start_date != min_date or end_date != max_date:
                filtered = filtered[
                    (filtered["data"].dt.date >= start_date)
                    & (filtered["data"].dt.date <= end_date)
                ]


    for column in OPTIONAL_FILTER_COLUMNS:
        if column in dataframe.columns:
            label = column.replace("_", " ").title()
            selected = st.sidebar.multiselect(
                label,
                options=sorted_options(dataframe, column),
                default=[],
            )
            filtered = apply_multiselect_filter(filtered, column, selected)

    return filtered


def format_brl(value: float) -> str:
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def render_metrics(dataframe: pd.DataFrame) -> None:
    total_tickets = len(dataframe)
    total_value = dataframe["valor"].sum(skipna=True)

    col_records, col_value = st.columns(2)
    col_records.metric("Total de ingressos", f"{total_tickets:,}".replace(",", "."))
    col_value.metric("Soma de valores", format_brl(float(total_value)))


def render_charts(dataframe: pd.DataFrame) -> None:
    line_chart = (
        dataframe.dropna(subset=["data", "valor"])
        .assign(data=lambda frame: frame["data"].dt.date)
        .groupby("data", as_index=True)["valor"]
        .sum()
        .sort_index()
    )
    st.subheader("Valor por data")
    if line_chart.empty:
        st.info("Sem datas e valores validos para exibir.")
    else:
        st.line_chart(line_chart, use_container_width=True)


def render_breakdown_charts(dataframe: pd.DataFrame) -> None:
    st.subheader("Receita Total por cidade")
    if "cidade" not in dataframe.columns:
        st.info("Coluna 'item' ausente, nao e possivel identificar a cidade.")
    else:
        revenue_by_city = (
            dataframe.dropna(subset=["cidade", "valor"])
            .groupby("cidade")["valor"]
            .sum()
            .sort_values(ascending=False)
        )
        if revenue_by_city.empty:
            st.info("Sem dados de cidade e valor validos para exibir.")
        else:
            st.bar_chart(revenue_by_city, use_container_width=True)

    st.subheader("Receita por Metodo de Pagamento")
    if "metodo_pagamento" not in dataframe.columns:
        st.info("Coluna 'metodo_pagamento' ausente na planilha.")
    else:
        revenue_by_payment_method = (
            dataframe.dropna(subset=["metodo_pagamento", "valor"])
            .groupby("metodo_pagamento")["valor"]
            .sum()
            .sort_values(ascending=False)
        )
        if revenue_by_payment_method.empty:
            st.info("Sem dados de metodo de pagamento e valor validos para exibir.")
        else:
            st.bar_chart(revenue_by_payment_method, use_container_width=True)

    st.subheader("Quantidade de cortesias por cidade")
    if "cidade" not in dataframe.columns:
        st.info("Coluna 'item' ausente, nao e possivel identificar a cidade.")
    else:
        courtesies_by_city = (
            dataframe[dataframe["valor"] == 0]
            .dropna(subset=["cidade"])
            .groupby("cidade")
            .size()
            .sort_values(ascending=False)
        )
        if courtesies_by_city.empty:
            st.info("Nenhuma cortesia (valor=0) encontrada.")
        else:
            st.bar_chart(courtesies_by_city, use_container_width=True)


def render_table(dataframe: pd.DataFrame) -> None:
    st.subheader("Dados detalhados")
    display_dataframe = dataframe.copy()
    display_dataframe["data"] = display_dataframe["data"].dt.strftime("%d/%m/%Y")
    st.dataframe(display_dataframe, use_container_width=True, hide_index=True)


def load_dataframe() -> pd.DataFrame:
    spreadsheet_id = get_optional_env("GOOGLE_SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID)
    credentials_json = get_service_account_json()
    sheet_name = get_optional_env("GOOGLE_SHEET_NAME", DEFAULT_SHEET_NAME)
    values = fetch_sheet_values(spreadsheet_id, credentials_json, sheet_name)
    return values_to_dataframe(values)


def main() -> None:
    st.set_page_config(
        page_title="Dashboard Google Sheets",
        layout="wide",
    )
    st.title("Dashboard Google Sheets")

    if st.sidebar.button("Atualizar dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    try:
        dataframe = load_dataframe()
        filtered_dataframe = render_filters(dataframe)
        if filtered_dataframe.empty:
            st.warning("Nenhum registro encontrado para os filtros selecionados.")
            st.stop()

        render_metrics(filtered_dataframe)
        render_charts(filtered_dataframe)
        render_breakdown_charts(filtered_dataframe)
        render_table(filtered_dataframe)
    except DashboardError as exc:
        st.error(str(exc))
        st.stop()
    except Exception:
        logging.exception("Unexpected dashboard error")
        st.error("Erro inesperado ao carregar o dashboard. Tente novamente mais tarde.")
        st.stop()


if __name__ == "__main__":
    main()

