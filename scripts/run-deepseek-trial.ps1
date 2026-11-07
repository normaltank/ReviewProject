# Run exactly one item from an approved, hash-bound Flash trial plan.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Plan,
    [Parameter(Mandatory=$true)][string]$Approval,
    [Parameter(Mandatory=$true)][string]$Item,
    [string]$RunId = '',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repo '.tools/semantic-env/Scripts/python.exe'
$planPath = (Resolve-Path -LiteralPath $Plan).Path
$approvalPath = (Resolve-Path -LiteralPath $Approval).Path
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Install requirements-model.txt in .tools/semantic-env first.' }
$previousPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
$previousDsKey = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'Process')
$secret = $null
$credential = $null
try {
    $env:PYTHONPATH = $repo
    # Validation uses the same source/partition/approval checks as the client,
    # before this launcher decrypts any credential. This makes no API request.
    & $python -B -c 'import json,sys; from experiments.deepseek_trial import validate_plan; p=validate_plan(sys.argv[1],sys.argv[2],sys.argv[3]); print(json.dumps({"approved_item":p[1]["alias"],"model":p[0]["model"],"inference_requests":0,"check_only":True}))' $planPath $approvalPath $Item
    if ($LASTEXITCODE -ne 0) { throw 'Trial preflight failed; no credential was decrypted and no API request was made.' }
    if ($CheckOnly) { return }
    $keyPath = Join-Path $repo '.tools/credentials/deepseek-api-key.dpapi'
    $secret = ConvertTo-SecureString (Get-Content -LiteralPath $keyPath -Raw)
    $credential = [Management.Automation.PSCredential]::new('deepseek', $secret)
    $env:DEEPSEEK_API_KEY = $credential.GetNetworkCredential().Password
    $arguments = @('-B', (Join-Path $repo 'experiments/deepseek_trial.py'), '--plan', $planPath,
                   '--approval', $approvalPath, '--item', $Item)
    if ($RunId) { $arguments += @('--run-id', $RunId) }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'The trial is partial or failed; inspect its local artifacts before any further run.' }
}
finally {
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $previousPythonPath, 'Process')
    [Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', $previousDsKey, 'Process')
    $credential = $null
    if ($secret) { $secret.Dispose() }
}
