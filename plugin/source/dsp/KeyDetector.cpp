#include "KeyDetector.h"
#include <algorithm>
#include <cmath>
#include <string>
namespace trench
{
KeyDetector::KeyDetector()
    : resampled ((size_t) kFftSize, 0.0f),
      fftData ((size_t) kFftSize * 2u, 0.0f)
{
}
bool KeyDetector::loadModel (const void* jsonData, size_t jsonSize)
{
    model.reset();
    if (jsonData == nullptr || jsonSize == 0)
        return false;
    try
    {
        const std::string jsonText (static_cast<const char*> (jsonData), jsonSize);
        const auto json = nlohmann::json::parse (jsonText);
        auto parsed = RTNeural::json_parser::parseJson<float> (json, false);
        if (parsed == nullptr || parsed->getInSize() != 12 || parsed->getOutSize() != 24)
            return false;
        model = std::move (parsed);
        return true;
    }
    catch (...)
    {
        model.reset();
        return false;
    }
}
void KeyDetector::prepare (double hostSampleRate)
{
    preparedSampleRate = std::max (1.0, hostSampleRate);
    captureSamples = std::max (1, (int) std::llround (
        preparedSampleRate * (double) kFftSize / (double) kTargetSampleRate));
    for (auto& slot : slots)
    {
        slot.samples.assign ((size_t) captureSamples, 0.0f);
        slot.state.store (free, std::memory_order_relaxed);
    }
    activeSlot = -1;
    writePosition = 0;
    claimFreeSlot();
}
void KeyDetector::reset() noexcept
{
    for (auto& slot : slots)
        slot.state.store (free, std::memory_order_relaxed);
    activeSlot = -1;
    writePosition = 0;
    claimFreeSlot();
}
bool KeyDetector::claimFreeSlot() noexcept
{
    for (int index = 0; index < (int) slots.size(); ++index)
    {
        int expected = free;
        if (slots[(size_t) index].state.compare_exchange_strong (
                expected, writing, std::memory_order_acq_rel))
        {
            activeSlot = index;
            writePosition = 0;
            return true;
        }
    }
    activeSlot = -1;
    return false;
}
void KeyDetector::pushAudio (const juce::AudioBuffer<float>& buffer) noexcept
{
    const int channels = buffer.getNumChannels();
    const int samples = buffer.getNumSamples();
    if (channels <= 0 || samples <= 0 || captureSamples <= 0)
        return;
    int sourceOffset = 0;
    while (sourceOffset < samples)
    {
        if (activeSlot < 0 && ! claimFreeSlot())
            return;
        auto& slot = slots[(size_t) activeSlot];
        const int count = std::min (samples - sourceOffset, captureSamples - writePosition);
        for (int sample = 0; sample < count; ++sample)
        {
            float mono = 0.0f;
            for (int channel = 0; channel < channels; ++channel)
                mono += buffer.getReadPointer (channel)[sourceOffset + sample];
            slot.samples[(size_t) (writePosition + sample)] = mono / (float) channels;
        }
        sourceOffset += count;
        writePosition += count;
        if (writePosition == captureSamples)
        {
            slot.state.store (ready, std::memory_order_release);
            activeSlot = -1;
            writePosition = 0;
        }
    }
}
bool KeyDetector::computeChroma (const float* source, int sourceSamples,
                                 std::array<float, 12>& chroma) noexcept
{
    chroma.fill (0.0f);
    if (source == nullptr || sourceSamples <= 0)
        return false;
    if (sourceSamples == kFftSize)
    {
        std::copy_n (source, kFftSize, resampled.begin());
    }
    else
    {
        const double scale = (double) (sourceSamples - 1) / (double) (kFftSize - 1);
        for (int index = 0; index < kFftSize; ++index)
        {
            const double position = (double) index * scale;
            const int left = std::min ((int) position, sourceSamples - 1);
            const int right = std::min (left + 1, sourceSamples - 1);
            const float fraction = (float) (position - (double) left);
            resampled[(size_t) index] = source[left] + fraction * (source[right] - source[left]);
        }
    }
    double mean = 0.0;
    for (float sample : resampled)
        mean += sample;
    mean /= (double) kFftSize;
    for (int index = 0; index < kFftSize; ++index)
    {
        const double phase = juce::MathConstants<double>::twoPi * (double) index
                           / (double) (kFftSize - 1);
        const float window = (float) (0.5 - 0.5 * std::cos (phase));
        fftData[(size_t) index] = (resampled[(size_t) index] - (float) mean) * window;
    }
    std::fill (fftData.begin() + kFftSize, fftData.end(), 0.0f);
    fft.performRealOnlyForwardTransform (fftData.data(), true);
    for (int bin = 1; bin <= kFftSize / 2; ++bin)
    {
        const double frequency = (double) bin * (double) kTargetSampleRate / (double) kFftSize;
        if (frequency < 40.0 || frequency > 5000.0)
            continue;
        const double midi = 69.0 + 12.0 * std::log2 (frequency / 440.0);
        int pitchClass = ((int) std::floor (midi + 0.5)) % 12;
        if (pitchClass < 0)
            pitchClass += 12;
        const float real = fftData[(size_t) bin * 2u];
        const float imaginary = fftData[(size_t) bin * 2u + 1u];
        chroma[(size_t) pitchClass] += std::hypot (real, imaginary);
    }
    double normSquared = 0.0;
    for (float value : chroma)
        normSquared += (double) value * (double) value;
    const double norm = std::sqrt (normSquared);
    if (! std::isfinite (norm) || norm <= 1.0e-12)
        return false;
    for (auto& value : chroma)
        value = (float) ((double) value / norm);
    return true;
}
bool KeyDetector::analyse (Result& result)
{
    result = {};
    if (model == nullptr)
        return false;
    for (auto& slot : slots)
    {
        int expected = ready;
        if (! slot.state.compare_exchange_strong (expected, reading, std::memory_order_acq_rel))
            continue;
        std::array<float, 12> chroma {};
        const bool valid = computeChroma (slot.samples.data(), (int) slot.samples.size(), chroma);
        const bool inferred = valid && inferChroma (chroma, result);
        slot.state.store (free, std::memory_order_release);
        return inferred;
    }
    return false;
}
bool KeyDetector::inferChroma (const std::array<float, 12>& chroma, Result& result,
                               std::array<float, 24>* copiedProbabilities) noexcept
{
    result = {};
    if (model == nullptr)
        return false;
    model->forward (chroma.data());
    const float* probabilities = model->getOutputs();
    std::copy_n (probabilities, result.probabilities.size(), result.probabilities.begin());
    if (copiedProbabilities != nullptr)
        std::copy_n (probabilities, copiedProbabilities->size(), copiedProbabilities->begin());
    int best = 0;
    int second = 1;
    if (probabilities[second] > probabilities[best])
        std::swap (best, second);
    for (int index = 2; index < 24; ++index)
    {
        if (probabilities[index] > probabilities[best])
        {
            second = best;
            best = index;
        }
        else if (probabilities[index] > probabilities[second])
        {
            second = index;
        }
    }
    result.labelIndex = best;
    result.confidence = probabilities[best];
    result.margin = probabilities[best] - probabilities[second];
    return std::isfinite (result.confidence) && std::isfinite (result.margin);
}
}
