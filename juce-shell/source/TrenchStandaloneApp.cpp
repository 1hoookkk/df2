// Custom standalone host app — replaces JUCE's default
// `juce::StandaloneFilterApp` so we can suppress the redundant titlebar
// chrome (Options button, audio-mute warning bar). Activated by
// `JUCE_USE_CUSTOM_PLUGIN_STANDALONE_APP=1` in CMakeLists.txt.

#include <juce_core/system/juce_TargetPlatform.h>

#if JucePlugin_Build_Standalone

#include <juce_audio_devices/juce_audio_devices.h>
#include <juce_audio_utils/juce_audio_utils.h>
#include <juce_gui_extra/juce_gui_extra.h>
#include <juce_audio_plugin_client/Standalone/juce_StandaloneFilterWindow.h>

namespace trench
{

/// Borderless plugin host window — uses the OS titlebar only.
/// Inherits from `juce::DocumentWindow` directly so we get OS frame
/// chrome but none of the "Options" / mute-warning toolbar that
/// `StandaloneFilterWindow` paints by default.
class StandaloneHostWindow : public juce::DocumentWindow
{
public:
    StandaloneHostWindow (const juce::String& title,
                          juce::Colour bg,
                          std::unique_ptr<juce::StandalonePluginHolder> holderIn)
        : DocumentWindow (title, bg,
                          juce::DocumentWindow::minimiseButton
                              | juce::DocumentWindow::closeButton),
          holder (std::move (holderIn))
    {
        setUsingNativeTitleBar (true);
        setResizable (false, false);

        // The plugin editor IS the entire client area. No toolbar, no
        // mute-warning strip, no JUCE-drawn titlebar overlay.
        if (auto* processor = holder->processor.get())
        {
            // Defeat the feedback-loop heuristic — TRENCH is a fully
            // wet processor, the warning bar is just visual noise.
            holder->getMuteInputValue().setValue (false);

            editor.reset (processor->createEditorIfNeeded());
            if (editor != nullptr)
            {
                setContentNonOwned (editor.get(), true);
            }
        }

        centreWithSize (getWidth(), getHeight());
        setVisible (true);
    }

    ~StandaloneHostWindow() override
    {
        if (editor != nullptr && holder != nullptr && holder->processor != nullptr)
            holder->processor->editorBeingDeleted (editor.get());
        editor.reset();
    }

    void closeButtonPressed() override
    {
        juce::JUCEApplicationBase::quit();
    }

    juce::StandalonePluginHolder* getPluginHolder() noexcept { return holder.get(); }

private:
    std::unique_ptr<juce::StandalonePluginHolder> holder;
    std::unique_ptr<juce::AudioProcessorEditor>   editor;
};

class StandaloneApp final : public juce::JUCEApplication
{
public:
    StandaloneApp()
    {
        juce::PropertiesFile::Options options;
        options.applicationName     = juce::CharPointer_UTF8 (JucePlugin_Name);
        options.filenameSuffix      = ".settings";
        options.osxLibrarySubFolder = "Application Support";
       #if JUCE_LINUX || JUCE_BSD
        options.folderName          = "~/.config";
       #else
        options.folderName          = "";
       #endif
        appProperties.setStorageParameters (options);
    }

    const juce::String getApplicationName() override    { return juce::CharPointer_UTF8 (JucePlugin_Name); }
    const juce::String getApplicationVersion() override { return JucePlugin_VersionString; }
    bool moreThanOneInstanceAllowed() override          { return true; }
    void anotherInstanceStarted (const juce::String&) override {}

    void initialise (const juce::String&) override
    {
        if (juce::Desktop::getInstance().getDisplays().displays.isEmpty())
        {
            jassertfalse;
            return;
        }

        auto holder = std::make_unique<juce::StandalonePluginHolder> (
            appProperties.getUserSettings(),
            false,
            juce::String{},
            nullptr,
            juce::Array<juce::StandalonePluginHolder::PluginInOuts>{},
            false /* autoOpenMidiDevices */);

        const auto bg = juce::LookAndFeel::getDefaultLookAndFeel()
                          .findColour (juce::ResizableWindow::backgroundColourId);

        mainWindow = std::make_unique<StandaloneHostWindow> (
            getApplicationName(), bg, std::move (holder));
    }

    void shutdown() override
    {
        mainWindow.reset();
        appProperties.saveIfNeeded();
    }

    void systemRequestedQuit() override
    {
        if (mainWindow != nullptr && mainWindow->getPluginHolder() != nullptr)
            mainWindow->getPluginHolder()->savePluginState();

        if (juce::ModalComponentManager::getInstance()->cancelAllModalComponents())
        {
            juce::Timer::callAfterDelay (100, []()
            {
                if (auto* app = juce::JUCEApplicationBase::getInstance())
                    app->systemRequestedQuit();
            });
        }
        else
        {
            quit();
        }
    }

private:
    juce::ApplicationProperties appProperties;
    std::unique_ptr<StandaloneHostWindow> mainWindow;
};

} // namespace trench

juce::JUCEApplicationBase* juce_CreateApplication()
{
    return new trench::StandaloneApp();
}

#endif // JucePlugin_Build_Standalone
