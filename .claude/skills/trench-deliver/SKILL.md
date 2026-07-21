---
name: trench-deliver
description: Build, test, package, install, and smoke-test current targets of the df2-workstation checkout (C:\Users\hooki\df2-workstation only, not sibling checkouts) on Windows. Use when asked to build or rebuild one of its crates, apps, or plugins, run its test suites, produce or install an artifact such as a VST3, confirm something loads and runs in its real host, or diagnose build and install failures there. Not for designing code changes - for getting current code built, delivered, and demonstrably running.
---

# TRENCH Deliver

Discover the current targets and toolchains each time, deliver exactly what was asked, and keep three claims separate: it built, it installed, it ran.

## Discover targets — do not assume

- Enumerate live build roots by searching the repo for `Cargo.toml`, `CMakeLists.txt`, and build scripts, then read the relevant manifest for target names, binary lists, and output types. Target names and artifact paths go stale; trust the manifest just read, not memory.
- Identify the toolchain each build root expects (cargo, CMake generator and compiler, pinned SDK or framework paths declared in the build files) before invoking anything.

## Build

- Avoid overlapping builds of the same tree unless the build system explicitly supports them; they can cause locks, redundant work, or ambiguous artifact provenance.
- Keep failure diagnosis scoped: fix the break without upgrading dependencies, bumping toolchains, or restructuring the build system as a side effect. If the genuine fix requires one of those, stop and say so before doing it.
- Record what was built: configuration, target, and the artifact path the build actually wrote — read the path from build output, not from a remembered layout.

## Install

- Discover the install destination from the build system or the currently installed artifact; do not hardcode historical paths.
- Windows locks loaded modules: if a running host or app holds the destination file, the copy fails or silently does not take effect. Close or unload the consumer first, then install.
- Verify artifact identity after install: compare the installed file's hash or timestamp against the artifact just built. Do not smoke-test until the deployed file is proven to be the one that was built.

## Smoke test

- Runtime validation means observing the artifact in its real context — the host loads the plugin, the binary runs and does its job — not inferring it from a green build.
- Must: report the three stages truthfully and separately. A skipped stage is reported as skipped, never implied as passed.
