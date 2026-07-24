#pragma once
#include <RTNeural/RTNeural.h>
#include <juce_audio_basics/juce_audio_basics.h>
#include <juce_dsp/juce_dsp.h>
#include <array>
#include <atomic>
#include <memory>
#include <vector>
namespace trench
{
class KeyDetector final
{
public:
    static constexpr int kTargetSampleRate = 22050;
    static constexpr int kFftOrder = 17;
    static constexpr int kFftSize = 1 << kFftOrder;
    struct Result
    {
        int labelIndex = -1;
        float confidence = 0.0f;
        float margin = 0.0f;
        std::array<float, 24> probabilities {};
    };
    KeyDetector();
    bool loadModel (const void* jsonData, size_t jsonSize);
    bool isModelReady() const noexcept { return model != nullptr; }
    void prepare (double hostSampleRate);
    void reset() noexcept;
    void pushAudio (const juce::AudioBuffer<float>& buffer) noexcept;
    bool analyse (Result& result);
    bool inferChroma (const std::array<float, 12>& chroma, Result& result,
                      std::array<float, 24>* probabilities = nullptr) noexcept;
    bool computeChroma (const float* source, int sourceSamples,
                        std::array<float, 12>& chroma) noexcept;
private:
    enum SlotState : int { free = 0, writing = 1, ready = 2, reading = 3 };
    struct CaptureSlot
    {
        std::vector<float> samples;
        std::atomic<int> state { free };
    };
    bool claimFreeSlot() noexcept;
    std::array<CaptureSlot, 2> slots;
    int activeSlot = -1;
    int writePosition = 0;
    int captureSamples = kFftSize;
    double preparedSampleRate = kTargetSampleRate;
    juce::dsp::FFT fft { kFftOrder };
    std::vector<float> resampled;
    std::vector<float> fftData;
    std::unique_ptr<RTNeural::Model<float>> model;
};
}
