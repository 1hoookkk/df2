#pragma once

// TRENCH MOVE routing matrix — the hidden machine behind a Body Gesture.
//
// Page 2 is a REALTIME SECTION-MOVEMENT machine for tracks / buses / master (builds,
// pre-drop sucks, breakdown washes, hook lifts, vocal throws, bass pushes), NOT a loop
// generator. A Gesture drives a small 4x4 matrix:
//   sources (rows): PATH, ACCENT, LAG, DRIFT
//   targets (cols): MORPH, PRESS, SLAM, GUARD
// TENSION performs the whole machine. The 16 cell values live in plugin state (factory
// defaults per gesture in V1; a ROUTE editor comes later).
//
// GUARD is the master/track safety lane: output compensation / headroom trim that prevents
// huge level jumps at a gesture's peak. (A destructive BITE/Damage target can return later
// as a Damage mode — see BiteStage.h, kept on disk.)
//
// LAG is a deterministic, offline-safe slewed copy of the PATH (NOT an input-env follower).
//
// Pure, dependency-free (no JUCE) so the processor, editor preview, and the
// standalone render-dump all share one definition.

#include <cstdint>

namespace trench
{

enum class MoveSource { Path = 0, Accent, Lag, Drift };
enum class MoveTarget { Morph = 0, Press, Slam, Guard };
constexpr int kNumSources = 4;
constexpr int kNumTargets = 4;

inline const char* moveSourceName (int s) noexcept
{
    static const char* n[] = { "PATH", "ACC", "LAG", "DRFT" };
    return n[(s & 3)];
}
inline const char* moveTargetShort (int t) noexcept
{
    static const char* n[] = { "M", "P", "S", "G" };
    return n[(t & 3)];
}
inline const char* moveTargetName (int t) noexcept
{
    static const char* n[] = { "MORPH", "PRESS", "SLAM", "GUARD" };
    return n[(t & 3)];
}

// Playback modes, in priority order. ARM is the default (riser/transition behaviour).
//   ARM  — wait for the next bar, fire one gesture once, return to base.
//   LIVE — immediate one-shot performance, return to base.
//   HOLD — play into a target state and STAY there.
//   LOOP — continuous movement (secondary use).
enum class MoveMode { Arm = 0, Live, Hold, Loop };
constexpr int kNumMoveModes = 4;
inline const char* moveModeName (MoveMode m) noexcept
{
    switch (m) { case MoveMode::Arm: return "ARM"; case MoveMode::Live: return "LIVE";
                 case MoveMode::Hold: return "HOLD"; case MoveMode::Loop: return "LOOP"; }
    return "ARM";
}

// Quantized ROUTE levels (off / low / mid / high) for a future ROUTE editor.
inline float moveWeightLevel (int step) noexcept
{
    static const float v[] = { 0.0f, 0.34f, 0.67f, 1.0f };
    return v[step < 0 ? 0 : (step > 3 ? 3 : step)];
}
inline int moveWeightToStep (float w) noexcept
{
    if (w < 0.17f) return 0;
    if (w < 0.50f) return 1;
    if (w < 0.84f) return 2;
    return 3;
}

struct MoveMatrix
{
    float w[kNumSources][kNumTargets];
    float get (int s, int t) const noexcept { return w[s & 3][t & 3]; }
    void  set (int s, int t, float v) noexcept { w[s & 3][t & 3] = v; }
};

// Factory default matrix per gesture (index = Gesture enum: Lift..Drift).
// rows = PATH, ACCENT, LAG, DRIFT ; cols = MORPH, PRESS, SLAM, GUARD.
// GUARD column = output safety: routed for the safe gestures (LIFT/SUCK/WASH/ORBIT/PULSE)
// so the master ducks at the gesture's peak; near-zero for TEETH/DRIFT (danger, not master-safe).
inline MoveMatrix factoryMatrix (int gesture) noexcept
{
    constexpr float O = 0.0f, L = 0.34f, M = 0.67f, H = 1.0f;
    switch (gesture)
    {
        case 0: // LIFT — upward build/riser; press blooms late; SLAM eases up; GUARD tames the climax
            return {{ { H, O, M, O },    // PATH
                      { O, H, O, M },    // ACC   (t^3 late -> press + guard at the peak)
                      { O, O, L, O },    // LAG
                      { O, O, O, O } }}; // DRFT
        case 1: // SUCK — pre-drop pull/downward tension; press snaps early; brief SLAM; light GUARD
            return {{ { H, O, O, O },
                      { O, H, L, L },
                      { O, O, O, O },
                      { O, O, O, O } }};
        case 2: // WASH — slow breakdown/scene swell; gentle, master-safe
            return {{ { H, L, O, L },    // PATH: swell -> morph + a little press, light guard
                      { O, O, O, O },
                      { O, L, O, O },    // LAG: press trails
                      { L, O, O, O } }}; // DRFT: slow morph variation
        case 3: // ORBIT — signature 2D body movement: morph on sin, press on cos
            return {{ { H, O, O, O },
                      { O, H, O, O },
                      { O, O, O, O },
                      { O, O, O, L } }}; // DRFT: faint guard
        case 4: // PULSE — rhythmic track/bus movement; press accents; SLAM touch; GUARD on accents
            return {{ { H, O, O, O },
                      { O, M, L, M },
                      { O, O, O, O },
                      { O, O, O, O } }};
        case 5: // TEETH — aggressive track/bus damage; NO GUARD (not master-safe by default)
            return {{ { H, O, O, O },
                      { O, M, L, O },
                      { O, O, O, O },
                      { L, O, O, O } }}; // DRFT: bounded morph variation
        case 6: // DRIFT — slow bounded variation; drift-heavy; no guard
        default:
            return {{ { M, O, O, O },
                      { O, O, O, O },
                      { O, O, O, O },
                      { M, L, O, O } }};
    }
}

} // namespace trench
