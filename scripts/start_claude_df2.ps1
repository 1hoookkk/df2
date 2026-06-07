param(
    [switch]$Health,
    [switch]$SkipHealth,
    [switch]$Normal,
    [switch]$FullTools,
    [switch]$Bare
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location -LiteralPath $root

$env:API_TIMEOUT_MS = "1200000"
Remove-Item Env:\CLAUDE_PROJECT_DIR -ErrorAction SilentlyContinue

if ($Health -and -not $SkipHealth) {
    & (Join-Path $root "scripts\check_claude_df2.ps1") -Fast
    Write-Host ""
}

Write-Host "Starting Claude Code in $root"
Write-Host "API_TIMEOUT_MS=$env:API_TIMEOUT_MS"
Write-Host "CLAUDE_PROJECT_DIR is intentionally unset; cwd is the project root."
if ($Normal) {
    Write-Host "Mode: normal Claude Code"
} elseif ($Bare) {
    Write-Host "Mode: bare lean DF2 session"
} else {
    Write-Host "Mode: OAuth-safe lean DF2 session"
}
Write-Host ""

if ($Normal) {
    & claude
} else {
    $promptPath = Join-Path $root "scripts\claude_df2_lean_prompt.txt"
    $leanPrompt = Get-Content -LiteralPath $promptPath -Raw
    $emptyMcpConfig = '{"mcpServers":{}}'
    $toolArgs = @()
    if (-not $FullTools) {
        $toolArgs = @("--tools", "Bash,Read,Edit,Write,Glob,Grep,LS")
    }
    $baseArgs = @(
        "--no-chrome",
        "--setting-sources", "local",
        "--strict-mcp-config",
        "--mcp-config", $emptyMcpConfig,
        "--exclude-dynamic-system-prompt-sections",
        "--append-system-prompt", $leanPrompt,
        "--add-dir", $root,
        "--name", "df2-lean"
    )

    if ($Bare) {
        if (-not $env:ANTHROPIC_API_KEY) {
            Write-Warning "Bare mode requires ANTHROPIC_API_KEY. Falling back to OAuth-safe lean mode."
        } else {
            $baseArgs = @("--bare") + $baseArgs
        }
    }

    & claude @toolArgs @baseArgs
}
