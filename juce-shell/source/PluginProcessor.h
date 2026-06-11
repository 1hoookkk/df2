#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

#include "parameters/TrenchParameters.h"
#include "dsp/TrenchDspBridge.h"
#include "dsp/FixedRateTrenchIsland.h"
#include "dsp/TeleportEngine.h"
#include "dsp/TrenchCleanBody.h"

#include <array>
#include <atomic>

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

    // UI vectorscope feed: copies the most recent `count` post-filter stereo
    // samples (oldest -> newest) into the caller's buffers. Lock-free, may tear
    // a frame under contention — fine for a scope. Returns samples written.
    static constexpr int kScopeLen = 512;
    int copyScopeSamples (float* outL, float* outR, int count) const noexcept;

    // Status readout for the FX pane: which body is loaded and whether the last
    // load (body switch or authoring-slot hot-reload) parsed cleanly.
    int  getLoadedBodyIndex() const noexcept { return loadedBodyIndex.load (std::memory_order_relaxed); }
    bool getLastLoadOk()      const noexcept { return lastLoadOk.load (std::memory_order_relaxed); }
    bool isCleanGroundTruthAudio() const noexcept { return trench::clean_audio::kEnabled(); }
    float mapMorphForLoadedBody (float morph) const noexcept;
    float mapSecondaryForLoadedBody (float q) const noexcept;

private:
    // juce::AudioProcessorValueTreeState::Listener — body switching. May be
    // called on the audio thread (automation), so we only stash the request and
    // defer the JSON parse/load to handleAsyncUpdate() on the message thread.
    void parameterChanged (const juce::String& parameterID, float newValue) override;
    void handleAsyncUpdate() override;
    // Hot-reloads the Forge audition slot, but only while the audition body is
    // the selected body — so it never overrides a normal body selection.
    void timerCallback() override;
    void forceCleanAudioUiState();
    void setParameterDenormalized (const char* parameterID, float value);
    bool loadedSecondaryDrivesSlam() const noexcept;
    void storeLoadedBodyBehavior (int bodyIndex, const juce::String& cartridgeJson);

    trench::FixedRateTrenchIsland fixedRateIsland;
    trench::TeleportEngine        teleportEngine;

    std::atomic<int>  pendingBodyIndex { 0 };
    std::atomic<int>  loadedBodyIndex { 0 };
    std::atomic<int>  loadedSecondaryTarget { 0 };
    std::atomic<int>  loadedMorphTaper { 0 };
    std::atomic<bool> lastLoadOk { true };
    juce::Time        auditionSlotMtime;

    // Final user makeup gain (dB param -> linear), ramped to avoid zipper noise.
    juce::LinearSmoothedValue<float> outputGain { 1.0f };
    float smoothedMorph = 0.0f;
    float smoothedQ = 0.0f;
    bool controlSmoothersPrimed = false;
    std::atomic<float> inputMeterL { 0.0f };
    std::atomic<float> inputMeterR { 0.0f };

    std::array<std::atomic<float>, kScopeLen> scopeL {};
    std::array<std::atomic<float>, kScopeLen> scopeR {};
    std::atomic<int> scopeWritePos { 0 };

    // Sentinel (-1) so the first audio block forces a setInputMode call;
    // afterwards we only fire the FFI when the parameter actually changes,
    // so we don't thrash the engine's input-character stage every block.
    int lastInputModeSent = -1;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginProcessor)
};
