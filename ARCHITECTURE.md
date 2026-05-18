# df2 — Architecture Decision Record

**Status:** Locked (2026-05-18)
**Owner:** Tyson

---

## Decision

df2 is implemented as a thin JUCE C++ plugin shell wrapping a Rust core
that handles both DSP and rendering. All performance-critical code lives
in Rust. C++ is used only where unavoidable — DAW format boilerplate,
window handle plumbing, parameter declaration.

```
JUCE C++ shell (~5% of codebase)
├─ Plugin format wrappers (VST3, CLAP, AU)
├─ Parameter declarations + automation routing
├─ Audio buffer in/out
├─ Window/component lifecycle
└─ FFI bridge (cxx crate) → Rust core

Rust core (~95% of codebase)
├─ trench-core (frozen, patent-verified)
│   ├─ 12-stage DF2T biquad cascade
│   ├─ 4-corner bilinear interpolation
│   ├─ Cartridge format (compiled-v1)
│   └─ Per-buffer process()
│
├─ trench-render (new)
│   ├─ wgpu surface + swapchain
│   ├─ Curve visualization (fragment shader)
│   ├─ Body-specific palette + behavior
│   ├─ Audio-reactive breathing
│   └─ Per-frame render loop
│
└─ Shared state
    ├─ Atomic parameter cell (lock-free)
    │   ├─ morph: AtomicF32
    │   ├─ q: AtomicF32
    │   ├─ current_body: AtomicU32
    │   └─ bypass: AtomicBool
    └─ Audio ring buffer (rtrb, lock-free)
        └─ Recent samples for visualization reactivity
```

---

## Why this architecture

**Audio thread:** Lock-free, real-time, Rust. Reads parameter atomics,
processes audio buffer through trench-core, writes recent samples to
the ring buffer for the renderer.

**Render thread:** Driven by JUCE's display callback, runs in Rust via
wgpu. Reads parameter atomics + audio ring buffer, draws the
visualization at 60fps+. Zero allocations in steady state.

**UI thread:** JUCE C++ owns. Receives mouse/touch events from the
host window, forwards them through FFI to Rust, which updates the
parameter atomics. UI thread does not block on the audio or render
threads.

**No interop seam inside the audio path.** Parameter updates from UI
to audio happen through a single atomic store. No locks, no message
queues, no priority inversion. The audio thread reads atomics
per-buffer.

---

## Why all DSP in Rust (not C++)

1. trench-core already exists in Rust, patent-verified, null-tested.
   Re-implementing in C++ throws away months of validated work.
2. Rust's ownership model prevents data races between audio and render
   threads. C++ requires manual discipline for the same guarantees.
3. Cargo + crates.io give better dependency management than C++ for
   pure DSP work (rtrb, num-complex, libm, etc.).
4. Single toolchain to debug the entire performance-critical path.

## Why JUCE for the shell (not pure Rust)

1. DAW host compatibility is the actual hard problem in plugin
   development. JUCE has 20 years of accumulated workarounds for VST3
   quirks, AU edge cases, AAX requirements, host-specific bugs.
2. Plugin format wrappers in pure Rust exist (nih-plug, mlua-plugin)
   but are less battle-tested. For a commercial release, JUCE is the
   safer choice.
3. Resizable plugin window management with proper DAW integration is
   genuinely difficult; JUCE has solved this.

## Why wgpu (not OpenGL, not native APIs)

1. Cross-platform: works on macOS (Metal), Windows (Vulkan/DX12),
   Linux (Vulkan). Single codebase.
2. Modern API: compute shaders, real-time texture updates, proper
   GPU buffer management. OpenGL is deprecated on macOS.
3. Already in the Rust ecosystem, integrates cleanly with the rest
   of the core.
4. The right call for a project shipping in 2026-2027.

---

## Implementation order

1. **Verify trench-core builds and passes null tests in new df2 repo.**
   Carry from old trench/ repo via CARRY_OVER.md. Run null_test.py
   against canonical wets. Confirm bit-accuracy.

2. **Minimal JUCE C++ shell** with one parameter (gain or bypass),
   passthrough audio, blank window. Standard JUCE skeleton.
   Target: ~200 lines C++.

3. **Add cxx FFI bridge.** Define `extern "Rust"` and `extern "C++"`
   boundaries. Audio thread routes through Rust DSP via FFI.

4. **End-to-end null test through the C++ shell.** DAW → JUCE → Rust
   DSP → DAW. Confirm samples are bit-accurate (no C++ shell quirks).
   This is the critical validation gate before any UI work.

5. **Standalone Rust wgpu prototype** (no plugin shell). A native
   window that renders the curve visualization. Validates the
   rendering before tangling with JUCE.

6. **Integrate wgpu surface into JUCE window.** Pass native window
   handle from JUCE C++ to Rust, create wgpu surface on it, run
   render loop from JUCE's display callback.

7. **Wire visualization to parameter atomics.** UI input → atomic
   store → render thread reads → visualization updates. Confirm
   no latency, no tearing.

8. **First playable build.** Load in Ableton/Reaper, play audio,
   drag morph slider, see and hear the body respond. The "df2
   exists" milestone.

9. **Polish: chassis around the visualization, body selector, all
   four shipping bodies wired up.**

10. **Cartridge loading.** Read cartridge JSON, swap body without
    reloading the plugin.

---

## Risks and mitigations

**Risk: wgpu inside JUCE is novel.**
Few production plugins do this. Expect 2-3 weeks of integration
friction the first time.
*Mitigation:* Prototype standalone Rust wgpu first (step 5). Validate
rendering separately before plugin integration.

**Risk: cxx FFI overhead.**
Crossing the FFI boundary every audio buffer could add latency.
*Mitigation:* Bridge is only crossed once per buffer (not per sample).
Parameter atomics live in Rust, no cross-boundary state needed inside
the audio loop.

**Risk: GPU thread doesn't synchronize cleanly with audio thread.**
If render thread holds a lock or waits on GPU, audio could glitch.
*Mitigation:* Render thread reads atomics and ring buffer only. Never
blocks. Never allocates in steady state. Audio thread never touches
GPU resources.

**Risk: DAW window resize bugs.**
Resizing a wgpu surface inside a JUCE window during runtime is fragile.
*Mitigation:* Test resize on macOS (Logic, Ableton), Windows (FL,
Reaper), Linux (Reaper) early. Lock window aspect ratio in v1 if
resize proves unstable.

---

## What this means for the workflow

**Day-to-day development:**
- 95% of work happens in Rust (Cargo workspace with trench-core +
  trench-render + shared types)
- C++ shell is set up once, rarely touched
- Hot reload of shaders during development (wgpu supports this)
- Standard Rust tooling: cargo test, cargo bench, clippy, rust-analyzer

**Build pipeline:**
- Cargo builds the Rust core into a static library
- CMake builds the JUCE C++ shell linking against the Rust static lib
- Output: VST3, AU, CLAP plugin formats
- Single `make` or `cargo xtask build-plugin` command produces all formats

**Cross-platform:**
- macOS: ships as VST3 + AU + CLAP, Metal backend via wgpu
- Windows: ships as VST3 + CLAP, DirectX 12 backend
- Linux: ships as VST3 + CLAP, Vulkan backend

---

## Locked. Do not revisit unless a new constraint emerges.
