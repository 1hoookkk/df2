# shot.ps1 — launch the forge, grab its window to a PNG, close it.
# Lets Claude self-check the UI against the reference screenshots without
# Tyson having to run it. Usage:  pwsh -File shot.ps1 [out.png]
param(
  [string]$Out = "shot.png",
  [switch]$EditShape
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int command);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr h, ref POINT p);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, UIntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

# Workspace builds land in the repo-root target/; standalone in the local one.
# Prefer release, fall back to debug, in both layouts.
$candidates = @(
  "..\target\release\forge-clean.exe", "target\release\forge-clean.exe",
  "..\target\debug\forge-clean.exe",   "target\debug\forge-clean.exe"
)
$exe = $null
foreach ($c in $candidates) { $full = Join-Path $PSScriptRoot $c; if (Test-Path $full) { $exe = $full; break } }
if (-not $exe) { throw "forge-clean.exe not found (build it first)" }
# -EditShape opens the drawer deterministically via env (winit ignores
# synthetic PostMessage clicks), captured below.
if ($EditShape) { $env:FORGE_OPEN_EDIT = "1" } else { Remove-Item Env:\FORGE_OPEN_EDIT -ErrorAction SilentlyContinue }
$p = Start-Process $exe -PassThru
# Poll for a realized window: a valid handle AND a sane rect (cold first launch
# can take several seconds before eframe paints).
$h = [IntPtr]::Zero
$rr = New-Object Win+RECT
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 300
  $p.Refresh()
  $h = $p.MainWindowHandle
  if ($h -ne [IntPtr]::Zero) {
    [Win]::GetWindowRect($h, [ref]$rr) | Out-Null
    if (($rr.Right - $rr.Left) -gt 400 -and ($rr.Bottom - $rr.Top) -gt 300) { break }
  }
}
if ($h -eq [IntPtr]::Zero) { $p.Kill(); throw "no window handle" }
[Win]::ShowWindow($h, 9) | Out-Null
[Win]::SetWindowPos($h, [IntPtr](-1), 0, 0, 0, 0, 0x43) | Out-Null
[Win]::SetWindowPos($h, [IntPtr](-2), 0, 0, 0, 0, 0x43) | Out-Null
[Win]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 400

$r = New-Object Win+RECT
[Win]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.Right - $r.Left; $hgt = $r.Bottom - $r.Top
$bmp = New-Object System.Drawing.Bitmap $w, $hgt
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
$printed = [Win]::PrintWindow($h, $dc, 2)
$g.ReleaseHdc($dc)
if (-not $printed) {
  $g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size)
}
$path = Join-Path $PSScriptRoot $Out
$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
$p.Kill()
Write-Output "saved $path  ($w x $hgt)"
