#pragma once
#include "FuncGenPatterns.h"
#include <cmath>
#include <cstdint>

// One modulation engine. Produces a MORPH offset (and optional Q offset) per
// block, additive around the current knob position. Replaces the old
// MotionEngine step-sequencer + GestureEngine gesture-matrix tangle.
//
// Model (matches the SPEED / TRIGGER / DEPTH face controls):
//   TRIGGER  = SYNC (tempo LFO) | ENV (input follower) | RISER (one-shot ramp)
//   SPEED    = note value  x  feel(straight/triplet/dotted), or free Hz
//   DEPTH    = travel around the slider
//   SHAPE    = sine | ramp | square | random  (SYNC only)
// ORBIT (spatial pan) is a separate toggle and lives outside this engine.

namespace trench
{

struct MorphModResult { float morph = 0.0f; float q = 0.0f; };

enum class ModTrigger { Sync, Env, Riser };
// Smooth (Sine/Tri/Ramp) + rhythmic (Stair arp, Square call/response, Random S&H).
// Rhythmic shapes are what turn a drum loop into a melody as MORPH steps.
enum class ModShape   { Sine, Tri, Ramp, Stair, Square, Random };
// Shape indices >= kNumBaseShapes select an E-MU factory Function Generator
// pattern (FuncGenPatterns.h): shapeIdx - kNumBaseShapes = pattern id.
// SPEED clocks one pattern STEP (the X3 law), not the whole table.
inline constexpr int kNumBaseShapes = 6;
enum class ModFeel    { Straight, Triplet, Dotted };
// ponytail: 8-step arp; a user-editable pattern table is the upgrade path once
// Tyson's ear picks the rhythms worth shipping.
inline constexpr int kStairSteps = 8;

// Note value in quarter notes (4/4 reference). Bars are meter-scaled by the
// caller. Index order is the on-glass SPEED strip, slow -> fast.
inline constexpr int    kNumModNotes = 15;
inline constexpr double kModNoteQuarterNotes[kNumModNotes] = {
    16.0, // 4 bar
     8.0, // 2 bar
     4.0, // 1 bar
     2.0, // 1/2
     1.0, // 1/4
     0.5, // 1/8
     0.25,// 1/16
     0.125,// 1/32 (banned from the menu; kept for state compat)
     1.5,  // 3/8
     0.75, // 3/16
     1.25, // 5/16
     2.0 / 3.0,  // 1/6  (quarter triplet)
     1.0 / 3.0,  // 1/12 (eighth triplet)
     2.5,  // 5/8
     1.75  // 7/16
};

// Quarter notes per bar for a host time signature (e.g. 6/8 -> 3.0).
inline double quarterNotesPerBar (int tsNumerator, int tsDenominator) noexcept
{
    const double num = tsNumerator   > 0 ? (double) tsNumerator   : 4.0;
    const double den = tsDenominator > 0 ? (double) tsDenominator : 4.0;
    return num * 4.0 / den;
}

// Feel multiplier: triplet = x2/3 (faster), dotted = x3/2 (slower).
inline constexpr double modFeelMultiplier (ModFeel f) noexcept
{
    return f == ModFeel::Triplet ? (2.0 / 3.0)
         : f == ModFeel::Dotted  ? (3.0 / 2.0)
         : 1.0;
}

// Cycle length in quarter-note beats for a synced note+feel. Bars (indices 0..2)
// ignore feel and are scaled to the host meter; note values take the feel.
inline double modCycleBeats (int noteIdx, ModFeel feel, double quarterNotesPerBar) noexcept
{
    const int i = noteIdx < 0 ? 0 : (noteIdx >= kNumModNotes ? kNumModNotes - 1 : noteIdx);
    const double meter = quarterNotesPerBar > 1.0e-6 ? quarterNotesPerBar : 4.0;
    if (i <= 2) // 4 bar / 2 bar / 1 bar
        return kModNoteQuarterNotes[i] * meter / 4.0;
    return kModNoteQuarterNotes[i] * modFeelMultiplier (feel);
}

class MorphMod
{
public:
    void prepare (double sampleRate) noexcept
    {
        sr = sampleRate > 0.0 ? sampleRate : 48000.0;
        reset();
        rngState = 0x1234567u;
    }

    void reset() noexcept
    {
        freePhase = 0.0;
        phaseOffset = 0.0;
        restartPending = false;
        riserDone = false;
        prevPlaying = false;
        lastCycle = -1;
        held = 0.0f;
        smMorph = smQ = 0.0f;
        primed = false;
        patAnchor = 0; patCycle = -1; patPos = patNext = 0; patInit = false;
    }

    // The next apply() re-anchors the cycle so phase starts at 0 (e.g. after
    // the user re-places the Morph wheel: modulation restarts from the new
    // anchor instead of landing mid-cycle). Audio thread only.
    void requestRestart() noexcept { restartPending = true; }

    // centerMorph/centerQ are the current (smoothed) knob positions.
    // env is the input follower in [0,1]. depth/qDepth in [0,1].
    MorphModResult apply (bool on, ModTrigger trig, int shapeIdx,
                          bool synced, int noteIdx, ModFeel feel, float rateHz,
                          float depth, float qDepth, float env,
                          double bpm, double ppq, bool playing, double quarterNotesPerBar,
                          float centerMorph, float centerQ, int blockSize) noexcept
    {
        if (! on || depth <= 0.0005f)
            return { centerMorph, centerQ };

        const double blockSec = (double) blockSize / sr;

        float bipolar = 0.0f; // [-1,1] for Sync/Riser; env path handled below
        float unipolar = 0.0f; // [0,1]

        if (trig == ModTrigger::Env)
        {
            unipolar = env < 0.0f ? 0.0f : (env > 1.0f ? 1.0f : env);
        }
        else
        {
            // Advance a 0..1 cycle phase, host-locked when playing+synced.
            const double cycleSec = synced
                ? modCycleBeats (noteIdx, feel, quarterNotesPerBar) / ((bpm > 1.0e-6 ? bpm : 120.0) / 60.0)
                : 1.0 / (double) (rateHz > 0.01f ? rateHz : 0.01f);

            double phase;
            std::int64_t cycle;
            if (synced && playing && ppq >= 0.0)
            {
                const double beats = modCycleBeats (noteIdx, feel, quarterNotesPerBar);
                phase = std::fmod (ppq / beats, 1.0);
                if (phase < 0.0) phase += 1.0;
                cycle = (std::int64_t) std::floor (ppq / beats);
                freePhase = phase;
            }
            else
            {
                const double inc = cycleSec > 1.0e-9 ? blockSec / cycleSec : 0.0;
                const double prev = freePhase;
                freePhase = std::fmod (freePhase + inc, 1.0);
                if (freePhase < prev) ++freeCycle;
                phase = freePhase;
                cycle = (std::int64_t) freeCycle;
            }

            if (restartPending)
            {
                restartPending = false;
                phaseOffset = phase;          // this instant becomes phase 0
                riserDone = false;
                riserStartCycle = cycle;
                patAnchor = cycle;            // pattern restarts at step 0
                patInit = false;
            }
            phase -= phaseOffset;
            if (phase < 0.0) phase += 1.0;

            const bool transportStart = playing && ! prevPlaying;
            prevPlaying = playing;

            if (trig == ModTrigger::Riser)
            {
                if (transportStart) { riserDone = false; riserStartCycle = cycle; }
                // One-shot 0->1 across a single cycle, then hold at 1.
                if (synced && playing && ppq >= 0.0)
                {
                    if (! riserDone && cycle != riserStartCycle)
                        riserDone = true;   // the start cycle ended: land and hold
                    unipolar = riserDone ? 1.0f : (float) phase;
                }
                else
                {
                    if (! riserDone) unipolar = (float) phase;
                    if (freePhase < 1.0e-6 && unipolar > 0.5f) { riserDone = true; unipolar = 1.0f; }
                }
            }
            else // Sync LFO or E-MU function-generator pattern
            {
                const int pat = shapeIdx - kNumBaseShapes;
                if (pat >= 0 && pat < kNumFuncGenPatterns)
                    bipolar = patternValue (kFuncGenPatterns[pat], (float) phase, cycle);
                else
                    bipolar = shapeValue ((ModShape) shapeIdx, (float) phase, cycle);
            }
        }

        float rawMorph, rawQ;
        if (trig == ModTrigger::Sync)
        {
            rawMorph = centerMorph + bipolar * depth;
            rawQ     = centerQ     + std::fabs (bipolar) * qDepth;
        }
        else // Env / Riser are unipolar lifts
        {
            rawMorph = centerMorph + unipolar * depth;
            rawQ     = centerQ     + unipolar * qDepth;
        }

        // Per-block one-pole de-zipper (coeff ramp downstream still applies).
        if (! primed) { smMorph = rawMorph; smQ = rawQ; primed = true; }
        const float a = (float) (1.0 - std::exp (-blockSec / 0.015));
        smMorph += (rawMorph - smMorph) * a;
        smQ     += (rawQ     - smQ)     * a;

        return { clamp01 (smMorph), clamp01 (smQ) };
    }

    float uiPhase() const noexcept { return (float) freePhase; }

private:
    static float clamp01 (float x) noexcept { return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); }

    float shapeValue (ModShape s, float phase, std::int64_t cycle) noexcept
    {
        constexpr float kTwoPi = 6.28318530718f;
        switch (s)
        {
            case ModShape::Sine:   return std::sin (kTwoPi * phase);
            case ModShape::Tri:    return 1.0f - 4.0f * std::fabs (phase - 0.5f); // -1..1 bounce
            case ModShape::Ramp:   return 2.0f * phase - 1.0f;                    // -1 -> 1 saw
            case ModShape::Stair:  // rising 8-step arp, -1..1
            {
                const int st = (int) (phase * (float) kStairSteps);
                return 2.0f * ((float) st / (float) (kStairSteps - 1)) - 1.0f;
            }
            case ModShape::Square: return phase < 0.5f ? 1.0f : -1.0f;
            case ModShape::Random:
                if (cycle != lastCycle) { lastCycle = cycle; held = whiteBip(); }
                return held;
        }
        return 0.0f;
    }

    // One E-MU function-generator step per SPEED cycle. Direction, length and
    // smooth are the AUTHORED template values; DEPTH scales the travel.
    float patternValue (const FuncGenPattern& p, float phase, std::int64_t cycle) noexcept
    {
        const std::int64_t rel = cycle - patAnchor;
        if (! patInit || cycle != patCycle)
        {
            if (! patInit)
            {
                patInit = true;
                patPos = positionFor (p, rel);
                patNext = nextPosition (p, patPos, rel + 1);
            }
            else
            {
                // Advance one step per cycle tick (handles block-rate skips too).
                for (std::int64_t c = patCycle; c < cycle; ++c)
                {
                    patPos = patNext;
                    patNext = nextPosition (p, patPos, (c + 1 - patAnchor) + 1);
                }
            }
            patCycle = cycle;
        }
        const float cur = p.values[patPos];
        if (! p.smooth)
            return cur;
        return cur + (p.values[patNext] - cur) * phase;
    }
    // Deterministic directions map a step counter to a table position.
    int positionFor (const FuncGenPattern& p, std::int64_t rel) const noexcept
    {
        const int n = p.steps;
        if (n <= 1) return 0;
        const std::int64_t m = rel < 0 ? 0 : rel;
        switch (p.direction)
        {
            default:
            case 0: return (int) (m % n);                       // forward
            case 1: return n - 1 - (int) (m % n);               // reverse
            case 2:                                             // pendulum
            {
                const int period = 2 * n - 2;
                const int q = (int) (m % period);
                return q < n ? q : period - q;
            }
            case 5: return (int) (m < n ? m : n - 1);           // one-shot: hold end
            case 3: case 4: return (int) (m % n);               // random/brownian seed
        }
    }
    int nextPosition (const FuncGenPattern& p, int pos, std::int64_t relNext) noexcept
    {
        const int n = p.steps;
        if (n <= 1) return 0;
        switch (p.direction)
        {
            case 3: // random: any step
                return (int) ((whiteBip() * 0.5f + 0.5f) * (float) n) % n;
            case 4: // brownian: adjacent step, bounce off the ends
            {
                const bool up = whiteBip() >= 0.0f;
                if (pos <= 0) return 1;
                if (pos >= n - 1) return n - 2;
                return up ? pos + 1 : pos - 1;
            }
            default:
                return positionFor (p, relNext);
        }
    }

    float whiteBip() noexcept
    {
        rngState = rngState * 1664525u + 1013904223u;
        return (float) (rngState >> 8) * (1.0f / 8388608.0f) - 1.0f; // [-1,1)
    }

    double sr = 48000.0;
    double freePhase = 0.0;
    double phaseOffset = 0.0;
    bool restartPending = false;
    std::uint64_t freeCycle = 0;
    std::int64_t lastCycle = -1;
    std::int64_t riserStartCycle = -1;
    float held = 0.0f;
    bool riserDone = false;
    bool prevPlaying = false;
    float smMorph = 0.0f, smQ = 0.0f;
    bool primed = false;
    std::int64_t patAnchor = 0, patCycle = -1;
    int patPos = 0, patNext = 0;
    bool patInit = false;
    std::uint32_t rngState = 0x1234567u;
};

} // namespace trench
