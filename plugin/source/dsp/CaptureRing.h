#pragma once
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <vector>
namespace trench
{
class CaptureRing
{
public:
    void prepare (double sampleRate, double maxSeconds)
    {
        sr = (sampleRate > 0.0) ? sampleRate : 0.0;
        const double c = std::ceil (sr * ((maxSeconds > 0.0) ? maxSeconds : 0.0));
        cap = (c > 0.0) ? (int) c : 0;
        bufL.assign ((size_t) cap, 0.0f);
        bufR.assign ((size_t) cap, 0.0f);
        written.store (0, std::memory_order_release);
    }
    void write (const float* l, const float* r, int n) noexcept
    {
        if (cap == 0 || n <= 0 || l == nullptr)
            return;
        uint64_t w = written.load (std::memory_order_relaxed);
        for (int i = 0; i < n; ++i)
        {
            const size_t idx = (size_t) ((w + (uint64_t) i) % (uint64_t) cap);
            bufL[idx] = l[i];
            bufR[idx] = (r != nullptr) ? r[i] : l[i];
        }
        written.store (w + (uint64_t) n, std::memory_order_release);
    }
    int snapshotLast (double seconds, float* outL, float* outR, int maxFrames) const
    {
        if (cap == 0 || maxFrames <= 0 || outL == nullptr || outR == nullptr)
            return 0;
        const uint64_t w = written.load (std::memory_order_acquire);
        const uint64_t avail = (w < (uint64_t) cap) ? w : (uint64_t) cap;
        long long want = std::llround (seconds * sr);
        if (want < 0)
            want = 0;
        int frames = (int) std::min<uint64_t> ((uint64_t) want, avail);
        frames = std::min (frames, cap);
        frames = std::min (frames, maxFrames);
        const uint64_t startAbs = w - (uint64_t) frames;
        for (int i = 0; i < frames; ++i)
        {
            const size_t idx = (size_t) ((startAbs + (uint64_t) i) % (uint64_t) cap);
            outL[i] = bufL[idx];
            outR[i] = bufR[idx];
        }
        return frames;
    }
    double sampleRate() const noexcept { return sr; }
    int capacity() const noexcept { return cap; }
private:
    std::vector<float> bufL, bufR;
    int cap = 0;
    double sr = 0.0;
    std::atomic<uint64_t> written { 0 };
};
}
