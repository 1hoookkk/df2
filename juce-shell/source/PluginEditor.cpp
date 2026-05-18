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

    // ---- Center display: live frequency-response scope ------------------
    responseDisplay = std::make_unique<trench::TrenchResponseDisplay> (processorRef.dspBridge,
                                                                       processorRef.apvts,
                                                                       processorRef.getInputMeterLeftForUi(),
                                                                       processorRef.getInputMeterRightForUi(),
                                                                       [this] (float* l, float* r, int n)
                                                                       { return processorRef.copyScopeSamples (l, r, n); });
    addAndMakeVisible (*responseDisplay);

    // ---- Band sliders inside the long MORPH / Q slot rects --------------
    // DSP contract: top chassis slot is labeled MORPH but drives ParamID::q;
    // bottom chassis slot is labeled Q but drives ParamID::morph.
    if (auto* qp = processorRef.apvts.getParameter (ParamID::q))
    {
        morphBand  = std::make_unique<trench::TrenchShuttleControl> (*qp);
        morphValue = std::make_unique<trench::TrenchValueBox>      (*qp, trench::TrenchValueBox::Mode::Percent);
        addAndMakeVisible (*morphBand);
        addAndMakeVisible (*morphValue);
    }
    if (auto* mp = processorRef.apvts.getParameter (ParamID::morph))
    {
        qBand  = std::make_unique<trench::TrenchShuttleControl> (*mp);
        qValue = std::make_unique<trench::TrenchValueBox>      (*mp, trench::TrenchValueBox::Mode::Percent);
        addAndMakeVisible (*qBand);
        addAndMakeVisible (*qValue);
    }

    // Live TYPE strip — cartridge body selector inside the chassis TYPE region.
    if (auto* bp = processorRef.apvts.getParameter (ParamID::body))
    {
        bodyStrip = std::make_unique<trench::TrenchBodyStrip> (*bp);
        addAndMakeVisible (*bodyStrip);
    }

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
}

void PluginEditor::resized()
{
    const auto w = getWidth();
    const auto h = getHeight();

    if (responseDisplay) responseDisplay->setBounds (trench::layout::displayBounds (w, h));
    if (bodyStrip)  bodyStrip ->setBounds (trench::layout::typeBounds    (w, h));
    if (morphBand)  morphBand ->setBounds (trench::layout::morphBounds   (w, h));
    if (qBand)      qBand     ->setBounds (trench::layout::qBounds       (w, h));
    if (morphValue) morphValue->setBounds (trench::layout::valueBounds   (w, h));
    if (qValue)     qValue    ->setBounds (trench::layout::qValueBounds  (w, h));
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
