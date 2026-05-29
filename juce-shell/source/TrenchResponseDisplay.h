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

/// The screen. One job: draw the body's frequency-response shape as a single
/// living curve that eases to a new form when Morph or Q move, and is still
/// otherwise. No grid, no markers, no meters, no labels — the shape is the hero.
///
/// (The constructor still accepts the input meters + scope reader so the editor
/// that builds it does not have to change; they are simply unused now.)
class TrenchResponseDisplay final : public juce::Component
{
public:
    using ScopeReader = std::function<int (float*, float*, int)>;

    TrenchResponseDisplay (TrenchDspBridge& bridge,
                           juce::AudioProcessorValueTreeState& state,
                           const std::atomic<float>& inputL,
                           const std::atomic<float>& inputR,
                           ScopeReader scopeReader,
                           bool cleanModeIn = false);
    ~TrenchResponseDisplay() override = default;

    void paint (juce::Graphics&) override;
    void resized() override;

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
    void drawTrace (juce::Graphics& g) const;

    juce::Rectangle<int> screenBounds() const;

    static float coeffDistance (const CoeffSet& a, const CoeffSet& b) noexcept;
    static float easeInOutCubic (float t) noexcept;
    static CoeffSet lerpCoeffs (const CoeffSet& a, const CoeffSet& b, float t) noexcept;

    TrenchDspBridge& dspBridge;
    juce::AudioProcessorValueTreeState& parameters;
    const std::atomic<float>& inputMeterL;   // unused (kept for ctor compatibility)
    const std::atomic<float>& inputMeterR;   // unused
    ScopeReader scopeReader;                  // unused
    bool cleanMode = false;                   // unused

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

    juce::VBlankAttachment vBlank;
    double lastTickSec = 0.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchResponseDisplay)
};

} // namespace trench
