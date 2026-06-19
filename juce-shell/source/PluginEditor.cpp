#include "PluginEditor.h"
#include "BinaryData.h"
#include "TrenchBodyRoster.h"

namespace
{
constexpr int kEditorWidth = 360;
constexpr int kEditorHeight = 560;
constexpr float kPanelSourceWidth = 1024.0f;
constexpr float kPanelSourceHeight = 1591.0f;
constexpr int kThumbwheelRuntimeFrameWidth = 149;
constexpr int kThumbwheelRuntimeFrameHeight = 40;

juce::Rectangle<float> sourceRectToEditor (juce::Rectangle<float> sourceRect)
{
    return {
        sourceRect.getX() * kEditorWidth / kPanelSourceWidth,
        sourceRect.getY() * kEditorHeight / kPanelSourceHeight,
        sourceRect.getWidth() * kEditorWidth / kPanelSourceWidth,
        sourceRect.getHeight() * kEditorHeight / kPanelSourceHeight
    };
}

juce::Rectangle<float> thumbwheelBodyBounds (juce::Rectangle<float> well)
{
    const auto bounds = well.withSizeKeepingCentre ((float) kThumbwheelRuntimeFrameWidth,
                                                    (float) kThumbwheelRuntimeFrameHeight);
    const auto r = bounds.toNearestInt();
    return { (float) r.getX(),
             (float) r.getY(),
             (float) r.getWidth(),
             (float) r.getHeight() };
}

juce::Rectangle<int> thumbwheelSliderBounds (juce::Rectangle<float> well)
{
    return thumbwheelBodyBounds (well).toNearestInt();
}

juce::Font displayFont (float height, bool bold = false)
{
    return juce::Font (juce::FontOptions (juce::Font::getDefaultSansSerifFontName(), height,
                                          bold ? juce::Font::bold : juce::Font::plain));
}
}

PluginEditor::PluginEditor (PluginProcessor& p)
    : AudioProcessorEditor (&p),
      processor (p)
{
    trench::ensureUiLayoutFileExists (trench::uiLayoutFile());
    currentLayout = trench::loadUiLayoutOrDefaults();
    {
        const auto f = trench::uiLayoutFile();
        layoutFileModTime = f.existsAsFile() ? f.getLastModificationTime().toMilliseconds() : 0;
    }

    panelImage = juce::ImageCache::getFromMemory (BinaryData::df2_panel_shadow_png,
                                                  BinaryData::df2_panel_shadow_pngSize);
    thumbwheelStrip = juce::ImageCache::getFromMemory (BinaryData::thumbwheel_runtime_strip_129_149x40_png,
                                                       BinaryData::thumbwheel_runtime_strip_129_149x40_pngSize);

    const auto setupSlider = [this] (juce::Slider& slider)
    {
        slider.setSliderStyle (juce::Slider::LinearHorizontal);
        slider.setTextBoxStyle (juce::Slider::NoTextBox, false, 0, 0);
        slider.setRange (0.0, 1.0, 0.001);
        slider.setAlpha (0.0f);
        slider.setOpaque (false);
        slider.setInterceptsMouseClicks (false, false);
        slider.onValueChange = [this] { repaint(); };
        addAndMakeVisible (slider);
    };

    setupSlider (morphSlider);
    setupSlider (qSlider);

    bodySelector.setWantsKeyboardFocus (true);
    bodySelector.setColour (juce::ComboBox::backgroundColourId, juce::Colours::transparentBlack);
    bodySelector.setColour (juce::ComboBox::outlineColourId, juce::Colours::transparentBlack);
    bodySelector.setColour (juce::ComboBox::buttonColourId, juce::Colours::transparentBlack);
    bodySelector.setColour (juce::ComboBox::arrowColourId, juce::Colours::transparentBlack);
    bodySelector.setColour (juce::ComboBox::textColourId, juce::Colours::transparentBlack);
    bodySelector.setTextWhenNothingSelected ({});
    populateBodySelector();
    bodySelector.onChange = [this]
    {
        if (syncingBodySelector)
            return;

        const auto selectedIndex = bodySelector.getSelectedId() - 1;
        if (selectedIndex < 0)
            return;

        if (auto* parameter = processor.apvts.getParameter (ParamID::body))
        {
            parameter->beginChangeGesture();
            parameter->setValueNotifyingHost (parameter->convertTo0to1 ((float) selectedIndex));
            parameter->endChangeGesture();
        }
    };
    addAndMakeVisible (bodySelector);
    syncBodySelectorToParameter();

    morphHitTarget.setInterceptsMouseClicks (true, false);
    qHitTarget.setInterceptsMouseClicks (true, false);
    morphHitTarget.setAlwaysOnTop (true);
    qHitTarget.setAlwaysOnTop (true);
    morphHitTarget.addMouseListener (this, false);
    qHitTarget.addMouseListener (this, false);
    addAndMakeVisible (morphHitTarget);
    addAndMakeVisible (qHitTarget);

    morphSliderAttachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment> (processor.apvts, ParamID::morph, morphSlider);
    qSliderAttachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment> (processor.apvts, ParamID::q, qSlider);

    setOpaque (true);
    setResizable (false, false);
    setSize (kEditorWidth, kEditorHeight);
    startTimerHz (24);
}

PluginEditor::~PluginEditor()
{
    morphHitTarget.removeMouseListener (this);
    qHitTarget.removeMouseListener (this);
}

juce::Rectangle<float> PluginEditor::morphWheelWell() const
{
    return sourceRectToEditor (currentLayout.sourceRectFor ("morphWheel"));
}

juce::Rectangle<float> PluginEditor::qWheelWell() const
{
    return sourceRectToEditor (currentLayout.sourceRectFor ("qWheel"));
}

juce::Rectangle<float> PluginEditor::typeSelectorWell() const
{
    return sourceRectToEditor (currentLayout.sourceRectFor ("typeSelector"));
}

juce::Rectangle<float> PluginEditor::morphReadoutWell() const
{
    return sourceRectToEditor (currentLayout.sourceRectFor ("morphReadout"));
}

juce::Rectangle<float> PluginEditor::qReadoutWell() const
{
    return sourceRectToEditor (currentLayout.sourceRectFor ("qReadout"));
}

void PluginEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colours::black);

    if (panelImage.isValid())
        g.drawImage (panelImage, getLocalBounds().toFloat());

    drawSelectorAndReadouts (g);
    drawThumbwheels (g);
}

void PluginEditor::resized()
{
    auto selectorBounds = typeSelectorWell();
    const float labelWidth = 32.0f;
    selectorBounds.removeFromLeft (labelWidth);

    bodySelector.setBounds (selectorBounds.toNearestInt().reduced (1));
    morphSlider.setBounds (thumbwheelSliderBounds (morphWheelWell()));
    qSlider.setBounds (thumbwheelSliderBounds (qWheelWell()));
    morphHitTarget.setBounds (thumbwheelSliderBounds (morphWheelWell()).expanded (2, 3));
    qHitTarget.setBounds (thumbwheelSliderBounds (qWheelWell()).expanded (2, 3));
    morphHitTarget.toFront (false);
    qHitTarget.toFront (false);
}

void PluginEditor::mouseDown (const juce::MouseEvent& event)
{
    const auto position = event.getEventRelativeTo (this).position;
    const auto morphBody = thumbwheelBodyBounds (morphWheelWell()).expanded (1.0f, 2.0f);
    const auto qBody = thumbwheelBodyBounds (qWheelWell()).expanded (1.0f, 2.0f);

    if (morphBody.contains (position))
        activeThumbwheelParameter = ParamID::morph;
    else if (qBody.contains (position))
        activeThumbwheelParameter = ParamID::q;
    else
        activeThumbwheelParameter = nullptr;

    if (activeThumbwheelParameter != nullptr)
    {
        if (auto* parameter = processor.apvts.getParameter (activeThumbwheelParameter))
            parameter->beginChangeGesture();

        mouseDrag (event);
    }
}

void PluginEditor::mouseDrag (const juce::MouseEvent& event)
{
    if (activeThumbwheelParameter == nullptr)
        return;

    const auto position = event.getEventRelativeTo (this).position;
    const auto body = thumbwheelBodyBounds (activeThumbwheelParameter == ParamID::morph ? morphWheelWell() : qWheelWell());
    const auto normalised = juce::jlimit (0.0f, 1.0f, (position.x - body.getX()) / juce::jmax (1.0f, body.getWidth()));
    auto& targetSlider = activeThumbwheelParameter == ParamID::morph ? morphSlider : qSlider;

    targetSlider.setValue (normalised, juce::dontSendNotification);

    if (auto* parameter = processor.apvts.getParameter (activeThumbwheelParameter))
        parameter->setValueNotifyingHost (normalised);

    repaint();
}

void PluginEditor::mouseUp (const juce::MouseEvent&)
{
    if (activeThumbwheelParameter != nullptr)
        if (auto* parameter = processor.apvts.getParameter (activeThumbwheelParameter))
            parameter->endChangeGesture();

    activeThumbwheelParameter = nullptr;
}

void PluginEditor::drawThumbwheels (juce::Graphics& g)
{
    const auto readNormalised = [this] (const char* parameterID)
    {
        if (auto* value = processor.apvts.getRawParameterValue (parameterID))
            return juce::jlimit (0.0f, 1.0f, value->load());

        return 0.0f;
    };

    drawThumbwheelFrame (g, morphWheelWell(), readNormalised (ParamID::morph));
    drawThumbwheelFrame (g, qWheelWell(), readNormalised (ParamID::q));
}

void PluginEditor::drawThumbwheelFrame (juce::Graphics& g, juce::Rectangle<float> well, float normalisedValue)
{
    if (! thumbwheelStrip.isValid())
        return;

    constexpr int numFrames = 129;
    constexpr int lastPlayableFrame = numFrames - 1;
    const auto frameWidth = thumbwheelStrip.getWidth() / numFrames;
    const auto frameHeight = thumbwheelStrip.getHeight();

    if (frameWidth <= 0 || frameHeight <= 0)
        return;

    const auto frame = juce::jlimit (0, lastPlayableFrame, juce::roundToInt (normalisedValue * static_cast<float> (lastPlayableFrame)));
    const auto srcX = frame * frameWidth;
    const auto dst = thumbwheelBodyBounds (well).toNearestInt();

    juce::Graphics::ScopedSaveState saveState (g);
    g.reduceClipRegion (dst);
    g.setImageResamplingQuality (juce::Graphics::lowResamplingQuality);
    g.setOpacity (1.0f);
    g.drawImage (thumbwheelStrip,
                 dst.getX(), dst.getY(), dst.getWidth(), dst.getHeight(),
                 srcX, 0, frameWidth, frameHeight);
}

void PluginEditor::drawSelectorAndReadouts (juce::Graphics& g)
{
    const auto selectorBounds = typeSelectorWell();
    
    if (panelImage.isValid())
    {
        const float scaleX = panelImage.getWidth() / 360.0f;
        const float scaleY = panelImage.getHeight() / 560.0f;
        const float srcX = selectorBounds.getX() * scaleX;
        const float srcY = selectorBounds.getY() * scaleY;
        const float srcW = selectorBounds.getWidth() * scaleX;
        const float srcH = selectorBounds.getHeight() * scaleY;
        const float cleanSrcY = juce::jmax (0.0f, srcY - srcH - 15.0f);
        
        g.drawImage (panelImage,
                     juce::roundToInt (selectorBounds.getX()), juce::roundToInt (selectorBounds.getY()), 
                     juce::roundToInt (selectorBounds.getWidth()), juce::roundToInt (selectorBounds.getHeight()),
                     juce::roundToInt (srcX), juce::roundToInt (cleanSrcY), 
                     juce::roundToInt (srcW), juce::roundToInt (srcH));
    }

    auto buttonBounds = selectorBounds;
    const float labelWidth = 32.0f;
    auto labelArea = buttonBounds.removeFromLeft (labelWidth);

    g.setFont (displayFont (9.0f, true));
    g.setColour (juce::Colour (0xff333333));
    g.drawFittedText ("TYPE", labelArea.toNearestInt(), juce::Justification::centredLeft, 1);

    drawDisplayWell (g, buttonBounds);

    const auto selectedIndex = bodySelector.getSelectedId() - 1;
    const auto typeText = selectedIndex >= 0 ? trench::bodyDisplayName (selectedIndex)
                                             : juce::String ("TYPE");

    auto selectorText = buttonBounds.reduced (8.0f, 2.0f);
    const float arrowBoxWidth = buttonBounds.getHeight();
    auto arrowBox = selectorText.removeFromRight (arrowBoxWidth);

    // Regular weight (non-bold) for clean typography
    g.setFont (displayFont (12.0f, false));
    g.setColour (juce::Colours::black);
    g.drawFittedText (typeText, selectorText.toNearestInt(), juce::Justification::centredLeft, 1);

    g.setColour (juce::Colour (0xff909090));
    g.drawVerticalLine (juce::roundToInt (buttonBounds.getX() + buttonBounds.getWidth() - arrowBoxWidth),
                        buttonBounds.getY() + 1.0f, buttonBounds.getBottom() - 1.0f);

    const auto arrow = arrowBox.withSizeKeepingCentre (6.0f, 4.0f);
    juce::Path arrowPath;
    arrowPath.startNewSubPath (arrow.getX(), arrow.getY());
    arrowPath.lineTo (arrow.getCentreX(), arrow.getBottom());
    arrowPath.lineTo (arrow.getRight(), arrow.getY());
    arrowPath.closeSubPath();
    g.setColour (juce::Colours::black);
    g.fillPath (arrowPath);

    const auto readParameter = [this] (const char* parameterID)
    {
        if (auto* value = processor.apvts.getRawParameterValue (parameterID))
            return juce::jlimit (0.0f, 1.0f, value->load());

        return 0.0f;
    };

    drawReadout (g, morphReadoutWell(), "morphReadout", readParameter (ParamID::morph));
    drawReadout (g, qReadoutWell(), "qReadout", readParameter (ParamID::q));
}

void PluginEditor::drawDisplayWell (juce::Graphics& g, juce::Rectangle<float> bounds)
{
    if (panelImage.isValid())
    {
        const float scaleX = panelImage.getWidth() / 360.0f;
        const float scaleY = panelImage.getHeight() / 560.0f;
        const float srcX = bounds.getX() * scaleX;
        const float srcY = bounds.getY() * scaleY;
        const float srcW = bounds.getWidth() * scaleX;
        const float srcH = bounds.getHeight() * scaleY;
        const float cleanSrcY = juce::jmax (0.0f, srcY - srcH - 15.0f);
        
        g.drawImage (panelImage,
                     juce::roundToInt (bounds.getX()), juce::roundToInt (bounds.getY()), 
                     juce::roundToInt (bounds.getWidth()), juce::roundToInt (bounds.getHeight()),
                     juce::roundToInt (srcX), juce::roundToInt (cleanSrcY), 
                     juce::roundToInt (srcW), juce::roundToInt (srcH));
    }

    const auto r = bounds.reduced (1.0f);
    const auto radius = 3.0f;

    // Outer drop shadow (thick but small)
    g.setColour (juce::Colours::black.withAlpha (0.22f));
    g.fillRoundedRectangle (r.translated (0.0f, 1.5f), radius);
    g.setColour (juce::Colours::black.withAlpha (0.12f));
    g.fillRoundedRectangle (r.translated (0.0f, 0.8f), radius);

    // Button gradient background
    juce::ColourGradient grad (juce::Colour (0xfffafafa), r.getX(), r.getY(),
                               juce::Colour (0xffcfcfcf), r.getX(), r.getBottom(), false);
    g.setGradientFill (grad);
    g.fillRoundedRectangle (r, radius);

    // Outer border
    g.setColour (juce::Colour (0xff707070));
    g.drawRoundedRectangle (r, radius, 1.0f);

    // Diagonal gradient bevel inner border
    juce::ColourGradient bevelGrad (juce::Colours::white.withAlpha (0.9f), r.getX() + 1.0f, r.getY() + 1.0f,
                                    juce::Colours::black.withAlpha (0.24f), r.getRight() - 1.0f, r.getBottom() - 1.0f, false);
    g.setGradientFill (bevelGrad);
    g.drawRoundedRectangle (r.reduced (1.0f), radius - 0.5f, 1.0f);
}

void PluginEditor::drawReadout (juce::Graphics& g, juce::Rectangle<float> bounds, const juce::String& elementId, float value)
{
    drawDisplayWell (g, bounds);

    const auto pct = juce::jlimit (0.0f, 1.0f, value) * 100.0f;
    const auto numeric = juce::String (pct, 1);
    const auto fontSize = currentLayout.fontSizeFor (elementId).value_or (13.0f);
    const auto colour = currentLayout.textColourFor (elementId).value_or (juce::Colours::black);

    g.setFont (displayFont (fontSize, false));
    g.setColour (colour);
    g.drawFittedText (numeric, bounds.toNearestInt(), juce::Justification::centred, 1);
}

void PluginEditor::populateBodySelector()
{
    bodySelector.clear (juce::dontSendNotification);

    int count = 0;
    const auto* entries = trench::bodyRoster (count);
    for (int i = 0; i < count; ++i)
        bodySelector.addItem (entries[i].displayName, i + 1);
}

void PluginEditor::syncBodySelectorToParameter()
{
    if (auto* value = processor.apvts.getRawParameterValue (ParamID::body))
    {
        syncingBodySelector = true;
        bodySelector.setSelectedId (juce::roundToInt (value->load()) + 1, juce::dontSendNotification);
        syncingBodySelector = false;
    }
}

void PluginEditor::reloadLayoutIfChanged()
{
    const auto file = trench::uiLayoutFile();
    const auto mod = file.existsAsFile() ? file.getLastModificationTime().toMilliseconds() : 0;
    if (mod == layoutFileModTime)
        return;

    layoutFileModTime = mod;
    currentLayout = trench::loadUiLayoutOrDefaults();
    resized();
    repaint();
}

void PluginEditor::timerCallback()
{
    reloadLayoutIfChanged();
    syncBodySelectorToParameter();
    repaint();
}
