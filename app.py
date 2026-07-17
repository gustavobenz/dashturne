from __future__ import annotations

import json
import logging
import os
import re
import secrets
import unicodedata
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


DEFAULT_SPREADSHEET_ID = "1ogY8-8jjibTWu1PKcPyKHofoOEL9Hn4RLJUssG2IXao"
DEFAULT_SHEET_NAME = "Sheet1"
DASHBOARD_PASSWORD_ENV_VAR = "DASHBOARD_PASSWORD"
REQUIRED_COLUMNS = {"data_de_criacao", "descricao", "valor"}
OPTIONAL_FILTER_COLUMNS = ("cidade", "metodo_pagamento")
SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)
PRESET_FILTER_START_DATE = date(2026, 7, 1)
STATUS_COLUMN = "status"
APPROVED_STATUS = "approved"
CITY_SOURCE_COLUMN = "item"
OFERTA_COLUMN = "oferta"
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

# Vendas antes desta data sao pre-venda; a partir desta data (inclusive), perpetuo.
DATA_CORTE = date(2026, 7, 6)
TIPO_PRE_VENDA = "Pre-venda"
TIPO_PERPETUO = "Perpetuo"
TIPO_VENDA_OPTIONS = ("Todas as vendas", "Apenas pre-venda", "Apenas perpetuo")

# Sufixo (ja normalizado: sem acento, maiusculo, sem hifen) que faz uma venda valer 2 ingressos.
LANCAMENTO_DUPLO_SUFIXO = "LANCAMENTO DUPLO"

# So "approved" conta como venda paga. Cortesia (valor = 0) continua contando independente
# do status, preservando o comportamento ja validado do dashboard. STATUS_VALIDOS existe
# como ponto unico de extensao caso outros status precisem entrar na regra de venda paga.
STATUS_VALIDOS = {APPROVED_STATUS}

# Capacidade por cidade. Chaves usam os mesmos nomes canonicos (sem acento) que
# ALLOWED_CITY_NAMES ja produz, para casar direto com a coluna "cidade" normalizada.
CAPACIDADES = {
    "Sao Paulo": 120,
    "Maringa": 50,
    "Porto Velho": 40,
    "Cuiaba": 60,
    "Rio de Janeiro": 60,
    "Salvador": 60,
    "Fortaleza": 60,
}

CONSOLIDATED_CITY_COLUMNS = [
    "Cidade",
    "Total de vendas",
    "Total de ingressos",
    "Valor total vendido",
    "Clinicas unicas",
    "Cortesias",
    "Capacidade",
    "% de ocupacao",
]

PLOTLY_TEMPLATE_NAME = "turne_seven"


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


def check_password(candidate: str, expected: str) -> bool:
    """Constant-time comparison so response timing does not leak the password."""
    return secrets.compare_digest(candidate, expected)


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

    return (
        dataframe[STATUS_COLUMN].fillna("").astype(str).str.strip().str.lower()
        .isin(STATUS_VALIDOS)
    )


def is_paid_ticket(dataframe: pd.DataFrame) -> pd.Series:
    return status_is_approved(dataframe) & dataframe["valor"].fillna(0).gt(0)


def is_courtesy_ticket(dataframe: pd.DataFrame) -> pd.Series:
    return dataframe["valor"].fillna(-1).eq(0)


def is_valid_sale(dataframe: pd.DataFrame) -> pd.Series:
    """Venda valida = paga ou cortesia. Carrinhos abandonados/pendentes/cancelados ficam fora."""
    return is_paid_ticket(dataframe) | is_courtesy_ticket(dataframe)


def classificar_tipo_venda(dataframe: pd.DataFrame) -> pd.Series:
    """Classifica cada linha como Pre-venda (antes de DATA_CORTE) ou Perpetuo (a partir dela)."""
    datas = dataframe["data"].dt.date
    return pd.Series(
        np.select(
            [datas.isna(), datas < DATA_CORTE],
            [None, TIPO_PRE_VENDA],
            default=TIPO_PERPETUO,
        ),
        index=dataframe.index,
    )


def oferta_e_lancamento_duplo(oferta: object) -> bool:
    """Testa (de forma robusta a caixa/espacos/acentos) se a oferta termina em LANCAMENTO DUPLO."""
    return normalize_text(oferta).endswith(LANCAMENTO_DUPLO_SUFIXO)


def calcular_ingressos(dataframe: pd.DataFrame) -> pd.Series:
    """1 ingresso por venda valida; 2 se a oferta for lancamento duplo. Vendas invalidas contam 0."""
    valid_mask = is_valid_sale(dataframe)
    if OFERTA_COLUMN in dataframe.columns:
        duplo_mask = dataframe[OFERTA_COLUMN].apply(oferta_e_lancamento_duplo)
    else:
        duplo_mask = pd.Series(False, index=dataframe.index)

    ingressos = pd.Series(1, index=dataframe.index, dtype="int64")
    ingressos = ingressos.where(~duplo_mask, 2)
    return ingressos.where(valid_mask, 0)


def calcular_indicadores_gerais(dataframe: pd.DataFrame) -> dict[str, float | int]:
    """Indicadores dos cards de topo. Total de clinicas = Total de vendas (sem coluna de comprador)."""
    valid_mask = is_valid_sale(dataframe)
    paid_mask = is_paid_ticket(dataframe)
    total_vendas = int(valid_mask.sum())
    return {
        "total_vendas": total_vendas,
        "total_ingressos": int(calcular_ingressos(dataframe).sum()),
        "total_clinicas": total_vendas,
        "receita_total": float(dataframe.loc[paid_mask, "valor"].sum(skipna=True)),
        "cortesias": int(is_courtesy_ticket(dataframe).sum()),
    }


def classificar_faixa_ocupacao(percentual: float | None) -> str:
    """Faixa de ocupacao: >=90 esgotando, 60-89 saudavel, <60 atencao, sem capacidade '-'."""
    if percentual is None or pd.isna(percentual):
        return "-"
    if percentual >= 90:
        return "Esgotando"
    if percentual >= 60:
        return "Saudavel"
    return "Atencao"


def consolidar_por_cidade(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Tabela por cidade: vendas, ingressos, receita, clinicas, cortesias, capacidade e ocupacao."""
    if dataframe.empty or "cidade" not in dataframe.columns:
        return pd.DataFrame(columns=CONSOLIDATED_CITY_COLUMNS)

    working = dataframe.copy()
    working["_ingressos"] = calcular_ingressos(working)
    working["_valida"] = is_valid_sale(working)
    working["_paga"] = is_paid_ticket(working)
    working["_cortesia"] = is_courtesy_ticket(working)

    rows = []
    for city, group in working.groupby("cidade", sort=False):
        total_vendas = int(group["_valida"].sum())
        total_ingressos = int(group["_ingressos"].sum())
        if total_vendas == 0 and total_ingressos == 0:
            continue

        capacidade = CAPACIDADES.get(city)
        ocupacao = round(total_ingressos / capacidade * 100, 1) if capacidade else None
        rows.append(
            {
                "Cidade": city,
                "Total de vendas": total_vendas,
                "Total de ingressos": total_ingressos,
                "Valor total vendido": float(group.loc[group["_paga"], "valor"].sum(skipna=True)),
                "Clinicas unicas": total_vendas,
                "Cortesias": int(group["_cortesia"].sum()),
                "Capacidade": capacidade,
                "% de ocupacao": ocupacao,
            }
        )

    table = pd.DataFrame(rows, columns=CONSOLIDATED_CITY_COLUMNS)
    return table.sort_values(
        "% de ocupacao", ascending=False, na_position="last", kind="stable"
    ).reset_index(drop=True)


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


def tickets_by_city(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty or "cidade" not in dataframe.columns:
        return pd.DataFrame(columns=["Cidade", "Ingressos"])

    working = dataframe.copy()
    working["_ingressos"] = calcular_ingressos(working)
    result = (
        working.groupby("cidade", as_index=False)["_ingressos"]
        .sum()
        .rename(columns={"cidade": "Cidade", "_ingressos": "Ingressos"})
    )
    result = result[result["Ingressos"] > 0]
    return result.sort_values("Ingressos", ascending=False, kind="stable").reset_index(drop=True)


def sales_over_time(dataframe: pd.DataFrame) -> pd.DataFrame:
    valid = dataframe[is_valid_sale(dataframe)].dropna(subset=["data"])
    if valid.empty:
        return pd.DataFrame(columns=["Data", "Vendas"])

    working = valid.copy()
    working["Data"] = working["data"].dt.date
    result = working.groupby("Data", as_index=False).size().rename(columns={"size": "Vendas"})
    return result.sort_values("Data", kind="stable").reset_index(drop=True)


def presale_vs_perpetual_summary(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return pd.DataFrame(columns=["Tipo", "Ingressos", "Receita"])

    working = dataframe.copy()
    working["_tipo"] = classificar_tipo_venda(working)
    working["_ingressos"] = calcular_ingressos(working)
    working["_paga"] = is_paid_ticket(working)

    rows = []
    for tipo in (TIPO_PRE_VENDA, TIPO_PERPETUO):
        subset = working[working["_tipo"] == tipo]
        rows.append(
            {
                "Tipo": tipo,
                "Ingressos": int(subset["_ingressos"].sum()),
                "Receita": float(subset.loc[subset["_paga"], "valor"].sum(skipna=True)),
            }
        )
    return pd.DataFrame(rows)


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


def apply_sale_type_filter(dataframe: pd.DataFrame, selected: str) -> pd.DataFrame:
    if selected == "Apenas pre-venda":
        return dataframe[classificar_tipo_venda(dataframe) == TIPO_PRE_VENDA]
    if selected == "Apenas perpetuo":
        return dataframe[classificar_tipo_venda(dataframe) == TIPO_PERPETUO]
    return dataframe


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

    tipo_venda_selecionado = st.sidebar.selectbox("Tipo de venda", TIPO_VENDA_OPTIONS, index=0)
    filtered = apply_sale_type_filter(filtered, tipo_venda_selecionado)

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


def format_int_ptbr(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


CUSTOM_CSS = """
<style>
:root {
    --ts-accent: #2563eb;
    --ts-surface: rgba(37, 99, 235, 0.06);
    --ts-border: rgba(15, 23, 42, 0.10);
    --ts-text-muted: #64748b;
    --ts-text-strong: #0f172a;
}
@media (prefers-color-scheme: dark) {
    :root {
        --ts-surface: rgba(37, 99, 235, 0.16);
        --ts-border: rgba(148, 163, 184, 0.20);
        --ts-text-muted: #94a3b8;
        --ts-text-strong: #f1f5f9;
    }
}
.block-container {
    padding-top: 2.2rem;
    padding-bottom: 3rem;
}
.ts-kpi-card {
    background: var(--ts-surface);
    border: 1px solid var(--ts-border);
    border-radius: 14px;
    padding: 1.05rem 1.2rem;
    height: 100%;
}
.ts-kpi-card .ts-kpi-icon {
    font-size: 1.25rem;
    opacity: 0.85;
}
.ts-kpi-card .ts-kpi-label {
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--ts-text-muted);
    margin-top: 0.3rem;
}
.ts-kpi-card .ts-kpi-value {
    font-size: 1.85rem;
    font-weight: 700;
    color: var(--ts-text-strong);
    line-height: 1.15;
    margin-top: 0.1rem;
}
.ts-caption {
    color: var(--ts-text-muted);
    font-size: 0.85rem;
}
h1, h2, h3 {
    font-weight: 700;
}
</style>
"""


def render_custom_css() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def render_kpi_card(column: Any, label: str, value: str, icon: str = "") -> None:
    column.markdown(
        f"""
        <div class="ts-kpi-card">
            <div class="ts-kpi-icon">{icon}</div>
            <div class="ts-kpi-label">{label}</div>
            <div class="ts-kpi-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metrics(dataframe: pd.DataFrame) -> None:
    indicadores = calcular_indicadores_gerais(dataframe)
    columns = st.columns(5)
    render_kpi_card(columns[0], "Total de vendas", format_int_ptbr(indicadores["total_vendas"]), "\U0001F4CB")
    render_kpi_card(columns[1], "Total de ingressos", format_int_ptbr(indicadores["total_ingressos"]), "\U0001F3AB")
    render_kpi_card(columns[2], "Total de clinicas", format_int_ptbr(indicadores["total_clinicas"]), "\U0001F3E5")
    render_kpi_card(columns[3], "Receita total", format_brl(float(indicadores["receita_total"])), "\U0001F4B0")
    render_kpi_card(columns[4], "Cortesias", format_int_ptbr(indicadores["cortesias"]), "\U0001F39F")
    st.caption(
        "Total de clinicas ainda equivale ao total de vendas: a planilha nao tem uma "
        "coluna de comprador/clinica para deduplicar."
    )


def register_plotly_template() -> None:
    template = go.layout.Template()
    template.layout = go.Layout(
        colorway=PALETTE,
        font=dict(family="Segoe UI, -apple-system, sans-serif", size=13, color="#334155"),
        title=dict(font=dict(size=16, color="#0f172a")),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(showgrid=False, zeroline=False, showline=True, linecolor="rgba(148,163,184,0.35)"),
        yaxis=dict(showgrid=True, gridcolor="rgba(148,163,184,0.16)", zeroline=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Segoe UI, sans-serif"),
    )
    pio.templates[PLOTLY_TEMPLATE_NAME] = template


register_plotly_template()


def render_revenue_by_city_chart(dataframe: pd.DataFrame) -> None:
    chart_data = revenue_by_city(dataframe)
    st.subheader("Receita por cidade")
    if chart_data.empty:
        st.info("Sem receita aprovada para exibir por cidade.")
        return

    chart_data = chart_data.sort_values("Receita", ascending=True)
    chart_data["_label"] = chart_data["Receita"].apply(format_brl)
    fig = px.bar(
        chart_data,
        x="Receita",
        y="Cidade",
        orientation="h",
        template=PLOTLY_TEMPLATE_NAME,
        color_discrete_sequence=[PALETTE[0]],
        custom_data=["_label"],
    )
    fig.update_traces(hovertemplate="%{y}<br>%{customdata[0]}<extra></extra>")
    fig.update_layout(
        height=max(280, 40 * len(chart_data)),
        xaxis_title=None,
        yaxis_title=None,
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_tickets_by_city_chart(dataframe: pd.DataFrame) -> None:
    chart_data = tickets_by_city(dataframe)
    st.subheader("Ingressos por cidade")
    if chart_data.empty:
        st.info("Sem ingressos para exibir por cidade.")
        return

    chart_data = chart_data.sort_values("Ingressos", ascending=True)
    chart_data["_label"] = chart_data["Ingressos"].apply(format_int_ptbr)
    fig = px.bar(
        chart_data,
        x="Ingressos",
        y="Cidade",
        orientation="h",
        template=PLOTLY_TEMPLATE_NAME,
        color_discrete_sequence=[PALETTE[1]],
        custom_data=["_label"],
    )
    fig.update_traces(hovertemplate="%{y}<br>%{customdata[0]} ingressos<extra></extra>")
    fig.update_layout(
        height=max(280, 40 * len(chart_data)),
        xaxis_title=None,
        yaxis_title=None,
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_sales_over_time_chart(dataframe: pd.DataFrame) -> None:
    chart_data = sales_over_time(dataframe)
    st.subheader("Evolucao de vendas")
    if chart_data.empty:
        st.info("Sem vendas para exibir na linha do tempo.")
        return

    fig = px.line(
        chart_data,
        x="Data",
        y="Vendas",
        template=PLOTLY_TEMPLATE_NAME,
        color_discrete_sequence=[PALETTE[0]],
        markers=True,
    )
    fig.update_traces(hovertemplate="%{x|%d/%m/%Y}<br>%{y} vendas<extra></extra>")

    min_data = chart_data["Data"].min()
    max_data = chart_data["Data"].max()
    if min_data <= DATA_CORTE <= max_data:
        fig.add_vline(x=DATA_CORTE, line_dash="dash", line_color=PALETTE[3])
        fig.add_annotation(
            x=DATA_CORTE,
            y=1,
            yref="paper",
            showarrow=False,
            text="Corte perpetuo (06/07)",
            font=dict(size=11, color=PALETTE[3]),
            yanchor="bottom",
        )

    fig.update_layout(xaxis_title=None, yaxis_title=None, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)


def render_presale_vs_perpetual_chart(dataframe: pd.DataFrame) -> None:
    summary = presale_vs_perpetual_summary(dataframe)
    st.subheader("Pre-venda vs Perpetuo")
    if summary.empty or summary["Ingressos"].sum() == 0:
        st.info("Sem vendas para comparar pre-venda e perpetuo.")
        return

    summary = summary.copy()
    summary["_label"] = summary["Receita"].apply(format_brl)
    fig = px.bar(
        summary,
        x="Tipo",
        y="Ingressos",
        template=PLOTLY_TEMPLATE_NAME,
        color="Tipo",
        color_discrete_sequence=[PALETTE[0], PALETTE[1]],
        custom_data=["_label"],
    )
    fig.update_traces(hovertemplate="%{x}<br>%{y} ingressos<br>%{customdata[0]}<extra></extra>")
    fig.update_layout(xaxis_title=None, yaxis_title=None, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)


def render_payment_method_chart(dataframe: pd.DataFrame) -> None:
    chart_data = payment_method_totals(dataframe)
    st.subheader("Receita por metodo de pagamento")
    if chart_data.empty:
        st.info("Sem receita aprovada por metodo de pagamento.")
        return

    chart_data = chart_data.copy()
    chart_data["_label"] = chart_data["Receita"].apply(format_brl)
    fig = px.bar(
        chart_data,
        x="Metodo de pagamento",
        y="Receita",
        template=PLOTLY_TEMPLATE_NAME,
        color_discrete_sequence=[PALETTE[2]],
        custom_data=["_label"],
    )
    fig.update_traces(hovertemplate="%{x}<br>%{customdata[0]}<extra></extra>")
    fig.update_layout(xaxis_title=None, yaxis_title=None, showlegend=False, height=320)
    st.plotly_chart(fig, use_container_width=True)


def render_city_table(dataframe: pd.DataFrame) -> None:
    st.subheader("Consolidado por cidade")
    table = consolidar_por_cidade(dataframe)
    if table.empty:
        st.info("Sem cidades validas para exibir com os filtros atuais.")
        return

    cidades_sem_capacidade = table.loc[table["Capacidade"].isna(), "Cidade"].tolist()
    if cidades_sem_capacidade:
        st.markdown(
            f'<p class="ts-caption">Sem capacidade cadastrada (ocupacao nao calculada): '
            f'{", ".join(cidades_sem_capacidade)}</p>',
            unsafe_allow_html=True,
        )

    display = table.copy()
    display["Faixa"] = display["% de ocupacao"].apply(classificar_faixa_ocupacao)
    display["Valor total vendido"] = display["Valor total vendido"].apply(format_brl)
    display["Capacidade"] = display["Capacidade"].apply(
        lambda value: "-" if pd.isna(value) else format_int_ptbr(value)
    )

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "% de ocupacao": st.column_config.ProgressColumn(
                "% de ocupacao",
                format="%.1f%%",
                min_value=0,
                max_value=100,
            ),
            "Total de vendas": st.column_config.NumberColumn(format="%d"),
            "Total de ingressos": st.column_config.NumberColumn(format="%d"),
            "Clinicas unicas": st.column_config.NumberColumn(format="%d"),
            "Cortesias": st.column_config.NumberColumn(format="%d"),
        },
    )


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


def require_authentication() -> None:
    if st.session_state.get("authenticated", False):
        return

    try:
        expected_password = get_required_env(DASHBOARD_PASSWORD_ENV_VAR)
    except DashboardError as exc:
        st.error(str(exc))
        st.stop()
        return

    st.caption("Acesso restrito")
    password = st.text_input("Senha", type="password", key="password_input")
    submitted = st.button("Entrar")

    if submitted:
        if check_password(password, expected_password):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")

    if not st.session_state.get("authenticated", False):
        st.stop()


def main() -> None:
    st.set_page_config(
        page_title="Dashboard Turne Seven",
        layout="wide",
    )
    require_authentication()
    render_custom_css()
    st.title("Dashboard Turne Seven")
    st.caption("Vendas, ingressos, ocupacao e receita nas cidades da turne")

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
        render_city_table(filtered_dataframe)
        st.divider()
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            render_revenue_by_city_chart(filtered_dataframe)
            render_sales_over_time_chart(filtered_dataframe)
        with chart_col2:
            render_tickets_by_city_chart(filtered_dataframe)
            render_presale_vs_perpetual_chart(filtered_dataframe)
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
