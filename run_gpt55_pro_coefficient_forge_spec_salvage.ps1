param(
    [switch]$DryRun,
    [int]$MaxOutputTokens = 6000
)

$ErrorActionPreference = 'Stop'

if (-not $DryRun -and [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw 'OPENAI_API_KEY is not set.'
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$promptPath = Join-Path $root 'gpt55-pro-coefficient-forge-spec-salvage-prompt.md'
$reasoningInputPath = Join-Path $root 'gpt55-pro-reasoning-summary-coefficient-forge-spec.md'
$reportPath = Join-Path $root 'gpt55-pro-report-coefficient-forge-spec.md'
$reasoningPath = Join-Path $root 'gpt55-pro-reasoning-summary-coefficient-forge-spec-salvage.md'
$responsePath = Join-Path $root 'gpt55-pro-response-coefficient-forge-spec-salvage.json'
$responseIdPath = Join-Path $root 'gpt55-pro-response-id-coefficient-forge-spec-salvage.txt'

foreach ($path in @($promptPath, $reasoningInputPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required input is missing: $path"
    }
}

$prompt = Get-Content -LiteralPath $promptPath -Raw
$savedReasoning = Get-Content -LiteralPath $reasoningInputPath -Raw
$fullPrompt = @"
$prompt

# Saved XHigh Reasoning Summary

$savedReasoning
"@

function Get-ReasoningSummary {
    param($Response)
    $parts = @()
    foreach ($item in @($Response.output)) {
        if ($item.type -eq 'reasoning') {
            foreach ($summary in @($item.summary)) {
                if (-not [string]::IsNullOrWhiteSpace($summary.text)) {
                    $parts += $summary.text
                }
            }
        }
    }
    $parts -join "`r`n`r`n"
}

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
    # The runner remains usable on machines without Python/tiktoken.
}

$body = @{
    model = 'gpt-5.5-pro'
    background = $true
    store = $true
    max_output_tokens = $MaxOutputTokens
    reasoning = @{
        effort = 'medium'
        summary = 'detailed'
    }
    text = @{
        verbosity = 'high'
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

Write-Host 'Submitting GPT-5.5 Pro DF2 Forge report salvage request...'
Write-Host 'Model:                 gpt-5.5-pro'
Write-Host 'Reasoning:             medium continuation over saved xhigh summary'
Write-Host 'Verbosity:             high'
Write-Host "Estimated text input:  ~$estimatedTextTokens tokens ($tokenEstimateKind)"
Write-Host "Max output+reasoning:  $MaxOutputTokens tokens"
Write-Host "Visible TPM reserve:   ~$($estimatedTextTokens + $MaxOutputTokens) tokens"
Write-Host "Serialized JSON bytes: $($jsonBytes.Length) (validated UTF-8)"

$visibleTpmCeiling = 18000
if (($estimatedTextTokens + $MaxOutputTokens) -gt $visibleTpmCeiling) {
    throw "Refusing to submit: visible text+output reserve $($estimatedTextTokens + $MaxOutputTokens) exceeds the conservative $visibleTpmCeiling-token ceiling. Slim the salvage input first."
}

if ($DryRun) {
    Write-Host 'Dry run only: no API request submitted.'
    exit 0
}

$response = Invoke-RestMethod -Method Post -Uri 'https://api.openai.com/v1/responses' -Headers $headers -ContentType 'application/json; charset=utf-8' -Body $jsonBytes
$response.id | Set-Content -LiteralPath $responseIdPath

Write-Host "Submitted:             $($response.id)"
Write-Host "Initial status:        $($response.status)"
Write-Host 'Polling every 15 seconds. You can stop safely; the response ID is saved.'

$lastSummary = ''
while ($response.status -in @('queued', 'in_progress')) {
    Start-Sleep -Seconds 15
    $response = Invoke-RestMethod -Method Get -Uri "https://api.openai.com/v1/responses/$($response.id)" -Headers $headers
    Write-Host "$(Get-Date -Format 'HH:mm:ss')  $($response.status)"
    $summary = Get-ReasoningSummary -Response $response
    if (-not [string]::IsNullOrWhiteSpace($summary) -and $summary -ne $lastSummary) {
        Write-Host ''
        Write-Host 'Reasoning summary update:'
        Write-Host $summary
        Write-Host ''
        $lastSummary = $summary
        $summary | Set-Content -LiteralPath $reasoningPath
    }
}

$response | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $responsePath
$summary = Get-ReasoningSummary -Response $response
if (-not [string]::IsNullOrWhiteSpace($summary)) {
    $summary | Set-Content -LiteralPath $reasoningPath
}

$report = Get-OutputText -Response $response
if (-not [string]::IsNullOrWhiteSpace($report)) {
    $report | Set-Content -LiteralPath $reportPath
    Write-Host "Recovered report:      $reportPath"
}
else {
    Write-Host 'No complete report message was present.'
}

if (Test-Path -LiteralPath $reasoningPath) {
    Write-Host "Reasoning summary:     $reasoningPath"
}

Write-Host "Request ended with status: $($response.status)"
Write-Host "Full response saved to:    $responsePath"

if ($response.status -eq 'failed') {
    throw "GPT-5.5 Pro salvage request failed. Inspect $responsePath"
}

