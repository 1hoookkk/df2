#pragma once

#include "PluginProcessor.h"

#include <juce_gui_basics/juce_gui_basics.h>

#include <array>
#include <memory>
#include <string>

struct WorkstationState;

class WorkstationEditor final : public juce::Component,
                                private juce::Timer
{
public:
    explicit WorkstationEditor (PluginProcessor& processor);
    ~WorkstationEditor() override;

    void paint (juce::Graphics&) override;
    void resized() override;
    void mouseDown (const juce::MouseEvent&) override;
    void mouseDrag (const juce::MouseEvent&) override;
    void mouseUp (const juce::MouseEvent&) override;

private:
    class AuthoringBridge;

    enum class EditField : int
    {
        poleHz = 0,
        poleRadius,
        zeroHz,
        zeroRadius,
        scale,
    };

    void timerCallback() override;
    void refresh (bool installPending);
    void installBody (bool pending);
    void showError (const juce::String& message);
    void selectCorner (int corner);
    void selectLane (int lane);
    void chooseField (EditField field);
    void previewValue (double value);
    void applyPreview();
    void discardPreview();
    void makeFilter();
    void newFilter();
    void saveSession();
    void promoteBody();
    void setAudioMode (bool bodySolo);
    void setMorph (double value);
    void setQ (double value);
    void drawResponse (juce::Graphics&, const juce::Rectangle<float>&);
    void drawRightRail (juce::Graphics&, const juce::Rectangle<float>&);
    void drawInspect (juce::Graphics&, const juce::Rectangle<float>&);
    void drawText (juce::Graphics&, const juce::String&, float x, float y, float w,
                   float h, juce::Colour colour, float size, juce::Justification justification = juce::Justification::left);
    juce::Rectangle<float> plotBounds() const;
    juce::Rectangle<float> rightBounds() const;
    juce::Rectangle<float> footerBounds() const;
    int laneAtPlotPoint (juce::Point<float> point) const;
    double frequencyForX (float x) const;
    double radiusForY (float y) const;
    void editFromPlot (juce::Point<float> point);
    void updateParameter (const char* id, float value);

    PluginProcessor& processor;
    std::unique_ptr<AuthoringBridge> authoring;
    juce::var snapshot;
    juce::var installedScreen;
    juce::String status;
    juce::String error;
    std::array<unsigned char, 240> installedBody {};
    std::array<float, 30> installedCoefficients {};
    float installedBoost = 1.0f;

    int selectedCorner = 0;
    int selectedLane = 0;
    EditField editField = EditField::poleHz;
    bool allCorners = true;
    bool bodySolo = true;
    bool inspectOpen = false;
    bool draggingPlot = false;
    bool previewInstalled = false;
    double morph = 0.5;
    double q = 0.0;

    juce::TextButton newFilterButton { "NEW FILTER" };
    juce::TextButton makeButton { "MAKE" };
    juce::TextButton saveButton { "SAVE" };
    juce::TextButton promoteButton { "PROMOTE" };
    juce::TextButton undoButton { "UNDO" };
    juce::TextButton redoButton { "REDO" };
    juce::TextButton applyButton { "APPLY" };
    juce::TextButton cancelButton { "CANCEL" };
    juce::TextButton inspectButton { "INSPECT" };
    juce::TextButton bodySoloButton { "BODY SOLO" };
    juce::TextButton productButton { "PRODUCT" };
    juce::TextButton allCornersButton { "ALL 4 POSES" };
    juce::TextButton fieldButtons[5];
    juce::Slider morphSlider;
    juce::Slider qSlider;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (WorkstationEditor)
};
