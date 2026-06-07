param(
    [switch]$Untracked,
    [switch]$Files
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location -LiteralPath $root

Write-Host "DF2 git status"
Write-Host "--------------"
Write-Host "Root:   $root"
Write-Host "Branch: $(git branch --show-current)"
Write-Host ""

$tracked = @(git status --short -uno)
$trackedByKind = $tracked |
    ForEach-Object { $_.Substring(0, 2).Trim() } |
    Where-Object { $_ } |
    Group-Object |
    Sort-Object Count -Descending

Write-Host "Tracked changes by kind:"
if ($trackedByKind.Count) {
    $trackedByKind | Select-Object Count, Name | Format-Table -AutoSize
} else {
    Write-Host "  none"
}

Write-Host "Tracked changes by top folder:"
$trackedByFolder = $tracked |
    ForEach-Object {
        if ($_.Length -gt 3) {
            ($_.Substring(3) -split "[\\/]")[0]
        }
    } |
    Where-Object { $_ } |
    Group-Object |
    Sort-Object Count -Descending |
    Select-Object -First 20 Count, Name

if ($trackedByFolder.Count) {
    $trackedByFolder | Format-Table -AutoSize
} else {
    Write-Host "  none"
}

if ($Untracked) {
    Write-Host "Untracked files by top folder:"
    $all = @(git status --short --untracked-files=normal)
    $all |
        Where-Object { $_.StartsWith("?? ") } |
        ForEach-Object {
            if ($_.Length -gt 3) {
                ($_.Substring(3) -split "[\\/]")[0]
            }
        } |
        Where-Object { $_ } |
        Group-Object |
        Sort-Object Count -Descending |
        Select-Object -First 25 Count, Name |
        Format-Table -AutoSize
}

if ($Files) {
    Write-Host "Tracked file list:"
    $tracked
}
