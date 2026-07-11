#pragma once

// TRENCH SLAM helpers. The old pre-cascade gain-change path is kept for A/B
// renders, but the plug-in's live SLAM path is output-only: the body sees clean
// input, then SLAM pushes the rendered output into a rounded pressure limiter.
//
//   live: input -> body filter (+AGC) -> [SLAM output pressure] -> out
//   A/B:  input -> [SLAM gain change dB] -> [internal clip] -> body filter (+AGC) -> out
//
// Output pressure is the live SLAM sound. The legacy pre-cascade helper reports
// INT CLIP only for explicit input-slam A/B renders. Pure header, no JUCE, so it
// is unit-testable and shared by the processor and any render tool.
//
// Live output-pressure mapping:
//   SLAM 0    -> +0 dB
//   SLAM 25   -> +3 dB
//   SLAM 50   -> +6 dB
//   SLAM 75   -> +9 dB
//   SLAM 100  -> +12 dB

#include <cmath>

namespace trench
{

inline float slamGainDb (float slamNorm) noexcept
{
    const float s = slamNorm < 0.0f ? 0.0f : (slamNorm > 1.0f ? 1.0f : slamNorm);
    if (s <= 0.75f)
        return 24.0f * s;                       // 0,6,12,18 at 0,.25,.5,.75
    return 18.0f + 48.0f * (s - 0.75f);         // 18 -> 30 over the danger quarter
}

inline float slamGainLinear (float slamNorm) noexcept
{
    return std::pow (10.0f, slamGainDb (slamNorm) / 20.0f);
}

// Input headroom (the real-time "normalize/level the sample" step). The SLAM gain
// change is applied on top of a -kSlamHeadroomDb trim so the bottom of the knob is
// genuinely clean and the clip only starts partway up — that's what gives SLAM a
// usable gentle->sweet->blown range instead of jumping straight to blown-out.
// Makeup is restored downstream (output trim / AGC). Kept for legacy input-slam
// A/B renders only; the live plug-in path calls slamOutputPressureBlockStereo instead.
constexpr float kSlamHeadroomDb = 9.0f;

// Hard digital clip — predictable harmonic density. (Soft knee deliberately
// omitted in V1: this is gain-change crunch, not warm tape.)
inline float internalClip (float x) noexcept
{
    return x > 1.0f ? 1.0f : (x < -1.0f ? -1.0f : x);
}

// Pre-cascade: apply the SLAM gain change, then hard-clip. Returns the fraction
// of samples that clipped (INT CLIP meter).
inline float slamPreProcess (float* buf, int n, float slamNorm) noexcept
{
    if (buf == nullptr || n <= 0)
        return 0.0f;
    const float g = slamGainLinear (slamNorm);
    int clipped = 0;
    for (int i = 0; i < n; ++i)
    {
        float y = buf[i] * g;
        if (y > 1.0f || y < -1.0f) { ++clipped; y = internalClip (y); }
        buf[i] = y;
    }
    return (float) clipped / (float) n;
}

// Post-cascade: output headroom trim (dB, usually <= 0), then a final safety
// clip. Returns the fraction of samples the safety clip caught (OUT CLIP meter)
// — ideally ~0; non-zero means the master is being protected, i.e. OUT HOT.
inline float slamPostProcess (float* buf, int n, float outTrimDb) noexcept
{
    if (buf == nullptr || n <= 0)
        return 0.0f;
    const float g = std::pow (10.0f, outTrimDb / 20.0f);
    int clipped = 0;
    for (int i = 0; i < n; ++i)
    {
        float y = buf[i] * g;
        if (y > 1.0f || y < -1.0f) { ++clipped; y = internalClip (y); }
        buf[i] = y;
    }
    return (float) clipped / (float) n;
}

// Live output law: much smaller than the legacy input-slam gain. The old +30 dB
// hard clip sounded exciting but harsh; this keeps the last-in-chain pressure
// while leaving useful knob travel.
inline float slamOutputGainDb (float slamNorm) noexcept
{
    const float s = slamNorm < 0.0f ? 0.0f : (slamNorm > 1.0f ? 1.0f : slamNorm);
    return 12.0f * s; // 0..+12 dB
}

inline float slamRoundedLimit (float x) noexcept
{
    constexpr float knee = 0.72f;
    const float a = std::fabs (x);
    if (a <= knee)
        return x;
    return (x < 0.0f ? -1.0f : 1.0f)
        * (knee + (1.0f - knee) * std::tanh ((a - knee) / (1.0f - knee)));
}

// Live plug-in path: SLAM affects only the already-rendered stereo output.
inline float slamOutputPressureBlockStereo (float* left, float* right, int n, float slamNorm) noexcept
{
    if (left == nullptr || right == nullptr || n <= 0)
        return 0.0f;

    const float s = slamNorm < 0.0f ? 0.0f : (slamNorm > 1.0f ? 1.0f : slamNorm);
    if (s <= 1.0e-4f)
        return 0.0f;

    const float drive = std::pow (10.0f, slamOutputGainDb (s) / 20.0f);
    int limited = 0;
    for (int i = 0; i < n; ++i)
    {
        float l = left[i] * drive;
        float r = right[i] * drive;

        if (std::fabs (l) > 0.72f || std::fabs (r) > 0.72f)
            ++limited;

        left[i] = slamRoundedLimit (l);
        right[i] = slamRoundedLimit (r);
    }

    return (float) limited / (float) n;
}

// Legacy one-channel output clip helper, kept for old audition code.
inline float slamOutputDriveBlock (float* buf, int n, float slamNorm) noexcept
{
    return slamPostProcess (buf, n, slamGainDb (slamNorm));
}

// Full pre-cascade SLAM chain in one pass: input headroom -> gain change ->
// hard clip -> tapered makeup. Clean unity at slamNorm=0 (engaging SLAM does not
// drop level); progressively denser crunch as it rises; the makeup tapers to 0 as
// the signal saturates so the level into the cascade stays controlled. Returns the
// INT-CLIP fraction. This is what the processor calls per channel.
inline float slamDriveBlock (float* buf, int n, float slamNorm,
                             float headroomDb = kSlamHeadroomDb) noexcept
{
    if (buf == nullptr || n <= 0)
        return 0.0f;
    const float s = slamNorm < 0.0f ? 0.0f : (slamNorm > 1.0f ? 1.0f : slamNorm);
    const float drive  = std::pow (10.0f, (slamGainDb (s) - headroomDb) / 20.0f);
    const float makeup = std::pow (10.0f, (headroomDb * (1.0f - s)) / 20.0f);
    int clipped = 0;
    for (int i = 0; i < n; ++i)
    {
        float y = buf[i] * drive;
        if (y > 1.0f || y < -1.0f) { ++clipped; y = internalClip (y); }
        buf[i] = y * makeup;
    }
    return (float) clipped / (float) n;
}

// Short status label for the upper numeric readout: "+0".."+12" or "HOT" near max.
inline const char* slamStatusLabel (float slamNorm) noexcept
{
    if (slamNorm >= 0.97f) return "HOT";
    const int db = (int) std::lround (slamOutputGainDb (slamNorm));
    switch (db)
    {
        case 0:  return "+0";
        case 3:  return "+3";
        case 6:  return "+6";
        case 9:  return "+9";
        case 12: return "+12";
        default: break;
    }
    // coarse buckets between the anchors
    if (db < 3)  return "+0";
    if (db < 6)  return "+3";
    if (db < 9)  return "+6";
    if (db < 12) return "+9";
    return "+12";
}

} // namespace trench
