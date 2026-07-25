#include "WorkstationEditor.h"

#include <juce_audio_utils/juce_audio_utils.h>

namespace
{
// loops an audio file into the processor's input: the audition path
class LoopFeeder final : public juce::AudioIODeviceCallback,
                         public WorkstationLoop
{
public:
    juce::AudioProcessorPlayer inner;

    bool loadFile (const juce::File& f) override
    {
        juce::AudioFormatManager fm;
        fm.registerBasicFormats();
        std::unique_ptr<juce::AudioFormatReader> reader (fm.createReaderFor (f));
        if (reader == nullptr || reader->lengthInSamples <= 0)
            return false;
        const int len = (int) juce::jmin<juce::int64> (reader->lengthInSamples,
                                                       (juce::int64) (reader->sampleRate * 120.0));
        juce::AudioBuffer<float> buf ((int) reader->numChannels, len);
        reader->read (&buf, 0, len, 0, true, true);
        const juce::ScopedLock sl (lock);
        loop = std::move (buf);
        fileRate = reader->sampleRate;
        position = 0.0;
        name = f.getFileName();
        path = f.getFullPathName();
        return true;
    }

    void setPlaying (bool shouldPlay) override { playing = shouldPlay; }
    bool isPlaying() const override            { return playing; }
    juce::String loopName() const override     { const juce::ScopedLock sl (lock); return name; }
    juce::String loopPath() const              { const juce::ScopedLock sl (lock); return path; }

    void audioDeviceAboutToStart (juce::AudioIODevice* device) override
    {
        deviceRate = device->getCurrentSampleRate();
        feed.setSize (2, device->getCurrentBufferSizeSamples() * 2);
        inner.audioDeviceAboutToStart (device);
    }

    void audioDeviceStopped() override { inner.audioDeviceStopped(); }

    void audioDeviceIOCallbackWithContext (const float* const* input, int numInputs,
                                           float* const* output, int numOutputs, int numSamples,
                                           const juce::AudioIODeviceCallbackContext& context) override
    {
        juce::ignoreUnused (input, numInputs);
        if (feed.getNumSamples() < numSamples)
            feed.setSize (2, numSamples, false, false, true);
        feed.clear();
        {
            const juce::ScopedTryLock sl (lock);   // never block the audio thread on a load
            if (sl.isLocked() && playing && loop.getNumSamples() > 1 && deviceRate > 0.0)
            {
                const double ratio = fileRate / deviceRate;
                const int total = loop.getNumSamples();
                double p = position;
                for (int i = 0; i < numSamples; ++i)
                {
                    const int i0 = (int) p;
                    const float frac = (float) (p - i0);
                    const int i1 = (i0 + 1) % total;
                    for (int ch = 0; ch < 2; ++ch)
                    {
                        const auto* src = loop.getReadPointer (juce::jmin (ch, loop.getNumChannels() - 1));
                        feed.setSample (ch, i, src[i0] + (src[i1] - src[i0]) * frac);
                    }
                    p += ratio;
                    if (p >= total)
                        p -= total;
                }
                position = p;
            }
        }
        const float* ins[2] = { feed.getReadPointer (0), feed.getReadPointer (1) };
        inner.audioDeviceIOCallbackWithContext (ins, 2, output, numOutputs, numSamples, context);
    }

private:
    mutable juce::CriticalSection lock;
    juce::AudioBuffer<float> loop, feed;
    juce::String name, path;
    double fileRate = 0.0, deviceRate = 0.0;
    double position = 0.0;
    std::atomic<bool> playing { false };
};

class WorkstationWindow final : public juce::DocumentWindow
{
public:
    WorkstationWindow (juce::String name, PluginProcessor& processor)
        : juce::DocumentWindow (std::move (name), juce::Colours::black,
                                juce::DocumentWindow::allButtons)
    {
        setUsingNativeTitleBar (true);
        setResizable (true, false);
        setContentOwned (new WorkstationEditor (processor), true);
        centreWithSize (1440, 900);
        setVisible (true);
    }

    void closeButtonPressed() override
    {
        juce::JUCEApplication::getInstance()->systemRequestedQuit();
    }
};
} // namespace

class WorkstationApplication final : public juce::JUCEApplication
{
public:
    const juce::String getApplicationName() override { return "TRENCH Workstation"; }
    const juce::String getApplicationVersion() override { return "1.0.0"; }
    bool moreThanOneInstanceAllowed() override { return false; }

    void initialise (const juce::String&) override
    {
        processor = std::make_unique<PluginProcessor>();
        processor->setWorkstationBodySolo (false);   // author on the SHIPPING chain (gain budget, mix, AGC, sat)
        window = std::make_unique<WorkstationWindow> (getApplicationName(), *processor);

        if (juce::SystemStats::getEnvironmentVariable ("TRENCH_WORKSTATION_SKIP_AUDIO", {}) != "1")
        {
            const auto result = deviceManager.initialiseWithDefaultDevices (0, 2);
            if (result.isNotEmpty())
                juce::Logger::writeToLog ("TRENCH Workstation audio: " + result);

            feeder.inner.setProcessor (processor.get());
            deviceManager.addAudioCallback (&feeder);
            gWorkstationLoop = &feeder;

            // remember the last audition loop between sessions
            const auto memo = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                                  .getChildFile ("TRENCH").getChildFile ("player_loop.txt");
            if (const juce::File last (memo.loadFileAsString().trim()); last.existsAsFile())
                feeder.loadFile (last);
        }
    }

    void shutdown() override
    {
        if (gWorkstationLoop == &feeder && feeder.loopName().isNotEmpty())
            juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                .getChildFile ("TRENCH").getChildFile ("player_loop.txt")
                .replaceWithText (feeder.loopPath());
        gWorkstationLoop = nullptr;
        window.reset();
        deviceManager.removeAudioCallback (&feeder);
        feeder.inner.setProcessor (nullptr);
        processor.reset();
    }

    void systemRequestedQuit() override { quit(); }
    void anotherInstanceStarted (const juce::String&) override {}

private:
    juce::AudioDeviceManager deviceManager;
    LoopFeeder feeder;
    std::unique_ptr<PluginProcessor> processor;
    std::unique_ptr<WorkstationWindow> window;
};

START_JUCE_APPLICATION (WorkstationApplication)
