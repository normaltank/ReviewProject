[CmdletBinding()]
param(
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$check = @'
import importlib.metadata
import os
from pathlib import Path
import shutil
import sys
import unittest

print(f"Python: {sys.version}", flush=True)
print(f"Interpreter: {sys.executable}", flush=True)
if os.name != 'nt' or not shutil.which('pwsh') or not shutil.which('powershell.exe'):
    sys.exit('CHECK FAILED: Windows, PowerShell 7 (pwsh), and Windows PowerShell are required.')
if 'REVIEW_BROWSER_BINARY' in os.environ:
    binary = os.environ['REVIEW_BROWSER_BINARY']
    if not binary or not Path(binary).is_file():
        sys.exit('CHECK FAILED: explicit REVIEW_BROWSER_BINARY must point to an existing Chromium/Chrome/Edge executable.')
else:
    candidates = [Path(base) / relative
                  for variable in ('ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA')
                  if (base := os.environ.get(variable))
                  for relative in ('Google/Chrome/Application/chrome.exe', 'Microsoft/Edge/Application/msedge.exe')]
    binary = next((str(path) for path in candidates if path.is_file()), '')
    if not binary:
        sys.exit('CHECK FAILED: no installed Chrome/Edge found; set REVIEW_BROWSER_BINARY. UI checks must not skip.')
    os.environ['REVIEW_BROWSER_BINARY'] = binary
print(f"Browser: {binary}", flush=True)
try:
    from playwright.sync_api import sync_playwright
    print(f"Playwright: {importlib.metadata.version('playwright')}", flush=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=binary, headless=True)
        print(f"Browser version: {browser.version}", flush=True)
        browser.close()
except Exception as error:
    sys.exit(f'CHECK FAILED: browser preflight: {error}')

suite = unittest.defaultTestLoader.discover('tests')
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(f'CHECK SUMMARY: ran={result.testsRun} failures={len(result.failures)} '
      f'errors={len(result.errors)} skipped={len(result.skipped)}', flush=True)
for test, reason in result.skipped:
    print(f'CHECK INCOMPLETE: {test}: {reason}', flush=True)
if result.testsRun == 0 or result.skipped or not result.wasSuccessful():
    sys.exit(1)
'@

Push-Location -LiteralPath $repoRoot
try {
    # Stream output and preserve the selected interpreter's actual exit status.
    $check | & $Python -
    $checkExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $checkExitCode
