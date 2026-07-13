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
constexpr double kGuardCutoffHz = 19300.0;    // anti-fold LP, just under emu Nyquist
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
    maxHostBlock = juce::jmax (1, maxBlockSizeSamples);
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

    // Worst-case scratch sizing for this host rate. `outputRatio` is the number
    // of internal (E-mu rate) samples produced per host sample; it governs both
    // how big a single resampler push can get and the steady-state FIFO depth.
    const double outputRatio = TrenchRates::emuInternalRate / hostRate;

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

    // Anti-fold guard: 8th-order Butterworth as 4 cascaded biquads with the
    // standard maximally-flat Q ladder, only meaningful when the host rate is
    // above the internal rate (content above 19531 Hz would fold).
    static const double kButterQ8[kGuardStages] = { 0.50979558, 0.60134489, 0.89997622, 2.5629154 };
    for (int ch = 0; ch < 2; ++ch)
        for (int s = 0; s < kGuardStages; ++s)
        {
            guardLP[ch][s].coefficients = juce::dsp::IIR::Coefficients<float>::makeLowPass (
                hostRate, (float) juce::jmin (kGuardCutoffHz, hostRate * 0.45), (float) kButterQ8[s]);
            guardLP[ch][s].reset();
        }
    guardScratchL.assign ((size_t) maxHostBlock, 0.0f);
    guardScratchR.assign ((size_t) maxHostBlock, 0.0f);

    // Honest pipeline latency (host samples): output for a block becomes
    // available one production round late (≈ one max block), plus the sinc
    // group delay on both legs (input leg at host rate, output leg at the
    // internal rate mapped back to host samples). The FIFO guard is kernel
    // HISTORY, not delay — it sits behind the read cursor. Validated against
    // the measured best-fit delay in IslandNullTests (736 @ 48k/512).
    const double outLegHost = (double) kSincHalfKernel * hostRate / TrenchRates::emuInternalRate;
    latencySamples = maxHostBlock
                   + kSincHalfKernel
                   + (int) std::ceil (outLegHost);
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

    const double inputRatio = hostRate / TrenchRates::emuInternalRate;
    const double outputRatio = TrenchRates::emuInternalRate / hostRate;

    const float* inL = buffer.getReadPointer (0);
    const float* inR = (buffer.getNumChannels() > 1) ? buffer.getReadPointer (1) : inL;

    // Anti-fold guard ahead of the downsample (state persists across blocks).
    float* gL = guardScratchL.data();
    float* gR = guardScratchR.data();
    for (int i = 0; i < numSamplesHost; ++i)
    {
        float l = inL[i], r = inR[i];
        for (int s = 0; s < kGuardStages; ++s)
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
