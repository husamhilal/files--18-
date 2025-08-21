# Banking Assistant - Single Deployment Script (SQLite + MCP)
# Creates folders, venv, installs deps, sets environment variables, seeds SQLite, and runs the app

# 1) Move to script directory
Set-Location $PSScriptRoot

# 2) Create required directories first
$dirs = @("uploads","logs","static","static\css","static\js","templates","services","scripts","data")
foreach ($d in $dirs) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null } }

# 3) Create venv if missing
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Host "Failed to create venv" -ForegroundColor Red; Read-Host "Press Enter to exit"; exit 1 }
}

# 4) Activate venv
& ".venv\Scripts\Activate.ps1"
if ($LASTEXITCODE -ne 0) { Write-Host "Failed to activate venv" -ForegroundColor Red; Read-Host "Press Enter to exit"; exit 1 }

# 5) Upgrade pip and install dependencies (pinned for compatibility)
python -m pip install --upgrade pip
pip install -r requirements.txt

# 6) Set environment variables HERE (edit to your endpoints/deployment)
$env:AZURE_OPENAI_ENDPOINT = "https://your-openai-resource.openai.azure.com"
$env:AZURE_OPENAI_CHAT_DEPLOYMENT = "gpt-5-mini"   # your deployment name
$env:AZURE_OPENAI_API_VERSION = "2024-02-15-preview"
$env:AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = "https://your-docintel.cognitiveservices.azure.com"

# SQLite path (local on-prem simulation)
$env:SQLITE_DB_PATH = (Join-Path $PSScriptRoot "data\banking.db")
$env:DEMO_USER_ID = "husamhilal"

# Optional
$env:FLASK_SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(16))")
$env:FLASK_ENV = "development"
$env:PORT = "5000"
$env:LOG_LEVEL = "INFO"
$env:MAX_CHAT_HISTORY = "50"
$env:CHAT_SESSION_TIMEOUT = "3600"

Write-Host "Seeding SQLite sample data..." -ForegroundColor Cyan
python scripts/seed_sqlite.py

Write-Host "Starting app at http://localhost:$($env:PORT)" -ForegroundColor Cyan
python app.py

Write-Host "`nPress any key to exit..."
[void][System.Console]::ReadKey($true)

deactivate