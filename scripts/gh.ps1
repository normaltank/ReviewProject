[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GhArgs
)

$ErrorActionPreference = 'Stop'
$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0) { throw 'Run this helper from inside the project repository.' }
$installedGh = Get-Command gh -CommandType Application -ErrorAction SilentlyContinue
$ghExecutable = if ($installedGh) { $installedGh.Source } else { Join-Path $repoRoot '.tools/github-cli/bin/gh.exe' }
if (-not (Test-Path -LiteralPath $ghExecutable)) { throw 'GitHub CLI is missing. Install the official GitHub CLI, or restore the local portable installation.' }

$previousGhToken = $env:GH_TOKEN
$previousGcmInteractive = $env:GCM_INTERACTIVE
$previousGitPrompt = $env:GIT_TERMINAL_PROMPT
$ghExitCode = 1
try {
    if (-not $env:GH_TOKEN -and -not $env:GITHUB_TOKEN) {
        & $ghExecutable auth status --hostname github.com *> $null
        if ($LASTEXITCODE -ne 0) {
            $env:GCM_INTERACTIVE = 'never'
            $env:GIT_TERMINAL_PROMPT = '0'
            $credentialLines = "protocol=https`nhost=github.com`n`n" | & git credential fill 2>$null
            if ($LASTEXITCODE -ne 0) { throw 'No existing GitHub login is available. Run gh auth login, then retry.' }
            $passwordLine = @($credentialLines | Where-Object { $_.StartsWith('password=') })
            if ($passwordLine.Count -ne 1) { throw 'GitHub authentication was unavailable. Run gh auth login, then retry.' }
            $env:GH_TOKEN = $passwordLine[0].Substring('password='.Length)
            $credentialLines = $null
            $passwordLine = $null
        }
    }
    & $ghExecutable @GhArgs
    $ghExitCode = $LASTEXITCODE
}
finally {
    $env:GH_TOKEN = $previousGhToken
    $env:GCM_INTERACTIVE = $previousGcmInteractive
    $env:GIT_TERMINAL_PROMPT = $previousGitPrompt
}
exit $ghExitCode
