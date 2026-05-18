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
        internalBuffer.setSize (2, numInternal + 64, true, true);

    const float* hostL = buffer.getReadPointer (0);
    const float* hostR = (buffer.getNumChannels() > 1) ? buffer.getReadPointer (1) : buffer.getReadPointer (0);
    float* intL = internalBuffer.getWritePointer (0);
    float* intR = internalBuffer.getWritePointer (1);

    inputResamplerL.process (inputRatio, hostL, intL, numInternal);
    inputResamplerR.process (inputRatio, hostR, intR, numInternal);

    // 2. Process through DSP Bridge at 39062.5 Hz
    // We need to pass the internal buffer to the bridge.
    // However, TrenchDspBridge::process takes an AudioBuffer.
    // We can use a temporary AudioBuffer wrapper.
    juce::AudioBuffer<float> intWrapper (internalBuffer.getArrayOfWritePointers(), 2, numInternal);
    bridge.process (intWrapper, params);

    // 3. Resample Internal -> Host
    outputResamplerL.process (outputRatio, intL, buffer.getWritePointer (0), numSamplesHost);
    if (buffer.getNumChannels() > 1)
        outputResamplerR.process (outputRatio, intR, buffer.getWritePointer (1), numSamplesHost);
}

} // namespace trench
