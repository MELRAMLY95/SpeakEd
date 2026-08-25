# Start or stop the throwaway local PostgreSQL server used by the real-database
# tests. This server holds no production data; it exists only so the test suite
# can exercise the true production code path.
#
#   .\scripts\local_test_postgres.ps1 start
#   .\scripts\local_test_postgres.ps1 stop
#   .\scripts\local_test_postgres.ps1 status
#
# Then run the tests with:
#   $env:SPEAKED_TEST_PG="postgresql://postgres@127.0.0.1:55432/postgres?sslmode=disable"
#   python -m pytest -q
#
# Without SPEAKED_TEST_PG the real-PostgreSQL tests skip cleanly.

param([Parameter(Mandatory = $true)][ValidateSet("start", "stop", "status")][string]$Action)

$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root ".pgtmp\extract\pgsql\bin"
$data = Join-Path $root ".pgtmp\data"
$log = Join-Path $root ".pgtmp\pg.log"

if (-not (Test-Path (Join-Path $bin "pg_ctl.exe"))) {
    Write-Host "PostgreSQL binaries not found at $bin"
    Write-Host "Download the Windows binaries zip from https://www.enterprisedb.com/download-postgresql-binaries"
    Write-Host "and extract it to .pgtmp\extract, then run: initdb -D .pgtmp\data -U postgres --auth=trust"
    exit 1
}

switch ($Action) {
    "start" { & "$bin\pg_ctl.exe" -D $data -l $log -o "-p 55432 -c listen_addresses=127.0.0.1" start }
    "stop" { & "$bin\pg_ctl.exe" -D $data stop }
    "status" { & "$bin\pg_ctl.exe" -D $data status }
}
