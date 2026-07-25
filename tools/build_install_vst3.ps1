# One-shot: build the TRENCH VST3 (Release) and install it to the system VST3 dir.
# If FL has the old plugin loaded (folder locked), the old one is renamed aside
# (.inuse-old-<timestamp>, the established convention) instead of failing.
#   powershell -ExecutionPolicy Bypass -File tools\build_install_vst3.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent

cmake --build "$repo\plugin\build" --config Release --target TRENCH_VST3
if ($LASTEXITCODE -ne 0) { throw "build failed" }

$src = "$repo\plugin\build\TRENCH_artefacts\Release\VST3\TRENCH.vst3"
$dst = "C:\Program Files\Common Files\VST3\TRENCH.vst3"

if (Test-Path $dst) {
    try { Remove-Item $dst -Recurse -Force -ErrorAction Stop }
    catch {
        $aside = "$dst.inuse-old-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Rename-Item $dst $aside
        Write-Host "old plugin in use -> parked as $(Split-Path $aside -Leaf)"
    }
}
Copy-Item $src $dst -Recurse
Write-Host "installed: $dst"
Write-Host "restart FL (DLL cache) to pick it up."
