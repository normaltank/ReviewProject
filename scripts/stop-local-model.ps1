# Stop only the process created and identified by scripts/start-local-model.ps1.
[CmdletBinding()]
param(
    [string]$ExpectedRunId,
    [string]$ResourceRoot,
    [string]$RuntimeDir
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
if ($PSBoundParameters.ContainsKey('ExpectedRunId') -and $ExpectedRunId -cnotmatch '^[0-9a-f]{32}$') {
    throw 'E_MODEL_RUN_ID'
}
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $ResourceRoot) { $ResourceRoot = $repoRoot }
$ResourceRoot = (Resolve-Path -LiteralPath $ResourceRoot).Path
if (-not $RuntimeDir) { $RuntimeDir = Join-Path $repoRoot 'work/local-model' }
$runtimeDir = [IO.Path]::GetFullPath($RuntimeDir)
$exe = Join-Path $ResourceRoot '.tools/local-llm/llama-b12110-vulkan/llama-server.exe'
$statePath = Join-Path $runtimeDir 'server-state.json'
$guard = [Threading.Mutex]::new($false, 'Local\ReviewProjectLocalModel8766')
$lockHeld = $false
try {
try { $lockHeld = $guard.WaitOne(0) }
catch [Threading.AbandonedMutexException] { $lockHeld = $true }
if (-not $lockHeld) { throw 'Another local-model lifecycle command is running. No process was stopped.' }

if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    throw 'No owned work/local-model/server-state.json exists. No process was stopped.'
}
try { $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json }
catch { throw 'The local service state is not readable JSON. No process was stopped.' }
# GUI callers bind their own launch identity. Check while holding the lifecycle
# mutex, before looking up or stopping any process; a later run is never theirs.
if ($PSBoundParameters.ContainsKey('ExpectedRunId') -and $state.run_id -cne $ExpectedRunId) {
    throw 'E_MODEL_NOT_OWNED'
}
. (Join-Path $PSScriptRoot 'local-model-profile.ps1')
$modelId = 'reviewproject-qwen3-4b-q4km'
if ($state.PSObject.Properties.Name -contains 'profile_id') { $modelId = $state.profile_id }
$profile = Get-LocalModelProfile $modelId
if (-not (Test-LocalModelStateProfile $state $modelId)) { throw 'E_MODEL_PROFILE' }
$model = Join-Path $ResourceRoot ('.tools/local-llm/' + $profile.filename)
$expectedArguments = Get-LocalModelArguments $model $modelId $profile.context_tokens $state.run_id
if ($state.owner -ne 'ReviewProject/scripts/local-model/v1' -or $state.repo_root -ne $repoRoot -or
    $state.executable -ne $exe -or $state.model_path -ne $model -or
    $state.model_sha256 -ne $profile.sha256 -or
    $state.run_id -notmatch '^[0-9a-f]{32}$' -or $state.arguments -cne $expectedArguments -or
    ($state.pid -isnot [int] -and $state.pid -isnot [long]) -or
    $state.pid -le 0 -or $state.pid -gt [int]::MaxValue) {
    throw 'The state does not identify this approved local service. No process was stopped.'
}
$processInfo = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $state.pid)
if (-not $processInfo) {
    Write-Output 'The recorded local model process is already stopped.'
    return
}
$target = Get-Process -Id $state.pid
try {
    # Holding the handle also avoids targeting a later process with the same PID.
    $null = $target.Handle
    if ($processInfo.ExecutablePath -ne $exe -or
        $target.StartTime.ToUniversalTime().Ticks -ne $state.process_start_ticks_utc -or
        $processInfo.CommandLine -cne $state.process_command_line -or
        -not $processInfo.CommandLine.EndsWith($expectedArguments, [StringComparison]::Ordinal)) {
        throw 'The PID, creation time, executable or command target changed. Refusing to stop a reused or unrelated process.'
    }
    $listener = @(Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue)
    if (@($listener | Where-Object { $_.OwningProcess -ne $state.pid -or $_.LocalAddress -ne '127.0.0.1' }).Count -gt 0) {
        throw 'Port 8766 has an unexpected listener. No process was stopped.'
    }
    $target.Kill()
    if (-not $target.WaitForExit(10000)) { throw 'The identified process did not exit within 10 seconds.' }
    $state.status = 'stopped'
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
    Write-Output ('Stopped the recorded local model process, PID ' + $state.pid)
} finally {
    $target.Dispose()
}
} finally {
    if ($lockHeld) { $guard.ReleaseMutex() }
    $guard.Dispose()
}
