#include "PluginEditor.h"
#include "BinaryData.h"

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

juce::Rectangle<float> morphWheelWell()
{
    return sourceRectToEditor ({ 127.0f, 694.0f, 423.0f, 101.0f });
}

juce::Rectangle<float> qWheelWell()
{
    return sourceRectToEditor ({ 127.0f, 871.0f, 423.0f, 101.0f });
}
}

PluginEditor::PluginEditor (PluginProcessor& p)
    : AudioProcessorEditor (&p),
      processor (p)
{
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
}

PluginEditor::~PluginEditor()
{
    morphHitTarget.removeMouseListener (this);
    qHitTarget.removeMouseListener (this);
}

void PluginEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colours::black);

    if (panelImage.isValid())
        g.drawImage (panelImage, getLocalBounds().toFloat());

    drawThumbwheels (g);
}

void PluginEditor::resized()
{
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
