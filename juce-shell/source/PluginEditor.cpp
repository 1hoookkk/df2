#include "PluginEditor.h"
#include "TrenchChassisLayout.h"

namespace
{
    constexpr float kFixedEditorDivisor = 3.4f; // a touch bigger than the old 4.0

    int fixedEditorWidth()
    {
        return juce::roundToInt ((float) trench::layout::chassisWidth() / kFixedEditorDivisor);
    }

    int fixedEditorHeight()
    {
        return juce::roundToInt ((float) trench::layout::chassisHeight() / kFixedEditorDivisor);
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

    // ---- The two invisible sliders + their readouts ------------------------
    // Morph and Q remain draggable over the plain faceplate. The only painted
    // UI components are their numeric values.
    makeWellSliderInvisible (morphWell);
    makeWellSliderInvisible (qWell);
    addAndMakeVisible (morphWell);
    addAndMakeVisible (qWell);

    morphAttachment = std::make_unique<SliderAttachment> (processorRef.apvts, ParamID::morph, morphWell);
    qAttachment     = std::make_unique<SliderAttachment> (processorRef.apvts, ParamID::q,     qWell);

    if (auto* mp = processorRef.apvts.getParameter (ParamID::morph))
        morphReadout = std::make_unique<trench::TrenchValueBox> (*mp, trench::TrenchValueBox::Mode::IntPercent);
    if (auto* qp = processorRef.apvts.getParameter (ParamID::q))
        qReadout = std::make_unique<trench::TrenchValueBox> (*qp, trench::TrenchValueBox::Mode::IntPercent);
    if (morphReadout) addAndMakeVisible (*morphReadout);
    if (qReadout)     addAndMakeVisible (*qReadout);

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

void PluginEditor::makeWellSliderInvisible (juce::Slider& s)
{
    s.setSliderStyle (juce::Slider::LinearHorizontal);
    s.setTextBoxStyle (juce::Slider::NoTextBox, true, 0, 0);
    s.setRange (0.0, 1.0, 0.0); // mirrors morph/q normalised range; attachment owns the value
    s.setMouseDragSensitivity (1); // 1:1 horizontal travel across the well
    // Fully transparent: the chassis PNG cutout is the only visible surface.
    for (auto id : { juce::Slider::backgroundColourId,
                     juce::Slider::trackColourId,
                     juce::Slider::thumbColourId,
                     juce::Slider::rotarySliderFillColourId,
                     juce::Slider::rotarySliderOutlineColourId,
                     juce::Slider::textBoxTextColourId,
                     juce::Slider::textBoxBackgroundColourId,
                     juce::Slider::textBoxOutlineColourId })
        s.setColour (id, juce::Colours::transparentBlack);
}

void PluginEditor::resized()
{
    const auto w = getWidth();
    const auto h = getHeight();

    morphWell.setBounds (trench::layout::morphBounds (w, h));
    qWell.setBounds     (trench::layout::qBounds     (w, h));
    if (morphReadout) morphReadout->setBounds (trench::layout::valueBounds  (w, h));
    if (qReadout)     qReadout->setBounds     (trench::layout::qValueBounds (w, h));
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
