#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

#include "parameters/TrenchParameters.h"
#include "dsp/TrenchDspBridge.h"
#include "dsp/FixedRateTrenchIsland.h"
#include "TrenchAuthoringSlot.h"

#include <array>
#include <atomic>

class PluginProcessor final : public juce::AudioProcessor
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

private:
    trench::FixedRateTrenchIsland fixedRateIsland;
    trench::TrenchAuthoringSlot authoringSlot;
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
