param(
    [switch]$DryRun,
    [int]$MaxOutputTokens = 4500
)

$ErrorActionPreference = 'Stop'

if (-not $DryRun -and [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw 'OPENAI_API_KEY is not set.'
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$promptPath = Join-Path $root 'gpt55-pro-corner-authoring-algorithm-prompt.md'
$reportPath = Join-Path $root 'gpt55-pro-report-corner-authoring-algorithm.md'
$reasoningPath = Join-Path $root 'gpt55-pro-reasoning-summary-corner-authoring-algorithm.md'
$responsePath = Join-Path $root 'gpt55-pro-response-corner-authoring-algorithm.json'
$responseIdPath = Join-Path $root 'gpt55-pro-response-id-corner-authoring-algorithm.txt'
$retrySummaryPath = Join-Path $root 'gpt55-pro-retry-salvage-corner-authoring.md'

$observedInputs = @(
    'dev\tmp\p2k_talking_hedz_truth\manifest.json'
    'ref\p2k_variants\study_best_of_best\algorithm_prompt_digest_slim.json'
)

$excerptInputs = @(
    @{ classification = 'CANDIDATE-AUTHORING'; path = 'tools\corner_words.py'; start = 38; count = 58 }
    @{ classification = 'CANDIDATE-AUTHORING'; path = 'tools\corner_words.py'; start = 164; count = 65 }
    @{ classification = 'CANDIDATE-AUTHORING'; path = 'tools\corner_author.py'; start = 19; count = 73 }
    @{ classification = 'CANDIDATE-TESTS'; path = 'tools\test_corner_author.py'; start = 21; count = 34 }
    @{ classification = 'OBSERVED-RUNTIME'; path = 'trench-core\src\cascade.rs'; start = 1; count = 8 }
    @{ classification = 'OBSERVED-RUNTIME'; path = 'trench-core\src\minifloat.rs'; start = 138; count = 43 }
    @{ classification = 'OBSERVED-RUNTIME'; path = 'trench-core\src\minifloat.rs'; start = 249; count = 34 }
    @{ classification = 'OBSERVED-RUNTIME'; path = 'trench-core\src\cartridge.rs'; start = 303; count = 20 }
    @{ classification = 'OBSERVED-RUNTIME'; path = 'trench-core\src\ffi.rs'; start = 93; count = 13 }
    @{ classification = 'OBSERVED-RUNTIME'; path = 'trench-core\src\ffi.rs'; start = 165; count = 39 }
)

$imageInputs = @(
    'dev\tmp\p2k_talking_hedz_truth\talking_hedz_variant0_truth_sheet.png'
)

foreach ($relativePath in @($promptPath) + $observedInputs + @($excerptInputs | ForEach-Object { $_.path }) + $imageInputs) {
    $path = if ([IO.Path]::IsPathRooted($relativePath)) {
        $relativePath
    }
    else {
        Join-Path $root $relativePath
    }
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required input is missing: $path"
    }
}

$prompt = Get-Content -LiteralPath $promptPath -Raw
$evidence = [Text.StringBuilder]::new()

function Add-EvidenceFile {
    param(
        [string]$Classification,
        [string]$RelativePath
    )
    $path = Join-Path $root $RelativePath
    $body = Get-Content -LiteralPath $path -Raw
    [void]$evidence.AppendLine()
    [void]$evidence.AppendLine("===== BEGIN $Classification EVIDENCE: $RelativePath =====")
    [void]$evidence.AppendLine($body)
    [void]$evidence.AppendLine("===== END $Classification EVIDENCE: $RelativePath =====")
}

foreach ($relativePath in $observedInputs) {
    Add-EvidenceFile -Classification 'OBSERVED-INPUT' -RelativePath $relativePath
}

function Add-EvidenceExcerpt {
    param(
        [string]$Classification,
        [string]$RelativePath,
        [int]$Start,
        [int]$Count
    )
    $path = Join-Path $root $RelativePath
    $lines = @(Get-Content -LiteralPath $path)
    $first = [Math]::Max(1, $Start)
    $last = [Math]::Min($lines.Count, $first + $Count - 1)
    [void]$evidence.AppendLine()
    [void]$evidence.AppendLine("===== BEGIN $Classification EXCERPT: ${RelativePath}:${first}-${last} =====")
    for ($lineNumber = $first; $lineNumber -le $last; $lineNumber++) {
        [void]$evidence.AppendLine(("{0,5}: {1}" -f $lineNumber, $lines[$lineNumber - 1]))
    }
    [void]$evidence.AppendLine("===== END $Classification EXCERPT: ${RelativePath}:${first}-${last} =====")
}

foreach ($excerpt in $excerptInputs) {
    Add-EvidenceExcerpt `
        -Classification $excerpt.classification `
        -RelativePath $excerpt.path `
        -Start $excerpt.start `
        -Count $excerpt.count
}

$retrySummary = ''
if (Test-Path -LiteralPath $retrySummaryPath) {
    $retrySummary = Get-Content -LiteralPath $retrySummaryPath -Raw
}

$fullPrompt = @"
$prompt

# Embedded Repo Evidence

$($evidence.ToString())

# Incomplete Prior Reasoning Summary

The previous background request failed at the API TPM gate after producing the
following incomplete reasoning summary. It is salvage context, NOT evidence and
NOT doctrine. Correct it where necessary, then finish the requested deliverable.

$retrySummary
"@

function Convert-ImageToDataUrl {
    param([string]$Path)
    $bytes = [IO.File]::ReadAllBytes($Path)
    $base64 = [Convert]::ToBase64String($bytes)
    "data:image/png;base64,$base64"
}

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

$content = [Collections.Generic.List[object]]::new()
$content.Add(@{ type = 'input_text'; text = $fullPrompt })
foreach ($relativePath in $imageInputs) {
    $path = Join-Path $root $relativePath
    $content.Add(@{
        type = 'input_image'
        image_url = Convert-ImageToDataUrl -Path $path
        detail = 'low'
    })
}

$maxOutputTokens = $MaxOutputTokens
$roughTextTokens = [Math]::Ceiling($fullPrompt.Length / 4)
$estimatedTextTokens = $roughTextTokens
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
    max_output_tokens = $maxOutputTokens
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
            content = $content
        }
    )
}

$headers = @{
    Authorization = "Bearer $env:OPENAI_API_KEY"
    'Content-Type' = 'application/json'
}

Write-Host 'Submitting GPT-5.5 Pro DF2 definitive corner-authoring algorithm request...'
Write-Host 'Model:                 gpt-5.5-pro'
Write-Host "Estimated text input:  ~$estimatedTextTokens tokens ($tokenEstimateKind) plus $($imageInputs.Count) truth plots"
Write-Host "Max output+reasoning:  $maxOutputTokens tokens"
Write-Host "Visible TPM reserve:   ~$($estimatedTextTokens + $maxOutputTokens) tokens before image and hidden-reasoning accounting"

$visibleTpmCeiling = 18000
if (($estimatedTextTokens + $maxOutputTokens) -gt $visibleTpmCeiling) {
    throw "Refusing to submit: visible text+output reserve $($estimatedTextTokens + $maxOutputTokens) exceeds the conservative $visibleTpmCeiling-token ceiling for a 50,000 TPM xhigh run. Slim the evidence pack first."
}

if ($DryRun) {
    Write-Host "Estimated text+output: ~$($estimatedTextTokens + $maxOutputTokens) tokens before image accounting"
    Write-Host 'Dry run only: no API request submitted.'
    exit 0
}

$jsonBody = $body | ConvertTo-Json -Depth 20 -Compress
$response = Invoke-RestMethod -Method Post -Uri 'https://api.openai.com/v1/responses' -Headers $headers -Body $jsonBody
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

if ($response.status -eq 'failed' -and -not [string]::IsNullOrWhiteSpace($report)) {
    Write-Warning "The outer response ended as 'failed', but a complete message was present and recovered. Inspect the report before deciding whether to retry."
}
