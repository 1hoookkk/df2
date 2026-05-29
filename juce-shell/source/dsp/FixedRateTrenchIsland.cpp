#include "FixedRateTrenchIsland.h"

namespace trench
{

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
    const double inputRatio = hostRate / TrenchRates::emuInternalRate;
    const double outputRatio = TrenchRates::emuInternalRate / hostRate;

    const int numInternal = juce::roundToInt (numSamplesHost * (TrenchRates::emuInternalRate / hostRate));
    
    if (numInternal > internalBuffer.getNumSamples())
        internalBuffer.setSize (2, numInternal + 64, false, true, true);
    internalBuffer.clear (0, 0, juce::jmin (internalBuffer.getNumSamples(), numInternal + 4));
    internalBuffer.clear (1, 0, juce::jmin (internalBuffer.getNumSamples(), numInternal + 4));

    const float* hostL = buffer.getReadPointer (0);
    const float* hostR = (buffer.getNumChannels() > 1) ? buffer.getReadPointer (1) : buffer.getReadPointer (0);
    float* intL = internalBuffer.getWritePointer (0);
    float* intR = internalBuffer.getWritePointer (1);

    // The interpolators keep fractional position across blocks. With the old
    // unbounded overload, normal block sizes occasionally consumed one sample
    // past the supplied buffer (44.1/48 kHz on the input side, 96 kHz on the
    // output side). That reads random host/internal memory and becomes audible
    // static even when the Bypass body is selected. The bounded overload
    // zero-feeds short block edges instead of reading outside the buffer.
    inputResamplerL.process (inputRatio, hostL, intL, numInternal, numSamplesHost, 0);
    inputResamplerR.process (inputRatio, hostR, intR, numInternal, numSamplesHost, 0);

    // 2. Process through DSP Bridge at 39062.5 Hz
    // We need to pass the internal buffer to the bridge.
    // However, TrenchDspBridge::process takes an AudioBuffer.
    // We can use a temporary AudioBuffer wrapper.
    juce::AudioBuffer<float> intWrapper (internalBuffer.getArrayOfWritePointers(), 2, numInternal);
    bridge.process (intWrapper, params);

    // 3. Resample Internal -> Host
    outputResamplerL.process (outputRatio, intL, buffer.getWritePointer (0), numSamplesHost, numInternal, 0);
    if (buffer.getNumChannels() > 1)
        outputResamplerR.process (outputRatio, intR, buffer.getWritePointer (1), numSamplesHost, numInternal, 0);
}

} // namespace trench
