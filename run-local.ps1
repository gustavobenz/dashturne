$ErrorActionPreference = "Stop"

$credentialsPath = Join-Path $PSScriptRoot "google-credentials.json"
if (-not (Test-Path -LiteralPath $credentialsPath)) {
    throw "Arquivo google-credentials.json nao encontrado em $PSScriptRoot"
}

$env:GOOGLE_SPREADSHEET_ID = "1ogY8-8jjibTWu1PKcPyKHofoOEL9Hn4RLJUssG2IXao"
$env:GOOGLE_SHEET_NAME = "Sheet1"
$env:GOOGLE_SERVICE_ACCOUNT_JSON = Get-Content -Raw -LiteralPath $credentialsPath
$env:DASHBOARD_PASSWORD = "senha-local-dev"

py -m streamlit run (Join-Path $PSScriptRoot "app.py")
