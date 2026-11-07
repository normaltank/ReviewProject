# Store a project-only API credential using the current Windows user's DPAPI.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$directory = Join-Path $repo '.tools/credentials'
$target = Join-Path $directory 'deepseek-api-key.dpapi'
foreach ($candidate in @((Join-Path $repo '.tools'), $directory, $target)) {
    if ((Test-Path -LiteralPath $candidate) -and
        ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Refusing to store a credential through a linked path.'
    }
}
if (Test-Path -LiteralPath $target) {
    throw 'A project credential already exists; it was preserved.'
}
$secret = Read-Host 'DeepSeek API key (hidden)' -AsSecureString
if ($secret.Length -lt 16) { throw 'Credential was not stored: input is too short.' }
$encrypted = ConvertFrom-SecureString -SecureString $secret
[IO.Directory]::CreateDirectory($directory) | Out-Null
$stream = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
    $bytes = [Text.Encoding]::UTF8.GetBytes($encrypted)
    $stream.Write($bytes, 0, $bytes.Length)
}
finally { $stream.Dispose(); $secret.Dispose() }
Write-Output 'Stored the project credential encrypted for the current Windows user. No API request was made.'
