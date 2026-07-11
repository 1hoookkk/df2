# juce-shell

TRENCH consumer plug-in shell (VST3 + Standalone). Hosts `trench-core` via FFI
in the shipping audio path.

## Build

```powershell
.\juce-shell\build-standalone.ps1 -Launch
```

This builds only the Rust static library needed by the JUCE shell, reuses the
shared CPM source cache at `%USERPROFILE%\.cache\CPM`, relinks the standalone
target through Ninja, and launches it. JUCE is pinned to the current stable
release in `CMakeLists.txt`; no workspace-local `JUCE` junction is required.

To build the VST3 for DAW installation:

```powershell
.\juce-shell\build-standalone.ps1 -Target TRENCH_VST3
```

The Release VST3 lands in
`C:\Program Files\Common Files\VST3\TRENCH.vst3` (admin-elevated auto-copy).
Manual install fallback: copy from
`juce-shell/build-ninja/TRENCH_artefacts/Release/VST3/` into the same path.

## Dev tools

The editor has a Melatonin Inspector hook when
`TRENCH_ENABLE_MELATONIN_INSPECTOR=ON` (default). Right-click the faceplate or
Ctrl-click the faceplate to open the component inspector. `Ctrl+I` on Windows
or `Cmd+I` on macOS may also work when the editor has keyboard focus.
For distribution builds, configure CMake with
`-DTRENCH_ENABLE_MELATONIN_INSPECTOR=OFF`.

After building the VST3, run pluginval:

```powershell
.\juce-shell\validate-pluginval.ps1
```

The script downloads the official Windows `pluginval` release zip on first run,
caches it under `juce-shell/build/tools/pluginval`, and validates the built
Release VST3 at strictness level 5.

## Dev-iteration workflow

**Do not iterate inside FL Studio.** Windows maps a plug-in DLL once per host
process and keeps it resident until the host fully exits — closing the FL
window leaves `FL64.exe` running in the system tray, so rebuilds land on disk
but the host never reloads them. A six-hour debug session on 2026-05-28 was
spent chasing ghosts in a DLL FL had loaded three days earlier.

For iteration use one of:
- `TRENCH_Standalone.exe` (preferred — restart between builds is a click)
- JUCE `AudioPluginHost`

Reserve FL for *using* the plug-in in a real session. When FL must be used,
fully kill `FL64.exe` via Task Manager (not the window close button) before
reloading.

## Regression checklist (manual)

Run before tagging a release build. These cover the JUCE-shell defect classes
we have actually hit; the Rust core has its own `cargo test`.

### Body strip parameter contract

The body parameter expects DENORMALIZED values
(`0..bodyCount-1`) in `setValueAsCompleteGesture`. Passing `0..1` causes JUCE
to renormalise twice and collapses every click to indices `0` or `1` — the
"only two presets reachable" bug found 2026-05-28 in `TrenchBodyStrip::setIndex`
(now fixed at `juce-shell/source/TrenchBodyStrip.h:110`).

- [ ] In `TRENCH_Standalone.exe`, click each body in the strip from index 0
  through the last index. The body name in the strip and the audible output
  must change at every click. A run that lands on index 0 / 1 only is the
  regression returning.
- [ ] Same check by mouse-wheel over the strip (covers the
  `setIndex(index ± 1)` wheel path).
- [ ] Same check by arrow-key navigation if implemented.

### Parameter defaults on fresh boot

Open a fresh instance (no project recall, no preset load). Inspect the
parameter values via the host's parameter list / generic editor:

- [ ] `body` = 0 (first roster entry)
- [ ] `morph` = 0
- [ ] `q` = 0
- [ ] `slamDrive` = 0
- [ ] `fiveD` = `Off`
- [ ] `teleportMode` = `Off`
- [ ] `inputMode` = `Normal`
- [ ] `output` = 0 dB

A non-zero default on `slamDrive` (we shipped `0.35` mid-session 2026-05-28)
adds ~12.6 dB of pre-cascade saturation on every body; the regression looks
like "every body distorts the same way."

### Body load failure → bypass, not stale-body continuation

- [ ] Temporarily point the roster at a deliberately broken cartridge JSON
  (rename a working one to `.broken.json`). Plug-in must bypass (silent
  output) and the "BODY FAILED — bypass" chassis overlay must appear.
  `getLastLoadOk()` should return `false`. The previous body must not keep
  playing.

### VST3 install hygiene

- [ ] After a Release build, exactly one `TRENCH.vst3` is present on disk:
  `C:\Program Files\Common Files\VST3\TRENCH.vst3`. There must be **no**
  copy in `%LOCALAPPDATA%\Programs\Common\VST3\`. A drifted second copy
  lets the DAW scan whichever it sees first — usually the stale one.

### Null parity

- [ ] `cargo test -p trench-core` is green (covers AGC, packed math, null
  vs X3, body-bytes-canonical, FG-1 ROM-decode parity).
- [ ] Spot-check `python tools/null_test.py` lands ≤ -60 dB at every tested
  M/Q position, with M50/Q50 in the -95 dB band.
