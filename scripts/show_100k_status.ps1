$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$RunDir = Join-Path $ProjectDir "runs\voc_100k_postgres"
$StatusPath = Join-Path $RunDir "status.json"
$LogPath = Join-Path $RunDir "pipeline.log"
$CheckpointPath = Join-Path $ProjectDir `
    "data\generated\voc_100k_pg_v1.jsonl.gz.work\checkpoint.json"

if (Test-Path -LiteralPath $StatusPath) {
    $status = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
} else {
    $status = [pscustomobject]@{ state = "NOT_STARTED" }
}

$workerAlive = $false
if ($status.updated_at -and $status.state -eq "RUNNING") {
    $lastUpdate = [DateTimeOffset]::Parse($status.updated_at)
    $ageSeconds = (
        [DateTimeOffset]::UtcNow - $lastUpdate.ToUniversalTime()
    ).TotalSeconds
    $workerAlive = $ageSeconds -lt 30
}

$checkpoint = $null
if (Test-Path -LiteralPath $CheckpointPath) {
    $rawCheckpoint = Get-Content -LiteralPath $CheckpointPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $completedRows = (
        $rawCheckpoint.completed_chunks |
            Measure-Object -Property row_count -Sum
    ).Sum
    if ($null -eq $completedRows) {
        $completedRows = 0
    }
    $checkpoint = [ordered]@{
        status = $rawCheckpoint.status
        completed_chunks = @($rawCheckpoint.completed_chunks).Count
        completed_rows = $completedRows
        target_rows = $rawCheckpoint.target_count
    }
}

$databaseReachable = $false
$client = [System.Net.Sockets.TcpClient]::new()
try {
    $connect = $client.ConnectAsync("127.0.0.1", 5433)
    $databaseReachable = $connect.Wait(2000) -and $client.Connected
} finally {
    $client.Dispose()
}
$database = [ordered]@{
    reachable = $databaseReachable
    host = "127.0.0.1"
    port = 5433
    name = "appdb"
    data_directory = "D:\PostgreSQL\18\data"
    loaded_rows = $status.database_row_count
}

$recentLog = @()
if (Test-Path -LiteralPath $LogPath) {
    $recentLog = @(Get-Content -LiteralPath $LogPath -Tail 12 -Encoding UTF8)
}

Write-Output "=== VoC 100k PostgreSQL Pipeline ==="
Write-Output "State             : $($status.state)"
Write-Output "Stage             : $($status.stage)"
Write-Output "Updated (UTC)     : $($status.updated_at)"
Write-Output "Elapsed seconds   : $($status.elapsed_seconds)"
Write-Output "Worker PID        : $($status.pid)"
Write-Output "Worker alive      : $workerAlive"
if ($checkpoint) {
    Write-Output "Completed chunks  : $($checkpoint.completed_chunks)"
    Write-Output "Completed rows    : $($checkpoint.completed_rows) / $($checkpoint.target_rows)"
} else {
    Write-Output "Checkpoint        : not created yet"
}
Write-Output "DB reachable      : $($database.reachable)"
Write-Output "DB endpoint       : $($database.host):$($database.port)/$($database.name)"
Write-Output "DB data directory : $($database.data_directory)"
if ($database.loaded_rows) {
    Write-Output "DB loaded rows    : $($database.loaded_rows)"
}
Write-Output "Status file       : $StatusPath"
Write-Output "Log file          : $LogPath"
Write-Output ""
Write-Output "--- Recent log ---"
$recentLog | ForEach-Object { Write-Output $_ }
