---
description: Build the TRENCH VST3 (Release) and install it to C:\Program Files\Common Files\VST3
allowed-tools: Bash(powershell:*), PowerShell
---

Run the one-shot build+install script and report the outcome:

```
powershell -ExecutionPolicy Bypass -File tools\build_install_vst3.ps1
```

- On success, report the install path and remind that FL must be restarted (DLL cache) to pick up the new build.
- If the old plugin folder was parked as `.inuse-old-<timestamp>`, say so.
- On build failure, show the failing compiler output — do not retry blindly.
