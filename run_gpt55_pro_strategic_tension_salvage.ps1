param(
    [switch]$DryRun,
    [int]$MaxOutputTokens = 1800,
    [int]$CooldownSeconds = 75
)

$ErrorActionPreference = 'Stop'

if (-not $DryRun -and [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw 'OPENAI_API_KEY is not set.'
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$promptPath = Join-Path $root 'gpt55-pro-strategic-tension-salvage-prompt.md'
$partialReportPath = Join-Path $root 'gpt55-pro-report-strategic-tension.md'
$reasoningInputPath = Join-Path $root 'gpt55-pro-reasoning-summary-strategic-tension.md'
$tailPath = Join-Path $root 'gpt55-pro-report-strategic-tension-tail.md'
$responsePath = Join-Path $root 'gpt55-pro-response-strategic-tension-salvage.json'
$responseIdPath = Join-Path $root 'gpt55-pro-response-id-strategic-tension-salvage.txt'

foreach ($path in @($promptPath, $partialReportPath, $reasoningInputPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required input is missing: $path"
    }
}

$prompt = Get-Content -LiteralPath $promptPath -Raw
$partialReport = Get-Content -LiteralPath $partialReportPath -Raw
$savedReasoning = Get-Content -LiteralPath $reasoningInputPath -Raw
$fullPrompt = @"
$prompt

$partialReport

# Saved Reasoning Summary

$savedReasoning
"@

function Get-OutputText {
    param($Response)
    $parts = @()
    foreach ($item in @($Response.output)) {
        if ($item.type -eq 'message') {
            foreach ($content in @($item.content)) {
                if ($content.type -eq 'output_text' -and -not [string]::IsNullOrWhiteSpace($content.text)) {
                    $parts += $content.text
                }
            }
        }
    }
    $parts -join "`r`n`r`n"
}

$estimatedTextTokens = [Math]::Ceiling($fullPrompt.Length / 4)
$tokenEstimateKind = 'rough chars/4'
try {
    $tokenizedTextTokens = $fullPrompt | python -c "import sys, tiktoken; print(len(tiktoken.get_encoding('o200k_base').encode(sys.stdin.read())))"
    if ($LASTEXITCODE -eq 0 -and $tokenizedTextTokens -match '^\d+$') {
        $estimatedTextTokens = [int]$tokenizedTextTokens
        $tokenEstimateKind = 'o200k tokenizer'
    }
}
catch {
    # The runner remains usable without Python/tiktoken.
}

$body = @{
    model = 'gpt-5.5-pro'
    background = $true
    store = $true
    max_output_tokens = $MaxOutputTokens
    reasoning = @{
        effort = 'medium'
        summary = 'auto'
    }
    text = @{
        verbosity = 'medium'
    }
    input = @(
        @{
            role = 'user'
            content = @(
                @{
                    type = 'input_text'
                    text = $fullPrompt
                }
            )
        }
    )
}

$headers = @{
    Authorization = "Bearer $env:OPENAI_API_KEY"
}

$jsonBody = $body | ConvertTo-Json -Depth 20 -Compress
$jsonBytes = [Text.Encoding]::UTF8.GetBytes($jsonBody)
$decodedJson = [Text.Encoding]::UTF8.GetString($jsonBytes)
$null = $decodedJson | ConvertFrom-Json

Write-Host 'Submitting GPT-5.5 Pro DF2 strategic-tension tail salvage...'
Write-Host 'Model:                 gpt-5.5-pro'
Write-Host 'Reasoning:             medium continuation'
Write-Host 'Verbosity:             medium'
Write-Host "Estimated text input:  ~$estimatedTextTokens tokens ($tokenEstimateKind)"
Write-Host "Max output+reasoning:  $MaxOutputTokens tokens"
Write-Host "Serialized JSON bytes: $($jsonBytes.Length) (validated UTF-8)"

if ($DryRun) {
    Write-Host 'Dry run only: no API request submitted.'
    exit 0
}

if ($CooldownSeconds -gt 0) {
    Write-Host "Cooling down for $CooldownSeconds seconds to clear the TPM window..."
    Start-Sleep -Seconds $CooldownSeconds
}

$response = Invoke-RestMethod -Method Post -Uri 'https://api.openai.com/v1/responses' -Headers $headers -ContentType 'application/json; charset=utf-8' -Body $jsonBytes
$response.id | Set-Content -LiteralPath $responseIdPath

Write-Host "Submitted:             $($response.id)"
Write-Host "Initial status:        $($response.status)"
Write-Host 'Polling every 15 seconds. You can stop safely; the response ID is saved.'

while ($response.status -in @('queued', 'in_progress')) {
    Start-Sleep -Seconds 15
    $response = Invoke-RestMethod -Method Get -Uri "https://api.openai.com/v1/responses/$($response.id)" -Headers $headers
    Write-Host "$(Get-Date -Format 'HH:mm:ss')  $($response.status)"
}

$response | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $responsePath
$tail = Get-OutputText -Response $response
if (-not [string]::IsNullOrWhiteSpace($tail)) {
    $tail | Set-Content -LiteralPath $tailPath
    Write-Host "Recovered tail:        $tailPath"
}
else {
    Write-Host 'No complete tail message was present.'
}

Write-Host "Request ended with status: $($response.status)"
Write-Host "Full response saved to:    $responsePath"

if ($response.status -ne 'completed') {
    throw "GPT-5.5 Pro salvage request ended with status '$($response.status)'. Inspect $responsePath"
}
