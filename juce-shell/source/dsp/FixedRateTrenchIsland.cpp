#include "FixedRateTrenchIsland.h"

namespace trench
{
namespace
{
constexpr int kInterpolatorGuardSamples = 8;
constexpr int kProcessedFifoMargin = 16;

void appendToFifo (std::vector<float>& fifo, const float* data, int count)
{
    if (data == nullptr || count <= 0)
        return;

    fifo.insert (fifo.end(), data, data + count);
}

void eraseConsumed (std::vector<float>& fifo, int consumed)
{
    if (consumed <= 0)
        return;

    if (consumed >= (int) fifo.size())
    {
        fifo.clear();
        return;
    }

    fifo.erase (fifo.begin(), fifo.begin() + consumed);
}

int sharedSize (const std::vector<float>& a, const std::vector<float>& b)
{
    return juce::jmin ((int) a.size(), (int) b.size());
}
}

FixedRateTrenchIsland::FixedRateTrenchIsland()
{
}

FixedRateTrenchIsland::~FixedRateTrenchIsland()
{
}

void FixedRateTrenchIsland::prepare (double hostSampleRate, int maxBlockSizeSamples, TrenchDspBridge& bridge)
{
    hostRate = hostSampleRate;
    bypassSRC = (std::abs (hostRate - TrenchRates::emuInternalRate) < 0.001);

    if (bypassSRC)
    {
        bridge.prepare (hostRate, maxBlockSizeSamples);
        latencySamples = 0;
        return;
    }

    // Prepare the internal DSP bridge at the fixed E-mu rate
    bridge.prepare (TrenchRates::emuInternalRate, maxBlockSizeSamples);

    // Reset resamplers
    inputResamplerL.reset();
    inputResamplerR.reset();
    outputResamplerL.reset();
    outputResamplerR.reset();
    hostFifoL.clear();
    hostFifoR.clear();
    processedFifoL.clear();
    processedFifoR.clear();

    const double ratio = TrenchRates::emuInternalRate / hostRate;
    const int internalSamplesNeeded = juce::roundToInt (maxBlockSizeSamples * ratio) + 128;
    internalBuffer.setSize (2, internalSamplesNeeded);
    internalBuffer.clear();

    latencySamples = 0; 
}

void FixedRateTrenchIsland::process (juce::AudioBuffer<float>& buffer, TrenchDspBridge& bridge, const TrenchParams& params)
{
    if (bypassSRC)
    {
        bridge.process (buffer, params);
        return;
    }

    const int numSamplesHost = buffer.getNumSamples();
    if (numSamplesHost <= 0)
        return;

    const double inputRatio = hostRate / TrenchRates::emuInternalRate;
    const double outputRatio = TrenchRates::emuInternalRate / hostRate;

    appendToFifo (hostFifoL, buffer.getReadPointer (0), numSamplesHost);
    appendToFifo (hostFifoR,
                  (buffer.getNumChannels() > 1) ? buffer.getReadPointer (1) : buffer.getReadPointer (0),
                  numSamplesHost);

    const int internalNeededForOutput = (int) std::ceil ((double) numSamplesHost * outputRatio)
                                      + kProcessedFifoMargin;

    while (sharedSize (processedFifoL, processedFifoR) < internalNeededForOutput)
    {
        const int availableHost = sharedSize (hostFifoL, hostFifoR);
        if (availableHost <= kInterpolatorGuardSamples)
            break;

        // JUCE's interpolator returns how many input samples it consumed. Keep
        // a small unread guard in the host FIFO so the bounded overload never
        // has to zero-feed a fractional edge on normal sustained audio.
        const int safeHost = availableHost - kInterpolatorGuardSamples;
        const int numInternal = juce::jmax (1, (int) std::floor ((double) safeHost / inputRatio));

        if (numInternal > internalBuffer.getNumSamples())
            internalBuffer.setSize (2, numInternal + 64, false, true, true);

        float* intL = internalBuffer.getWritePointer (0);
        float* intR = internalBuffer.getWritePointer (1);
        const int consumedL = inputResamplerL.process (inputRatio, hostFifoL.data(), intL, numInternal, availableHost, 0);
        const int consumedR = inputResamplerR.process (inputRatio, hostFifoR.data(), intR, numInternal, availableHost, 0);
        const int consumed = juce::jmax (0, juce::jmin (consumedL, consumedR));

        if (consumed <= 0)
            break;

        eraseConsumed (hostFifoL, consumed);
        eraseConsumed (hostFifoR, consumed);

        juce::AudioBuffer<float> intWrapper (internalBuffer.getArrayOfWritePointers(), 2, numInternal);
        bridge.process (intWrapper, params);

        appendToFifo (processedFifoL, intL, numInternal);
        appendToFifo (processedFifoR, intR, numInternal);
    }

    const int availableInternal = sharedSize (processedFifoL, processedFifoR);
    if (availableInternal < internalNeededForOutput)
    {
        buffer.clear();
        return;
    }

    const int consumedL = outputResamplerL.process (outputRatio,
                                                    processedFifoL.data(),
                                                    buffer.getWritePointer (0),
                                                    numSamplesHost,
                                                    availableInternal,
                                                    0);
    int consumedR = consumedL;
    if (buffer.getNumChannels() > 1)
    {
        consumedR = outputResamplerR.process (outputRatio,
                                              processedFifoR.data(),
                                              buffer.getWritePointer (1),
                                              numSamplesHost,
                                              availableInternal,
                                              0);
    }

    const int consumed = juce::jmax (0, juce::jmin (consumedL, consumedR));
    eraseConsumed (processedFifoL, consumed);
    eraseConsumed (processedFifoR, consumed);
}

} // namespace trench
