#include "FixedRateTrenchIsland.h"

#include <cmath>

namespace trench
{
namespace
{
// The windowed-sinc kernel spans 200 input samples; keep a full kernel of
// unread history in the host FIFO so block edges never zero-feed the tail.
constexpr int kInterpolatorGuardSamples = 220;
constexpr int kProcessedFifoMargin = 16;
constexpr int kSincHalfKernel = 100;          // group delay of the 200-tap sinc

// Anti-fold guard geometry. Everything above the island's Nyquist folds, so the
// stopband must START there — the passband edge is the only thing we get to
// choose, and 17.5 kHz buys enough transition for an elliptic to reach -80 dB.
// Pass edge sits 2031.25 Hz below the fold (17.5 kHz at the 39062.5 island);
// at the HD island the fold (and with it the whole guard) moves up an octave.
constexpr double kGuardTransitionHz = 2031.25;
constexpr double kGuardPassRippleDb = -0.1;
constexpr double kGuardStopDb = -80.0;

// The first output block is not always the first maxHostBlock after prepare:
// the input FIFO must cross the interpolator guard and the processed FIFO must
// contain one complete host block's worth of internal samples. Mirror that
// bounded scheduling law here so the host receives the actual startup latency.
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

    // Host rates and block sizes are bounded by the prepared FIFO contract; this
    // is only a defensive fallback for an invalid caller configuration.
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

    // Prepare the internal DSP bridge at the island rate (39062.5 default; the
    // HD option runs the same unit at exactly 2x)
    bridge.prepare (islandRate, maxBlockSizeSamples);

    // Reset resamplers
    inputResamplerL.reset();
    inputResamplerR.reset();
    outputResamplerL.reset();
    outputResamplerR.reset();

    // Worst-case scratch sizing for this host rate. `outputRatio` is the number
    // of internal (E-mu rate) samples produced per host sample; it governs both
    // how big a single resampler push can get and the steady-state FIFO depth.
    const double inputRatio = hostRate / islandRate;
    const double outputRatio = islandRate / hostRate;

    // The host FIFO holds at most one incoming block plus the small unread guard
    // the interpolator keeps for fractional continuity between blocks.
    const int hostFifoCap = maxHostBlock + kInterpolatorGuardSamples + 256;

    // A single input-resampler push converts up to `hostFifoCap` host samples
    // into internal samples; this is the hard cap for `internalBuffer` and for
    // any one chunk appended to the processed FIFO.
    maxInternalSamples = (int) std::ceil ((double) hostFifoCap * outputRatio) + 128;

    // The processed FIFO peaks at "needed for this block's output" plus one
    // over-produced internal chunk before the loop's guard stops it.
    const int processedFifoCap = (int) std::ceil ((double) maxHostBlock * outputRatio)
                               + kProcessedFifoMargin + maxInternalSamples + 128;

    internalBuffer.setSize (2, maxInternalSamples);
    internalBuffer.clear();

    hostFifoL.prepare (hostFifoCap);
    hostFifoR.prepare (hostFifoCap);
    processedFifoL.prepare (processedFifoCap);
    processedFifoR.prepare (processedFifoCap);

    // Anti-fold guard. Only meaningful when the host can actually carry content
    // above the island's Nyquist — below that rate there is nothing to fold.
    const double guardStopHz = islandRate * 0.5;              // the fold
    const double guardPassHz = guardStopHz - kGuardTransitionHz;
    guardActive = (hostRate * 0.5) > (guardStopHz + 100.0);
    for (auto& ch : guardLP)
        ch.clear();

    if (guardActive)
    {
        // JUCE designs around the transition CENTRE: fp = f - w/2, fs = f + w/2.
        // Aim fs exactly at the fold so nothing above it survives the downsample.
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
                ch[(size_t) s].coefficients = coeffs[s]; // immutable + shared across channels
                ch[(size_t) s].reset();
            }
        }
    }

    guardScratchL.assign ((size_t) maxHostBlock, 0.0f);
    guardScratchR.assign ((size_t) maxHostBlock, 0.0f);

    // Honest pipeline latency (host samples): account for the number of bounded
    // production rounds needed to cross the input guard and fill one output
    // block, then add the two sinc legs. The small phase margin covers the
    // fractional edge of JUCE's 200-tap interpolator at higher downsample ratios.
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

    // Defensive: the buffers are sized for maxHostBlock. If a host hands us a
    // larger block than it declared in prepare(), drop to silence rather than
    // grow a buffer on the audio thread.
    if (numSamplesHost > maxHostBlock)
    {
        buffer.clear();
        return;
    }

    const double inputRatio = hostRate / islandRate;
    const double outputRatio = islandRate / hostRate;

    const float* inL = buffer.getReadPointer (0);
    const float* inR = (buffer.getNumChannels() > 1) ? buffer.getReadPointer (1) : inL;

    // Anti-fold guard ahead of the downsample (state persists across blocks).
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

        // JUCE's interpolator reports how many input samples it consumed. Keep a
        // small unread guard in the host FIFO so the bounded overload never has
        // to zero-feed a fractional edge on normal sustained audio.
        const int safeHost = availableHost - kInterpolatorGuardSamples;
        int numInternal = juce::jmax (1, (int) std::floor ((double) safeHost / inputRatio));

        // Never exceed the preallocated internal buffer (no setSize in process).
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
            // Sizing guarantees this fits; bail to silence rather than overflow.
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

} // namespace trench
