#pragma once
#include <algorithm>
#include <cmath>
#include <vector>
namespace trench
{
// TRUE wet/dry mix (2026-07-25 per Tyson: "mix is not truly wet/dry").
// Latency-compensated linear crossfade: out = dry + (wet - dry) * mix.
// The previous psycho blend (band-split sqrt/square laws + transient ducking)
// was program-dependent at every setting except 0 and 100.
class PunchBlend
{
public:
    void prepare (double sampleRate, int maxLatency, int maxBlock)
    {
        sr = (sampleRate > 0.0) ? sampleRate : 48000.0;
        dlCap = std::max (1, maxLatency + maxBlock + 8);
        for (auto& d : delay) d.assign ((size_t) dlCap, 0.0f);
        dry.assign ((size_t) std::max (2, 2 * maxBlock), 0.0f);
        mixCoef = tauCoef (0.020);
        reset();
    }
    void setLatency (int samples) noexcept { latency = std::clamp (samples, 0, dlCap - 1); }
    void reset() noexcept
    {
        for (auto& d : delay) std::fill (d.begin(), d.end(), 0.0f);
        dlWrite = 0;
        mixSmoothed = -1.0f;
    }
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
    void blend (float* const* wet, int numCh, int n, float mixTarget) noexcept
    {
        if (mixSmoothed < 0.0f) mixSmoothed = mixTarget;
        const int ch = std::min ({ 2, numCh, capCh });
        const int len = std::min (n, capN);
        for (int i = 0; i < len; ++i)
        {
            mixSmoothed += mixCoef * (mixTarget - mixSmoothed);
            const float m = std::clamp (mixSmoothed, 0.0f, 1.0f);
            for (int c = 0; c < 2; ++c)
            {
                const int wi = dlWrite;
                delay[c][(size_t) wi] = dry[(size_t) (2 * i) + (size_t) std::min (c, capCh - 1)];
                int ri = wi - latency; if (ri < 0) ri += dlCap;
                const float d = delay[c][(size_t) ri];
                if (c >= ch) continue;
                wet[c][i] = d + (wet[c][i] - d) * m;
            }
            dlWrite = (dlWrite + 1 < dlCap) ? dlWrite + 1 : 0;
        }
    }
private:
    float tauCoef (double tauSeconds) const noexcept
    {
        return (float) (1.0 - std::exp (-1.0 / (std::max (1.0e-6, tauSeconds) * sr)));
    }
    double sr = 48000.0;
    float mixCoef = 0.0f;
    std::vector<float> delay[2];
    std::vector<float> dry;
    int dlCap = 1, dlWrite = 0, latency = 0;
    int capCh = 0, capN = 0;
    float mixSmoothed = -1.0f;
};
}
