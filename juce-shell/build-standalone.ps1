param(
    [switch] $Launch
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $PSScriptRoot "build"
$standalone = Join-Path $buildDir "TRENCH_artefacts\Release\Standalone\TRENCH.exe"
$rustCrate = Join-Path $repoRoot "trench-core"
$rustLib = Join-Path $repoRoot "target\release\trench_core.lib"

Push-Location $repoRoot
try {
    # The JUCE shell links the Rust static library. Building only that crate
    # type avoids replacing trench_core.dll while browser helpers are using it.
    $rustInputs = @(
        Get-Item (Join-Path $repoRoot "Cargo.toml")
        Get-Item (Join-Path $repoRoot "Cargo.lock")
        Get-Item (Join-Path $rustCrate "Cargo.toml")
        Get-ChildItem (Join-Path $rustCrate "src") -Recurse -File -Filter "*.rs"
    )
    $rustBuildRequired = -not (Test-Path $rustLib)
    if (-not $rustBuildRequired) {
        $rustLibTimestamp = (Get-Item $rustLib).LastWriteTimeUtc
        $rustBuildRequired = $null -ne ($rustInputs | Where-Object LastWriteTimeUtc -gt $rustLibTimestamp | Select-Object -First 1)
    }

    if ($rustBuildRequired) {
        cargo rustc -p trench-core --release --lib --crate-type staticlib
        if ($LASTEXITCODE -ne 0) {
            throw "Rust static-library build failed with exit code $LASTEXITCODE"
        }
    }

    if (-not (Test-Path (Join-Path $buildDir "CMakeCache.txt"))) {
        cmake -S $PSScriptRoot -B $buildDir -G "Visual Studio 17 2022"
        if ($LASTEXITCODE -ne 0) {
            throw "CMake configure failed with exit code $LASTEXITCODE"
        }
    }

    if ($Launch) {
        Get-Process TRENCH -ErrorAction SilentlyContinue |
            Where-Object Path -eq $standalone |
            Stop-Process -Force
    }

    cmake --build $buildDir --config Release --target TRENCH_Standalone --parallel
    if ($LASTEXITCODE -ne 0) {
        throw "Standalone build failed with exit code $LASTEXITCODE"
    }

    if ($Launch) {
        Start-Process -FilePath $standalone -WorkingDirectory $repoRoot
    }
}
finally {
    Pop-Location
}
