$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw 'OPENAI_API_KEY is not set.'
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$reportPath = Join-Path $root 'gpt55-pro-report-ui-pass.md'
$reasoningPath = Join-Path $root 'gpt55-pro-reasoning-summary-ui-pass.md'
$responsePath = Join-Path $root 'gpt55-pro-response-ui-pass.json'
$responseIdPath = Join-Path $root 'gpt55-pro-response-id-ui-pass.txt'
$destructionPath = Join-Path $root 'gpt55-pro-report-destruction.md'
$quarryPath = Join-Path $root 'CORNER_QUARRY_TRUTH.md'
$imagePaths = @(
    'C:\Users\hooki\OneDrive\Pictures\Screenshots\Screenshot 2026-05-30 235440.png'
    'C:\Users\hooki\OneDrive\Pictures\Screenshots\Screenshot 2026-05-30 235748.png'
    'C:\Users\hooki\OneDrive\Pictures\Screenshots\Screenshot 2026-05-31 183534.png'
    'C:\Users\hooki\OneDrive\Pictures\Screenshots\Screenshot 2026-05-31 175324.png'
)

foreach ($path in @($destructionPath, $quarryPath) + $imagePaths) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required input is missing: $path"
    }
}

$destruction = Get-Content -LiteralPath $destructionPath -Raw
$quarry = Get-Content -LiteralPath $quarryPath -Raw

$prompt = @"
You are the independent product-design judge for a private desktop authoring app called DF2 Forge.

This is one focused UX pass. Do not write code. Do not create implementation phases. Do not restate the supplied reports. Do not design the shipped plugin UI. Evaluate the private authoring experience used by one expert to create a small set of extreme, commercially distinctive morphing-filter presets and record short-form video content while doing it.

The four attached screenshots are evidence from the old Forge. Inspect them closely and judge them on their merits. Do not assume that any visible element, interaction pattern, layout, or visual style must survive. The author felt that parts of this old interface were unusually understandable and musically direct, but that is an observation to investigate rather than a design instruction.

Two reports follow. Treat them as technical context. Decide for yourself which implications belong in the visible experience and which should remain hidden:

<BODY_ARCHITECTURE_REPORT>
$destruction
</BODY_ARCHITECTURE_REPORT>

<CORNER_QUARRY_REPORT>
$quarry
</CORNER_QUARRY_REPORT>

The design problem:

The author is considering the following ideas. None is mandatory. Challenge, replace, combine, or reject them when a stronger answer exists:

- A sequential preset-engineering experience, possibly inspired by the clarity of Blender workflows with purposeful sections.
- A simple corner picker, possibly using a 2D low-to-high and closed-to-open space.
- Plain language rather than DSP terminology.
- Physical bodies, objects, or materials as memorable family metaphors.
- A deliberately simple mental taxonomy that may still retrieve the full sonic spectrum.
- Extreme results: vocal-tract motion, unstable resonant edges, impossible physical objects, violent transformations, and unusual high-impact presets. The ambition is to create original results with the impact associated with famous extreme morphing filters, without copying third-party assets or importing their naming systems.
- A visually impactful and confident aesthetic suitable for recording short-form content.
- A possible 60:30:10 color-allocation strategy. Evaluate whether this is useful. If it is, choose the actual palette and explain its function. If it is not, replace it with a better color strategy.
- The usability and functional clarity expected from mature audio tools, without copying an existing product.

Your job is to find the strongest visible UX from first principles. Nothing about the old Forge, the reports, or the author's current ideas is immune from critique. Do not comply with an idea merely because it was suggested.

Required deliverables:

1. TEARDOWN: explain how a UI can become over-abstracted even when the hidden architecture is correct. Identify the relevant failure modes in this project.

2. OLD FORGE EVIDENCE REVIEW: inspect each screenshot and identify what works, what fails, what is ambiguous, what deserves preservation, and what should be discarded. Do not preserve elements out of nostalgia.

3. ONE-SENTENCE UX PRINCIPLE: derive the rule that should govern every visible feature.

4. WORKFLOW VERDICT: decide whether a Blender-like sequence of sections is the best visible model. If yes, define the minimum useful sections, give them plain-language names, and explain the single musical question answered by each one. If no, provide a better model.

5. EXACT PRESET-BUILDING SEQUENCE: walk through one authoring session from opening the app to keeping or rejecting one preset. Every step must identify what the author sees, what they do, what they hear, and why the step exists. Keep it concrete.

6. TAXONOMY VERDICT: decide whether a visible 2D low-to-high and closed-to-open picker is the strongest simple retrieval model. If it is, define it precisely. If it is not, replace it. Propose the smallest useful mental taxonomy, test whether it covers the full sonic spectrum, identify missing regions, and explain how memorable visual identities could attach to it without pretending that the taxonomy is mathematical truth.

7. CONTEXTUAL DEPTH: decide how deeper operations such as midpoint checks, secondary behavior, audition comparisons, and body approval should appear, if they should appear at all.

8. VISUAL LANGUAGE: propose one visually impactful and confident aesthetic direction suitable for screen recording. Specify hierarchy, graph treatment if appropriate, color logic, typography character, motion, and the dominant visual subject. Evaluate the 60:30:10 idea and define the palette only if it strengthens the result. Do not assume light mode, dark mode, or any specific accent color.

9. OPPORTUNITY AUDIT: identify the most important overlooked opportunities. Challenge the user's assumptions where needed. Prioritize only ideas that materially improve sound discovery, author speed, or short-form content.

10. DO NOT BUILD: based on your analysis, provide a strict list of visible features, screens, panels, abstractions, and taxonomies that should not be built.

11. FINAL BLUEPRINT: provide the smallest concrete screen model and navigation model that should guide a later visual design pass. This is a UX specification, not a mockup and not code.

Use OBSERVED, INFERRED, and SPECULATIVE labels where appropriate. Be decisive. Favor directness over exhaustive formatting.

CRITICAL INDEPENDENCE REQUIREMENT:
Do not rubber-stamp the reports, the screenshots, or the author's suggestions. Do not turn internal architecture into visible workflow merely because the reports name it. Do not assume the old Forge should be preserved, and do not assume it should be discarded. Do not prescribe implementation work. Produce one independent, concrete UX judgment and end with one firm recommendation.
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
$content.Add(@{ type = 'input_text'; text = $prompt })
foreach ($imagePath in $imagePaths) {
    $content.Add(@{
        type = 'input_image'
        image_url = Convert-ImageToDataUrl -Path $imagePath
        detail = 'high'
    })
}

$maxOutputTokens = 24000
$estimatedTextTokens = [Math]::Ceiling($prompt.Length / 4)
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

Write-Host 'Submitting one focused GPT-5.5 Pro visible-Forge UX request...'
Write-Host 'Model:                 gpt-5.5-pro'
Write-Host "Estimated text input:  ~$estimatedTextTokens tokens plus 4 high-detail screenshots"
Write-Host "Max output+reasoning:  $maxOutputTokens tokens"

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
