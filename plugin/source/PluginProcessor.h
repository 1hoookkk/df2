#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include "parameters/TrenchParameters.h"
#include "TrenchBodyRoster.h"
#include "dsp/TrenchDspBridge.h"
#include "dsp/FixedRateTrenchIsland.h"
#include "dsp/MorphMod.h"
#include "dsp/KeyDetector.h"
#include "dsp/TrenchCleanBody.h"
#include "dsp/CaptureRing.h"
#include "dsp/PunchBlend.h"
#include "dsp/CapturePlan.h"
#include "dsp/TakeWriter.h"
#include <array>
#include <atomic>
#include <vector>
class PluginProcessor final : public juce::AudioProcessor,
                              private juce::AudioProcessorValueTreeState::Listener,
                              private juce::AsyncUpdater,
                              private juce::Timer
{
public:
    PluginProcessor();
    ~PluginProcessor() override;
    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;
    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override;
    const juce::String getName() const override;
    bool acceptsMidi() const override;
    bool producesMidi() const override;
    bool isMidiEffect() const override;
    double getTailLengthSeconds() const override;
    int getNumPrograms() override;
    int getCurrentProgram() override;
    void setCurrentProgram (int index) override;
    const juce::String getProgramName (int index) override;
    void changeProgramName (int index, const juce::String& newName) override;
    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;
    juce::AudioProcessorValueTreeState apvts;
    TrenchDspBridge dspBridge;
    const std::atomic<float>& getInputMeterLeftForUi() const noexcept  { return inputMeterL; }
    const std::atomic<float>& getInputMeterRightForUi() const noexcept { return inputMeterR; }
    static constexpr int kScopeLen = 512;
    int copyScopeSamples (float* outL, float* outR, int count) const noexcept;
    float getOutClipForUi() const noexcept { return outClipForUi.load (std::memory_order_relaxed); }
    bool isKeyModelReady() const noexcept { return keyDetector.isModelReady(); }
    int getDetectedKeyForUi() const noexcept { return detectedKeyForUi.load (std::memory_order_relaxed); }
    int getDetectedAltKeyForUi() const noexcept { return detectedAltKeyForUi.load (std::memory_order_relaxed); }
    float getKeyConfidenceForUi() const noexcept { return keyConfidenceForUi.load (std::memory_order_relaxed); }
    int  getLoadedBodyIndex() const noexcept { return loadedBodyIndex.load (std::memory_order_relaxed); }
    bool getLastLoadOk()      const noexcept { return lastLoadOk.load (std::memory_order_relaxed); }
    bool isCleanGroundTruthAudio() const noexcept { return trench::clean_audio::kEnabled(); }
    float mapMorphForLoadedBody (float morph) const noexcept;
    float mapSecondaryForLoadedBody (float q) const noexcept;
    float getEffectiveMorphForUi() const noexcept { return effectiveMorphForUi.load (std::memory_order_relaxed); }
    float getEffectiveQForUi() const noexcept     { return effectiveQForUi.load (std::memory_order_relaxed); }
    bool isMorphModulatedForUi() const noexcept   { return morphModulatedForUi.load (std::memory_order_relaxed); }
    // UI thread: the user re-placed the Morph wheel — restart the mod cycle.
    void restartModCycleFromUi() noexcept { modRestartRequest.store (true, std::memory_order_relaxed); }
    bool isQModulatedForUi() const noexcept       { return qModulatedForUi.load (std::memory_order_relaxed); }
    float getEffectiveSpaceForUi() const noexcept { return lastSpaceSent.load (std::memory_order_relaxed); }
    float getModPhaseForUi() const noexcept       { return modPhaseForUi.load (std::memory_order_relaxed); }
    bool seedCurrentBody();
    void exportCurrentBody();
    void forgeAuditionTyped (const std::vector<double>& cards);
    juce::File forgeSaveBody (const juce::String& name, bool overwrite = false);
    enum Axis { AxisFamily = 0, AxisMorph, AxisQ, AxisQSound, AxisSlam };
    static constexpr int kTakeWaveN = 56;
    struct VariantPreview
    {
        std::array<unsigned char, 240> bytes {};
        float morph = 0.0f, q = 0.0f, slam = 0.0f;
        bool  qsound = false;
        int   axis = AxisFamily;
        float wmin[kTakeWaveN] {};
        float wmax[kTakeWaveN] {};
        float bright = 0.0f;
        bool  valid = false;
        bool  asHeard = false;
    };
    std::vector<VariantPreview> buildTakeTray (int n);
    bool installBodyBytes (const void* bytes, size_t len);
    bool copyCurrentBodyBytes (void* out, size_t len);
    bool probeCurrentBodyForUi (float morph, float q, float outCoeffs[30], float& outBoost);
    void setWorkstationBodySolo (bool enabled) noexcept
    {
        workstationBodySolo.store (enabled, std::memory_order_release);
    }
    bool isWorkstationBodySolo() const noexcept
    {
        return workstationBodySolo.load (std::memory_order_acquire);
    }
    static constexpr const char* processorBuildIdentifier() noexcept
    {
        return "trench-plugin-processor-v1";
    }
    juce::File captureTake (trench::CaptureRange range);
    juce::File getLastTakeFile() const { return lastTakeFile; }
    void setCaptureFrozen (bool f) noexcept { captureFrozen.store (f, std::memory_order_relaxed); }
    juce::File captureSmartTake();
    int getTakePreview (float* out, int count);
private:
    void parameterChanged (const juce::String& parameterID, float newValue) override;
    void handleAsyncUpdate() override;
    void timerCallback() override;
    void forceCleanAudioUiState();
    void setParameterDenormalized (const char* parameterID, float value);
    void storeLoadedBodyBehavior (int bodyIndex, const juce::String& cartridgeJson);
    trench::FixedRateTrenchIsland fixedRateIsland;
    trench::MorphMod              morphMod;
    trench::KeyDetector           keyDetector;
    int currentProgram = 0;
    std::atomic<int>  pendingBodyIndex { trench::kNoFilterIndex };
    std::atomic<int>  loadedBodyIndex { trench::kNoFilterIndex };
    std::atomic<int>   bakedReactMode { 0 };
    std::atomic<float> bakedReactCutoff { 0.0f };
    float bakedDetState1[2] { 0.0f, 0.0f };
    float bakedDetState2[2] { 0.0f, 0.0f };
    std::atomic<int>  loadedSecondaryTarget { 0 };
    std::atomic<int>  loadedMorphTaper { 0 };
    std::atomic<bool> lastLoadOk { true };
    juce::Time        auditionSlotMtime;
    juce::String      watchedBodyPath;      // in-place reload of a disk-loaded body
    juce::Time        watchedBodyMtime;
    juce::LinearSmoothedValue<float> outputGain { 1.0f };
    float smoothedMorph = 0.0f;
    float smoothedQ = 0.0f;
    float motionInputEnv = 0.0f;
    bool controlSmoothersPrimed = false;
    std::atomic<float> inputMeterL { 0.0f };
    std::atomic<float> inputMeterR { 0.0f };
    std::atomic<float> outClipForUi { 0.0f };
    std::atomic<float> modPhaseForUi { 0.0f };
    std::atomic<float> effectiveMorphForUi { 0.0f };
    std::atomic<float> effectiveQForUi { 0.0f };
    std::atomic<bool> morphModulatedForUi { false };
    std::atomic<bool> modRestartRequest { false };
    std::atomic<bool> qModulatedForUi { false };
    std::atomic<int> detectedKeyForUi { -1 };
    std::atomic<int> detectedAltKeyForUi { -1 };
    std::atomic<float> keyConfidenceForUi { 0.0f };
    std::array<float, 24> keyProbabilitySum {};
    int keyProbabilityWindows = 0;
    std::array<std::atomic<float>, kScopeLen> scopeL {};
    std::array<std::atomic<float>, kScopeLen> scopeR {};
    std::atomic<int> scopeWritePos { 0 };
public:
    std::atomic<float> rigPan { 0.0f };
private:
    float lastRigPanSent = -999.0f;
    std::atomic<float> lastSpaceSent { 0.0f };
    double spatialOrbitPhase = 0.0;
    std::atomic<bool> demoMode { false };
    juce::uint64  demoSample = 0;
    double        demoSawPhase = 0.0;
    juce::uint32  demoRng = 0x9e3779b9u;
    void generateDemoBlock (juce::AudioBuffer<float>& buffer);
    juce::MemoryBlock currentBodyBytes;
    juce::MemoryBlock rosterBodyBytes;
    uint64_t seedCounter = 0;
    uint64_t variantBankCursor = 0;
    void captureCurrentBodyBytes (const juce::String& cartridgeJson);
    static constexpr double kCaptureMaxSeconds = 24.0;
    trench::CaptureRing captureRing;
    trench::CaptureRing dryRing;
    trench::PunchBlend punchBlend;
    std::atomic<bool> captureFrozen { false };
    bool renderRecipe (const unsigned char* body, float morph, float q, float slam,
                       bool qsound, double seconds, juce::AudioBuffer<float>& out);
    std::atomic<double> hostBpm { 0.0 };
    juce::File lastTakeFile;
    juce::File writeTake (double seconds, bool oneShot, int beats);
    double smartTakeSeconds() const;
    juce::RangedAudioParameter* morphParamForGesture = nullptr;
    juce::RangedAudioParameter* slamParamForGesture = nullptr;
    std::atomic<juce::uint64> processedFrames { 0 };
    std::atomic<juce::uint64> lastMoveFrame { 0 };
    std::atomic<juce::uint64> gestureAnchorFrame { 0 };
    std::atomic<bool> haveGesture { false };
    float prevGestureMorph = 0.0f;
    float prevGestureSlam = 0.0f;
    bool gestureTrackPrimed = false;
    std::atomic<bool> workstationBodySolo { false };
    bool lastWorkstationBodySolo = false;
    bool hdModeApplied = true;      // mirrors the HD param's last APPLIED state
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginProcessor)
};
