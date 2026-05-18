#pragma once

#include "dsp/TrenchDspBridge.h"
#include "TrenchRates.h"
#include "TrenchStyle.h"

#include <juce_gui_basics/juce_gui_basics.h>
#include <juce_audio_processors/juce_audio_processors.h>

#include <array>
#include <atomic>
#include <functional>

namespace trench
{

/// DF-II command display — laid out to match the Rossum Morpheus HD reference:
///   meters (chunky, L=green, R=red, segments green→yellow→red)
///   massive preset name      `013 SPEAKER KNOCKERZ`
///   sub-line numeric         cyan `M 73   Q 100` (positional, no themed labels)
///   M / Q / S bars  (left)   2-D corner-bank pad (right) — pad's 4 edges
///                            magenta/blue/red/yellow, white `+` inside at (M, Q)
///   toggle strip             INPUT  |  BIT  (DF-II-specific surfacing)
///   spectrum                 multi-colour grid + white pixel-stair-step trace
class TrenchResponseDisplay final : public juce::Component
{
public:
    using ScopeReader = std::function<int (float*, float*, int)>;

    TrenchResponseDisplay (TrenchDspBridge& bridge,
                           juce::AudioProcessorValueTreeState& state,
                           const std::atomic<float>& inputL,
                           const std::atomic<float>& inputR,
                           ScopeReader scopeReader);
    ~TrenchResponseDisplay() override = default;

    void paint (juce::Graphics&) override;
    void resized() override;
    void mouseDown (const juce::MouseEvent&) override;

private:
    static constexpr int   kSamples      = 256;
    static constexpr float kDbFloor      = -60.0f;
    static constexpr float kDbCeil       =  30.0f;
    static constexpr float kFreqLo       =  20.0f;
    static constexpr float kFreqHi       = 20000.0f;
    static constexpr double kAnimMinMs   =  80.0;
    static constexpr double kAnimMaxMs   = 320.0;
    static constexpr float  kBigChangeL2 =  6.0f;

    using CoeffSet = std::array<float, 30>;

    void onVBlankTick (double timestampSec);
    void rebuildTraceFromCoeffs (const CoeffSet& coeffs, float boost);
    void rebuildGridImage();

    void drawSlamMeters (juce::Graphics& g) const;
    void drawIdentity (juce::Graphics& g) const;
    void drawSubLine (juce::Graphics& g) const;
    void drawParamBars (juce::Graphics& g) const;
    void drawCornerBankPad (juce::Graphics& g) const;
    void drawToggleStrip (juce::Graphics& g) const;
    void drawTrace (juce::Graphics& g) const;

    juce::Rectangle<int> meterBounds() const;
    juce::Rectangle<int> identityBounds() const;
    juce::Rectangle<int> subLineBounds() const;
    juce::Rectangle<int> barsBounds() const;
    juce::Rectangle<int> cornerBankPadBounds() const;
    juce::Rectangle<int> toggleStripBounds() const;
    juce::Rectangle<int> inputCellBounds() const;
    juce::Rectangle<int> bitCellBounds() const;
    juce::Rectangle<int> spectrumBounds() const;

    float param01 (const char* id) const noexcept;
    int   paramInt (const char* id) const noexcept;
    int   bodyIndex() const noexcept;
    int   pixelStepForBit() const noexcept;
    void  cycleChoice (const char* id);

    static float coeffDistance (const CoeffSet& a, const CoeffSet& b) noexcept;
    static float easeInOutCubic (float t) noexcept;
    static CoeffSet lerpCoeffs (const CoeffSet& a, const CoeffSet& b, float t) noexcept;

    TrenchDspBridge& dspBridge;
    juce::AudioProcessorValueTreeState& parameters;
    const std::atomic<float>& inputMeterL;
    const std::atomic<float>& inputMeterR;
    ScopeReader scopeReader;

    juce::Image gridImage;

    CoeffSet animFromCoeffs {};
    CoeffSet animToCoeffs {};
    float    animFromBoost = 1.0f;
    float    animToBoost   = 1.0f;
    double   animStartSec  = 0.0;
    double   animDurationSec = 0.0;
    bool     haveTarget    = false;

    std::array<int, kSamples> traceY {};
    std::array<int, kSamples> traceX {};
    int   traceSampleCount = 0;
    int   traceFloorY = 0;
    bool  tracePathValid = false;
    double flickerUntilSec = 0.0;

    juce::VBlankAttachment vBlank;
    double lastTickSec = 0.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchResponseDisplay)
};

} // namespace trench
