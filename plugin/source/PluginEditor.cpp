#include "PluginEditor.h"
#include "TrenchRates.h"
#include "BinaryData.h"
#include "TrenchBodyRoster.h"
using namespace trench::ui;
PluginEditor::PluginEditor (PluginProcessor& p)
    : AudioProcessorEditor (&p),
      processor (p)
{
    processor.setKeyDetectionEnabled (true);
    reloadLayoutFromDisk();
    auto panel = juce::ImageCache::getFromMemory (BinaryData::df2_panel_beige_png,
                                                  BinaryData::df2_panel_beige_pngSize);
    auto strip = juce::ImageCache::getFromMemory (BinaryData::trench_roller_strip_png,
                                                  BinaryData::trench_roller_strip_pngSize);
    faceplate    = std::make_unique<FaceplateView> (panel, theme);
    faceplate->setBufferedToImage (true);
    graph        = std::make_unique<GraphDisplay> (theme, processor.apvts, ParamID::slamDrive);
    moveChip = std::make_unique<MoveChip> (processor.apvts, theme);
    keySnapBox = std::make_unique<KeySnapBox> (processor.apvts, theme);
    keySnapBox->setSuggestionProviders (
        [this] { return processor.getDetectedKeyForUi(); },
        [this] { return processor.getDetectedAltKeyForUi(); });
    keySnapBox->setListeningProvider ([this]
    {
        return juce::jmax (processor.getInputMeterLeftForUi().load (std::memory_order_relaxed),
                           processor.getInputMeterRightForUi().load (std::memory_order_relaxed))
               > 0.0015f;
    });
    typeSelector = std::make_unique<TypeSelectorView> (processor.apvts, theme);
    const auto runSeed = [this]
    {
        if (processor.seedCurrentBody())
        {
            graph->playSeedPulse();
            moveChip->flashSiblingLabel();
        }
    };
    typeSelector->onSeed       = runSeed;
    typeSelector->onExportBody = [this] { processor.exportCurrentBody(); };
    typeSelector->onAnnounce   = [this] (const juce::String& s) { graph->announce (s); };
    morphWheel   = std::make_unique<WheelControl> (processor.apvts, ParamID::morph, strip, theme);
    // Re-placing the wheel restarts the modulation cycle from the new anchor.
    morphWheel->onGestureEnd = [this] { processor.restartModCycleFromUi(); };
    secondaryWheel = std::make_unique<WheelControl> (processor.apvts, ParamID::q, strip, theme);
    morphReadout = std::make_unique<ValueReadout> ("morphReadout", theme);
    secondaryReadout = std::make_unique<ValueReadout> ("qReadout", theme);
    morphReadout->bindParameter (processor.apvts.getParameter (ParamID::morph));
    secondaryReadout->bindParameter (processor.apvts.getParameter (ParamID::q));
    amountWheel = std::make_unique<ThinWheel> (processor.apvts, ParamID::amount);
    amountWheel->onValueGesture = [this] (float v) { graph->showAmountCue (v); };
    moveChip->onAnnounce = [this] (const juce::String& s) { graph->announce (s); };
    onboarding = std::make_unique<Onboarding> (theme);
    // The tour teaches over a REAL curve: it loads a demo body while it is up
    // (NO FILTER is the default and shows nothing), then lands on NO FILTER.
    const auto setBodyIndex = [this] (int idx)
    {
        if (auto* b = processor.apvts.getParameter (ParamID::body))
            b->setValueNotifyingHost (b->convertTo0to1 ((float) idx));
    };
    const auto loadTourDemoBody = [setBodyIndex]
    {
        int n = 0;
        trench::bodyRoster (n);
        for (int i = 0; i < n; ++i)
            if (trench::bodyDisplayName (i) == "Morph LP X")
                return setBodyIndex (i);
        setBodyIndex (juce::jmin (1, n - 1));
    };
    onboarding->onDismiss = [this, setBodyIndex]
    {
        onboarding->setVisible (false);
        setBodyIndex (trench::kNoFilterIndex);
    };
    // MORPH demo step: the tour sweeps the wheel to the far pose and back so the
    // travel is SEEN. The editor owns the gesture and restores the pose after.
    onboarding->onDemoMorph = [this] (float phase)
    {
        auto* p = processor.apvts.getParameter (ParamID::morph);
        if (p == nullptr)
            return;
        if (onboardingDemoStart < 0.0f)
        {
            onboardingDemoStart = p->getValue();
            p->beginChangeGesture();
        }
        const float far = onboardingDemoStart < 0.5f ? 1.0f : 0.0f;
        const float v = onboardingDemoStart
                      + (far - onboardingDemoStart)
                            * std::sin (juce::MathConstants<float>::pi * phase);
        p->setValueNotifyingHost (juce::jlimit (0.0f, 1.0f, v));
    };
    onboarding->onDemoEnd = [this]
    {
        if (auto* p = processor.apvts.getParameter (ParamID::morph);
            p != nullptr && onboardingDemoStart >= 0.0f)
        {
            p->setValueNotifyingHost (onboardingDemoStart);
            p->endChangeGesture();
        }
        onboardingDemoStart = -1.0f;
    };
    onboardingReplayHotspot.onClick = [this, loadTourDemoBody]
    {
        loadTourDemoBody();
        onboarding->replay();
    };
    labels       = std::make_unique<LabelsLayer> (theme);
    labels->setRailLabels ("MORPH (%)", "Q (%)");
    decalsLayer  = std::make_unique<DecalsLayer> (theme);
    decalsLayer->setBufferedToImage (true);
    addAndMakeVisible (*faceplate);
    addAndMakeVisible (*graph);
    addAndMakeVisible (*moveChip);
    addAndMakeVisible (*typeSelector);
    addAndMakeVisible (*keySnapBox);   // after typeSelector: it sits on the bar
    addAndMakeVisible (*morphWheel);
    addAndMakeVisible (*secondaryWheel);
    addAndMakeVisible (*morphReadout);
    addAndMakeVisible (*secondaryReadout);
    addAndMakeVisible (*amountWheel);
    addChildComponent (*onboarding);
    // First-run teach: shown for the first few openings, or until clicked away.
    if (trench::ui::Onboarding::shouldShow())
    {
        loadTourDemoBody();
        onboarding->setVisible (true);
        onboarding->toFront (false);
    }
    addAndMakeVisible (*labels);
    addAndMakeVisible (*decalsLayer);
    // Click the TRENCH badge to replay the tour. No new faceplate furniture.
    addAndMakeVisible (onboardingReplayHotspot);
#if TRENCH_TABLE_STITCH_PANEL
    tableStitchButton = std::make_unique<juce::TextButton> ("TABLES");
    tableStitchButton->setTooltip ("Open the external raw-table stitcher");
    tableStitchButton->setColour (juce::TextButton::buttonColourId, juce::Colour (0xff1d2b25));
    tableStitchButton->setColour (juce::TextButton::textColourOffId, juce::Colour (0xffefc36b));
    tableStitchButton->onClick = [this] { openTableStitcher(); };
    addAndMakeVisible (*tableStitchButton);
#endif
    setResizable (false, false);
    setSize (kEditorWidth, kEditorHeight);
    setWantsKeyboardFocus (false);
    vblank = std::make_unique<juce::VBlankAttachment> (this, [this] { onFrame(); });
   #ifdef TRENCH_PLAYER_DIAGNOSTICS
    startTimer (350);
    rigPanel = std::make_unique<trench::ui::RigPanel> (processor, theme);
    addAndMakeVisible (*rigPanel);
    authorView = std::make_unique<trench::ui::AuthorView> (processor, theme);
    rigPanel->onToggleLab = [this]
    {
        if (labWindow == nullptr)
            labWindow = std::make_unique<trench::ui::LabWindow> (authorView.get());
        labWindow->setVisible (! labWindow->isVisible());
        if (labWindow->isVisible()) labWindow->toFront (true);
    };
    resized();
   #endif
}
void PluginEditor::showOnboardingStep (int step)
{
    onboarding->replay (step);
}
PluginEditor::~PluginEditor()
{
    processor.setKeyDetectionEnabled (false);
#if TRENCH_TABLE_STITCH_PANEL
    if (tableStitchProcess != nullptr && tableStitchProcess->isRunning())
        tableStitchProcess->kill();
#endif
}
#if TRENCH_TABLE_STITCH_PANEL
void PluginEditor::openTableStitcher()
{
    const auto root = juce::File (TRENCH_TABLE_STITCH_ROOT);
    const auto script = root.getChildFile ("tools").getChildFile ("table_stitch_gui.py");
    if (! script.existsAsFile())
    {
        graph->announce ("TABLES: tools/table_stitch_gui.py not found");
        return;
    }
    if (tableStitchProcess == nullptr || ! tableStitchProcess->isRunning())
    {
        tableStitchProcess = std::make_unique<juce::ChildProcess>();
        juce::StringArray command;
        const auto configuredPython = juce::SystemStats::getEnvironmentVariable ("TRENCH_PYTHON", {});
        command.add (configuredPython.isNotEmpty() ? configuredPython : juce::String ("python"));
        command.add (script.getFullPathName());
        command.add ("--port");
        command.add ("8758");
        if (! tableStitchProcess->start (command, juce::ChildProcess::wantStdErr))
        {
            graph->announce ("TABLES: could not start table stitcher");
            tableStitchProcess.reset();
            return;
        }
    }
    juce::Component::SafePointer<PluginEditor> safeThis (this);
    juce::Timer::callAfterDelay (450, [safeThis]
    {
        if (safeThis != nullptr)
            juce::URL ("http://127.0.0.1:8758/").launchInDefaultBrowser();
    });
    graph->announce ("TABLES: external raw-table panel opened");
}
#endif
void PluginEditor::reloadLayoutFromDisk()
{
   #ifdef TRENCH_PLAYER_DIAGNOSTICS
    auto f = trench::uiLayoutFile();
    if (f.existsAsFile())
    {
        currentLayout = trench::UiLayout::fromJson (f.loadFileAsString());
    }
    else
    {
        f.getParentDirectory().createDirectory();
        f.replaceWithText (currentLayout.toJson());
    }
    layoutMtime = f.getLastModificationTime();
   #endif
}
void PluginEditor::timerCallback()
{
   #ifdef TRENCH_PLAYER_DIAGNOSTICS
    auto f = trench::uiLayoutFile();
    if (! f.existsAsFile())
        return;
    const auto t = f.getLastModificationTime();
    if (t == layoutMtime)
        return;
    layoutMtime = t;
    currentLayout = trench::UiLayout::fromJson (f.loadFileAsString());
    layoutComponents();
    repaint();
   #endif
}
void PluginEditor::resized()
{
    layoutComponents();
#if TRENCH_TABLE_STITCH_PANEL
    if (tableStitchButton != nullptr)
    {
        tableStitchButton->setBounds (getWidth() - 77, 7, 62, 22);
        tableStitchButton->toFront (false);
    }
#endif
}
void PluginEditor::layoutComponents()
{
    trench::ui::uiFontFamily() = currentLayout.string ("fontFamily", trench::ui::kUiFontName);
    trench::ui::uiEmphasisFontFamily() = currentLayout.string ("fontFamilyEmphasis",
                                                                trench::ui::kUiEmphasisFontName);
    trench::ui::uiBoldEnabled() = currentLayout.param ("fontBold", 0.0) > 0.5;
    const juce::Rectangle<int> base { 0, 0, kEditorWidth, kEditorHeight };
    faceplate->setBounds (base);
    labels->setBounds (base);
    labels->toFront (false);
    decalsLayer->toFront (false);
    const auto rectOf = [this] (const char* id) { return theme.rect (id).getSmallestIntegerContainer(); };
    graph->setBounds (rectOf ("spectrumGrid"));
    {
        const auto scr = rectOf ("spectrumGrid");
        moveChip->setBounds (scr.getX() + 14, scr.getBottom() - 28, scr.getWidth() - 28, 18);
    }
    {
        // KEY perches ABOVE the BODY bar, right-aligned — its own quiet spot.
        const auto sel = rectOf ("typeSelector");
        keySnapBox->setBounds (sel.getRight() - 128, sel.getY() - 24, 128, 22);
    }
    typeSelector->setBounds (rectOf ("typeSelector"));
    morphWheel->setBounds (rectOf ("morphWheel"));
    secondaryWheel->setBounds (rectOf ("qWheel"));
    morphReadout->setBounds (rectOf ("morphReadout"));
    secondaryReadout->setBounds (rectOf ("qReadout"));
    amountWheel->setBounds (rectOf ("amountWheel"));
    onboarding->setBounds (base);   // full face: the tour spotlights each control
    onboardingReplayHotspot.setBounds (rectOf ("brandLabel"));
    decalsLayer->setBounds (base);
   #ifdef TRENCH_PLAYER_DIAGNOSTICS
    if (rigPanel != nullptr)
        rigPanel->setBounds (40, 652, 440, 78);
   #endif
    const auto fade = [this] (juce::Component* c, const char* id) { if (c) c->setAlpha (theme.opacity (id)); };
    fade (graph.get(),        "spectrumGrid");
    fade (typeSelector.get(), "typeSelector");
    fade (morphWheel.get(),   "morphWheel");
    fade (secondaryWheel.get(), "qWheel");
    fade (morphReadout.get(), "morphReadout");
    fade (secondaryReadout.get(), "qReadout");
}
void PluginEditor::onFrame()
{
    keySnapBox->refreshSuggestion();
    const auto read = [this] (const char* paramID)
    {
        if (auto* v = processor.apvts.getRawParameterValue (paramID))
            return juce::jlimit (0.0f, 1.0f, v->load());
        return 0.0f;
    };
    // The response curve draws from the EFFECTIVE (modulated) morph/Q, so an
    // armed modulation visibly plays the curve along with the wheel.
    float coeffs[30] = {};
    float boost = 1.0f;
    const bool morphMoving = processor.isMorphModulatedForUi();
    const bool qMovingNow  = processor.isQModulatedForUi();
    const float baseMorph = processor.mapMorphForLoadedBody (
        morphMoving ? processor.getEffectiveMorphForUi() : read (ParamID::morph));
    const float baseQ     = processor.mapSecondaryForLoadedBody (
        qMovingNow ? processor.getEffectiveQForUi() : read (ParamID::q));
    if (processor.probeCurrentBodyForUi (baseMorph, baseQ, coeffs, boost))
    {
        // the probed coefficients live in the packed 39062.5 domain; plotting
        // them at the host rate shifted every feature up to ~23% high in Hz
        graph->updateFromCoeffs (coeffs, boost, TrenchRates::emuInternalRate);
    }
    graph->setSlamMeter (processor.getOutClipForUi());
    const bool moving = processor.isMorphModulatedForUi();
    const float morphValue = moving ? processor.getEffectiveMorphForUi() : read (ParamID::morph);
    morphWheel->setDisplayOverride (moving, morphValue);
    morphReadout->setNormalised (morphValue);
    const bool qMoving = processor.isQModulatedForUi();
    const float qValue = qMoving ? processor.getEffectiveQForUi() : read (ParamID::q);
    secondaryWheel->setDisplayOverride (qMoving, qValue);
    secondaryReadout->setNormalised (qValue);
    const bool morphActive = morphWheel->isMouseOverOrDragging (true) || morphReadout->isMouseOverOrDragging (true);
    const bool secondaryActive = secondaryWheel->isMouseOverOrDragging (true) || secondaryReadout->isMouseOverOrDragging (true);
    morphReadout->setActive (morphActive);
    secondaryReadout->setActive (secondaryActive);
}
