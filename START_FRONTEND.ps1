Set-Location "$PSScriptRoot\frontend"
if (!(Test-Path .env.local)) { Copy-Item .env.local.example .env.local }
npm install
npm run dev
