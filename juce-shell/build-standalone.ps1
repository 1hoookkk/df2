param(
    [switch] $Launch,
    [string] $Target = "TRENCH_Standalone",
    [switch] $Diagnostics
)

$ErrorActionPreference = "Stop"

# Canonical build: Ninja (single-config) + MSVC. Fast incremental dev loop.
# The Rust staticlib (trench-core) is built by CMake's `trench_core_build` target
# as a dependency of every plugin format, so there is no separate cargo step.

$repoRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $PSScriptRoot "build-ninja"

function Import-VsDevEnvironment {
    if ($env:VCToolsInstallDir -and $env:INCLUDE -match "MSVC") {
        return
    }

    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) {
        throw "vswhere.exe was not found; install Visual Studio C++ tools or run from a Developer PowerShell."
    }

    $installPath = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
    if (-not $installPath) {
        throw "No Visual Studio install with MSVC C++ tools was found."
    }

    $vsDevCmd = Join-Path $installPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path $vsDevCmd)) {
        throw "VsDevCmd.bat was not found at $vsDevCmd"
    }

    $cmd = "`"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 && set"
    $envBlock = cmd.exe /d /s /c $cmd
    if ($LASTEXITCODE -ne 0) {
        throw "VsDevCmd.bat failed with exit code $LASTEXITCODE"
    }

    foreach ($line in $envBlock) {
        if ($line -match '^([^=]+)=(.*)$') {
            Set-Item -Path ("Env:{0}" -f $matches[1]) -Value $matches[2]
        }
    }
}

Import-VsDevEnvironment

Push-Location $repoRoot
try {
    # Product builds stay clean. Pass -Diagnostics for the dev standalone that
    # reads/hot-reloads Documents/TRENCH authoring/layout files.
    $diagnosticsFlag = if ($Diagnostics) { "ON" } else { "OFF" }
    cmake -S $PSScriptRoot -B $buildDir -G Ninja -DCMAKE_BUILD_TYPE=Release "-DTRENCH_PLAYER_DIAGNOSTICS=$diagnosticsFlag" -DTRENCH_FORGE=OFF -DTRENCH_COPY_PLUGIN_AFTER_BUILD=OFF
    if ($LASTEXITCODE -ne 0) {
        throw "CMake configure failed with exit code $LASTEXITCODE"
    }

    # Single-config Ninja puts artefacts under the configured build type.
    $cfg = (Select-String -Path (Join-Path $buildDir "CMakeCache.txt") `
            -Pattern '^CMAKE_BUILD_TYPE:\w+=(.*)$').Matches.Groups[1].Value
    if (-not $cfg) { $cfg = "Release" }
    $standalone = Join-Path $buildDir "TRENCH_artefacts\$cfg\Standalone\TRENCH.exe"

    if ($Launch -and $Target -ne "TRENCH_Standalone") {
        throw "-Launch is only valid with -Target TRENCH_Standalone"
    }

    if ($Target -eq "TRENCH_Standalone") {
        Get-Process TRENCH -ErrorAction SilentlyContinue |
            Where-Object Path -eq $standalone |
            Stop-Process -Force
    }

    cmake --build $buildDir --target $Target
    if ($LASTEXITCODE -ne 0) {
        throw "Build target '$Target' failed with exit code $LASTEXITCODE"
    }

    if ($Launch) {
        Start-Process -FilePath $standalone -WorkingDirectory $repoRoot
    }
}
finally {
    Pop-Location
}
