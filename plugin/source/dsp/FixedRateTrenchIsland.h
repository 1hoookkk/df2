#pragma once
#include "../TrenchRates.h"
#include "TrenchDspBridge.h"
#include <juce_audio_basics/juce_audio_basics.h>
#include <juce_dsp/juce_dsp.h>
#include <vector>
namespace trench
{
class FixedRateTrenchIsland
{
public:
    FixedRateTrenchIsland();
    ~FixedRateTrenchIsland();
    void prepare (double hostSampleRate, int maxBlockSizeSamples, TrenchDspBridge& bridge,
                  double islandRateHz = TrenchRates::emuInternalRate);
    void process (juce::AudioBuffer<float>& buffer, TrenchDspBridge& bridge, const TrenchParams& params);
    int getLatencySamples() const noexcept { return latencySamples; }
private:
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
        void compact() noexcept
        {
            const int live = size();
            if (readPos > 0 && live > 0)
                std::copy (storage.data() + readPos, storage.data() + writePos, storage.data());
            readPos = 0;
            writePos = live;
        }
        std::vector<float> storage;
        int readPos = 0;
        int writePos = 0;
    };
    static int sharedSize (const ScratchFifo& a, const ScratchFifo& b) noexcept
    {
        return juce::jmin (a.size(), b.size());
    }
    double hostRate = 44100.0;
    double islandRate = TrenchRates::emuInternalRate;
    int latencySamples = 0;
    int maxHostBlock = 0;
    int maxInternalSamples = 0;
    juce::WindowedSincInterpolator inputResamplerL, inputResamplerR;
    juce::WindowedSincInterpolator outputResamplerL, outputResamplerR;
    std::vector<juce::dsp::IIR::Filter<float>> guardLP[2];
    std::vector<float> guardScratchL, guardScratchR;
    bool guardActive = false;
    juce::AudioBuffer<float> internalBuffer;
    ScratchFifo hostFifoL, hostFifoR;
    ScratchFifo processedFifoL, processedFifoR;
    bool bypassSRC = false;
};
}
