#include "WorkstationEditor.h"

#include <juce_audio_utils/juce_audio_utils.h>

namespace
{
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
        centreWithSize (1240, 760);
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
        processor->setWorkstationBodySolo (true);

        const auto result = deviceManager.initialiseWithDefaultDevices (2, 2);
        if (result.isNotEmpty())
            juce::Logger::writeToLog ("TRENCH Workstation audio: " + result);

        player.setProcessor (processor.get());
        deviceManager.addAudioCallback (&player);
        window = std::make_unique<WorkstationWindow> (getApplicationName(), *processor);
    }

    void shutdown() override
    {
        window.reset();
        deviceManager.removeAudioCallback (&player);
        player.setProcessor (nullptr);
        processor.reset();
    }

    void systemRequestedQuit() override { quit(); }
    void anotherInstanceStarted (const juce::String&) override {}

private:
    juce::AudioDeviceManager deviceManager;
    juce::AudioProcessorPlayer player;
    std::unique_ptr<PluginProcessor> processor;
    std::unique_ptr<WorkstationWindow> window;
};

START_JUCE_APPLICATION (WorkstationApplication)
