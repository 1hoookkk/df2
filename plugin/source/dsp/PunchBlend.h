#pragma once

#include <algorithm>
#include <cmath>
#include <vector>

namespace trench
{
// MIX — the punch-preserving parallel blend (replaces the old serial AMOUNT dose).
//
// A plain dry/wet crossfade treats every part of the signal the same, so at 25%
// you hear "a faint version of TRENCH". This blend instead keeps what a producer
// wants to RETAIN dry and introduces what they want ADDED early, so 25% reads as
// "the original drum impact with a clearly audible TRENCH melody wrapped around it":
//
//   character / body   wet early      wHi = sqrt(m)
//   low-end anchor     stays dry      wLo = m*m
//   transients         stay dry       ducked toward smoothstep(0.4,1,m) on attacks
//   m = 1              everything fully wet (bit-identical to the pre-MIX sound)
//
// The dry path is the pristine host input delayed to match the island's reported
// latency, summed in parallel against the full-imprint wet output. All state is
// sized in prepare(); process() allocates nothing and is real-time safe.
//
// ponytail: one-pole complementary split (dLo+dHi == dry exactly), not a proper
// crossover network — upgrade to multiband only if the ear asks for it.
class PunchBlend
{
public:
    // Message thread, before audio. maxLatency bounds the dry alignment delay
    // (the island's worst-case reported latency); maxBlock the largest host block.
    void prepare (double sampleRate, int maxLatency, int maxBlock)
    {
        sr = (sampleRate > 0.0) ? sampleRate : 48000.0;
        dlCap = std::max (1, maxLatency + maxBlock + 8);
        for (auto& d : delay) d.assign ((size_t) dlCap, 0.0f);
        dry.assign ((size_t) std::max (2, 2 * maxBlock), 0.0f); // interleaved L/R scratch

        // 120 Hz one-pole for the sub anchor; MIX smoothed ~20 ms to kill zipper
        // (the old serial dose was ramped inside the engine — this path is not).
        lpCoef  = onePole (120.0);
        mixCoef = tauCoef (0.020);
        // Transient = onset detector. Two PEAK followers differing in ATTACK:
        // fast catches an onset instantly, slow lags it; both hold on release so a
        // sustained tone converges to zero gap (no false ducking on steady notes).
        fastAtk = tauCoef (0.0002); fastRel = tauCoef (0.030);
        slowAtk = tauCoef (0.030);  slowRel = tauCoef (0.150);
        reset();
    }

    void setLatency (int samples) noexcept { latency = std::clamp (samples, 0, dlCap - 1); }

    void reset() noexcept
    {
        for (auto& d : delay) std::fill (d.begin(), d.end(), 0.0f);
        for (int c = 0; c < 2; ++c) { lpDry[c] = lpWet[c] = fastEnv[c] = slowEnv[c] = 0.0f; }
        dlWrite = 0;
        mixSmoothed = -1.0f; // force a snap to the first target (no fade in from 0)
    }

    // Audio thread, BEFORE the island overwrites `buffer` with the wet output.
    // Copies the pristine dry input for this block.
    void captureDry (const float* const* in, int numCh, int n) noexcept
    {
        capCh = std::min (2, numCh);
        capN  = std::min (n, (int) dry.size() / 2);
        for (int i = 0; i < capN; ++i)
        {
            const float l = in[0][i];
            const float r = (capCh > 1) ? in[1][i] : l;
            dry[(size_t) (2 * i)]     = l;
            dry[(size_t) (2 * i) + 1] = r;
        }
    }

    // Audio thread, AFTER the island. `wet` holds the full-imprint output; blends
    // the latency-aligned dry back in per the MIX law, in place. No allocation.
    void blend (float* const* wet, int numCh, int n, float mixTarget) noexcept
    {
        if (mixSmoothed < 0.0f) mixSmoothed = mixTarget;
        const int ch = std::min ({ 2, numCh, capCh });
        const int len = std::min (n, capN);

        for (int i = 0; i < len; ++i)
        {
            mixSmoothed += mixCoef * (mixTarget - mixSmoothed);
            const float m   = std::clamp (mixSmoothed, 0.0f, 1.0f);
            const float wHi = std::sqrt (m);              // character appears early
            const float wLo = m * m;                      // bass stays dry longer
            const float tMx = smoothstep (0.4f, 1.0f, m); // punch stays dry longest

            for (int c = 0; c < 2; ++c)
            {
                // Push this sample's dry into the alignment delay, read it back
                // `latency` samples later so it lines up with the wet output.
                const int wi = dlWrite;
                delay[c][(size_t) wi] = dry[(size_t) (2 * i) + (size_t) std::min (c, capCh - 1)];
                int ri = wi - latency; if (ri < 0) ri += dlCap;
                const float d = delay[c][(size_t) ri];

                if (c >= ch) continue; // still advance the delay for silent channels

                const float w = wet[c][i];

                // One-pole complementary split: lo + hi == signal, exactly.
                lpDry[c] += lpCoef * (d - lpDry[c]); const float dLo = lpDry[c], dHi = d - dLo;
                lpWet[c] += lpCoef * (w - lpWet[c]); const float wLoS = lpWet[c], wHiS = w - wLoS;

                // Transient confidence from the dry. A fast peak-follower smooths
                // |d| into an envelope; a slow follower chases THAT envelope (not the
                // raw AC — else a sustained note reads as a permanent transient).
                // In steady state the two converge (t->0); a real onset opens a gap.
                // ponytail: fixed feel constants — expose as knobs only if the ear needs tuning.
                const float a = std::abs (d);
                fastEnv[c] += (a > fastEnv[c] ? fastAtk : fastRel) * (a - fastEnv[c]);
                const float fe = fastEnv[c];
                slowEnv[c] += (fe > slowEnv[c] ? slowAtk : slowRel) * (fe - slowEnv[c]);
                const float t = std::clamp ((fe - slowEnv[c]) / (slowEnv[c] + 1.0e-4f) * kSens, 0.0f, 1.0f);

                // On an attack, duck the character wet toward its transient ceiling
                // so the dry impact punches through; never boost it.
                const float wHiG = wHi - t * std::max (0.0f, wHi - tMx);

                wet[c][i] = (dLo + (wLoS - dLo) * wLo) + (dHi + (wHiS - dHi) * wHiG);
            }
            dlWrite = (dlWrite + 1 < dlCap) ? dlWrite + 1 : 0;
        }
    }

private:
    static float smoothstep (float e0, float e1, float x) noexcept
    {
        const float t = std::clamp ((x - e0) / (e1 - e0), 0.0f, 1.0f);
        return t * t * (3.0f - 2.0f * t);
    }
    float onePole (double fc) const noexcept  // one-pole LP by corner frequency
    {
        return (float) (1.0 - std::exp (-2.0 * 3.14159265358979 * fc / sr));
    }
    float tauCoef (double tauSeconds) const noexcept  // one-pole follower by time constant
    {
        return (float) (1.0 - std::exp (-1.0 / (std::max (1.0e-6, tauSeconds) * sr)));
    }

    static constexpr float kSens = 3.0f; // how strongly the fast/slow gap gates the wet

    double sr = 48000.0;
    float lpCoef = 0.0f, mixCoef = 0.0f;
    float fastAtk = 0.0f, fastRel = 0.0f, slowAtk = 0.0f, slowRel = 0.0f;
    std::vector<float> delay[2];
    std::vector<float> dry;      // interleaved L/R scratch for the current block
    int dlCap = 1, dlWrite = 0, latency = 0;
    int capCh = 0, capN = 0;
    float lpDry[2] {}, lpWet[2] {};
    float fastEnv[2] {}, slowEnv[2] {};
    float mixSmoothed = -1.0f;
};
} // namespace trench
