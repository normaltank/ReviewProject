# Shared fixed catalog and canonical command identity. No download capability.
function Get-LocalModelProfile([string]$ModelId) {
    $catalogPath = Join-Path $PSScriptRoot '../reviewproto/local_model_profiles.json'
    $catalog = Get-Content -LiteralPath $catalogPath -Raw | ConvertFrom-Json
    $property = @($catalog.profiles.PSObject.Properties | Where-Object { $_.Name -ceq $ModelId })
    if ($property.Count -ne 1) { throw 'E_MODEL_PROFILE' }
    return $property[0].Value
}

function Get-LocalModelArguments([string]$modelPath, [string]$modelId, [int]$contextTokens, [string]$runId) {
    return '-m "' + $modelPath + '" --alias ' + $modelId + ' --tags reviewproject-local-run-' + $runId + ' --host 127.0.0.1 --port 8766 --cors-origins localhost -c ' + $contextTokens + ' -np 1 -ngl 99 --device Vulkan0 --reasoning off --offline --no-webui --no-slots --no-cache-prompt --cache-ram 0 --log-colors off'
}

function Test-LocalModelStateProfile($state, [string]$modelId) {
    if ($state.PSObject.Properties.Name -contains 'model_id' -and $state.model_id -cne $modelId) { return $false }
    # Receipts made before profiles existed describe only the legacy 4B model.
    if ($state.PSObject.Properties.Name -contains 'profile_id') {
        if ($state.profile_id -cne $modelId -or $state.model_id -cne $modelId) { return $false }
        $p = Get-LocalModelProfile $modelId
        if ($state.model_size -ne $p.size) { return $false }
    } elseif ($modelId -cne 'reviewproject-qwen3-4b-q4km') { return $false }
    return $true
}
