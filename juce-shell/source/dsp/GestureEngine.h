#pragma once

// TRENCH Body Gesture Engine — realtime section movement for tracks / buses / master.
//
// A Gesture drives a hidden 4x4 matrix (MoveMatrix.h): four SOURCES (PATH, ACCENT, LAG,
// DRIFT) feeding four TARGET lanes (MORPH, PRESS/Q, SLAM, GUARD) over a tempo-synced TIME.
// The user sees only Shape (job), TENSION, TIME and a mode (ARM/LIVE/HOLD/LOOP). TENSION
// performs the whole machine. MOVE is ADDITIVE around the Page-1 base values.
//
// Jobs (surface names) map to the internal gesture math:
//   LIFT(build)  SUCK(pull)  WASH(scene swell)  ORBIT(2D)  PULSE(rhythm)  TEETH(damage)  DRIFT(variation)
//
// GUARD is the safety lane (output compensation, headroom trim) — keeps tracks/master safe.
// LAG is a deterministic slewed copy of PATH (offline-bounce safe). All randomness is seeded.
//
// Pure, dependency-free (no JUCE) so it can be unit-tested standalone and reused by the
// processor (audio thread), the editor (preview), and the render-dump.

#include "MoveMatrix.h"

#include <cmath>
#include <cstdint>

namespace trench
{

// Internal order == surface order (the moveShape choices).
enum class Gesture { Lift, Suck, Wash, Orbit, Pulse, Teeth, Drift };
constexpr int kNumGestures = 7;

inline const char* gestureName (Gesture g) noexcept
{
    switch (g)
    {
        case Gesture::Lift:  return "LIFT";
        case Gesture::Suck:  return "SUCK";
        case Gesture::Wash:  return "WASH";
        case Gesture::Orbit: return "ORBIT";
        case Gesture::Pulse: return "PULSE";
        case Gesture::Teeth: return "TEETH";
        case Gesture::Drift: return "DRIFT";
    }
    return "LIFT";
}

// One-word plain-language intent for the PLAY screen.
inline const char* gestureIntent (int g) noexcept
{
    static const char* in[] = { "build", "pull", "wash", "circle", "bounce", "chop", "drift" };
    return in[g < 0 ? 0 : (g > 6 ? 6 : g)];
}

// Safety clamps so TENSION can never push a lane into an obviously broken range.
struct GestureLimits
{
    float qMax     = 0.92f;
    float slamMax  = 0.75f;
    float guardMax = 1.0f;    // GUARD is a 0..1 safety amount
    float morphMin = 0.0f;
    float morphMax = 1.0f;
};

// Back-compat 3-lane result (Morph, Q/Press, Slam) used by the editor preview/glyphs.
struct GestureResult { float morph = 0.0f, q = 0.0f, slam = 0.0f; };

// Full 4-lane result: MORPH, PRESS, SLAM, GUARD (output safety).
struct MoveLanes { float morph = 0.0f, press = 0.0f, slam = 0.0f, guard = 0.0f; };

struct MoveContext
{
    float driftAmt    = 0.0f;            // move_drift 0..1 — scales the DRIFT source
    float swing       = 0.0f;            // move_swing 0..1 — delays off-beats (rhythmic shapes)
    float phaseOffset = 0.0f;            // move_phase 0..1 — static phase rotation
    std::uint32_t seed = 0x5EEDu;        // preset seed
    std::uint32_t cycleIndex = 0u;       // deterministic from transport (offline-safe randomness)
    float routeMaster[kNumTargets] = { 1.0f, 1.0f, 1.0f, 1.0f };
};

struct MoveSources { float path = 0.0f, accent = 0.0f, lag = 0.0f, drift = 0.0f; };

namespace detail
{
    constexpr float kTwoPi    = 6.2831853f;
    constexpr float kPi       = 3.14159265f;
    constexpr float kLagPhase = 0.10f;

    inline float clampf (float x, float lo, float hi) noexcept { return x < lo ? lo : (x > hi ? hi : x); }
    inline float smoothstep (float x) noexcept { x = clampf (x, 0.0f, 1.0f); return x * x * (3.0f - 2.0f * x); }
    inline float fracf (float x) noexcept { return x - std::floor (x); }
    inline float lerpf (float a, float b, float t) noexcept { return a + (b - a) * t; }

    inline float hash01 (std::uint32_t seed, std::uint32_t i) noexcept
    {
        std::uint32_t x = i * 747796405u + 2891336453u + seed * 2246822519u;
        x ^= x >> 16; x *= 2246822519u; x ^= x >> 13; x *= 3266489917u; x ^= x >> 16;
        return (float) (x >> 8) * (1.0f / 16777216.0f);
    }
    inline std::uint32_t mixSeed (std::uint32_t seed, std::uint32_t shape, std::uint32_t cycle) noexcept
    {
        return seed ^ (shape * 0x9E3779B1u) ^ (cycle * 0x85EBCA77u);
    }

    inline float bump (float t, float events) noexcept { return 0.5f * (1.0f - std::cos (kTwoPi * fracf (t * events))); }
    inline float edgeSpike (float t, int steps) noexcept
    {
        const float ph = fracf (t * (float) steps);
        return ph < 0.18f ? (1.0f - ph / 0.18f) : 0.0f;
    }
    inline float stepBip (float t, int steps, std::uint32_t seed) noexcept
    {
        const int idx = (int) (fracf (t) * (float) steps);
        return (hash01 (seed ^ 0x7EE7u, (std::uint32_t) idx) - 0.5f) * 1.8f;
    }
    inline float randHoldBip (float t, int holds, std::uint32_t mixedSeed) noexcept
    {
        const int idx = (int) (fracf (t) * (float) holds);
        return (hash01 (mixedSeed, (std::uint32_t) idx) - 0.5f) * 2.0f;
    }
    inline float driftSig (float t, std::uint32_t mixedSeed) noexcept
    {
        constexpr int holds = 6;
        const float pos = fracf (t) * (float) holds;
        const int i = (int) pos;
        const float fr = pos - (float) i;
        const float a = hash01 (mixedSeed ^ 0xD21Fu, (std::uint32_t) i);
        const float b = hash01 (mixedSeed ^ 0xD21Fu, (std::uint32_t) ((i + 1) % holds));
        return (lerpf (a, b, smoothstep (fr)) - 0.5f) * 2.0f;
    }
    inline float applySwing (float t, float swing) noexcept
    {
        if (swing <= 1.0e-4f) return t;
        constexpr float e = 8.0f;
        const float pairLen = 2.0f / e;
        const float base = std::floor (t / pairLen) * pairLen;
        const float pp = clampf ((t - base) / pairLen, 0.0f, 1.0f);
        const float r = 0.5f + 0.45f * clampf (swing, 0.0f, 1.0f);
        const float warped = pp < 0.5f ? (pp / 0.5f) * r : r + ((pp - 0.5f) / 0.5f) * (1.0f - r);
        return base + warped * pairLen;
    }
    inline float tensionShape (int /*target*/, float T) noexcept { return clampf (T, 0.0f, 1.0f); }

    inline float gesturePath (Gesture g, float t, float swing,
                              std::uint32_t seed, std::uint32_t cycle) noexcept
    {
        const float ts = applySwing (t, swing);
        switch (g)
        {
            case Gesture::Lift:  return  smoothstep (t);
            case Gesture::Suck:  return -smoothstep (t);
            case Gesture::Wash:  return  std::sin (kPi * t);                    // 0->1->0 swell
            case Gesture::Orbit: return  std::sin (kTwoPi * t);
            case Gesture::Pulse: return  bump (ts, 4.0f);
            case Gesture::Teeth: return  stepBip (ts, 8, seed ^ ((std::uint32_t) g * 0x9E37u));
            case Gesture::Drift: return  randHoldBip (t, 8, mixSeed (seed, (std::uint32_t) g, cycle));
        }
        return 0.0f;
    }
    inline float gestureAccent (Gesture g, float t, float swing) noexcept
    {
        const float ts = applySwing (t, swing);
        switch (g)
        {
            case Gesture::Lift:  return t * t * t;
            case Gesture::Suck:  return (1.0f - t) * (1.0f - t) * (1.0f - t);
            case Gesture::Wash:  return 0.0f;
            case Gesture::Orbit: return std::cos (kTwoPi * t);
            case Gesture::Pulse: return bump (ts, 4.0f);
            case Gesture::Teeth: return edgeSpike (ts, 8);
            case Gesture::Drift: return 0.0f;
        }
        return 0.0f;
    }
}

inline MoveSources evaluateSources (Gesture g, float t, const MoveContext& ctx = {}) noexcept
{
    using namespace detail;
    t = fracf (t + ctx.phaseOffset);
    const float path   = gesturePath (g, t, ctx.swing, ctx.seed, ctx.cycleIndex);
    const float accent = gestureAccent (g, t, ctx.swing);
    const float lag    = gesturePath (g, fracf (t - kLagPhase), ctx.swing, ctx.seed, ctx.cycleIndex);
    const float drift  = driftSig (t, mixSeed (ctx.seed, (std::uint32_t) g, ctx.cycleIndex)) * ctx.driftAmt;
    return { path, accent, lag, drift };
}

// ADDITIVE combine: move = tensionShape * (matrix . sources) * routeMaster ; final = clamp(base + move).
inline MoveLanes evaluateLanes (Gesture g, float t, float tension,
                                float baseMorph, float baseQ, float baseSlam, float baseGuard,
                                const MoveMatrix& mtx, const GestureLimits& lim = {},
                                const MoveContext& ctx = {}) noexcept
{
    using namespace detail;
    tension = clampf (tension, 0.0f, 1.0f);
    const auto s = evaluateSources (g, t, ctx);
    const float src[kNumSources] = { s.path, s.accent, s.lag, s.drift };
    const float base[kNumTargets] = { baseMorph, baseQ, baseSlam, baseGuard };
    const float hi  [kNumTargets] = { lim.morphMax, lim.qMax, lim.slamMax, lim.guardMax };
    const float lo  [kNumTargets] = { lim.morphMin, 0.0f, 0.0f, 0.0f };

    float out[kNumTargets];
    for (int tgt = 0; tgt < kNumTargets; ++tgt)
    {
        float sum = 0.0f;
        for (int srcI = 0; srcI < kNumSources; ++srcI)
            sum += mtx.get (srcI, tgt) * src[srcI];
        const float move = tensionShape (tgt, tension) * sum * clampf (ctx.routeMaster[tgt], 0.0f, 1.0f);
        out[tgt] = clampf (base[tgt] + move, lo[tgt], hi[tgt]);
    }
    return { out[0], out[1], out[2], out[3] };
}

// Back-compat 3-lane evaluate (factory matrix; cycle 0 -> preview-stable).
inline GestureResult evaluateGesture (Gesture g, float t, float tension,
                                      float baseMorph, float baseQ, float baseSlam,
                                      const GestureLimits& lim = {},
                                      std::uint32_t seed = 0x5EEDu) noexcept
{
    MoveContext ctx; ctx.seed = seed;
    const auto L = evaluateLanes (g, t, tension, baseMorph, baseQ, baseSlam, 0.0f,
                                  factoryMatrix ((int) g), lim, ctx);
    return { L.morph, L.press, L.slam };
}

// TIME rail. FREE is manual: no timeline. Synced values are in QUARTER NOTES so
// they lock to the host bar at any meter.
enum class GestureTime { Free, Quarter, Half, Bar1, Bar2, Bar4, Bar8 };
constexpr int kNumGestureTimes = 7;

inline bool gestureTimeIsFree (int timeIdx) noexcept { return timeIdx <= 0; }

inline double quarterNotesPerBar (int tsNumerator, int tsDenominator) noexcept
{
    const double num = tsNumerator   > 0 ? (double) tsNumerator   : 4.0;
    const double den = tsDenominator > 0 ? (double) tsDenominator : 4.0;
    return num * 4.0 / den;
}
inline double gestureCycleQuarterNotes (int timeIdx, double qnPerBar) noexcept
{
    switch (timeIdx)
    {
        case 1: return 1.0;            // 1/4
        case 2: return 2.0;            // 1/2
        case 3: return qnPerBar;       // 1 BAR
        case 4: return 2.0 * qnPerBar; // 2 BAR
        case 5: return 4.0 * qnPerBar; // 4 BAR
        case 6: return 8.0 * qnPerBar; // 8 BAR
    }
    return qnPerBar;
}
inline double gestureTimeBeats (GestureTime t) noexcept { return gestureCycleQuarterNotes ((int) t, 4.0); }

inline const char* gestureTimeName (GestureTime t) noexcept
{
    switch (t)
    {
        case GestureTime::Free:    return "FREE";
        case GestureTime::Quarter: return "1/4";
        case GestureTime::Half:    return "1/2";
        case GestureTime::Bar1:    return "1 BAR";
        case GestureTime::Bar2:    return "2 BAR";
        case GestureTime::Bar4:    return "4 BAR";
        case GestureTime::Bar8:    return "8 BAR";
    }
    return "1 BAR";
}

// Processor-owned, host-synced player.
//   ARM  — wait for the next bar, fire one cycle, RETURN TO BASE.
//   LIVE — immediate one-shot, RETURN TO BASE.
//   HOLD — immediate one-shot, then HOLD the target state.
//   LOOP — repeat (free-runs from BPM with no transport).
// All four lanes are smoothed PER LANE (anti-zipper, click-free on start/end).
class GestureEngine
{
public:
    void prepare (double sampleRate) noexcept { sr = sampleRate > 0 ? sampleRate : 48000.0; reset(); }

    void reset() noexcept
    {
        freePhase = 0.0; oneAccum = 0.0; startPpq = -1.0; freeCycle = 0; primed = false; pending = false;
    }

    MoveLanes advanceLanes (Gesture g, float tension, double cycleBeats,
                            float baseMorph, float baseQ, float baseSlam, float baseGuard,
                            const MoveMatrix& mtx, MoveMode mode,
                            double bpm, double ppqPosition, bool playing, int blockSize,
                            double barBeats = 4.0,
                            const MoveContext& ctxIn = {}, const GestureLimits& lim = {}) noexcept
    {
        const double cb  = cycleBeats > 1e-6 ? cycleBeats : 1.0;
        const double bar = barBeats   > 1e-6 ? barBeats   : 4.0;
        const double bps = (bpm > 1e-6 ? bpm : 120.0) / 60.0;
        const double cycleSec = cb / bps;
        const double inc = cycleSec > 1e-9 ? ((double) blockSize / sr) / cycleSec : 0.0;

        bool active = true;
        double phase = 0.0;
        std::uint32_t cycleIdx = 0;
        pending = false;

        if (mode == MoveMode::Loop)
        {
            if (playing && ppqPosition >= 0.0)
            {
                phase = std::fmod (ppqPosition / cb, 1.0);
                if (phase < 0.0) phase += 1.0;
                freePhase = phase;
                cycleIdx = (std::uint32_t) std::floor (ppqPosition / cb);
            }
            else
            {
                const double prev = freePhase;
                freePhase = std::fmod (freePhase + inc, 1.0);
                if (freePhase < prev) ++freeCycle;
                phase = freePhase;
                cycleIdx = freeCycle;
            }
        }
        else // ARM / LIVE / HOLD : one-shot
        {
            if (playing && ppqPosition >= 0.0)
            {
                if (startPpq < 0.0)
                    startPpq = (mode == MoveMode::Arm)
                                 ? (std::floor (ppqPosition / bar) + 1.0) * bar   // next bar
                                 : ppqPosition;
                const double elapsed = ppqPosition - startPpq;
                if (elapsed < 0.0)            { active = false; pending = true; }   // ARM waiting -> base, "FIRES NEXT BAR"
                else if (elapsed >= cb)        { if (mode == MoveMode::Hold) phase = 0.99999; else active = false; }
                else                           phase = elapsed / cb;
                cycleIdx = (std::uint32_t) std::floor (startPpq / cb);
            }
            else
            {
                oneAccum += inc;
                if (oneAccum >= 1.0) { if (mode == MoveMode::Hold) phase = 0.99999; else active = false; }
                else                 phase = oneAccum;
                cycleIdx = 0;
            }
        }

        MoveContext ctx = ctxIn;
        ctx.cycleIndex = cycleIdx;
        const auto raw = active
            ? evaluateLanes (g, (float) phase, tension, baseMorph, baseQ, baseSlam, baseGuard, mtx, lim, ctx)
            : MoveLanes { baseMorph, baseQ, baseSlam, baseGuard };   // return to base

        if (! primed) { smM = raw.morph; smP = raw.press; smS = raw.slam; smG = raw.guard; primed = true; }
        const double blockSec = (double) blockSize / sr;
        const float aM = (float) (1.0 - std::exp (-blockSec / 0.015));   // Morph 15 ms
        const float aP = (float) (1.0 - std::exp (-blockSec / 0.022));   // Press 22 ms
        const float aS = (float) (1.0 - std::exp (-blockSec / 0.007));   // Slam 7 ms
        const float aG = (float) (1.0 - std::exp (-blockSec / 0.012));   // Guard 12 ms
        smM += (raw.morph - smM) * aM;
        smP += (raw.press - smP) * aP;
        smS += (raw.slam  - smS) * aS;
        smG += (raw.guard - smG) * aG;
        return { smM, smP, smS, smG };
    }

    float uiPhase() const noexcept { return (float) freePhase; }
    bool  armedPending() const noexcept { return pending; }   // ARM waiting for the next bar

private:
    double sr = 48000.0;
    double freePhase = 0.0;
    double oneAccum = 0.0;
    double startPpq = -1.0;
    std::uint32_t freeCycle = 0;
    float smM = 0.0f, smP = 0.0f, smS = 0.0f, smG = 0.0f;
    bool primed = false;
    bool pending = false;
};

} // namespace trench
