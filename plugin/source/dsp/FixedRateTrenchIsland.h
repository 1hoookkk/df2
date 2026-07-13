#pragma once

#include "../TrenchRates.h"
#include "TrenchDspBridge.h"
#include <juce_audio_basics/juce_audio_basics.h>
#include <juce_dsp/juce_dsp.h>
#include <vector>

namespace trench
{

/**
 * FixedRateTrenchIsland handles the SRC path from Host Rate -> 39062.5 Hz -> Host Rate.
 * In this clean migration version, it manages a TrenchDspBridge.
 *
 * Realtime contract: process() performs NO heap allocation and NO unbounded
 * shift/erase work. All scratch storage is sized once in prepare() to the
 * worst case for the prepared host rate and max block size. The sample FIFOs are
 * fixed-capacity linear buffers that advance a read cursor and compact (a single
 * bounded memmove) only when the write cursor would run off the end — never an
 * O(n)-per-sample erase and never a reallocation. If the host violates its block
 * contract the path degrades to a cleared block rather than growing a buffer.
 */
class FixedRateTrenchIsland
{
public:
    FixedRateTrenchIsland();
    ~FixedRateTrenchIsland();

    void prepare (double hostSampleRate, int maxBlockSizeSamples, TrenchDspBridge& bridge);
    void process (juce::AudioBuffer<float>& buffer, TrenchDspBridge& bridge, const TrenchParams& params);

    int getLatencySamples() const noexcept { return latencySamples; }

private:
    // Fixed-capacity, single-producer/single-consumer (audio thread only) linear
    // sample FIFO. Capacity is allocated once in prepare(); push()/consume() never
    // allocate. The live region [readPos, writePos) is always contiguous, so
    // readPtr() hands the interpolator a valid contiguous span of size() samples.
    struct ScratchFifo
    {
        void prepare (int capacitySamples)
        {
            storage.assign ((size_t) juce::jmax (0, capacitySamples), 0.0f);
            readPos = 0;
            writePos = 0;
        }

        void reset() noexcept { readPos = 0; writePos = 0; }

        int  size()     const noexcept { return writePos - readPos; }
        int  capacity() const noexcept { return (int) storage.size(); }
        const float* readPtr() const noexcept { return storage.data() + readPos; }

        // Returns false (without writing) if the data genuinely does not fit in
        // the fixed capacity — the caller then drops the block to silence.
        bool push (const float* src, int n) noexcept
        {
            if (n <= 0)
                return true;
            if (size() + n > capacity())
                return false;
            if (writePos + n > capacity())
                compact();
            std::copy (src, src + n, storage.data() + writePos);
            writePos += n;
            return true;
        }

        void consume (int n) noexcept
        {
            readPos += juce::jlimit (0, size(), n);
            if (readPos >= writePos)
                reset();
        }

        // Single bounded memmove of the live region down to the front. Runs at
        // most once per push, only when the tail is exhausted.
        void compact() noexcept
        {
            const int live = size();
            if (readPos > 0 && live > 0)
                std::copy (storage.data() + readPos, storage.data() + writePos, storage.data());
            readPos = 0;
            writePos = live;
        }

        std::vector<float> storage; // capacity fixed in prepare(); never grows in process()
        int readPos = 0;
        int writePos = 0;
    };

    static int sharedSize (const ScratchFifo& a, const ScratchFifo& b) noexcept
    {
        return juce::jmin (a.size(), b.size());
    }

    double hostRate = 44100.0;
    int latencySamples = 0;
    int maxHostBlock = 0;
    int maxInternalSamples = 0;

    // Resamplers: 200-tap windowed-sinc both directions. The old 4th-order
    // Lagrange had ~-30 dBc images folding into the audible band (measured in
    // IslandNullTests); the sinc kernel puts interpolation images below -90 dB.
    juce::WindowedSincInterpolator inputResamplerL, inputResamplerR;
    juce::WindowedSincInterpolator outputResamplerL, outputResamplerR;

    // Anti-fold guard before the 48k->39062.5 downsample: host-band content
    // above the E-mu Nyquist (19531 Hz) would alias straight into the band.
    // 8th-order Butterworth at 19.3 kHz (4 cascaded biquads per channel).
    // Passband cost: ~-1 dB at 18 kHz — period-correct (the hardware had
    // nothing above 19.5 kHz either); fold rejection >40 dB by 21 kHz.
    static constexpr int kGuardStages = 4;
    juce::dsp::IIR::Filter<float> guardLP[2][kGuardStages];
    std::vector<float> guardScratchL, guardScratchR;

    // Intermediate buffer at 39062.5 Hz, sized once in prepare().
    juce::AudioBuffer<float> internalBuffer;
    ScratchFifo hostFifoL, hostFifoR;
    ScratchFifo processedFifoL, processedFifoR;

    bool bypassSRC = false;
};

} // namespace trench
