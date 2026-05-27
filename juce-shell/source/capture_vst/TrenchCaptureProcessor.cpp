#include "TrenchCaptureProcessor.h"
#include "TrenchCaptureEditor.h"

#include <cmath>

namespace
{
    constexpr const char* kSlotNames[] = { "A", "B", "C", "D" };
    constexpr float kBands[6][2] = {
        { 50.0f, 200.0f },
        { 200.0f, 600.0f },
        { 600.0f, 1200.0f },
        { 1200.0f, 2500.0f },
        { 2500.0f, 5500.0f },
        { 5500.0f, 12000.0f },
    };

    juce::String slotName (int slot)
    {
        return kSlotNames[juce::jlimit (0, 3, slot)];
    }
}

TrenchCaptureProcessor::TrenchCaptureProcessor()
    : AudioProcessor (BusesProperties()
                        .withInput  ("Input",  juce::AudioChannelSet::stereo(), true)
                        .withOutput ("Output", juce::AudioChannelSet::stereo(), true))
{
    for (auto& hz : polePreviewHz)
        hz.store (0.0f, std::memory_order_relaxed);

    captureDirectory().createDirectory();
    appendLog ("plugin constructed");
    startTimerHz (10);
}

TrenchCaptureProcessor::~TrenchCaptureProcessor()
{
    stopTimer();
    appendLog ("plugin destroyed");
}

const juce::String TrenchCaptureProcessor::getName() const { return JucePlugin_Name; }
bool TrenchCaptureProcessor::acceptsMidi() const { return false; }
bool TrenchCaptureProcessor::producesMidi() const { return false; }
bool TrenchCaptureProcessor::isMidiEffect() const { return false; }
double TrenchCaptureProcessor::getTailLengthSeconds() const { return 0.0; }
int TrenchCaptureProcessor::getNumPrograms() { return 1; }
int TrenchCaptureProcessor::getCurrentProgram() { return 0; }
void TrenchCaptureProcessor::setCurrentProgram (int index) { juce::ignoreUnused (index); }
const juce::String TrenchCaptureProcessor::getProgramName (int index)
{
    juce::ignoreUnused (index);
    return "Capture";
}
void TrenchCaptureProcessor::changeProgramName (int index, const juce::String& newName)
{
    juce::ignoreUnused (index, newName);
}

void TrenchCaptureProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    juce::ignoreUnused (samplesPerBlock);
    currentSampleRate = sampleRate > 0.0 ? sampleRate : 44100.0;
    maxCaptureSamples = juce::roundToInt (currentSampleRate * kMaxCaptureSeconds);
    captureBuffer.setSize (2, maxCaptureSamples, false, true, true);
    captureBuffer.clear();
    captureActive.store (false, std::memory_order_release);
    captureReady.store (false, std::memory_order_release);
    captureWritePos.store (0, std::memory_order_relaxed);
    progress.store (0.0f, std::memory_order_relaxed);
    appendLog ("prepare sr=" + juce::String (currentSampleRate) + " max=" + juce::String (maxCaptureSamples));
}

void TrenchCaptureProcessor::releaseResources()
{
    captureActive.store (false, std::memory_order_release);
}

bool TrenchCaptureProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    const auto out = layouts.getMainOutputChannelSet();
    if (out != juce::AudioChannelSet::mono() && out != juce::AudioChannelSet::stereo())
        return false;

    return layouts.getMainInputChannelSet() == out;
}

void TrenchCaptureProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midiMessages)
{
    juce::ignoreUnused (midiMessages);
    juce::ScopedNoDenormals noDenormals;

    for (auto ch = getTotalNumInputChannels(); ch < getTotalNumOutputChannels(); ++ch)
        buffer.clear (ch, 0, buffer.getNumSamples());

    float peak = 0.0f;
    for (int ch = 0; ch < juce::jmin (2, buffer.getNumChannels()); ++ch)
    {
        const auto* data = buffer.getReadPointer (ch);
        for (int i = 0; i < buffer.getNumSamples(); ++i)
            peak = juce::jmax (peak, std::abs (data[i]));
    }
    const float oldPeak = peakMeter.load (std::memory_order_relaxed);
    peakMeter.store (juce::jmax (peak, oldPeak * 0.92f), std::memory_order_relaxed);

    if (! captureActive.load (std::memory_order_acquire))
        return;

    int wp = captureWritePos.load (std::memory_order_relaxed);
    const int target = captureTargetSamples.load (std::memory_order_relaxed);
    if (wp >= target || wp >= maxCaptureSamples)
    {
        captureActive.store (false, std::memory_order_release);
        captureReady.store (true, std::memory_order_release);
        return;
    }

    const int toCopy = juce::jmin (buffer.getNumSamples(), target - wp, maxCaptureSamples - wp);
    if (toCopy <= 0)
        return;

    const auto* left = buffer.getReadPointer (0);
    const auto* right = buffer.getNumChannels() > 1 ? buffer.getReadPointer (1) : left;
    captureBuffer.copyFrom (0, wp, left, toCopy);
    captureBuffer.copyFrom (1, wp, right, toCopy);

    wp += toCopy;
    captureWritePos.store (wp, std::memory_order_relaxed);
    progress.store (target > 0 ? (float) wp / (float) target : 0.0f, std::memory_order_relaxed);

    if (wp >= target)
    {
        captureActive.store (false, std::memory_order_release);
        captureReady.store (true, std::memory_order_release);
    }
}

bool TrenchCaptureProcessor::hasEditor() const { return true; }

juce::AudioProcessorEditor* TrenchCaptureProcessor::createEditor()
{
    return new TrenchCaptureEditor (*this);
}

void TrenchCaptureProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    destData.setSize (0);
}

void TrenchCaptureProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    juce::ignoreUnused (data, sizeInBytes);
}

void TrenchCaptureProcessor::startCapture (int slotIndex)
{
    const int slot = juce::jlimit (0, kSlotCount - 1, slotIndex);
    captureSlot.store (slot, std::memory_order_relaxed);
    captureReady.store (false, std::memory_order_release);
    captureWritePos.store (0, std::memory_order_relaxed);
    progress.store (0.0f, std::memory_order_relaxed);
    captureTargetSamples.store (juce::jmin (maxCaptureSamples,
                                            juce::roundToInt (currentSampleRate * kCaptureSeconds)),
                                std::memory_order_relaxed);
    captureBuffer.clear();
    captureActive.store (true, std::memory_order_release);
    lastStatus = "capturing " + slotName (slot);
    appendLog ("start slot=" + slotName (slot)
               + " targetSamples=" + juce::String (captureTargetSamples.load (std::memory_order_relaxed)));
}

bool TrenchCaptureProcessor::hasReadyCapture() const noexcept
{
    return captureReady.load (std::memory_order_acquire);
}

juce::String TrenchCaptureProcessor::writeReadyCapture()
{
    if (! captureReady.exchange (false, std::memory_order_acq_rel))
        return lastStatus;

    const int slot = captureSlot.load (std::memory_order_relaxed);
    const int samples = juce::jlimit (0, maxCaptureSamples, captureWritePos.load (std::memory_order_relaxed));
    if (samples <= 0)
    {
        lastStatus = "empty capture";
        return lastStatus;
    }

    updatePolePreview (samples);

    const auto dir = captureDirectory();
    dir.createDirectory();

    const auto slotText = slotName (slot);
    const auto stamp = juce::String (juce::Time::currentTimeMillis());
    const auto latest = dir.getChildFile ("latest_" + slotText + ".wav");
    const auto stamped = dir.getChildFile (stamp + "_" + slotText + ".wav");

    const bool wroteLatest = writeWavFile (latest, samples);
    const bool wroteStamped = writeWavFile (stamped, samples);
    const auto peak = peakMeter.load (std::memory_order_relaxed);
    writeMetadataFile (latest.withFileExtension (".json"), slot, samples, peak);
    writeMetadataFile (stamped.withFileExtension (".json"), slot, samples, peak);

    lastStatus = (wroteLatest && wroteStamped)
        ? ("wrote latest_" + slotText + ".wav")
        : "write failed";
    appendLog (lastStatus);
    return lastStatus;
}

juce::String TrenchCaptureProcessor::statusText() const
{
    if (captureActive.load (std::memory_order_acquire))
        return "capturing " + slotName (captureSlot.load (std::memory_order_relaxed));
    if (captureReady.load (std::memory_order_acquire))
        return "writing";
    return lastStatus;
}

float TrenchCaptureProcessor::progress01() const noexcept
{
    return juce::jlimit (0.0f, 1.0f, progress.load (std::memory_order_relaxed));
}

float TrenchCaptureProcessor::inputPeak() const noexcept
{
    return peakMeter.load (std::memory_order_relaxed);
}

void TrenchCaptureProcessor::copyPolePreviewHz (float* out, int count) const noexcept
{
    if (out == nullptr || count <= 0)
        return;

    const int n = juce::jmin (count, (int) polePreviewHz.size());
    for (int i = 0; i < n; ++i)
        out[i] = polePreviewHz[(size_t) i].load (std::memory_order_relaxed);
}

juce::File TrenchCaptureProcessor::captureDirectory()
{
    return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
        .getChildFile ("TRENCH")
        .getChildFile ("captures");
}

bool TrenchCaptureProcessor::writeWavFile (const juce::File& file, int numSamples)
{
    file.deleteFile();

    juce::WavAudioFormat wav;
    std::unique_ptr<juce::OutputStream> stream (file.createOutputStream().release());
    if (stream == nullptr)
        return false;

    auto options = juce::AudioFormatWriterOptions()
        .withSampleRate (currentSampleRate)
        .withNumChannels (2)
        .withBitsPerSample (24);

    auto writer = wav.createWriterFor (stream, options);
    if (writer == nullptr)
        return false;

    return writer->writeFromAudioSampleBuffer (captureBuffer, 0, numSamples);
}

void TrenchCaptureProcessor::writeMetadataFile (const juce::File& file,
                                                int slotIndex,
                                                int numSamples,
                                                float peak)
{
    juce::String text;
    text << "{\n"
         << "  \"slot\": \"" << slotName (slotIndex) << "\",\n"
         << "  \"sampleRate\": " << currentSampleRate << ",\n"
         << "  \"samples\": " << numSamples << ",\n"
         << "  \"durationSeconds\": " << (currentSampleRate > 0.0 ? numSamples / currentSampleRate : 0.0) << ",\n"
         << "  \"peak\": " << peak << ",\n"
         << "  \"createdMs\": " << juce::Time::currentTimeMillis() << "\n"
         << "}\n";
    file.replaceWithText (text);
}

void TrenchCaptureProcessor::updatePolePreview (int numSamples)
{
    const int n = juce::jlimit (128, juce::jmin (8192, numSamples), numSamples);
    const int start = juce::jmax (0, (numSamples - n) / 2);
    constexpr int stepsPerBand = 18;

    for (int band = 0; band < 6; ++band)
    {
        const double lo = kBands[band][0];
        const double hi = juce::jmin ((double) kBands[band][1], currentSampleRate * 0.45);
        double bestHz = lo;
        double bestMag = -1.0;

        for (int s = 0; s < stepsPerBand; ++s)
        {
            const double t = (double) s / (double) (stepsPerBand - 1);
            const double hz = lo * std::pow (hi / lo, t);
            const double w = juce::MathConstants<double>::twoPi * hz / currentSampleRate;
            double re = 0.0;
            double im = 0.0;

            for (int i = 0; i < n; ++i)
            {
                const double hann = 0.5 - 0.5 * std::cos (juce::MathConstants<double>::twoPi * i / (double) (n - 1));
                const float x = 0.5f * (captureBuffer.getSample (0, start + i)
                                      + captureBuffer.getSample (1, start + i));
                const double a = w * i;
                re += hann * x * std::cos (a);
                im -= hann * x * std::sin (a);
            }

            const double mag = re * re + im * im;
            if (mag > bestMag)
            {
                bestMag = mag;
                bestHz = hz;
            }
        }

        polePreviewHz[(size_t) band].store ((float) bestHz, std::memory_order_relaxed);
    }
}

void TrenchCaptureProcessor::timerCallback()
{
    if (hasReadyCapture())
        writeReadyCapture();
}

void TrenchCaptureProcessor::appendLog (const juce::String& line)
{
    const auto dir = captureDirectory();
    dir.createDirectory();
    const auto file = dir.getChildFile ("capture.log");
    file.appendText (juce::Time::getCurrentTime().toString (true, true, true, true)
                     + "  " + line + "\n");
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new TrenchCaptureProcessor();
}
