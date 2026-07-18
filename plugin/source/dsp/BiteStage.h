#pragma once

// TRENCH BITE / DAMAGE — post-cascade harmonic grit.
//
// SLAM (SlamStage.h) is the PRE-filter gain-change clip — it gives the body dense
// harmonics to chew. BITE is the complement: a POST-filter bounded soft-fold that
// colours the already-filtered signal with controlled odd/even harmonics + a touch
// of "damage". It is distinct, gain-safe by construction (output stays within the
// soft-fold's bounded range), and exact unity at bite = 0.
//
// Pure header, no JUCE, so the processor and the render-dump share one definition.

#include <cmath>

namespace trench
{

inline float biteClamp (float x) noexcept { return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); }

// One block of BITE. biteNorm in [0,1]. The signal is driven into tanh for harmonics,
// then PEAK-MATCHED back to the dry block peak so BITE adds grit/damage WITHOUT a level
// jump (it can only hold or reduce the peak, never boost it — gain-safe by construction,
// no maximiser effect). The shaped signal is then blended dry->shaped by biteNorm, so
// the bottom of the lane is exact unity and the colour comes in progressively.
inline void biteDriveBlock (float* buf, int n, float biteNorm) noexcept
{
    if (buf == nullptr || n <= 0)
        return;
    const float s = biteClamp (biteNorm);
    if (s <= 1.0e-4f)
        return;                                   // exact unity — engaging nothing
    // HARD clip (the ear-picked "G" curve, 2026-07-18): straight clip, no knee.
    // Drive 1..~5x (+14 dB at full) — the drum-bus crunch, not the desk smear.
    const float drive = 1.0f + 4.0f * s;

    float peakDry = 0.0f, peakSh = 0.0f;
    for (int i = 0; i < n; ++i)
    {
        const float a = std::fabs (buf[i]);
        if (a > peakDry) peakDry = a;
        const float d = a * drive;
        const float sh = d > 1.0f ? 1.0f : d;
        if (sh > peakSh) peakSh = sh;
    }
    const float g = peakSh > 1.0e-6f ? (peakDry / peakSh) : 1.0f;   // peak-match: level-neutral

    for (int i = 0; i < n; ++i)
    {
        const float d = buf[i] * drive;
        const float y = (d > 1.0f ? 1.0f : (d < -1.0f ? -1.0f : d)) * g;
        buf[i] = buf[i] + (y - buf[i]) * s;       // dry -> clipped blend
    }
}

// How much harmonic lift BITE adds at this amount (UI/meter helper, 0..1).
inline float biteAmount (float biteNorm) noexcept { return biteClamp (biteNorm); }

} // namespace trench
