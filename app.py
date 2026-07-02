from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import date
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


DEFAULT_SPREADSHEET_ID = "1ogY8-8jjibTWu1PKcPyKHofoOEL9Hn4RLJUssG2IXao"
DEFAULT_SHEET_NAME = "Sheet1"
REQUIRED_COLUMNS = {"data_de_criacao", "descricao", "valor"}
OPTIONAL_FILTER_COLUMNS = ("cidade", "metodo_pagamento")
SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)
PRESET_FILTER_START_DATE = date(2026, 7, 1)
STATUS_COLUMN = "status"
APPROVED_STATUS = "approved"
CITY_SOURCE_COLUMN = "item"
PALETTE = ["#2563eb", "#16a34a", "#f97316", "#9333ea", "#0f766e", "#e11d48"]
ALLOWED_CITY_NAMES = {
    "SAO PAULO": "Sao Paulo",
    "RIO DE JANEIRO": "Rio de Janeiro",
    "RIO DE JANIERO": "Rio de Janeiro",
    "BELO HORIZONTE": "Belo Horizonte",
    "CUIABA": "Cuiaba",
    "MARINGA": "Maringa",
    "PORTO VELHO": "Porto Velho",
    "SALVADOR": "Salvador",
    "FORTALEZA": "Fortaleza",
    "BRASILIA": "Brasilia",
    "VITORIA": "Vitoria",
    "FLORIANOPOLIS": "Florianopolis",
    "CAMPINAS": "Campinas",
}
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
    "status": "status",
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


def normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""

    text = str(value).strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().upper()


def canonicalize_city(value: object) -> str | None:
    normalized = normalize_text(value)
    return ALLOWED_CITY_NAMES.get(normalized)


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
    normalized = normalize_text(text)
    marker = "TURNE SEVEN"
    marker_index = normalized.find(marker)
    if marker_index < 0:
        return None

    city_text = normalized[marker_index + len(marker) :].strip()
    return canonicalize_city(city_text)


def derive_city_column(dataframe: pd.DataFrame) -> pd.DataFrame:
    if CITY_SOURCE_COLUMN in dataframe.columns:
        dataframe["cidade"] = dataframe[CITY_SOURCE_COLUMN].apply(extract_city_from_item)
    elif "cidade" in dataframe.columns:
        dataframe["cidade"] = dataframe["cidade"].apply(canonicalize_city)
    return dataframe


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

    return dataframe


def filter_allowed_cities(dataframe: pd.DataFrame) -> pd.DataFrame:
    if "cidade" not in dataframe.columns:
        return dataframe.iloc[0:0].copy()

    filtered = dataframe[dataframe["cidade"].isin(set(ALLOWED_CITY_NAMES.values()))].copy()
    return filtered


def status_is_approved(dataframe: pd.DataFrame) -> pd.Series:
    if STATUS_COLUMN not in dataframe.columns:
        return pd.Series(False, index=dataframe.index)

    return dataframe[STATUS_COLUMN].fillna("").astype(str).str.strip().str.lower() == APPROVED_STATUS


def is_paid_ticket(dataframe: pd.DataFrame) -> pd.Series:
    return status_is_approved(dataframe) & dataframe["valor"].fillna(0).gt(0)


def is_courtesy_ticket(dataframe: pd.DataFrame) -> pd.Series:
    return dataframe["valor"].fillna(-1).eq(0)


def build_kpis(dataframe: pd.DataFrame) -> dict[str, float | int]:
    paid_mask = is_paid_ticket(dataframe)
    courtesy_mask = is_courtesy_ticket(dataframe)
    return {
        "receita_total": float(dataframe.loc[paid_mask, "valor"].sum(skipna=True)),
        "ingressos_pagos": int(paid_mask.sum()),
        "cortesias": int(courtesy_mask.sum()),
    }


def revenue_by_city(dataframe: pd.DataFrame) -> pd.DataFrame:
    paid = dataframe[is_paid_ticket(dataframe)].dropna(subset=["cidade", "valor"])
    if paid.empty:
        return pd.DataFrame(columns=["Cidade", "Receita"])

    return (
        paid.groupby("cidade", as_index=False)["valor"]
        .sum()
        .rename(columns={"cidade": "Cidade", "valor": "Receita"})
        .sort_values("Receita", ascending=False, kind="stable")
        .reset_index(drop=True)
    )


def payment_method_totals(dataframe: pd.DataFrame) -> pd.DataFrame:
    if "metodo_pagamento" not in dataframe.columns:
        return pd.DataFrame(columns=["Metodo de pagamento", "Receita"])

    paid = dataframe[is_paid_ticket(dataframe)].dropna(subset=["metodo_pagamento", "valor"])
    if paid.empty:
        return pd.DataFrame(columns=["Metodo de pagamento", "Receita"])

    return (
        paid.groupby("metodo_pagamento", as_index=False)["valor"]
        .sum()
        .rename(columns={"metodo_pagamento": "Metodo de pagamento", "valor": "Receita"})
        .sort_values("Receita", ascending=False, kind="stable")
        .reset_index(drop=True)
    )


def aggregate_city_ticket_table(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty or "cidade" not in dataframe.columns:
        return pd.DataFrame(columns=["Cidade", "Total", "Pago", "Cortesia"])

    rows = []
    for city, group in dataframe.groupby("cidade", sort=False):
        paid_mask = is_paid_ticket(group)
        rows.append(
            {
                "Cidade": city,
                "Total": int(len(group)),
                "Pago": int(paid_mask.sum()),
                "Cortesia": int(is_courtesy_ticket(group).sum()),
                "_receita": float(group.loc[paid_mask, "valor"].sum(skipna=True)),
            }
        )

    return (
        pd.DataFrame(rows)
        .sort_values(["_receita", "Total", "Cidade"], ascending=[False, False, True], kind="stable")
        .drop(columns=["_receita"])
        .reset_index(drop=True)
    )


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


def compute_default_date_range(min_date: date, max_date: date) -> tuple[date, date]:
    if PRESET_FILTER_START_DATE > max_date:
        return min_date, max_date
    return max(PRESET_FILTER_START_DATE, min_date), max_date


def render_filters(dataframe: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filtros")
    filtered = dataframe.copy()

    valid_dates = dataframe["data"].dropna()
    if not valid_dates.empty:
        min_date = valid_dates.min().date()
        max_date = valid_dates.max().date()
        default_start, default_end = compute_default_date_range(min_date, max_date)
        date_range = st.sidebar.date_input(
            "Periodo",
            value=(default_start, default_end),
            min_value=min_date,
            max_value=max_date,
        )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
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
    kpis = build_kpis(dataframe)
    col_revenue, col_paid, col_courtesy = st.columns(3)
    col_revenue.metric("Receita total", format_brl(float(kpis["receita_total"])))
    col_paid.metric("Ingressos pagos", f"{int(kpis['ingressos_pagos']):,}".replace(",", "."))
    col_courtesy.metric("Cortesias", f"{int(kpis['cortesias']):,}".replace(",", "."))


def currency_axis() -> alt.Axis:
    return alt.Axis(format="$,.0f", title=None)


def render_revenue_by_city_chart(dataframe: pd.DataFrame) -> None:
    chart_data = revenue_by_city(dataframe)
    st.subheader("Receita por cidade")
    if chart_data.empty:
        st.info("Sem receita aprovada para exibir por cidade.")
        return

    chart = (
        alt.Chart(chart_data)
        .mark_bar(cornerRadiusEnd=5, color=PALETTE[0])
        .encode(
            x=alt.X("Receita:Q", axis=currency_axis()),
            y=alt.Y("Cidade:N", sort="-x", title=None),
            tooltip=["Cidade:N", alt.Tooltip("Receita:Q", format=",.2f")],
        )
        .properties(height=max(260, 34 * len(chart_data)))
    )
    st.altair_chart(chart, use_container_width=True)


def render_city_ticket_table(dataframe: pd.DataFrame) -> None:
    st.subheader("Quantidade por cidade")
    table = aggregate_city_ticket_table(dataframe)
    if table.empty:
        st.info("Sem cidades validas para exibir.")
        return

    st.dataframe(table, use_container_width=True, hide_index=True)


def render_payment_method_chart(dataframe: pd.DataFrame) -> None:
    chart_data = payment_method_totals(dataframe)
    st.subheader("Receita por metodo de pagamento")
    if chart_data.empty:
        st.info("Sem receita aprovada por metodo de pagamento.")
        return

    chart = (
        alt.Chart(chart_data)
        .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, color=PALETTE[2])
        .encode(
            x=alt.X("Metodo de pagamento:N", sort="-y", title=None, axis=alt.Axis(labelAngle=-25)),
            y=alt.Y("Receita:Q", axis=currency_axis()),
            tooltip=["Metodo de pagamento:N", alt.Tooltip("Receita:Q", format=",.2f")],
        )
        .properties(height=320)
    )
    st.altair_chart(chart, use_container_width=True)


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
        page_title="Dashboard Turne Seven",
        layout="wide",
    )
    st.title("Dashboard Turne Seven")
    st.caption("Receita, ingressos pagos e cortesias nas cidades da turne")

    if st.sidebar.button("Atualizar dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    try:
        dataframe = filter_allowed_cities(load_dataframe())
        filtered_dataframe = render_filters(dataframe)
        if filtered_dataframe.empty:
            st.warning("Nenhum registro encontrado para os filtros selecionados.")
            st.stop()

        render_metrics(filtered_dataframe)
        st.divider()
        render_revenue_by_city_chart(filtered_dataframe)
        render_city_ticket_table(filtered_dataframe)
        render_payment_method_chart(filtered_dataframe)
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