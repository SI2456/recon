$psql = "C:\Program Files\PostgreSQL\18\bin\psql.exe"
$sqlFile = Join-Path $PSScriptRoot "init_postgres.sql"

if (-not (Test-Path $psql)) {
    Write-Host "Could not find PostgreSQL psql.exe at: $psql"
    Write-Host "Update server/scripts/init_postgres.ps1 if PostgreSQL is installed in a different folder."
    exit 1
}

& $psql -U postgres -h localhost -d postgres -f $sqlFile
