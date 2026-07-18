#pragma once

#include <cmath>

namespace trench
{

// KEY TRACKING detector — the lost Morpheus Frequency Tracking axis, plugin
// half. Hears the input's note (YIN difference function on a 4x-decimated
// ring), snaps it to 12-TET, and answers with a PITCH-CLASS transpose ratio
// in ±6 semitones around the authored body (C anchor: an input C leaves the
// body untouched). Pitch class, not absolute pitch, so a bass line and its
// octave ask for the same colour and the body never runs away in register.
//
// Audio-thread safe: fixed buffers, no allocation. Analyze cost ~100k mults
// per hop (>= kHopSamples input samples between analyses).
struct KeyTrackDetector
{
    static constexpr int   kDecim = 4;
    static constexpr int   kWin = 512;             // analysis window (decimated)
    static constexpr int   kMaxLag = 256;          // min f0 = decimRate / kMaxLag
    static constexpr int   kHopSamples = 512;      // host samples between analyses
    static constexpr float kThreshold = 0.15f;     // YIN CMND voicing threshold
    static constexpr float kMinLevel = 1.0e-3f;    // gate: don't track silence

    void prepare (double hostRate)
    {
        decimRate = (float) (hostRate / kDecim);
        write = 0; phase = 0; sinceHop = 0; lp = 0.0f;
        ratio = 1.0f; pendingSemis = 99; stableSemis = 99;
        for (auto& v : ring) v = 0.0f;
    }

    // Feed one host-rate block of the DRY input; returns the current ratio.
    float process (const float* mono, int n) noexcept
    {
        for (int i = 0; i < n; ++i)
        {
            lp += 0.5f * (mono[i] - lp);           // crude anti-alias for /4
            if (++phase == kDecim)
            {
                phase = 0;
                ring[write] = lp;
                write = (write + 1) & (kRing - 1);
            }
        }
        sinceHop += n;
        if (sinceHop >= kHopSamples)
        {
            sinceHop = 0;
            analyze();
        }
        return ratio;
    }

    float currentRatio() const noexcept { return ratio; }

private:
    static constexpr int kRing = 1024;             // power of two >= kWin + kMaxLag

    void analyze() noexcept
    {
        // unroll the ring into a linear window ending at `write`
        float x[kWin + kMaxLag];
        const int start = (write - (kWin + kMaxLag)) & (kRing - 1);
        float level = 0.0f;
        for (int i = 0; i < kWin + kMaxLag; ++i)
        {
            x[i] = ring[(start + i) & (kRing - 1)];
            level = std::fmax (level, std::fabs (x[i]));
        }
        if (level < kMinLevel)
            return;                                 // silence: hold the last ratio

        // YIN: difference function + cumulative mean normalization
        float d[kMaxLag + 1];
        d[0] = 0.0f;
        float running = 0.0f;
        int best = 0;
        float bestVal = 1.0f;
        for (int tau = 1; tau <= kMaxLag; ++tau)
        {
            float sum = 0.0f;
            for (int i = 0; i < kWin; ++i)
            {
                const float diff = x[i] - x[i + tau];
                sum += diff * diff;
            }
            running += sum;
            d[tau] = running > 0.0f ? sum * (float) tau / running : 1.0f;
            if (tau >= 8 && d[tau] < kThreshold)   // first dip below threshold wins
            {
                best = tau;
                bestVal = d[tau];
                // walk down to the local minimum
                int t = tau;
                while (t + 1 <= kMaxLag)
                {
                    float s2 = 0.0f;
                    for (int i = 0; i < kWin; ++i)
                    {
                        const float diff = x[i] - x[i + t + 1];
                        s2 += diff * diff;
                    }
                    running += s2;
                    const float dv = s2 * (float) (t + 1) / running;
                    if (dv >= bestVal) break;
                    ++t; best = t; bestVal = dv;
                    d[t] = dv;
                }
                break;
            }
        }
        if (best == 0)
            return;                                 // unvoiced: hold

        const float f0 = decimRate / (float) best;
        const int semis = (int) std::lround (12.0 * std::log2 ((double) f0 / 440.0));
        // pitch class relative to C (A440 is pitch class 9), folded to +-6
        int pc = ((semis + 9) % 12 + 12) % 12;      // 0 = C
        if (pc > 6) pc -= 12;
        // debounce: a new pitch class must be seen twice in a row to take
        if (pc == pendingSemis)
        {
            if (pc != stableSemis)
            {
                stableSemis = pc;
                ratio = (float) std::pow (2.0, (double) pc / 12.0);
            }
        }
        pendingSemis = pc;
    }

    float ring[kRing] {};
    float decimRate = 11025.0f;
    float lp = 0.0f;
    float ratio = 1.0f;
    int write = 0, phase = 0, sinceHop = 0;
    int pendingSemis = 99, stableSemis = 99;
};

} // namespace trench
