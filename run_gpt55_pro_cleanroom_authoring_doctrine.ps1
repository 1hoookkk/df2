param(
    [switch]$DryRun,
    [int]$MaxOutputTokens = 5600,
    [int]$CooldownSeconds = 90
)

$ErrorActionPreference = 'Stop'

if (-not $DryRun -and [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw 'OPENAI_API_KEY is not set.'
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$promptPath = Join-Path $root 'gpt55-pro-cleanroom-authoring-doctrine-prompt.md'
$reportPath = Join-Path $root 'gpt55-pro-report-cleanroom-authoring-doctrine.md'
$reasoningPath = Join-Path $root 'gpt55-pro-reasoning-summary-cleanroom-authoring-doctrine.md'
$responsePath = Join-Path $root 'gpt55-pro-response-cleanroom-authoring-doctrine.json'
$responseIdPath = Join-Path $root 'gpt55-pro-response-id-cleanroom-authoring-doctrine.txt'

$fullEvidenceFiles = @(
    @{ classification = 'OBSERVED-RE'; path = 'ref\ghidra_extracts\morphdesigner_types.md' }
    @{ classification = 'OBSERVED-MORPH-DESIGNER'; path = 'dev\tmp\morph_designer_template_study\summary.md' }
)

$evidenceExcerpts = @(
    @{ classification = 'OBSERVED-RE'; path = 'ref\ghidra_extracts\runtime_hacks.md'; start = 1; count = 86 }
    @{ classification = 'OBSERVED-REFERENCE-REDUCTION'; path = 'dev\tmp\p2k_reference_fundamentals\report.md'; start = 1; count = 17 }
    @{ classification = 'OBSERVED-REFERENCE-REDUCTION'; path = 'dev\tmp\p2k_reference_fundamentals\report.md'; start = 205; count = 40 }
    @{ classification = 'CLEAN-ROOM-PUBLIC-LAW-TABLE'; path = 'tables\vowel_formants.json'; start = 1; count = 76 }
    @{ classification = 'CLEAN-ROOM-PUBLIC-LAW-TABLE'; path = 'tables\tube_resonances.json'; start = 1; count = 48 }
    @{ classification = 'CLEAN-ROOM-PUBLIC-LAW-TABLE'; path = 'tables\metallic_modes.json'; start = 1; count = 76 }
)

function Resolve-InputPath {
    param([string]$InputPath)
    if ([IO.Path]::IsPathRooted($InputPath)) {
        return $InputPath
    }
    Join-Path $root $InputPath
}

foreach ($inputPath in @($promptPath) + @($fullEvidenceFiles | ForEach-Object { $_.path }) + @($evidenceExcerpts | ForEach-Object { $_.path })) {
    $path = Resolve-InputPath -InputPath $inputPath
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required input is missing: $path"
    }
}

$prompt = Get-Content -LiteralPath $promptPath -Raw
$evidence = [Text.StringBuilder]::new()

foreach ($entry in $fullEvidenceFiles) {
    $path = Resolve-InputPath -InputPath $entry.path
    $body = Get-Content -LiteralPath $path -Raw
    [void]$evidence.AppendLine()
    [void]$evidence.AppendLine("===== BEGIN $($entry.classification) EVIDENCE: $($entry.path) =====")
    [void]$evidence.AppendLine($body)
    [void]$evidence.AppendLine("===== END $($entry.classification) EVIDENCE: $($entry.path) =====")
}

foreach ($excerpt in $evidenceExcerpts) {
    $path = Resolve-InputPath -InputPath $excerpt.path
    $lines = @(Get-Content -LiteralPath $path)
    $first = [Math]::Max(1, [int]$excerpt.start)
    $last = [Math]::Min($lines.Count, $first + [int]$excerpt.count - 1)
    [void]$evidence.AppendLine()
    [void]$evidence.AppendLine("===== BEGIN $($excerpt.classification) EXCERPT: $($excerpt.path):${first}-${last} =====")
    for ($lineNumber = $first; $lineNumber -le $last; $lineNumber++) {
        [void]$evidence.AppendLine(("{0,5}: {1}" -f $lineNumber, $lines[$lineNumber - 1]))
    }
    [void]$evidence.AppendLine("===== END $($excerpt.classification) EXCERPT: $($excerpt.path):${first}-${last} =====")
}

$fullPrompt = @"
$prompt

# Embedded Evidence

$($evidence.ToString())
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
    # The runner remains usable without Python/tiktoken.
}

$body = @{
    model = 'gpt-5.5-pro'
    background = $true
    store = $true
    max_output_tokens = $MaxOutputTokens
    reasoning = @{
        effort = 'xhigh'
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

Write-Host 'Submitting GPT-5.5 Pro DF2 clean-room authoring doctrine request...'
Write-Host 'Model:                 gpt-5.5-pro'
Write-Host 'Reasoning:             xhigh'
Write-Host 'Verbosity:             high'
Write-Host "Estimated text input:  ~$estimatedTextTokens tokens ($tokenEstimateKind)"
Write-Host "Max output+reasoning:  $MaxOutputTokens tokens"
Write-Host "Serialized JSON bytes: $($jsonBytes.Length) (validated UTF-8)"

$visibleTpmCeiling = 22000
if (($estimatedTextTokens + $MaxOutputTokens) -gt $visibleTpmCeiling) {
    throw "Refusing to submit: visible text+output reserve $($estimatedTextTokens + $MaxOutputTokens) exceeds the conservative $visibleTpmCeiling-token ceiling. Slim the evidence pack first."
}

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

if ($response.status -ne 'completed') {
    throw "GPT-5.5 Pro request ended with status '$($response.status)'. Inspect $responsePath"
}
