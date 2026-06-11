param(
    [switch]$DryRun,
    [int]$MaxOutputTokens = 5200
)

$ErrorActionPreference = 'Stop'

if (-not $DryRun -and [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw 'OPENAI_API_KEY is not set.'
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$promptPath = Join-Path $root 'gpt55-pro-coefficient-forge-spec-prompt.md'
$reportPath = Join-Path $root 'gpt55-pro-report-coefficient-forge-spec.md'
$reasoningPath = Join-Path $root 'gpt55-pro-reasoning-summary-coefficient-forge-spec.md'
$responsePath = Join-Path $root 'gpt55-pro-response-coefficient-forge-spec.json'
$responseIdPath = Join-Path $root 'gpt55-pro-response-id-coefficient-forge-spec.txt'

$observedInputs = @(
    'dev\tmp\p2k_reference_grammar\report.md'
    'dev\tmp\morph_designer_template_study\summary.md'
)

$excerptInputs = @(
    @{ classification = 'OBSERVED-RUNTIME'; path = 'trench-core\src\cascade.rs'; start = 1; count = 28 }
    @{ classification = 'OBSERVED-RUNTIME'; path = 'trench-core\src\cartridge.rs'; start = 301; count = 28 }
    @{ classification = 'OBSERVED-RE'; path = 'ref\ghidra_extracts\morphdesigner_types.md'; start = 1; count = 38 }
    @{ classification = 'OBSERVED-RE'; path = 'ref\ghidra_extracts\runtime_hacks.md'; start = 59; count = 36 }
    @{ classification = 'CANDIDATE-EXPLORATORY'; path = 'tools\voxbench.py'; start = 37; count = 82 }
)

$imageInputs = @(
    'dev\tmp\p2k_reference_grammar\foundations.png'
    'dev\tmp\p2k_reference_grammar\response_overview.png'
    'C:\Users\hooki\OneDrive\Pictures\Screenshots\Screenshot 2026-05-30 235748.png'
)

function Resolve-InputPath {
    param([string]$InputPath)
    if ([IO.Path]::IsPathRooted($InputPath)) {
        return $InputPath
    }
    Join-Path $root $InputPath
}

foreach ($inputPath in @($promptPath) + $observedInputs + @($excerptInputs | ForEach-Object { $_.path }) + $imageInputs) {
    $path = Resolve-InputPath -InputPath $inputPath
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
    $path = Resolve-InputPath -InputPath $RelativePath
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
    $path = Resolve-InputPath -InputPath $RelativePath
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

$fullPrompt = @"
$prompt

# Embedded Repo Evidence

$($evidence.ToString())
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
foreach ($inputPath in $imageInputs) {
    $path = Resolve-InputPath -InputPath $inputPath
    $content.Add(@{
        type = 'input_image'
        image_url = Convert-ImageToDataUrl -Path $path
        detail = 'low'
    })
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
}

Write-Host 'Submitting GPT-5.5 Pro DF2 private Forge stage-composer request...'
Write-Host 'Model:                 gpt-5.5-pro'
Write-Host "Reasoning:             xhigh"
Write-Host "Verbosity:             high"
Write-Host "Estimated text input:  ~$estimatedTextTokens tokens ($tokenEstimateKind) plus $($imageInputs.Count) low-detail plots"
Write-Host "Max output+reasoning:  $MaxOutputTokens tokens"
Write-Host "Visible TPM reserve:   ~$($estimatedTextTokens + $MaxOutputTokens) tokens before image and hidden-reasoning accounting"

$visibleTpmCeiling = 18000
if (($estimatedTextTokens + $MaxOutputTokens) -gt $visibleTpmCeiling) {
    throw "Refusing to submit: visible text+output reserve $($estimatedTextTokens + $MaxOutputTokens) exceeds the conservative $visibleTpmCeiling-token ceiling for a 50,000 TPM xhigh run. Slim the evidence pack first."
}

$jsonBody = $body | ConvertTo-Json -Depth 20 -Compress
# Windows PowerShell can send a string body using the active ANSI code page.
# This prompt intentionally contains Unicode punctuation, so send explicit
# UTF-8 bytes. Otherwise the Responses API receives invalid JSON byte sequences.
$jsonBytes = [Text.Encoding]::UTF8.GetBytes($jsonBody)

# Validate the exact byte payload locally before any network request.
$decodedJson = [Text.Encoding]::UTF8.GetString($jsonBytes)
$null = $decodedJson | ConvertFrom-Json
Write-Host "Serialized JSON bytes: $($jsonBytes.Length) (validated UTF-8)"

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
    throw "GPT-5.5 Pro request failed. Inspect $responsePath"
}
