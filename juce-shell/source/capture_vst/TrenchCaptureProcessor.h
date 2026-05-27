#pragma once

#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_audio_processors/juce_audio_processors.h>

#include <atomic>
#include <array>

class TrenchCaptureProcessor final : public juce::AudioProcessor,
                                      private juce::Timer
{
public:
    TrenchCaptureProcessor();
    ~TrenchCaptureProcessor() override;

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

    void startCapture (int slotIndex);
    bool hasReadyCapture() const noexcept;
    juce::String writeReadyCapture();
    juce::String statusText() const;
    float progress01() const noexcept;
    float inputPeak() const noexcept;
    void copyPolePreviewHz (float* out, int count) const noexcept;

    static juce::File captureDirectory();

private:
    static constexpr int kSlotCount = 4;
    static constexpr double kCaptureSeconds = 2.0;
    static constexpr double kMaxCaptureSeconds = 3.0;

    bool writeWavFile (const juce::File& file, int numSamples);
    void writeMetadataFile (const juce::File& file, int slotIndex, int numSamples, float peak);
    void updatePolePreview (int numSamples);
    void timerCallback() override;
    void appendLog (const juce::String& line);

    juce::AudioBuffer<float> captureBuffer;
    double currentSampleRate = 44100.0;
    int maxCaptureSamples = 0;

    std::atomic<bool> captureActive { false };
    std::atomic<bool> captureReady { false };
    std::atomic<int> captureWritePos { 0 };
    std::atomic<int> captureTargetSamples { 0 };
    std::atomic<int> captureSlot { 0 };
    std::atomic<float> progress { 0.0f };
    std::atomic<float> peakMeter { 0.0f };
    std::array<std::atomic<float>, 6> polePreviewHz {};

    juce::String lastStatus { "idle" };

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchCaptureProcessor)
};
