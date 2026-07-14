#pragma once

#include "PluginProcessor.h"

#include <juce_gui_basics/juce_gui_basics.h>
#include <juce_opengl/juce_opengl.h>

#include <array>
#include <memory>
#include <optional>
#include <string>

struct WorkstationState;

class WorkstationEditor final : public juce::Component,
                                private juce::Timer
{
public:
    explicit WorkstationEditor (PluginProcessor& processor);
    ~WorkstationEditor() override;

    void paint (juce::Graphics&) override;
    void mouseDown (const juce::MouseEvent&) override;
    void mouseDrag (const juce::MouseEvent&) override;
    void mouseUp (const juce::MouseEvent&) override;
    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails&) override;

private:
    class AuthoringBridge;

    struct QueuedRootPreview
    {
        bool pole = false;
        bool relative = false;
        double hz = 0.0;
        double radius = 0.0;
    };

    struct LiveRoot
    {
        int corner = 0;
        bool pole = false;
        double hz = 0.0;
        double radius = 0.0;
    };

    enum class EditField : int
    {
        zeroHz = 0,
        zeroRadius,
        zeroRootA,
        zeroRootB,
        poleHz,
        poleRadius,
        poleRootA,
        poleRootB,
        scale,
        identity,
    };

    enum class DragTarget
    {
        none,
        conjugatePole,
        conjugateZero,
        poleRootA,
        poleRootB,
        zeroRootA,
        zeroRootB,
        scale,
    };

    void refresh (bool installPending);
    void timerCallback() override;
    void installBody (bool pending);
    void installPreviewBody();
    bool installAuditionBody (bool pending);
    void updateInstalledScreen();
    void performQueuedPreview();
    void queueScreenRefresh();
    void showError (const juce::String& message);
    void selectCorner (int corner);
    void selectLane (int lane);
    void chooseField (EditField field);
    void previewValue (double value);
    void previewConjugateRoot (bool pole, double hz, double radius);
    void applyPreview();
    void discardPreview();
    void fillCornerFromSource();
    void replaceLaneFromSource();
    void chooseActorRecording();
    void loadActorRecording (const juce::File&);
    void openSession();
    void loadSessionFile (const juce::File&);
    void newFilter();
    void saveSession();
    void promoteBody();
    void setAudioMode (bool bodySolo);
    void setStageAudition (bool solo);
    void setMorph (double value);
    void setQ (double value);
    void selectSource (int source);
    void selectRecipe (int recipe);
    void applyRecipe();
    void drawLanguagePicker (juce::Graphics&, const juce::Rectangle<float>&);
    void drawPoseEditor (juce::Graphics&, const juce::Rectangle<float>&);
    void drawLanguageMenu (juce::Graphics&);
    void drawRecipeMenu (juce::Graphics&);
    void drawResponse (juce::Graphics&, const juce::Rectangle<float>&);
    void drawRightRail (juce::Graphics&, const juce::Rectangle<float>&);
    void drawInspect (juce::Graphics&, const juce::Rectangle<float>&);
    void drawControl (juce::Graphics&, const juce::Rectangle<float>&, const juce::String&, bool active = false);
    void drawSlider (juce::Graphics&, const juce::Rectangle<float>&, const juce::String&, double value);
    void drawText (juce::Graphics&, const juce::String&, float x, float y, float w,
                   float h, juce::Colour colour, float size, juce::Justification justification = juce::Justification::left);
    juce::Rectangle<float> plotBounds() const;
    juce::Rectangle<float> languagePickerBounds() const;
    juce::Rectangle<float> languageSelectorBounds() const;
    juce::Rectangle<float> endpointBounds (bool high) const;
    juce::Rectangle<float> sourceSectionBounds() const;
    juce::Rectangle<float> languageCornerBounds (int corner) const;
    juce::Rectangle<float> poseBounds (int corner) const;
    juce::Rectangle<float> zPlaneBounds (int corner) const;
    juce::Rectangle<float> poseScaleBounds (int corner) const;
    juce::Rectangle<float> poseIdentityBounds (int corner) const;
    juce::Rectangle<float> linkAllPosesBounds() const;
    juce::Rectangle<float> rootToolBounds (bool pole) const;
    juce::Rectangle<float> sourceFillBounds() const;
    juce::Rectangle<float> languageMenuBounds() const;
    juce::Rectangle<float> languageMenuItemBounds (int visibleRow) const;
    juce::Rectangle<float> recipeSelectorBounds() const;
    juce::Rectangle<float> recipeApplyBounds() const;
    juce::Rectangle<float> recipeMiniPlotBounds() const;
    juce::Rectangle<float> recipeMenuBounds() const;
    juce::Rectangle<float> recipeMenuItemBounds (int visibleRow) const;
    juce::Rectangle<float> headerControlBounds (int control) const;
    juce::Rectangle<float> railControlBounds (int control) const;
    juce::Rectangle<float> fieldControlBounds (int field) const;
    juce::Rectangle<float> sliderBounds (int slider) const;
    juce::Rectangle<float> rightBounds() const;
    juce::Rectangle<float> footerBounds() const;
    int laneAtPlotPoint (juce::Point<float> point) const;
    double frequencyForX (float x) const;
    double radiusForY (float y) const;
    double realRootForY (float y) const;
    DragTarget dragTargetAt (int corner, juce::Point<float> point) const;
    void editRootFromPose (int corner, DragTarget target, juce::Point<float> point);
    double selectedFieldValue (int corner, DragTarget target) const;
    void editFromPlot (juce::Point<float> point);
    void updateParameter (const char* id, float value);

    PluginProcessor& processor;
    juce::OpenGLContext openGLContext;
    std::unique_ptr<AuthoringBridge> authoring;
    std::unique_ptr<juce::FileChooser> actorChooser;
    std::unique_ptr<juce::FileChooser> sessionChooser;
    juce::var snapshot;
    juce::var installedScreen;
    juce::String status;
    juce::String error;
    std::array<unsigned char, 240> installedBody {};
    std::array<float, 30> installedCoefficients {};
    float installedBoost = 1.0f;

    int selectedCorner = 0;
    int selectedLane = 0;
    int selectedSource = 0;
    int sourceSection = 0;
    int sourceMenuOffset = 0;
    int selectedRecipe = 0;
    int recipeMenuOffset = 0;
    EditField editField = EditField::zeroHz;
    bool sourceHigh = false;
    bool bodySolo = true;
    bool stageSolo = false;
    bool inspectOpen = false;
    bool evidenceOpen = false;
    bool linkAllPoses = false;
    bool poleTool = false;
    bool languageMenuOpen = false;
    bool recipeMenuOpen = false;
    bool draggingPlot = false;
    DragTarget draggingRoot = DragTarget::none;
    int draggingPose = -1;
    double dragStartValue = 0.0;
    double dragStartHz = 0.0;
    double dragStartRadius = 0.0;
    float dragStartX = 0.0f;
    int draggingSlider = -1;
    bool previewInstalled = false;
    bool screenRefreshQueued = false;
    int screenRefreshTicks = 0;
    std::optional<double> queuedPreviewValue;
    std::optional<QueuedRootPreview> queuedRootPreview;
    std::optional<LiveRoot> liveRoot;
    double morph = 0.5;
    double q = 0.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (WorkstationEditor)
};
