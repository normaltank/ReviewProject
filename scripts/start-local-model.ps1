# Start the already installed, verified local model. No download or cloud fallback.
[CmdletBinding()]
param(
    [string]$ResourceRoot,
    [string]$RuntimeDir
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $ResourceRoot) { $ResourceRoot = $repoRoot }
$ResourceRoot = (Resolve-Path -LiteralPath $ResourceRoot).Path
if (-not $RuntimeDir) { $RuntimeDir = Join-Path $repoRoot 'work/local-model' }
$runtimeDir = [IO.Path]::GetFullPath($RuntimeDir)
$exe = Join-Path $ResourceRoot '.tools/local-llm/llama-b12110-vulkan/llama-server.exe'
$model = Join-Path $ResourceRoot '.tools/local-llm/Qwen3-4B-Q4_K_M.gguf'
$modelHash = '7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5'
$statePath = Join-Path $runtimeDir 'server-state.json'
$owner = 'ReviewProject/scripts/local-model/v1'

function Get-ModelArguments([string]$runId) {
    return '-m "' + $model + '" --alias reviewproject-qwen3-4b-q4km --tags reviewproject-local-run-' + $runId + ' --host 127.0.0.1 --port 8766 --cors-origins localhost -c 16384 -np 1 -ngl 99 --device Vulkan0 --reasoning off --offline --no-webui --no-slots --no-cache-prompt --cache-ram 0 --log-colors off'
}

$guard = [Threading.Mutex]::new($false, 'Local\ReviewProjectLocalModel8766')
$lockHeld = $false
try {
try { $lockHeld = $guard.WaitOne(0) }
catch [Threading.AbandonedMutexException] { $lockHeld = $true }
if (-not $lockHeld) { throw 'Another local-model lifecycle command is running. Nothing was started.' }

if (Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8766 already has a listener. No existing process will be reused or stopped.'
}
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw 'Install the approved llama.cpp b12110 Windows Vulkan package under .tools/local-llm first.'
}
if (-not (Test-Path -LiteralPath $model -PathType Leaf)) {
    throw 'The approved local Qwen3-4B-Q4_K_M.gguf file is missing. This script does not download models.'
}
if ((Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash.ToLowerInvariant() -ne $modelHash) {
    throw 'The local model SHA-256 does not match the approved official weight. Nothing was started.'
}

if (Test-Path -LiteralPath $runtimeDir) {
    if ((Get-Item -LiteralPath $runtimeDir).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'work/local-model is a link. Refusing to write service state or logs through it.'
    }
    $entries = @(Get-ChildItem -LiteralPath $runtimeDir -Force)
    if ($entries.Count -gt 0) {
        if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
            throw 'work/local-model contains files without an owned state record. Refusing to overwrite them.'
        }
        if (@($entries | Where-Object { $_.PSIsContainer -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $_.Name -notin @('server-state.json', 'server.stdout.log', 'server.stderr.log') }).Count -gt 0) {
            throw 'work/local-model contains unrecognized files or links. Refusing to overwrite the directory.'
        }
        try { $previous = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json }
        catch { throw 'The existing local service state is not readable JSON. Refusing to overwrite it.' }
        if ($previous.owner -ne $owner -or $previous.repo_root -ne $repoRoot -or
            $previous.executable -ne $exe -or $previous.model_path -ne $model -or
            $previous.model_sha256 -ne $modelHash -or $previous.run_id -notmatch '^[0-9a-f]{32}$' -or
            $previous.arguments -cne (Get-ModelArguments $previous.run_id) -or
            ($previous.pid -isnot [int] -and $previous.pid -isnot [long]) -or
            $previous.pid -le 0 -or $previous.pid -gt [int]::MaxValue) {
            throw 'The existing state does not belong to this approved local service. Refusing to overwrite it.'
        }
        if (Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $previous.pid)) {
            throw 'The recorded PID is active. It may belong to the previous service or a reused PID; inspect it before restarting.'
        }
    }
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$runId = [guid]::NewGuid().ToString('N')
$arguments = Get-ModelArguments $runId
$proc = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'server.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'server.stderr.log') -PassThru
# Open the process handle before recording its identity; keep it until setup ends.
$null = $proc.Handle
$processInfo = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $proc.Id)
if (-not $processInfo -or $processInfo.ExecutablePath -ne $exe -or
    -not $processInfo.CommandLine.EndsWith($arguments, [StringComparison]::Ordinal)) {
    throw 'The new process identity could not be verified. Existing processes were not touched; inspect local logs.'
}
$state = [ordered]@{
    owner = $owner
    repo_root = $repoRoot
    run_id = $runId
    pid = $proc.Id
    process_start_utc = $proc.StartTime.ToUniversalTime().ToString('o')
    process_start_ticks_utc = $proc.StartTime.ToUniversalTime().Ticks
    executable = $exe
    model_path = $model
    model_sha256 = $modelHash
    arguments = $arguments
    process_command_line = $processInfo.CommandLine
    endpoint = 'http://127.0.0.1:8766/v1'
    model_id = 'reviewproject-qwen3-4b-q4km'
    status = 'starting'
}
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8

$deadline = [DateTime]::UtcNow.AddSeconds(60)
while ([DateTime]::UtcNow -lt $deadline) {
    $proc.Refresh()
    if ($proc.HasExited) { throw 'The model process exited during startup. Inspect work/local-model logs locally.' }
    $listener = @(Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue)
    if ($listener.Count -gt 0) {
        if (@($listener | Where-Object { $_.OwningProcess -ne $proc.Id -or $_.LocalAddress -ne '127.0.0.1' }).Count -gt 0) {
            throw 'Port 8766 is owned by an unexpected process or address. No process was stopped.'
        }
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8766/health' -TimeoutSec 2
            if ($health.status -eq 'ok') {
                $state.status = 'ready'
                $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
                Write-Output ('Local model ready: http://127.0.0.1:8766/v1; model reviewproject-qwen3-4b-q4km; PID ' + $proc.Id)
                $proc.Dispose()
                return
            }
        } catch {
            # Loading commonly returns HTTP 503. Keep the owned state for safe stop/recovery.
        }
    }
    Start-Sleep -Milliseconds 250
}
$proc.Dispose()
throw 'Startup did not become healthy within 60 seconds. The owned process may still be loading; inspect local logs or use scripts/stop-local-model.ps1.'
} finally {
    if ($lockHeld) { $guard.ReleaseMutex() }
    $guard.Dispose()
}
