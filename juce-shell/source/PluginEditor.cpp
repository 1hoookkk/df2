#include "PluginEditor.h"
#include "TrenchChassisLayout.h"
#include "parameters/TrenchParameters.h"

namespace
{
    constexpr int kFixedEditorDivisor = 2;

    int fixedEditorWidth()
    {
        return trench::layout::chassisWidth() / kFixedEditorDivisor;
    }

    int fixedEditorHeight()
    {
        return trench::layout::chassisHeight() / kFixedEditorDivisor;
    }
}

PluginEditor::PluginEditor (PluginProcessor& p)
    : AudioProcessorEditor (&p), processorRef (p)
{
    setOpaque (true);

    // ---- Resolve runtime_layout.json (Documents → source tree → BinaryData) ----
    layoutFile = trench::layout::findRuntimeJson();
    trench::layout::reloadActive (layoutFile);
    if (layoutFile.existsAsFile())
        layoutFileMtime = layoutFile.getLastModificationTime();
    refreshVariantWatchFile();

    chassisImage = trench::layout::loadActiveChassisImage();

    setResizable (false, false);
    setSize (fixedEditorWidth(), fixedEditorHeight());

    // The response scope is the main frequency-trace screen for the chassis.
    // Deeper FX/debug panes still live behind TRENCH_PLAYER_DIAGNOSTICS.
    responseDisplay = std::make_unique<trench::TrenchResponseDisplay> (processorRef.dspBridge,
                                                                       processorRef.apvts,
                                                                       processorRef.getInputMeterLeftForUi(),
                                                                       processorRef.getInputMeterRightForUi(),
                                                                       [this] (float* l, float* r, int n)
                                                                       { return processorRef.copyScopeSamples (l, r, n); },
                                                                        processorRef.isCleanGroundTruthAudio());
    addAndMakeVisible (*responseDisplay);

#ifdef TRENCH_PLAYER_DIAGNOSTICS
    fxPane = std::make_unique<trench::TrenchFxPane> (processorRef);
    addChildComponent (*fxPane); // hidden until the switch flips to FX

    viewSwitch = std::make_unique<trench::TrenchViewSwitch> (false);
    viewSwitch->onToggle = [this] (bool showFx)
    {
        if (responseDisplay) responseDisplay->setVisible (! showFx);
        if (fxPane)          fxPane->setVisible (showFx);
    };
    addAndMakeVisible (*viewSwitch);
#endif // TRENCH_PLAYER_DIAGNOSTICS

    // ---- Band sliders inside the long MORPH / Q slot rects --------------
    // The visible labels and the DSP parameters must agree: MORPH drives the
    // morph axis, Q drives the q axis. Any hidden swap makes the instrument
    // feel like it is lying under the hand.
    if (auto* mp = processorRef.apvts.getParameter (ParamID::morph))
    {
        morphBand  = std::make_unique<trench::TrenchThumbwheel> (*mp);
        morphValue = std::make_unique<trench::TrenchValueBox>    (*mp, trench::TrenchValueBox::Mode::Percent);
        addAndMakeVisible (*morphBand);
        addAndMakeVisible (*morphValue);
    }
    if (auto* qp = processorRef.apvts.getParameter (ParamID::q))
    {
        qBand  = std::make_unique<trench::TrenchThumbwheel> (*qp);
        qValue = std::make_unique<trench::TrenchValueBox>    (*qp, trench::TrenchValueBox::Mode::Percent);
        addAndMakeVisible (*qBand);
        addAndMakeVisible (*qValue);
    }

    // PL-4: body strip is the consumer surface — always visible. The previous
    // gate (`if (! isCleanGroundTruthAudio())`) hid it whenever the clean-audio
    // toggle was on, which was correct for a null-parity test rig but wrong
    // for the shipping player. Body switching is what the Morph/Q wheels are
    // morphing *between*; the strip is how the user picks the world.
    if (auto* bp = processorRef.apvts.getParameter (ParamID::body))
    {
        bodyStrip = std::make_unique<trench::TrenchBodyStrip> (*bp);
        addAndMakeVisible (*bodyStrip);
    }

    // Seating overlay LAST so it paints on top of the chassis AND every control:
    // inner-shadow gaskets + display glass that seat them into the chassis.
    chassisGlass = std::make_unique<trench::TrenchChassisGlass>();
    addAndMakeVisible (*chassisGlass);

    // Position all child controls now that they exist (setSize above ran
    // resized() before any of them were constructed).
    resized();

    startTimer (200);
}

PluginEditor::~PluginEditor()
{
    stopTimer();
}

void PluginEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colours::black);
    if (chassisImage.isValid())
        g.drawImage (chassisImage, getLocalBounds().toFloat(),
                     juce::RectanglePlacement::stretchToFit);

    // PL-3: BODY FAILED — bypass overlay. Code-painted, no asset change. Drawn
    // last so it sits over every control. Audio is silent while this is up;
    // see PluginProcessor::processBlock lastLoadOk gate.
    if (! processorRef.getLastLoadOk())
    {
        auto bounds = getLocalBounds();
        const int barH = juce::jmax (18, bounds.getHeight() / 22);
        auto bar = bounds.removeFromTop (barH).reduced (4, 2);
        g.setColour (juce::Colour::fromRGBA (140, 24, 24, 220));
        g.fillRoundedRectangle (bar.toFloat(), 3.0f);
        g.setColour (juce::Colours::white);
        g.setFont ((float) juce::jmax (11, barH - 6));
        g.drawText ("BODY FAILED \xe2\x80\x94 bypass",
                    bar, juce::Justification::centred, true);
    }
}

void PluginEditor::resized()
{
    const auto w = getWidth();
    const auto h = getHeight();

    const auto disp = trench::layout::displayBounds (w, h);
    if (responseDisplay) responseDisplay->setBounds (disp);
    if (fxPane)          fxPane->setBounds (disp);
    if (viewSwitch)
    {
        const int sw = juce::jmax (56, disp.getWidth() * 28 / 100);
        const int sh = juce::jmax (16, disp.getHeight() * 8 / 100);
        viewSwitch->setBounds (disp.getRight() - sw - 5, disp.getY() + 5, sw, sh);
    }
    if (bodyStrip)  bodyStrip ->setBounds (trench::layout::typeBounds    (w, h));
    if (morphBand)  morphBand ->setBounds (trench::layout::morphBounds   (w, h));
    if (qBand)      qBand     ->setBounds (trench::layout::qBounds       (w, h));
    if (morphValue) morphValue->setBounds (trench::layout::valueBounds   (w, h));
    if (qValue)     qValue    ->setBounds (trench::layout::qValueBounds  (w, h));
    if (chassisGlass) chassisGlass->setBounds (getLocalBounds());
}

void PluginEditor::refreshVariantWatchFile()
{
    variantLayoutFile = trench::layout::findVariantFile (trench::layout::activeName(), ".layout.json");
    variantLayoutFileMtime = variantLayoutFile.existsAsFile()
        ? variantLayoutFile.getLastModificationTime()
        : juce::Time();
}

void PluginEditor::timerCallback()
{
    bool changed = false;

    // PL-3: repaint the "BODY FAILED — bypass" overlay only on edge changes,
    // not every 200 ms tick. The audio thread flips lastLoadOk; we mirror it.
    const bool ok = processorRef.getLastLoadOk();
    if (ok != lastKnownLoadOk)
    {
        lastKnownLoadOk = ok;
        repaint();
    }

    if (layoutFile.existsAsFile())
    {
        const auto t = layoutFile.getLastModificationTime();
        if (t != layoutFileMtime)
        {
            layoutFileMtime = t;
            changed = true;
        }
    }

    const auto currentVariantFile = trench::layout::findVariantFile (trench::layout::activeName(), ".layout.json");
    if (currentVariantFile != variantLayoutFile)
    {
        changed = true;
    }
    else if (currentVariantFile.existsAsFile())
    {
        const auto t = currentVariantFile.getLastModificationTime();
        if (t != variantLayoutFileMtime)
            changed = true;
    }

    if (! changed)
        return;

    const auto prevName = trench::layout::activeName();
    if (! trench::layout::reloadActive (layoutFile)) return;
    refreshVariantWatchFile();

    if (trench::layout::activeName() != prevName)
    {
        chassisImage = trench::layout::loadActiveChassisImage();
    }

    setSize (fixedEditorWidth(), fixedEditorHeight());

    resized();
    repaint();
}
