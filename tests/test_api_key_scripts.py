"""Windows-only secret storage regression using an invented key in a temp repo."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class SecretStorageTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell 7 needed for DPAPI')
    def test_encrypted_roundtrip_and_existing_key_preserved_without_echo(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / 'scripts').mkdir()
            shutil.copyfile(root / 'scripts/set-deepseek-key.ps1', folder / 'scripts/set-deepseek-key.ps1')
            harness = folder / 'verify.ps1'
            harness.write_text('''$ErrorActionPreference='Stop'
function global:Read-Host { param([string]$Prompt,[switch]$AsSecureString)
    ConvertTo-SecureString 'synthetic-not-a-real-key' -AsPlainText -Force
}
$null = & (Join-Path $PSScriptRoot 'scripts/set-deepseek-key.ps1')
$path = Join-Path $PSScriptRoot '.tools/credentials/deepseek-api-key.dpapi'
$before = Get-Content -LiteralPath $path -Raw
$secure = ConvertTo-SecureString $before
$credential = [Management.Automation.PSCredential]::new('test', $secure)
$equal = $credential.GetNetworkCredential().Password -ceq 'synthetic-not-a-real-key'
$refused = $false
try { $null = & (Join-Path $PSScriptRoot 'scripts/set-deepseek-key.ps1') }
catch { $refused = $true }
$after = Get-Content -LiteralPath $path -Raw
$secure.Dispose()
@{encrypted=($before -notlike '*synthetic-not-a-real-key*'); roundtrip=$equal; preserved=($refused -and $before -ceq $after)} | ConvertTo-Json -Compress
''', encoding='utf-8')
            result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(harness)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('synthetic-not-a-real-key', result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), {'encrypted': True, 'roundtrip': True, 'preserved': True})
