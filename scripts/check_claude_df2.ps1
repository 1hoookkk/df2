param(
    [switch]$Detailed,
    [switch]$Fast
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location -LiteralPath $root

$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$freeRamGb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$totalRamGb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 2)
$uptimeHours = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1)

$trackedChanges = "skipped"
if (-not $Fast) {
    try {
        $trackedChanges = (git status --short -uno | Measure-Object).Count
    } catch {
        $trackedChanges = -1
    }
}

$claude = Get-Command claude -ErrorAction SilentlyContinue
$claudeVersion = if ($Fast -and $claude) {
    "found"
} elseif ($claude) {
    try { (& claude --version 2>$null | Select-Object -First 1) } catch { "unknown" }
} else {
    "not found"
}

$userApiTimeout = [Environment]::GetEnvironmentVariable("API_TIMEOUT_MS", "User")
$processApiTimeout = [Environment]::GetEnvironmentVariable("API_TIMEOUT_MS", "Process")
$userProjectDir = [Environment]::GetEnvironmentVariable("CLAUDE_PROJECT_DIR", "User")
$processProjectDir = [Environment]::GetEnvironmentVariable("CLAUDE_PROJECT_DIR", "Process")

Write-Host "DF2 Claude health"
Write-Host "---------------"
Write-Host "Root:              $root"
Write-Host "Claude:            $claudeVersion"
Write-Host "RAM free/total:    $freeRamGb GB / $totalRamGb GB"
Write-Host "Uptime:            $uptimeHours hours"
Write-Host "Tracked changes:   $trackedChanges"
Write-Host "API_TIMEOUT user:  $userApiTimeout"
Write-Host "API_TIMEOUT proc:  $processApiTimeout"
Write-Host "PROJECT_DIR user:  $userProjectDir"
Write-Host "PROJECT_DIR proc:  $processProjectDir"

if ($freeRamGb -lt 3) {
    Write-Warning "Low RAM. Close heavy apps or reboot before a long Claude session."
}

if ($uptimeHours -gt 72) {
    Write-Warning "Long uptime. Reboot before debugging Claude/API issues."
}

if (($trackedChanges -is [int]) -and $trackedChanges -gt 80) {
    Write-Warning "Dirty worktree is large. Prefer scoped prompts and avoid full-repo scans."
}

if ($userProjectDir -or $processProjectDir) {
    Write-Warning "CLAUDE_PROJECT_DIR is set. For DF2, prefer cwd-based launch or the start_claude_df2.ps1 launcher."
}

if ($Detailed) {
    Write-Host ""
    Write-Host "Largest relevant processes:"
    Get-Process |
        Where-Object { $_.ProcessName -match "claude|codex|Code|firefox|blender|FL64|python|node|pwsh|powershell" } |
        Sort-Object WorkingSet64 -Descending |
        Select-Object -First 20 ProcessName, Id, @{n="WS_MB";e={[math]::Round($_.WorkingSet64 / 1MB, 1)}}, CPU |
        Format-Table -AutoSize
}
