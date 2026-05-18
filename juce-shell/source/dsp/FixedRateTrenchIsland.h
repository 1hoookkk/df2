#pragma once

#include "../TrenchRates.h"
#include "TrenchDspBridge.h"
#include <juce_audio_basics/juce_audio_basics.h>

namespace trench
{

/**
 * FixedRateTrenchIsland handles the SRC path from Host Rate -> 39062.5 Hz -> Host Rate.
 * In this clean migration version, it manages a TrenchDspBridge.
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
    double hostRate = 44100.0;
    int latencySamples = 0;
    
    // Resamplers: host -> 39062.5
    juce::LagrangeInterpolator inputResamplerL, inputResamplerR;
    // Resamplers: 39062.5 -> host
    juce::LagrangeInterpolator outputResamplerL, outputResamplerR;
    
    // Intermediate buffers at 39062.5 Hz
    juce::AudioBuffer<float> internalBuffer;
    
    bool bypassSRC = false;
};

} // namespace trench
