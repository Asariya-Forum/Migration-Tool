Set-Location "$PSScriptRoot\backend"
if (!(Test-Path .venv)) { py -3.11 -m venv .venv }
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
Write-Host 'Edit backend\.env DATABASE_URL before starting if needed.' -ForegroundColor Yellow
uvicorn app.main:app --reload
