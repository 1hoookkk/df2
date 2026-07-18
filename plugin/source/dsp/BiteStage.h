#pragma once

// TRENCH CLIP — post-cascade drum-bus hard clip (the ear-picked "G" curve,
// 2026-07-18). SLAM (SlamStage.h) is the desk at the very end; CLIP sits just
// after the cascade and flattens peaks like a drum-bus clipper. Straight hard
// clip, no knee (J's knee was auditioned and rejected). Standard drum-bus
// clipper law: gain INTO a fixed 1.0 ceiling — pushing CLIP gets louder and
// crunchier, like every clipper producers know. Deterministic and stateless
// (no per-block peak-match), so no block-rate pumping. Exact unity at clip = 0.
//
// (The function keeps its historical biteDriveBlock name — TrenchParams.bite
// carries the CLIP value; the inter-stage BITE lives in the Rust engine.)
//
// Pure header, no JUCE, so the processor and the render-dump share one definition.

#include <cmath>

#include "SlamStage.h"  // internalClip — the one hard-clip law

namespace trench
{

inline float biteClamp (float x) noexcept { return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); }

// One block of CLIP. clipNorm in [0,1]: blend dry -> clip(x*drive)/drive.
// Drive 1..5x (+14 dB at full).
inline void biteDriveBlock (float* buf, int n, float clipNorm) noexcept
{
    if (buf == nullptr || n <= 0)
        return;
    const float s = biteClamp (clipNorm);
    if (s <= 1.0e-4f)
        return;                                   // exact unity — engaging nothing
    const float drive = 1.0f + 4.0f * s;

    for (int i = 0; i < n; ++i)
    {
        const float y = internalClip (buf[i] * drive);
        buf[i] = buf[i] + (y - buf[i]) * s;       // dry -> clipped blend
    }
}

} // namespace trench
