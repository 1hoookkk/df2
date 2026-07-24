#include "FixedRateTrenchIsland.h"
#include <cmath>
namespace trench
{
namespace
{
constexpr int kInterpolatorGuardSamples = 220;
constexpr int kProcessedFifoMargin = 16;
constexpr int kSincHalfKernel = 100;
constexpr double kGuardTransitionHz = 2031.25;
constexpr double kGuardPassRippleDb = -0.1;
constexpr double kGuardStopDb = -80.0;
int estimateStartupBlockSamples (double inputRatio, double outputRatio, int blockSize) noexcept
{
    const int internalNeeded = (int) std::ceil ((double) blockSize * outputRatio)
                             + kProcessedFifoMargin;
    double availableHost = 0.0;
    int processedInternal = 0;
    for (int processCall = 0; processCall < 4096; ++processCall)
    {
        availableHost += (double) blockSize;
        if (availableHost > (double) kInterpolatorGuardSamples)
        {
            const int numInternal = juce::jmax (
                1, (int) std::floor ((availableHost - (double) kInterpolatorGuardSamples) / inputRatio));
            availableHost -= (double) numInternal * inputRatio;
            processedInternal += numInternal;
        }
        if (processedInternal >= internalNeeded)
            return juce::jmax (0, processCall * blockSize);
    }
    return blockSize + kInterpolatorGuardSamples;
}
}
FixedRateTrenchIsland::FixedRateTrenchIsland()
{
}
FixedRateTrenchIsland::~FixedRateTrenchIsland()
{
}
void FixedRateTrenchIsland::prepare (double hostSampleRate, int maxBlockSizeSamples, TrenchDspBridge& bridge,
                                     double islandRateHz)
{
    hostRate = hostSampleRate;
    islandRate = islandRateHz;
    maxHostBlock = juce::jmax (1, maxBlockSizeSamples);
    bypassSRC = (std::abs (hostRate - islandRate) < 0.001);
    if (bypassSRC)
    {
        bridge.prepare (hostRate, maxBlockSizeSamples);
        latencySamples = 0;
        return;
    }
    bridge.prepare (islandRate, maxBlockSizeSamples);
    inputResamplerL.reset();
    inputResamplerR.reset();
    outputResamplerL.reset();
    outputResamplerR.reset();
    const double inputRatio = hostRate / islandRate;
    const double outputRatio = islandRate / hostRate;
    const int hostFifoCap = maxHostBlock + kInterpolatorGuardSamples + 256;
    maxInternalSamples = (int) std::ceil ((double) hostFifoCap * outputRatio) + 128;
    const int processedFifoCap = (int) std::ceil ((double) maxHostBlock * outputRatio)
                               + kProcessedFifoMargin + maxInternalSamples + 128;
    internalBuffer.setSize (2, maxInternalSamples);
    internalBuffer.clear();
    hostFifoL.prepare (hostFifoCap);
    hostFifoR.prepare (hostFifoCap);
    processedFifoL.prepare (processedFifoCap);
    processedFifoR.prepare (processedFifoCap);
    const double guardStopHz = islandRate * 0.5;
    const double guardPassHz = guardStopHz - kGuardTransitionHz;
    guardActive = (hostRate * 0.5) > (guardStopHz + 100.0);
    for (auto& ch : guardLP)
        ch.clear();
    if (guardActive)
    {
        const double centreHz = 0.5 * (guardPassHz + guardStopHz);
        const double widthHz = guardStopHz - guardPassHz;
        auto coeffs = juce::dsp::FilterDesign<float>::designIIRLowpassHighOrderEllipticMethod (
            (float) centreHz, hostRate, (float) (widthHz / hostRate),
            (float) kGuardPassRippleDb, (float) kGuardStopDb);
        for (auto& ch : guardLP)
        {
            ch.resize ((size_t) coeffs.size());
            for (int s = 0; s < coeffs.size(); ++s)
            {
                ch[(size_t) s].coefficients = coeffs[s];
                ch[(size_t) s].reset();
            }
        }
    }
    guardScratchL.assign ((size_t) maxHostBlock, 0.0f);
    guardScratchR.assign ((size_t) maxHostBlock, 0.0f);
    const int startupSamples = estimateStartupBlockSamples (inputRatio, outputRatio, maxHostBlock);
    const double sincDelay = (double) kSincHalfKernel * (1.0 + inputRatio)
                           + 1.0
                           + 3.0 * juce::jmax (0.0, inputRatio - 1.5);
    latencySamples = startupSamples + (int) std::ceil (sincDelay);
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
    if (numSamplesHost > maxHostBlock)
    {
        buffer.clear();
        return;
    }
    const double inputRatio = hostRate / islandRate;
    const double outputRatio = islandRate / hostRate;
    const float* inL = buffer.getReadPointer (0);
    const float* inR = (buffer.getNumChannels() > 1) ? buffer.getReadPointer (1) : inL;
    float* gL = guardScratchL.data();
    float* gR = guardScratchR.data();
    const size_t guardStages = guardLP[0].size();
    for (int i = 0; i < numSamplesHost; ++i)
    {
        float l = inL[i], r = inR[i];
        for (size_t s = 0; s < guardStages; ++s)
        {
            l = guardLP[0][s].processSample (l);
            r = guardLP[1][s].processSample (r);
        }
        gL[i] = l;
        gR[i] = r;
    }
    if (! hostFifoL.push (gL, numSamplesHost) || ! hostFifoR.push (gR, numSamplesHost))
    {
        buffer.clear();
        return;
    }
    const int internalNeededForOutput = (int) std::ceil ((double) numSamplesHost * outputRatio)
                                      + kProcessedFifoMargin;
    while (sharedSize (processedFifoL, processedFifoR) < internalNeededForOutput)
    {
        const int availableHost = sharedSize (hostFifoL, hostFifoR);
        if (availableHost <= kInterpolatorGuardSamples)
            break;
        const int safeHost = availableHost - kInterpolatorGuardSamples;
        int numInternal = juce::jmax (1, (int) std::floor ((double) safeHost / inputRatio));
        numInternal = juce::jmin (numInternal, maxInternalSamples);
        float* intL = internalBuffer.getWritePointer (0);
        float* intR = internalBuffer.getWritePointer (1);
        const int consumedL = inputResamplerL.process (inputRatio, hostFifoL.readPtr(), intL, numInternal, availableHost, 0);
        const int consumedR = inputResamplerR.process (inputRatio, hostFifoR.readPtr(), intR, numInternal, availableHost, 0);
        const int consumed = juce::jmax (0, juce::jmin (consumedL, consumedR));
        if (consumed <= 0)
            break;
        hostFifoL.consume (consumed);
        hostFifoR.consume (consumed);
        juce::AudioBuffer<float> intWrapper (internalBuffer.getArrayOfWritePointers(), 2, numInternal);
        bridge.process (intWrapper, params);
        if (! processedFifoL.push (intL, numInternal) || ! processedFifoR.push (intR, numInternal))
        {
            buffer.clear();
            return;
        }
    }
    const int availableInternal = sharedSize (processedFifoL, processedFifoR);
    if (availableInternal < internalNeededForOutput)
    {
        buffer.clear();
        return;
    }
    const int consumedL = outputResamplerL.process (outputRatio,
                                                    processedFifoL.readPtr(),
                                                    buffer.getWritePointer (0),
                                                    numSamplesHost,
                                                    availableInternal,
                                                    0);
    int consumedR = consumedL;
    if (buffer.getNumChannels() > 1)
    {
        consumedR = outputResamplerR.process (outputRatio,
                                              processedFifoR.readPtr(),
                                              buffer.getWritePointer (1),
                                              numSamplesHost,
                                              availableInternal,
                                              0);
    }
    const int consumed = juce::jmax (0, juce::jmin (consumedL, consumedR));
    processedFifoL.consume (consumed);
    processedFifoR.consume (consumed);
}
}
