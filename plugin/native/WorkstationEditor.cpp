#include "WorkstationEditor.h"

#include "parameters/TrenchParameters.h"

#include <juce_core/juce_core.h>
#include <juce_audio_formats/juce_audio_formats.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <iterator>
#include <limits>
#include <utility>
#include <vector>

extern "C"
{
    WorkstationState* workstation_state_create (const char* path);
    void workstation_state_destroy (WorkstationState* state);
    size_t workstation_state_last_error (WorkstationState*, unsigned char*, size_t);
    size_t workstation_state_snapshot_json (WorkstationState*, unsigned char*, size_t);
    size_t workstation_state_session_json (WorkstationState*, unsigned char*, size_t);
    int workstation_state_load_session_json (WorkstationState*, const unsigned char*, size_t);
    int workstation_state_load_actor_audio (WorkstationState*, const float*, size_t, double,
                                            const char* sourcePath);
    size_t workstation_state_keep_json (WorkstationState*, unsigned char*, size_t);
    size_t workstation_state_cartridge_json (WorkstationState*, unsigned char*, size_t);
    int workstation_state_current_body (WorkstationState*, unsigned char*, size_t);
    int workstation_state_pending_body (WorkstationState*, unsigned char*, size_t);
    int workstation_state_stage_solo_body (WorkstationState*, int pending, unsigned char*, size_t);
    int workstation_state_select (WorkstationState*, size_t corner, size_t lane);
    int workstation_state_fill_corner_source (WorkstationState*, size_t corner, size_t source, int endpoint);
    int workstation_state_assign_lane_source (WorkstationState*, size_t corner, size_t lane,
                                              size_t source, int endpoint, size_t sourceSection);
    int workstation_state_apply_recipe (WorkstationState*, size_t candidateIndex);
    int workstation_state_new_filter (WorkstationState*);
    int workstation_state_preview_field (WorkstationState*, int field, double value, int allCorners);
    int workstation_state_preview_conjugate_root (WorkstationState*, int pole, double hz,
                                                   double radius, int allCorners);
    int workstation_state_preview_relative_conjugate_root (WorkstationState*, int pole,
                                                            double octaveDelta,
                                                            double radiusDelta);
    int workstation_state_apply (WorkstationState*);
    int workstation_state_discard_preview (WorkstationState*);
    int workstation_state_undo (WorkstationState*);
    int workstation_state_redo (WorkstationState*);
    int workstation_state_set_morph_q (WorkstationState*, double morph, double q);
    int workstation_state_validate (WorkstationState*);
    size_t workstation_state_screen_for_body_json (WorkstationState*, const unsigned char*, size_t,
                                                   unsigned char*, size_t);
}

namespace
{
constexpr size_t kFfiError = std::numeric_limits<size_t>::max();
constexpr float kPlotMinDb = -36.0f;
constexpr float kPlotMaxDb = 36.0f;
constexpr float kMinHz = 20.0f;
constexpr float kMaxHz = 16000.0f;
constexpr double kStageSampleRate = 39062.5;
constexpr const char* kCornerLabels[] = { "M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100" };
constexpr const char* kPoseLabels[] = { "BASE", "MORPH", "Q", "MORPH + Q" };

juce::var property (const juce::var& object, const char* name)
{
    return object.isObject() ? object.getProperty (name, {}) : juce::var();
}

juce::String stringProperty (const juce::var& object, const char* name)
{
    return property (object, name).toString();
}

double numberProperty (const juce::var& object, const char* name, double fallback = 0.0)
{
    const auto value = property (object, name);
    return value.isDouble() || value.isInt() || value.isInt64() ? static_cast<double> (value) : fallback;
}

juce::var arrayItem (const juce::var& array, int index)
{
    return array.isArray() && index >= 0 && index < array.size() ? array[index] : juce::var();
}

double numberAt (const juce::var& array, int index, double fallback = 0.0)
{
    const auto value = arrayItem (array, index);
    return value.isDouble() || value.isInt() || value.isInt64() ? static_cast<double> (value) : fallback;
}

int trueCount (const juce::var& array)
{
    if (! array.isArray())
        return 0;

    int count = 0;
    for (int index = 0; index < array.size(); ++index)
        if (static_cast<bool> (array[index]))
            ++count;
    return count;
}

constexpr int kSourceMenuRows = 13;
constexpr int kRecipeMenuRows = 9;
constexpr int kHeaderActionCount = 9;

juce::var sourceArray (const juce::var& snapshot)
{
    return property (property (snapshot, "sourceCatalog"), "sources");
}

int sourceCount (const juce::var& snapshot)
{
    const auto sources = sourceArray (snapshot);
    return sources.isArray() ? sources.size() : 0;
}

juce::var recipeArray (const juce::var& snapshot)
{
    return property (property (snapshot, "recipeCatalog"), "candidates");
}

int recipeCount (const juce::var& snapshot)
{
    const auto recipes = recipeArray (snapshot);
    return recipes.isArray() ? recipes.size() : 0;
}

juce::String indexedRecipeName (const juce::var& snapshot, int recipe)
{
    const auto recipes = recipeArray (snapshot);
    if (! recipes.isArray() || recipe < 0 || recipe >= recipes.size())
        return "NO ELIGIBLE RECIPES";
    const auto item = arrayItem (recipes, recipe);
    return stringProperty (item, "candidateId") + " / L"
           + juce::String (static_cast<int> (numberProperty (item, "recipeLane")));
}

juce::String indexedSourceName (const juce::var& snapshot, int source)
{
    const auto sources = sourceArray (snapshot);
    if (! sources.isArray() || source < 0 || source >= sources.size())
        return "NO XML SOURCES";
    const auto item = arrayItem (sources, source);
    return juce::String (source).paddedLeft ('0', 3) + "  " + stringProperty (item, "name")
           + "  [" + juce::String (static_cast<int> (numberProperty (item, "activeSections"))) + "/6]";
}

juce::Colour cornerColour (int corner)
{
    static const juce::Colour colours[] = {
        juce::Colour (0xfff2a65a), juce::Colour (0xff76c7c0),
        juce::Colour (0xfff17c9c), juce::Colour (0xffb7a0dc)
    };
    return colours[juce::jlimit (0, 3, corner)];
}

juce::String rootReadout (const juce::var& root)
{
    const auto conjugate = property (root, "Conjugate");
    if (conjugate.isObject())
        return juce::String (numberProperty (conjugate, "hz"), 1) + " Hz / r "
               + juce::String (numberProperty (conjugate, "radius"), 5);
    const auto real = property (root, "RealPair");
    if (real.isObject())
        return "A " + juce::String (numberProperty (real, "root_a"), 5) + " / B "
               + juce::String (numberProperty (real, "root_b"), 5);
    return "ORIGIN";
}

bool conjugateValues (const juce::var& root, double& hz, double& radius)
{
    const auto conjugate = property (root, "Conjugate");
    if (! conjugate.isObject())
        return false;
    hz = numberProperty (conjugate, "hz");
    radius = numberProperty (conjugate, "radius");
    return std::isfinite (hz) && std::isfinite (radius);
}

bool realValues (const juce::var& root, double& rootA, double& rootB)
{
    const auto real = property (root, "RealPair");
    if (! real.isObject())
        return false;
    rootA = numberProperty (real, "root_a");
    rootB = numberProperty (real, "root_b");
    return std::isfinite (rootA) && std::isfinite (rootB);
}

juce::Point<float> rootPoint (const juce::Rectangle<float>& plane, double hz, double radius,
                              bool upper = true)
{
    const auto angle = juce::jlimit (0.0, juce::MathConstants<double>::pi,
                                     juce::MathConstants<double>::twoPi * hz / kStageSampleRate);
    const auto diskRadius = plane.getWidth() * 0.5f;
    const auto x = plane.getCentreX() + diskRadius * static_cast<float> (radius * std::cos (angle));
    const auto yOffset = diskRadius * static_cast<float> (radius * std::sin (angle));
    return { x, plane.getCentreY() + (upper ? -yOffset : yOffset) };
}

juce::Point<float> realRootPoint (const juce::Rectangle<float>& plane, double root)
{
    return { plane.getCentreX() + plane.getWidth() * 0.5f * static_cast<float> (root),
             plane.getCentreY() };
}

juce::String cornerRecipeLabel (const juce::var& snapshot, int corner)
{
    if (static_cast<bool> (property (property (snapshot, "exportReadiness"),
                                     "ownedFixedActorScaffold")))
        return "FIXED ACTORS / 6 LANES";
    const auto corners = property (property (snapshot, "screen"), "corners");
    const auto lanes = property (arrayItem (corners, corner), "lanes");
    if (! lanes.isArray() || lanes.size() != 6)
        return "EMPTY";
    int active = 0;
    juce::String commonName;
    juce::String commonEndpoint;
    bool oneSource = true;
    for (int lane = 0; lane < lanes.size(); ++lane)
    {
        const auto stage = property (arrayItem (lanes, lane), "stage");
        if (! static_cast<bool> (property (stage, "identity")))
            ++active;
        const auto source = property (stage, "source");
        const auto name = stringProperty (source, "sourceName");
        const auto endpoint = stringProperty (source, "endpoint");
        const auto section = static_cast<int> (numberProperty (source, "sectionIndex", -1.0));
        if (lane == 0)
        {
            commonName = name;
            commonEndpoint = endpoint;
        }
        if (name.isEmpty() || name != commonName || endpoint != commonEndpoint || section != lane + 1)
            oneSource = false;
    }
    if (oneSource)
        return commonName + " / " + commonEndpoint.toUpperCase() + " / " + juce::String (active) + " ACTIVE";
    return (active == 0 ? "EMPTY" : "MIXED") + juce::String (" / ") + juce::String (active) + " ACTIVE";
}

juce::Colour laneColour (int lane)
{
    static const juce::Colour colours[] = {
        juce::Colour (0xfff2a65a), juce::Colour (0xff76c7c0), juce::Colour (0xff9ea7ff),
        juce::Colour (0xfff17c9c), juce::Colour (0xffd2c27a), juce::Colour (0xffb7a0dc)
    };
    return colours[juce::jlimit (0, 5, lane)];
}

juce::String safeFileStem (juce::String value)
{
    value = value.trim();
    if (value.isEmpty())
        value = "untitled_filter";
    value = value.replaceCharacters ("\\/:*?\"<>|", "_________");
    return value.replaceCharacters (" ", "_");
}
} // namespace

class WorkstationEditor::AuthoringBridge
{
public:
    explicit AuthoringBridge (const juce::File& repository)
        : root (repository)
    {
        const auto path = root.getFullPathName().toStdString();
        state = workstation_state_create (path.c_str());
    }

    ~AuthoringBridge()
    {
        workstation_state_destroy (state);
    }

    bool valid() const noexcept { return state != nullptr; }
    const juce::File& repository() const noexcept { return root; }

    juce::String lastError()
    {
        return text ([this] (unsigned char* out, size_t size) {
            return workstation_state_last_error (state, out, size);
        });
    }

    juce::String snapshot()
    {
        return text ([this] (unsigned char* out, size_t size) {
            return workstation_state_snapshot_json (state, out, size);
        });
    }

    juce::String session()
    {
        return text ([this] (unsigned char* out, size_t size) {
            return workstation_state_session_json (state, out, size);
        });
    }

    bool loadSession (const juce::String& json)
    {
        return workstation_state_load_session_json (
                   state, reinterpret_cast<const unsigned char*> (json.toRawUTF8()),
                   static_cast<size_t> (json.getNumBytesAsUTF8())) == 0;
    }

    bool loadActor (const std::vector<float>& mono, double sampleRate, const juce::File& source)
    {
        const auto path = source.getFullPathName();
        return workstation_state_load_actor_audio (state, mono.data(), mono.size(), sampleRate,
                                                    path.toRawUTF8()) == 0;
    }

    juce::String keep()
    {
        return text ([this] (unsigned char* out, size_t size) {
            return workstation_state_keep_json (state, out, size);
        });
    }

    juce::String cartridge()
    {
        return text ([this] (unsigned char* out, size_t size) {
            return workstation_state_cartridge_json (state, out, size);
        });
    }

    bool currentBody (std::array<unsigned char, 240>& out)
    {
        return workstation_state_current_body (state, out.data(), out.size()) == 0;
    }

    bool pendingBody (std::array<unsigned char, 240>& out)
    {
        return workstation_state_pending_body (state, out.data(), out.size()) == 0;
    }

    bool stageSoloBody (bool pending, std::array<unsigned char, 240>& out)
    {
        return workstation_state_stage_solo_body (state, pending ? 1 : 0,
                                                   out.data(), out.size()) == 0;
    }

    bool screenForBody (const std::array<unsigned char, 240>& body, juce::String& out)
    {
        out = text ([this, &body] (unsigned char* data, size_t size) {
            return workstation_state_screen_for_body_json (state, body.data(), body.size(), data, size);
        });
        return ! out.isEmpty();
    }

    bool select (int corner, int lane)
    {
        return workstation_state_select (state, static_cast<size_t> (corner), static_cast<size_t> (lane)) == 0;
    }

    bool fillCorner (int corner, int source, bool high)
    {
        return workstation_state_fill_corner_source (state, static_cast<size_t> (corner),
                                                      static_cast<size_t> (source), high ? 1 : 0) == 0;
    }

    bool assignLane (int corner, int lane, int source, bool high, int sourceSection)
    {
        return workstation_state_assign_lane_source (state, static_cast<size_t> (corner),
                                                      static_cast<size_t> (lane), static_cast<size_t> (source),
                                                      high ? 1 : 0, static_cast<size_t> (sourceSection)) == 0;
    }

    bool applyRecipe (int candidate)
    {
        return workstation_state_apply_recipe (state, static_cast<size_t> (candidate)) == 0;
    }

    bool newFilter() { return workstation_state_new_filter (state) == 0; }
    bool preview (int field, double value, bool allCorners)
    {
        return workstation_state_preview_field (state, field, value, allCorners ? 1 : 0) == 0;
    }
    bool previewRoot (bool pole, double hz, double radius, bool allCorners)
    {
        return workstation_state_preview_conjugate_root (state, pole ? 1 : 0, hz, radius,
                                                          allCorners ? 1 : 0) == 0;
    }
    bool previewRelativeRoot (bool pole, double octaveDelta, double radiusDelta)
    {
        return workstation_state_preview_relative_conjugate_root (
                   state, pole ? 1 : 0, octaveDelta, radiusDelta) == 0;
    }
    bool apply() { return workstation_state_apply (state) == 0; }
    bool discardPreview() { return workstation_state_discard_preview (state) == 0; }
    bool undo() { return workstation_state_undo (state) == 0; }
    bool redo() { return workstation_state_redo (state) == 0; }
    bool setMorphQ (double nextMorph, double nextQ)
    {
        return workstation_state_set_morph_q (state, nextMorph, nextQ) == 0;
    }
    bool validate() { return workstation_state_validate (state) == 0; }

private:
    template <typename Function>
    juce::String text (Function&& function)
    {
        if (scratch.size() < 1024 * 1024)
            scratch.resize (1024 * 1024);
        auto size = function (scratch.data(), scratch.size());
        if (size == kFfiError)
            return {};
        if (size > scratch.size())
        {
            scratch.resize (size);
            size = function (scratch.data(), scratch.size());
            if (size == kFfiError || size > scratch.size())
                return {};
        }
        return size == 0 ? juce::String()
                         : juce::String::fromUTF8 (reinterpret_cast<const char*> (scratch.data()),
                                                   static_cast<int> (size));
    }

    WorkstationState* state = nullptr;
    juce::File root;
    std::vector<unsigned char> scratch;
};

WorkstationEditor::WorkstationEditor (PluginProcessor& p)
    : processor (p),
      authoring (std::make_unique<AuthoringBridge> (juce::File (TRENCH_WORKSTATION_REPO_ROOT)))
{
    setOpaque (true);
    openGLContext.setMultisamplingEnabled (true);
    openGLContext.setComponentPaintingEnabled (true);
    openGLContext.setContinuousRepainting (true);
    openGLContext.attachTo (*this);
    chooseField (editField);

    if (! authoring->valid())
        showError ("authoring library failed to open");
    else
    {
        installBody (false);
        status = "DRAG A POLE OR ZERO / FOUR POSES ARE ALWAYS VISIBLE";
        repaint();
    }

    processor.setWorkstationBodySolo (true);
}

WorkstationEditor::~WorkstationEditor()
{
    stopTimer();
    openGLContext.detach();
}

void WorkstationEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colour (0xff101719));
    g.setColour (juce::Colour (0xffe9e2d6));
    g.fillRect (0, 0, getWidth(), 64);
    drawText (g, "TRENCH", 24.0f, 14.0f, 150.0f, 26.0f, juce::Colour (0xff102027), 23.0f, juce::Justification::left);
    drawText (g, "FILTER MAKER", 176.0f, 21.0f, 150.0f, 18.0f, juce::Colour (0xff0f7861), 11.0f);
    static const char* actions[] = { "NEW", "OPEN", "ACTORS", "SOURCES", "SAVE",
                                      "EXPORT", "UNDO", "REDO", "INSPECT" };
    for (int control = 0; control < kHeaderActionCount; ++control)
        drawControl (g, headerControlBounds (control), actions[control],
                     (control == 3 && evidenceOpen) || (control == 8 && inspectOpen));

    const auto plot = plotBounds();
    const auto languages = languagePickerBounds();
    const auto rail = rightBounds();
    const auto footer = footerBounds();
    if (evidenceOpen)
        drawLanguagePicker (g, languages);
    else
        drawPoseEditor (g, languages);
    drawResponse (g, plot);
    drawRightRail (g, rail);

    g.setColour (juce::Colour (0xff213136));
    g.fillRect (footer);
    drawSlider (g, sliderBounds (0), "MORPH", morph);
    drawSlider (g, sliderBounds (1), "Q", q);
    const auto readiness = property (snapshot, "exportReadiness");
    const bool exportReady = ! previewInstalled
                             && static_cast<bool> (property (readiness, "ready"));
    const auto readinessText = previewInstalled
                                   ? juce::String ("KEEP OR DISCARD")
                                   : (exportReady ? juce::String ("READY TO EXPORT")
                                                  : juce::String ("MAKE AND KEEP ONE EDIT"));
    drawText (g, readinessText,
              footer.getX() + 520.0f, footer.getY() + 25.0f, footer.getWidth() - 540.0f, 22.0f,
              exportReady ? juce::Colour (0xff53d6ad) : juce::Colour (0xffaebdb9),
              10.0f, juce::Justification::right);

    if (inspectOpen)
        drawInspect (g, juce::Rectangle<float> (20.0f, 82.0f,
                                                static_cast<float> (getWidth()) - 390.0f,
                                                static_cast<float> (getHeight()) - 174.0f));
    if (languageMenuOpen)
        drawLanguageMenu (g);
    if (recipeMenuOpen)
        drawRecipeMenu (g);
}

void WorkstationEditor::refresh (bool installPending)
{
    if (! authoring->valid())
        return;

    std::array<unsigned char, 240> body {};
    const bool gotBody = installPending ? authoring->pendingBody (body) : authoring->currentBody (body);
    if (gotBody)
    {
        installedBody = body;
        installAuditionBody (installPending);
        juce::String screenJson;
        if (authoring->screenForBody (installedBody, screenJson))
            installedScreen = juce::JSON::parse (screenJson);
    }
    const auto snapshotJson = authoring->snapshot();
    if (! snapshotJson.isEmpty())
        snapshot = juce::JSON::parse (snapshotJson);
    selectedRecipe = juce::jlimit (0, juce::jmax (0, recipeCount (snapshot) - 1), selectedRecipe);
    repaint();
}

void WorkstationEditor::timerCallback()
{
    if (queuedPreviewValue.has_value() || queuedRootPreview.has_value())
        performQueuedPreview();

    if (screenRefreshQueued)
    {
        ++screenRefreshTicks;
        const bool dragging = draggingPlot || draggingRoot != DragTarget::none || draggingSlider >= 0;
        if (screenRefreshTicks >= 3 || ! dragging)
        {
            screenRefreshQueued = false;
            screenRefreshTicks = 0;
            updateInstalledScreen();
            repaint();
        }
    }

    if (! draggingPlot && draggingRoot == DragTarget::none && draggingSlider < 0
        && ! queuedPreviewValue.has_value() && ! queuedRootPreview.has_value()
        && ! screenRefreshQueued)
        stopTimer();
}

void WorkstationEditor::installBody (bool pending)
{
    std::array<unsigned char, 240> body {};
    const bool ok = pending ? authoring->pendingBody (body) : authoring->currentBody (body);
    if (! ok)
    {
        showError (authoring->lastError().isNotEmpty() ? authoring->lastError() : "could not read body bytes");
        return;
    }
    installedBody = body;
    previewInstalled = pending;
    if (! installAuditionBody (pending))
        return;
    updateInstalledScreen();
    const auto snapshotJson = authoring->snapshot();
    if (! snapshotJson.isEmpty())
        snapshot = juce::JSON::parse (snapshotJson);
    selectedRecipe = juce::jlimit (0, juce::jmax (0, recipeCount (snapshot) - 1), selectedRecipe);
    repaint();
}

void WorkstationEditor::installPreviewBody()
{
    std::array<unsigned char, 240> body {};
    if (! authoring->pendingBody (body))
    {
        showError (authoring->lastError().isNotEmpty() ? authoring->lastError()
                                                       : "could not read preview body bytes");
        return;
    }
    installedBody = body;
    previewInstalled = true;
    if (! installAuditionBody (true))
        return;
    screenRefreshQueued = true;
    repaint();
}

bool WorkstationEditor::installAuditionBody (bool pending)
{
    auto audition = installedBody;
    if (stageSolo && ! authoring->stageSoloBody (pending, audition))
    {
        showError (authoring->lastError());
        return false;
    }
    if (! processor.installBodyBytes (audition.data(), audition.size()))
    {
        showError ("processor rejected packed audition body");
        return false;
    }
    return true;
}

void WorkstationEditor::updateInstalledScreen()
{
    juce::String screenJson;
    if (authoring->screenForBody (installedBody, screenJson))
        installedScreen = juce::JSON::parse (screenJson);
}

void WorkstationEditor::showError (const juce::String& message)
{
    error = message.isEmpty() ? "operation failed" : message;
    status = "ERROR";
    repaint();
}

void WorkstationEditor::selectCorner (int corner)
{
    if (authoring->select (corner, selectedLane))
    {
        selectedCorner = corner;
        status = juce::String (kCornerLabels[corner]) + " / " + cornerRecipeLabel (snapshot, corner);
        refresh (previewInstalled);
    }
    else showError (authoring->lastError());
}

void WorkstationEditor::selectLane (int lane)
{
    if (authoring->select (selectedCorner, lane))
    {
        selectedLane = lane;
        refresh (previewInstalled);
    }
    else showError (authoring->lastError());
}

void WorkstationEditor::chooseField (EditField field)
{
    editField = field;
    repaint();
}

void WorkstationEditor::previewValue (double value)
{
    queuedRootPreview.reset();
    queuedPreviewValue = value;
    if (! isTimerRunning())
    {
        performQueuedPreview();
        startTimerHz (60);
    }
}

void WorkstationEditor::previewConjugateRoot (bool pole, double hz, double radius)
{
    queuedPreviewValue.reset();
    if (linkAllPoses && dragStartHz > 0.0)
        queuedRootPreview = QueuedRootPreview {
            pole, true, std::log2 (hz / dragStartHz), radius - dragStartRadius
        };
    else
        queuedRootPreview = QueuedRootPreview { pole, false, hz, radius };
    if (! isTimerRunning())
    {
        performQueuedPreview();
        startTimerHz (60);
    }
}

void WorkstationEditor::performQueuedPreview()
{
    if (! queuedPreviewValue.has_value() && ! queuedRootPreview.has_value())
        return;
    bool ok = false;
    if (queuedRootPreview.has_value())
    {
        const auto root = *queuedRootPreview;
        queuedRootPreview.reset();
        ok = root.relative
                 ? authoring->previewRelativeRoot (root.pole, root.hz, root.radius)
                 : authoring->previewRoot (root.pole, root.hz, root.radius, false);
    }
    else
    {
        const auto value = *queuedPreviewValue;
        queuedPreviewValue.reset();
        ok = authoring->preview (static_cast<int> (editField), value, false);
    }
    if (! ok)
    {
        showError (authoring->lastError());
        return;
    }
    error.clear();
    previewInstalled = true;
    status = "PREVIEW / APPLY KEEPS THE EDIT";
    installPreviewBody();
}

void WorkstationEditor::queueScreenRefresh()
{
    screenRefreshQueued = true;
    screenRefreshTicks = 2;
    if (! isTimerRunning())
        startTimerHz (60);
}

void WorkstationEditor::applyPreview()
{
    if (! previewInstalled)
    {
        status = "drag a field first";
        repaint();
        return;
    }
    if (authoring->apply())
    {
        previewInstalled = false;
        status = "edit kept in the source session";
        error.clear();
        installBody (false);
    }
    else showError (authoring->lastError());
}

void WorkstationEditor::discardPreview()
{
    if (authoring->discardPreview())
    {
        previewInstalled = false;
        status = "preview discarded";
        error.clear();
        installBody (false);
    }
    else showError (authoring->lastError());
}

void WorkstationEditor::fillCornerFromSource()
{
    if (selectedSource < 0 || selectedSource >= sourceCount (snapshot))
    {
        showError ("select an XML source first");
        return;
    }
    if (! authoring->fillCorner (selectedCorner, selectedSource, sourceHigh))
    {
        showError (authoring->lastError());
        return;
    }
    previewInstalled = false;
    error.clear();
    installBody (false);
    const auto changed = property (property (snapshot, "lastSourceApply"), "changedWords");
    status = "STUDY ONLY / " + indexedSourceName (snapshot, selectedSource) + " / "
             + (sourceHigh ? "HIGH" : "LOW") + " -> " + kCornerLabels[selectedCorner]
             + " / " + juce::String (changed.size()) + " WORDS";
    repaint();
}

void WorkstationEditor::replaceLaneFromSource()
{
    if (selectedSource < 0 || selectedSource >= sourceCount (snapshot))
    {
        showError ("select an XML source first");
        return;
    }
    if (! authoring->assignLane (selectedCorner, selectedLane, selectedSource, sourceHigh, sourceSection))
    {
        showError (authoring->lastError());
        return;
    }
    previewInstalled = false;
    error.clear();
    installBody (false);
    const auto changed = property (property (snapshot, "lastSourceApply"), "changedWords");
    status = "STUDY ONLY / L" + juce::String (selectedLane + 1) + " <- "
             + indexedSourceName (snapshot, selectedSource) + " / "
             + (sourceHigh ? "HIGH" : "LOW") + " S" + juce::String (sourceSection + 1)
             + " / " + juce::String (changed.size()) + " WORDS";
    repaint();
}

void WorkstationEditor::chooseActorRecording()
{
    if (actorChooser != nullptr)
        return;
    actorChooser = std::make_unique<juce::FileChooser> (
        "Choose your owned actor recording", juce::File(), "*.wav;*.aif;*.aiff;*.flac");
    actorChooser->launchAsync (juce::FileBrowserComponent::openMode
                                   | juce::FileBrowserComponent::canSelectFiles,
                               [this] (const juce::FileChooser& chooser)
                               {
                                   const auto file = chooser.getResult();
                                   if (file.existsAsFile())
                                       loadActorRecording (file);
                                   actorChooser.reset();
                               });
}

void WorkstationEditor::loadActorRecording (const juce::File& file)
{
    juce::AudioFormatManager formats;
    formats.registerBasicFormats();
    auto reader = formats.createReaderFor (file);
    if (reader == nullptr)
    {
        showError ("could not decode the selected WAV, AIFF, or FLAC recording");
        return;
    }
    if (reader->numChannels == 0 || reader->lengthInSamples < 2048
        || reader->lengthInSamples > 12000000
        || reader->lengthInSamples > std::numeric_limits<int>::max())
    {
        showError ("actor recording must contain 2048..12000000 decodable samples");
        return;
    }
    const auto sampleCount = static_cast<int> (reader->lengthInSamples);
    const auto channelCount = static_cast<int> (reader->numChannels);
    juce::AudioBuffer<float> decoded (channelCount, sampleCount);
    if (! reader->read (&decoded, 0, sampleCount, 0, true, true))
    {
        showError ("could not read the selected actor recording");
        return;
    }
    std::vector<float> mono (static_cast<size_t> (sampleCount), 0.0f);
    const auto channelScale = 1.0f / static_cast<float> (channelCount);
    for (int channel = 0; channel < channelCount; ++channel)
    {
        const auto* source = decoded.getReadPointer (channel);
        for (int sample = 0; sample < sampleCount; ++sample)
            mono[static_cast<size_t> (sample)] += source[sample] * channelScale;
    }
    if (! authoring->loadActor (mono, reader->sampleRate, file))
    {
        showError (authoring->lastError());
        return;
    }
    previewInstalled = false;
    error.clear();
    installBody (false);
    const auto report = property (snapshot, "lastActorLoad");
    const auto lanes = property (report, "lanes");
    const auto changed = property (report, "changedWords");
    status = "PHASE 1 COMPLETE / " + juce::String (lanes.size())
             + " FIXED LPC ACTORS / ZERO MASKS CLOSED / "
             + juce::String (changed.size()) + " WORD RECEIPTS";
    repaint();
}

void WorkstationEditor::openSession()
{
    if (sessionChooser != nullptr)
        return;
    const auto sessions = authoring->repository().getChildFile ("workstation").getChildFile ("sessions");
    sessionChooser = std::make_unique<juce::FileChooser> (
        "Open a TRENCH source session", sessions, "*.session.json;*.json");
    sessionChooser->launchAsync (juce::FileBrowserComponent::openMode
                                     | juce::FileBrowserComponent::canSelectFiles,
                                 [this] (const juce::FileChooser& chooser)
                                 {
                                     const auto file = chooser.getResult();
                                     if (file.existsAsFile())
                                         loadSessionFile (file);
                                     sessionChooser.reset();
                                 });
}

void WorkstationEditor::loadSessionFile (const juce::File& file)
{
    if (file.getSize() <= 0 || file.getSize() > 8 * 1024 * 1024)
    {
        showError ("source session must contain 1..8388608 bytes");
        return;
    }
    const auto json = file.loadFileAsString();
    if (! authoring->loadSession (json))
    {
        showError (authoring->lastError());
        return;
    }
    previewInstalled = false;
    error.clear();
    installBody (false);
    status = "SESSION OPEN / EXACT PACKED BODY RESTORED / " + file.getFileName();
    repaint();
}

void WorkstationEditor::newFilter()
{
    if (authoring->newFilter())
    {
        previewInstalled = false;
        stageSolo = false;
        status = "ORIGINAL SIX-STAGE FRAME / DRAG POLES AND ZEROS IN FOUR POSES";
        error.clear();
        installBody (false);
    }
    else showError (authoring->lastError());
}

void WorkstationEditor::saveSession()
{
    if (! authoring->validate())
    {
        showError (authoring->lastError());
        return;
    }
    const auto session = authoring->session();
    const auto name = safeFileStem (stringProperty (property (snapshot, "screen"), "name"));
    const auto directory = authoring->repository().getChildFile ("workstation").getChildFile ("sessions");
    if (! directory.createDirectory().wasOk()
        || ! directory.getChildFile (name + ".session.json").replaceWithText (session))
    {
        showError ("could not write source session");
        return;
    }
    status = "SAVED SOURCE SESSION / " + name + ".session.json";
    error.clear();
    repaint();
}

void WorkstationEditor::promoteBody()
{
    const auto receiptText = authoring->keep();
    if (receiptText.isEmpty())
    {
        showError (authoring->lastError());
        return;
    }
    const auto receipt = juce::JSON::parse (receiptText);
    const auto proofDirectory = stringProperty (receipt, "directory");
    const auto name = safeFileStem (stringProperty (property (snapshot, "screen"), "name"));
    const auto directory = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                               .getChildFile ("TRENCH").getChildFile ("bodies");
    if (! directory.createDirectory().wasOk())
    {
        showError ("could not create the TRENCH body bank");
        return;
    }
    std::array<unsigned char, 240> committedBody {};
    if (! authoring->currentBody (committedBody))
    {
        showError ("proof passed but the committed body could not be read");
        return;
    }
    const auto bodyFile = directory.getChildFile (name + ".body240");
    const auto cartridgeFile = directory.getChildFile (name + ".cart.json");
    if (! bodyFile.replaceWithData (committedBody.data(), committedBody.size())
        || ! cartridgeFile.replaceWithText (authoring->cartridge()))
    {
        showError ("proof passed at " + proofDirectory + " but the body bank copy failed");
        return;
    }
    installBody (false);
    status = "EXPORTED " + name + " / PROOF BUNDLE + EXACT BODY + CARTRIDGE";
    error.clear();
    repaint();
}

void WorkstationEditor::setAudioMode (bool solo)
{
    bodySolo = solo;
    processor.setWorkstationBodySolo (bodySolo);
    status = bodySolo ? "BODY SOLO / PACKED SIX-STAGE BODY AT UNITY" : "PRODUCT / COMPLETE PROCESSOR PATH";
    repaint();
}

void WorkstationEditor::setStageAudition (bool solo)
{
    stageSolo = solo;
    if (! installAuditionBody (previewInstalled))
        return;
    status = stageSolo ? "STAGE SOLO / SELECTED REGISTERED STAGE ONLY"
                       : "FULL CASCADE / ALL SIX REGISTERED STAGES";
    error.clear();
    repaint();
}

void WorkstationEditor::setMorph (double value)
{
    morph = juce::jlimit (0.0, 1.0, value);
    if (! authoring->setMorphQ (morph, q))
    {
        showError (authoring->lastError());
        return;
    }
    updateParameter (ParamID::morph, static_cast<float> (morph));
    repaint();
    queueScreenRefresh();
}

void WorkstationEditor::setQ (double value)
{
    q = juce::jlimit (0.0, 1.0, value);
    if (! authoring->setMorphQ (morph, q))
    {
        showError (authoring->lastError());
        return;
    }
    updateParameter (ParamID::q, static_cast<float> (q));
    repaint();
    queueScreenRefresh();
}

void WorkstationEditor::selectSource (int source)
{
    if (source < 0 || source >= sourceCount (snapshot))
        return;
    selectedSource = source;
    languageMenuOpen = false;
    error.clear();
    status = indexedSourceName (snapshot, source) + " / SELECTED / 0 WORDS CHANGED";
    repaint();
}

void WorkstationEditor::selectRecipe (int recipe)
{
    if (recipe < 0 || recipe >= recipeCount (snapshot))
        return;
    selectedRecipe = recipe;
    recipeMenuOpen = false;
    error.clear();
    status = indexedRecipeName (snapshot, recipe) + " / ELIGIBLE / 0 WORDS CHANGED";
    repaint();
}

void WorkstationEditor::applyRecipe()
{
    if (! authoring->applyRecipe (selectedRecipe))
    {
        showError (authoring->lastError());
        return;
    }
    previewInstalled = false;
    installBody (false);
    selectedLane = static_cast<int> (numberProperty (property (snapshot, "screen"), "selectedLane"));
    const auto changed = property (property (snapshot, "lastRecipeApply"), "changedWords");
    status = indexedRecipeName (snapshot, selectedRecipe) + " / APPLIED / "
             + juce::String (changed.isArray() ? changed.size() : 0) + " ZERO WORDS CHANGED";
    error.clear();
    repaint();
}

void WorkstationEditor::drawLanguagePicker (juce::Graphics& g, const juce::Rectangle<float>& bounds)
{
    g.setColour (juce::Colour (0xff172226));
    g.fillRect (bounds);
    g.setColour (juce::Colour (0xff33454a));
    g.drawRect (bounds, 1.0f);

    drawText (g, "REFERENCE XML / STUDY ONLY", bounds.getX() + 12.0f, bounds.getY() + 11.0f,
              150.0f, 22.0f, juce::Colour (0xffe9e2d6), 9.0f);
    drawControl (g, languageSelectorBounds(), indexedSourceName (snapshot, selectedSource) + "  v", languageMenuOpen);
    drawControl (g, endpointBounds (false), "LOW", ! sourceHigh);
    drawControl (g, endpointBounds (true), "HIGH", sourceHigh);
    drawControl (g, sourceSectionBounds(), "S" + juce::String (sourceSection + 1), false);
    drawControl (g, sourceFillBounds(), "FILL POSE", false);
    drawControl (g, recipeSelectorBounds(), indexedRecipeName (snapshot, selectedRecipe) + "  v", recipeMenuOpen);
    drawControl (g, recipeApplyBounds(), "APPLY ZERO", false);

    const auto recipeMini = recipeMiniPlotBounds();
    g.setColour (juce::Colour (0xff0c1315));
    g.fillRect (recipeMini);
    g.setColour (juce::Colour (0xff33454a));
    g.drawRect (recipeMini, 1.0f);
    const auto recipes = recipeArray (snapshot);
    const auto candidate = arrayItem (recipes, selectedRecipe);
    const auto targets = property (candidate, "poseZeroTargets");
    if (targets.isArray() && targets.size() == 4)
    {
        double minimum = 0.0;
        double maximum = 0.0;
        for (int index = 0; index < targets.size(); ++index)
        {
            const auto delta = numberProperty (arrayItem (targets, index), "octaveDeltaFromAnchor");
            minimum = std::min (minimum, delta);
            maximum = std::max (maximum, delta);
        }
        if (maximum - minimum < 0.02) { minimum -= 0.01; maximum += 0.01; }
        const auto chart = recipeMini.reduced (8.0f, 7.0f);
        juce::Path path;
        for (int index = 0; index < targets.size(); ++index)
        {
            const auto delta = numberProperty (arrayItem (targets, index), "octaveDeltaFromAnchor");
            const auto x = chart.getX() + chart.getWidth() * static_cast<float> (index) / 3.0f;
            const auto y = juce::jmap (static_cast<float> (delta), static_cast<float> (minimum),
                                       static_cast<float> (maximum), chart.getBottom(), chart.getY());
            if (index == 0) path.startNewSubPath (x, y); else path.lineTo (x, y);
            g.setColour (cornerColour (index));
            g.fillEllipse (x - 2.5f, y - 2.5f, 5.0f, 5.0f);
        }
        g.setColour (juce::Colour (0xfff17c9c));
        g.strokePath (path, juce::PathStrokeType (1.4f));
    }

    const auto corners = property (installedScreen, "corners");
    for (int corner = 0; corner < 4; ++corner)
    {
        const auto tile = languageCornerBounds (corner);
        const bool isSelected = selectedCorner == corner;
        const auto colour = cornerColour (corner);

        g.setColour (juce::Colour (0xff0c1315));
        g.fillRect (tile);
        g.setColour (colour.withAlpha (isSelected ? 0.24f : 0.10f));
        g.fillRect (tile.reduced (1.0f));

        const auto mini = juce::Rectangle<float> (tile.getX() + 6.0f, tile.getY() + 6.0f,
                                                   tile.getHeight() - 12.0f, tile.getHeight() - 12.0f);
        g.setColour (juce::Colour (0xff101719));
        g.fillRect (mini);
        const auto glyph = mini.reduced (5.0f);
        g.setColour (juce::Colour (0xff28383c));
        const auto zeroY = juce::jmap (0.0f, kPlotMinDb, kPlotMaxDb, glyph.getBottom(), glyph.getY());
        g.drawHorizontalLine (juce::roundToInt (zeroY), glyph.getX(), glyph.getRight());
        for (int line = 1; line < 4; ++line)
        {
            const auto x = glyph.getX() + glyph.getWidth() * static_cast<float> (line) / 4.0f;
            g.drawVerticalLine (juce::roundToInt (x), glyph.getY(), glyph.getBottom());
        }

        const auto points = property (property (arrayItem (corners, corner), "response"), "points");
        juce::Path stroke;
        for (int sample = 0; sample < points.size(); ++sample)
        {
            const auto point = arrayItem (points, sample);
            const auto hz = juce::jlimit (static_cast<double> (kMinHz), static_cast<double> (kMaxHz),
                                          numberProperty (point, "freq_hz", kMinHz));
            const auto x01 = static_cast<float> (std::log (hz / kMinHz) / std::log (kMaxHz / kMinHz));
            const auto x = glyph.getX() + x01 * glyph.getWidth();
            const auto db = juce::jlimit (static_cast<double> (kPlotMinDb), static_cast<double> (kPlotMaxDb),
                                          numberProperty (point, "db"));
            const auto y = juce::jmap (static_cast<float> (db), kPlotMinDb, kPlotMaxDb,
                                       glyph.getBottom(), glyph.getY());
            if (sample == 0) stroke.startNewSubPath (x, y);
            else stroke.lineTo (x, y);
        }

        auto fill = stroke;
        fill.lineTo (glyph.getRight(), zeroY);
        fill.lineTo (glyph.getX(), zeroY);
        fill.closeSubPath();
        g.setColour (colour.withAlpha (isSelected ? 0.24f : 0.12f));
        g.fillPath (fill);
        g.setColour (colour.withAlpha (isSelected ? 1.0f : 0.78f));
        g.strokePath (stroke, juce::PathStrokeType (isSelected ? 2.4f : 1.6f,
                                                    juce::PathStrokeType::curved,
                                                    juce::PathStrokeType::rounded));

        const auto textX = mini.getRight() + 12.0f;
        drawText (g, kCornerLabels[corner], textX, tile.getY() + 14.0f,
                  tile.getRight() - textX - 8.0f, 16.0f, juce::Colour (0xff8da0a0), 9.0f);
        drawText (g, cornerRecipeLabel (snapshot, corner), textX, tile.getY() + 32.0f,
                  tile.getRight() - textX - 8.0f, 32.0f,
                  isSelected ? juce::Colour (0xfff3eee5) : juce::Colour (0xffaebdb9), 10.0f);
        g.setColour (isSelected ? colour : juce::Colour (0xff3a4b50));
        g.drawRect (tile, isSelected ? 2.0f : 1.0f);
        g.drawRect (mini, 1.0f);
    }
}

void WorkstationEditor::drawPoseEditor (juce::Graphics& g, const juce::Rectangle<float>& bounds)
{
    g.setColour (juce::Colour (0xff141f22));
    g.fillRect (bounds);
    g.setColour (juce::Colour (0xff33454a));
    g.drawRect (bounds, 1.0f);

    drawText (g, "STAGE " + juce::String (selectedLane + 1) + " OF 6",
              bounds.getX() + 12.0f, bounds.getY() + 8.0f, bounds.getWidth() - 450.0f, 22.0f,
              juce::Colour (0xfff3eee5), 11.0f);
    drawControl (g, rootToolBounds (true), "POLE", poleTool);
    drawControl (g, rootToolBounds (false), "ZERO", ! poleTool);
    drawControl (g, linkAllPosesBounds(), linkAllPoses ? "ALL POSES" : "ONE POSE", linkAllPoses);

    const auto corners = property (installedScreen, "corners");
    for (int corner = 0; corner < 4; ++corner)
    {
        const auto tile = poseBounds (corner);
        const auto plane = zPlaneBounds (corner);
        const bool selected = corner == selectedCorner;
        g.setColour (selected ? juce::Colour (0xff1d3032) : juce::Colour (0xff0d1517));
        g.fillRect (tile);
        g.setColour (selected ? cornerColour (corner) : juce::Colour (0xff35484c));
        g.drawRect (tile, selected ? 2.0f : 1.0f);

        drawText (g, kPoseLabels[corner], tile.getX() + 8.0f, tile.getY() + 5.0f,
                  92.0f, 16.0f, selected ? cornerColour (corner) : juce::Colour (0xff9aacac), 9.0f);
        g.setColour (juce::Colour (0xff26363a));
        g.drawEllipse (plane, 1.0f);
        g.drawHorizontalLine (juce::roundToInt (plane.getCentreY()), plane.getX(), plane.getRight());
        g.drawVerticalLine (juce::roundToInt (plane.getCentreX()), plane.getY(), plane.getBottom());

        const auto lanes = property (arrayItem (corners, corner), "lanes");

        // Keep the whole six-stage corner visible without turning overlapping
        // roots into ambiguous edit targets. Context roots are deliberately
        // small; the selected lane is drawn last with the large pole/zero
        // handles below.
        for (int lane = 0; lane < 6; ++lane)
        {
            if (lane == selectedLane)
                continue;

            const auto contextStage = property (arrayItem (lanes, lane), "stage");
            if (static_cast<bool> (property (contextStage, "identity")))
                continue;

            const auto contextColour = laneColour (lane).withAlpha (0.34f);
            const auto drawContextPole = [this, &g, contextColour, lane] (juce::Point<float> point,
                                                                          bool label)
            {
                g.setColour (contextColour);
                g.drawLine (point.x - 3.5f, point.y + 3.0f, point.x, point.y - 3.5f, 1.1f);
                g.drawLine (point.x, point.y - 3.5f, point.x + 3.5f, point.y + 3.0f, 1.1f);
                g.drawLine (point.x + 3.5f, point.y + 3.0f, point.x - 3.5f, point.y + 3.0f, 1.1f);
                if (label)
                    drawText (g, juce::String (lane + 1), point.x + 4.0f, point.y - 6.0f,
                              10.0f, 10.0f, contextColour, 7.0f);
            };
            const auto drawContextZero = [&g, contextColour] (juce::Point<float> point)
            {
                g.setColour (contextColour);
                g.drawEllipse (point.x - 3.5f, point.y - 3.5f, 7.0f, 7.0f, 1.1f);
            };

            double contextHz = 0.0, contextRadius = 0.0;
            const auto contextPole = property (contextStage, "pole");
            if (conjugateValues (contextPole, contextHz, contextRadius))
            {
                drawContextPole (rootPoint (plane, contextHz, contextRadius, true), true);
                drawContextPole (rootPoint (plane, contextHz, contextRadius, false), false);
            }
            else
            {
                double rootA = 0.0, rootB = 0.0;
                if (realValues (contextPole, rootA, rootB))
                {
                    drawContextPole (realRootPoint (plane, rootA), true);
                    drawContextPole (realRootPoint (plane, rootB), false);
                }
            }

            const auto contextZero = property (contextStage, "zero");
            if (conjugateValues (contextZero, contextHz, contextRadius))
            {
                drawContextZero (rootPoint (plane, contextHz, contextRadius, true));
                drawContextZero (rootPoint (plane, contextHz, contextRadius, false));
            }
            else
            {
                double rootA = 0.0, rootB = 0.0;
                if (realValues (contextZero, rootA, rootB))
                {
                    drawContextZero (realRootPoint (plane, rootA));
                    drawContextZero (realRootPoint (plane, rootB));
                }
            }
        }

        const auto stage = property (arrayItem (lanes, selectedLane), "stage");
        const auto pole = property (stage, "pole");
        const auto zero = property (stage, "zero");
        const auto drawPole = [&g] (juce::Point<float> point, juce::Colour colour, float alpha)
        {
            juce::Path triangle;
            triangle.startNewSubPath (point.x, point.y - 8.0f);
            triangle.lineTo (point.x - 7.0f, point.y + 6.0f);
            triangle.lineTo (point.x + 7.0f, point.y + 6.0f);
            triangle.closeSubPath();
            g.setColour (colour.withAlpha (alpha));
            g.fillPath (triangle);
            g.setColour (colour);
            g.strokePath (triangle, juce::PathStrokeType (1.3f));
        };
        const auto drawZero = [&g] (juce::Point<float> point, juce::Colour colour, float alpha)
        {
            g.setColour (juce::Colour (0xff0d1517).withAlpha (alpha));
            g.fillEllipse (point.x - 7.0f, point.y - 7.0f, 14.0f, 14.0f);
            g.setColour (colour.withAlpha (alpha));
            g.drawEllipse (point.x - 7.0f, point.y - 7.0f, 14.0f, 14.0f, 2.4f);
        };

        double hz = 0.0, radius = 0.0;
        if (conjugateValues (pole, hz, radius))
        {
            if (liveRoot.has_value() && liveRoot->corner == corner && liveRoot->pole)
            {
                hz = liveRoot->hz;
                radius = liveRoot->radius;
            }
            drawPole (rootPoint (plane, hz, radius, true), juce::Colour (0xff54d3c2), 1.0f);
            drawPole (rootPoint (plane, hz, radius, false), juce::Colour (0xff54d3c2), 0.42f);
        }
        else
        {
            double a = 0.0, b = 0.0;
            if (realValues (pole, a, b))
            {
                drawPole (realRootPoint (plane, a), juce::Colour (0xff54d3c2), 1.0f);
                drawPole (realRootPoint (plane, b), juce::Colour (0xff54d3c2), 0.72f);
            }
        }
        if (conjugateValues (zero, hz, radius))
        {
            if (liveRoot.has_value() && liveRoot->corner == corner && ! liveRoot->pole)
            {
                hz = liveRoot->hz;
                radius = liveRoot->radius;
            }
            drawZero (rootPoint (plane, hz, radius, true), juce::Colour (0xffff7da6), 1.0f);
            drawZero (rootPoint (plane, hz, radius, false), juce::Colour (0xffff7da6), 0.42f);
        }
        else
        {
            double a = 0.0, b = 0.0;
            if (realValues (zero, a, b))
            {
                drawZero (realRootPoint (plane, a), juce::Colour (0xffff7da6), 1.0f);
                drawZero (realRootPoint (plane, b), juce::Colour (0xffff7da6), 0.72f);
            }
        }

        const auto textX = plane.getRight() + 10.0f;
        const auto textWidth = tile.getRight() - textX - 8.0f;
        drawText (g, "POLE  " + rootReadout (pole), textX, tile.getY() + 25.0f, textWidth, 17.0f,
                  juce::Colour (0xff54d3c2), 9.0f);
        drawText (g, "ZERO  " + rootReadout (zero), textX, tile.getY() + 44.0f, textWidth, 17.0f,
                  juce::Colour (0xffff7da6), 9.0f);
        const auto scale = property (stage, "scale");
        drawControl (g, poseScaleBounds (corner), "SCALE  " + stringProperty (scale, "display"),
                     draggingPose == corner && draggingRoot == DragTarget::scale);
        drawControl (g, poseIdentityBounds (corner),
                     static_cast<bool> (property (stage, "identity")) ? "IDENTITY" : "MAKE IDENTITY",
                     static_cast<bool> (property (stage, "identity")));
    }
}

void WorkstationEditor::drawLanguageMenu (juce::Graphics& g)
{
    const auto bounds = languageMenuBounds();
    g.setColour (juce::Colour (0xff091012));
    g.fillRect (bounds);
    g.setColour (juce::Colour (0xff71858a));
    g.drawRect (bounds, 1.0f);
    const auto count = sourceCount (snapshot);
    const auto visible = juce::jmin (kSourceMenuRows, count - sourceMenuOffset);
    for (int rowIndex = 0; rowIndex < visible; ++rowIndex)
    {
        const auto source = sourceMenuOffset + rowIndex;
        const auto row = languageMenuItemBounds (rowIndex);
        const bool active = source == selectedSource;
        g.setColour (active ? juce::Colour (0xff0f7861) : juce::Colour (0xff172226));
        g.fillRect (row);
        drawText (g, indexedSourceName (snapshot, source), row.getX() + 10.0f, row.getY() + 2.0f,
                  row.getWidth() - 20.0f, row.getHeight() - 4.0f,
                  active ? juce::Colour (0xfff3eee5) : juce::Colour (0xffb7c2bf), 10.0f);
        g.setColour (juce::Colour (0xff29383c));
        g.drawHorizontalLine (juce::roundToInt (row.getBottom()), row.getX(), row.getRight());
    }
    drawText (g, juce::String (sourceMenuOffset + 1) + "-" + juce::String (sourceMenuOffset + visible)
              + " / " + juce::String (count) + "  WHEEL TO SCROLL",
              bounds.getX() + 8.0f, bounds.getBottom() - 18.0f, bounds.getWidth() - 16.0f, 15.0f,
              juce::Colour (0xff8da0a0), 8.0f, juce::Justification::right);
}

void WorkstationEditor::drawRecipeMenu (juce::Graphics& g)
{
    const auto bounds = recipeMenuBounds();
    g.setColour (juce::Colour (0xff091012));
    g.fillRect (bounds);
    g.setColour (juce::Colour (0xff71858a));
    g.drawRect (bounds, 1.0f);
    const auto count = recipeCount (snapshot);
    const auto visible = juce::jmin (kRecipeMenuRows, count - recipeMenuOffset);
    for (int rowIndex = 0; rowIndex < visible; ++rowIndex)
    {
        const auto recipe = recipeMenuOffset + rowIndex;
        const auto row = recipeMenuItemBounds (rowIndex);
        const bool active = recipe == selectedRecipe;
        g.setColour (active ? juce::Colour (0xff0f7861) : juce::Colour (0xff172226));
        g.fillRect (row);
        drawText (g, indexedRecipeName (snapshot, recipe), row.getX() + 8.0f, row.getY() + 2.0f,
                  row.getWidth() - 16.0f, row.getHeight() - 4.0f,
                  active ? juce::Colour (0xfff3eee5) : juce::Colour (0xffb7c2bf), 9.0f);
    }
    drawText (g, juce::String (recipeMenuOffset + 1) + "-" + juce::String (recipeMenuOffset + visible)
              + " / " + juce::String (count) + "  STRICT ONLY",
              bounds.getX() + 8.0f, bounds.getBottom() - 18.0f, bounds.getWidth() - 16.0f, 15.0f,
              juce::Colour (0xff8da0a0), 8.0f, juce::Justification::right);
}

void WorkstationEditor::drawResponse (juce::Graphics& g, const juce::Rectangle<float>& bounds)
{
    g.setColour (juce::Colour (0xff172226));
    g.fillRect (bounds);
    g.setColour (juce::Colour (0xff33454a));
    g.drawRect (bounds, 1.0f);

    const auto gap = 10.0f;
    const auto panelWidth = (bounds.getWidth() - gap - 20.0f) * 0.5f;
    const auto stagePanel = juce::Rectangle<float> (bounds.getX() + 5.0f, bounds.getY() + 5.0f,
                                                     panelWidth, bounds.getHeight() - 10.0f);
    const auto bodyPanel = stagePanel.withX (stagePanel.getRight() + gap);
    const auto corners = property (installedScreen, "corners");
    const auto selectedCornerObject = arrayItem (corners, selectedCorner);
    const auto selectedLanes = property (selectedCornerObject, "lanes");
    const auto stageCurve = property (arrayItem (selectedLanes, selectedLane), "response");
    const auto bodyCurve = property (installedScreen, "currentResponse");
    const auto committedCorners = property (property (snapshot, "screen"), "corners");
    const auto committedCorner = arrayItem (committedCorners, selectedCorner);
    const auto committedLanes = property (committedCorner, "lanes");
    const auto committedStageCurve = property (arrayItem (committedLanes, selectedLane), "response");
    const auto committedBodyCurve = property (property (snapshot, "screen"), "currentResponse");

    const auto drawPanel = [this, &g] (
                               const juce::Rectangle<float>& panel,
                               const juce::String& title,
                               const juce::var& curve,
                               const juce::var& beforeCurve,
                               juce::Colour colour)
    {
        g.setColour (juce::Colour (0xff10191b));
        g.fillRect (panel);
        g.setColour (juce::Colour (0xff314247));
        g.drawRect (panel, 1.0f);
        drawText (g, title, panel.getX() + 12.0f, panel.getY() + 7.0f,
                  150.0f, 18.0f, juce::Colour (0xffe9e2d6), 11.0f);

        const auto chart = panel.reduced (42.0f, 28.0f).withTrimmedTop (4.0f);
        const auto toX = [&chart] (double hz)
        {
            const auto bounded = juce::jlimit (static_cast<double> (kMinHz),
                                               static_cast<double> (kMaxHz), hz);
            const auto t = std::log (bounded / kMinHz) / std::log (kMaxHz / kMinHz);
            return chart.getX() + static_cast<float> (t) * chart.getWidth();
        };
        const auto toY = [&chart] (double db)
        {
            return juce::jmap (static_cast<float> (juce::jlimit (
                                   static_cast<double> (kPlotMinDb),
                                   static_cast<double> (kPlotMaxDb), db)),
                               kPlotMinDb, kPlotMaxDb, chart.getBottom(), chart.getY());
        };
        const auto pathFor = [&toX, &toY] (const juce::var& curve)
        {
            juce::Path path;
            const auto points = property (curve, "points");
            for (int index = 0; index < points.size(); ++index)
            {
                const auto point = arrayItem (points, index);
                const auto x = toX (numberProperty (point, "freq_hz"));
                const auto y = toY (numberProperty (point, "db"));
                if (index == 0) path.startNewSubPath (x, y); else path.lineTo (x, y);
            }
            return path;
        };
        for (const auto db : { -36.0, 0.0, 36.0 })
        {
            const auto y = toY (db);
            g.setColour (db == 0.0 ? juce::Colour (0xff596a6f) : juce::Colour (0xff28373b));
            g.drawHorizontalLine (juce::roundToInt (y), chart.getX(), chart.getRight());
            drawText (g, juce::String (static_cast<int> (db)), panel.getX() + 5.0f, y - 7.0f,
                      30.0f, 14.0f, juce::Colour (0xff849697), 8.0f,
                      juce::Justification::right);
        }
        for (const auto hz : { 20.0, 200.0, 2000.0, 16000.0 })
        {
            const auto x = toX (hz);
            g.setColour (juce::Colour (0xff28373b));
            g.drawVerticalLine (juce::roundToInt (x), chart.getY(), chart.getBottom());
            drawText (g, hz >= 1000.0 ? juce::String (hz / 1000.0, 0) + "k"
                                       : juce::String (static_cast<int> (hz)),
                      x - 18.0f, chart.getBottom() + 5.0f, 36.0f, 14.0f,
                      juce::Colour (0xff849697), 8.0f, juce::Justification::centred);
        }

        g.setColour (colour);
        g.strokePath (pathFor (curve), juce::PathStrokeType (2.4f));

        if (previewInstalled)
        {
            g.setColour (juce::Colour (0xffd4d7d0).withAlpha (0.70f));
            g.strokePath (pathFor (beforeCurve), juce::PathStrokeType (1.2f));
            drawText (g, "BEFORE", panel.getRight() - 62.0f, panel.getY() + 7.0f,
                      50.0f, 16.0f, juce::Colour (0xffaeb8b7), 8.0f,
                      juce::Justification::right);
        }
    };

    drawPanel (stagePanel,
               "STAGE " + juce::String (selectedLane + 1) + " / " + kPoseLabels[selectedCorner],
               stageCurve, committedStageCurve, laneColour (selectedLane));
    drawPanel (bodyPanel,
               "BODY / M " + juce::String (juce::roundToInt (morph * 100.0))
                   + " / Q " + juce::String (juce::roundToInt (q * 100.0)),
               bodyCurve, committedBodyCurve, juce::Colour (0xfff2a65a));
}

void WorkstationEditor::drawRightRail (juce::Graphics& g, const juce::Rectangle<float>& bounds)
{
    g.setColour (juce::Colour (0xff172226));
    g.fillRect (bounds);
    g.setColour (juce::Colour (0xff33454a));
    g.drawRect (bounds, 1.0f);
    drawControl (g, railControlBounds (0), "BODY", bodySolo);
    drawControl (g, railControlBounds (1), "PRODUCT", ! bodySolo);
    drawControl (g, railControlBounds (2), "ALL STAGES", ! stageSolo);
    drawControl (g, railControlBounds (3), "THIS STAGE", stageSolo);
    drawControl (g, railControlBounds (4), "KEEP", previewInstalled);
    drawControl (g, railControlBounds (5), "DISCARD", false);
    drawText (g, "STAGES", bounds.getX() + 16.0f, bounds.getY() + 132.0f, 130.0f, 16.0f,
              juce::Colour (0xffe9e2d6), 10.0f);
    drawText (g, "CLICK TO SELECT", bounds.getX() + 148.0f, bounds.getY() + 132.0f, 150.0f, 16.0f,
              juce::Colour (0xff8da0a0), 10.0f, juce::Justification::right);
    for (int lane = 0; lane < 6; ++lane)
    {
        const auto y = bounds.getY() + 153.0f + lane * 28.0f;
        g.setColour (lane == selectedLane ? laneColour (lane) : laneColour (lane).withAlpha (0.42f));
        g.fillRect (bounds.getX() + 16.0f, y, bounds.getWidth() - 32.0f, 24.0f);
        drawText (g, "S" + juce::String (lane + 1), bounds.getX() + 24.0f, y + 4.0f, 32.0f, 15.0f,
                   juce::Colour (0xff102027), 10.0f);
        const auto corners = property (property (snapshot, "screen"), "corners");
        const auto corner = arrayItem (corners, selectedCorner);
        const auto lanes = property (corner, "lanes");
        const auto stage = property (arrayItem (lanes, lane), "stage");
        auto laneLabel = juce::String ("STAGE ") + juce::String (lane + 1)
                         + (static_cast<bool> (property (stage, "identity")) ? "  /  OFF" : "");
        drawText (g, laneLabel, bounds.getX() + 62.0f, y + 4.0f,
                  bounds.getWidth() - 82.0f, 15.0f, juce::Colour (0xff102027), 9.0f);
    }

    const auto selectedStage = property (installedScreen, "selectedStage");
    const auto pole = property (selectedStage, "pole");
    const auto zero = property (selectedStage, "zero");
    const auto scale = property (selectedStage, "scale");
    const auto valueY = bounds.getY() + 370.0f;
    drawText (g, "STAGE " + juce::String (selectedLane + 1) + " / " + kPoseLabels[selectedCorner],
              bounds.getX() + 16.0f, bounds.getY() + 348.0f, bounds.getWidth() - 32.0f, 18.0f,
              juce::Colour (0xffe9e2d6), 11.0f);
    drawText (g, "POLE  " + rootReadout (pole),
              bounds.getX() + 16.0f, valueY, bounds.getWidth() - 32.0f, 17.0f,
              juce::Colour (0xff54d3c2), 10.0f);
    drawText (g, "ZERO  " + rootReadout (zero),
              bounds.getX() + 16.0f, valueY + 18.0f, bounds.getWidth() - 32.0f, 17.0f,
              juce::Colour (0xffff7da6), 10.0f);
    drawText (g, "SCALE  " + stringProperty (scale, "display"), bounds.getX() + 16.0f, valueY + 36.0f,
               bounds.getWidth() - 32.0f, 17.0f, juce::Colour (0xfff2a65a), 10.0f);
    const auto authoredStage = property (property (snapshot, "screen"), "selectedStage");
    const auto evidence = property (authoredStage, "evidence");
    const auto editMode = stringProperty (evidence, "evidenceType") == "clean-room-direct-stage-v1"
                              ? juce::String ("FULL EDIT")
                              : juce::String ("ZEROS ONLY");
    drawText (g, editMode, bounds.getX() + 16.0f, valueY + 58.0f, bounds.getWidth() - 32.0f, 17.0f,
              juce::Colour (0xff91a4a3), 9.0f);
    drawText (g, error.isEmpty() ? status : error, bounds.getX() + 16.0f, bounds.getBottom() - 38.0f,
              bounds.getWidth() - 32.0f, 28.0f, error.isEmpty() ? juce::Colour (0xffaebdb9) : juce::Colour (0xffff8d7d), 9.0f);
}

void WorkstationEditor::drawInspect (juce::Graphics& g, const juce::Rectangle<float>& bounds)
{
    g.setColour (juce::Colour (0xee0a1012));
    g.fillRect (bounds);
    g.setColour (juce::Colour (0xffe9e2d6));
    g.drawRect (bounds, 1.0f);
    drawText (g, "INSPECT / EXACT PACKED-RUNTIME CONSEQUENCE", bounds.getX() + 18.0f, bounds.getY() + 14.0f,
              bounds.getWidth() - 36.0f, 20.0f, juce::Colour (0xffe9e2d6), 13.0f);
    drawText (g, "SELECTED S" + juce::String (selectedLane + 1) + " / ALL FOUR AUTHORED POSES",
              bounds.getX() + 18.0f, bounds.getY() + 40.0f, bounds.getWidth() - 36.0f, 17.0f,
              juce::Colour (0xff8fa2a2), 10.0f);
    const auto corners = property (installedScreen, "corners");
    for (int corner = 0; corner < 4; ++corner)
    {
        const auto lanes = property (arrayItem (corners, corner), "lanes");
        const auto stage = property (arrayItem (lanes, selectedLane), "stage");
        const auto words = property (stage, "packedWords");
        const auto coefficients = property (stage, "runtimeCoefficients");
        juce::String wordLine;
        juce::String coefficientLine;
        for (int i = 0; i < words.size(); ++i)
            wordLine << (i == 0 ? "" : "  ") << juce::String (static_cast<int> (numberAt (words, i)));
        for (int i = 0; i < coefficients.size(); ++i)
            coefficientLine << (i == 0 ? "" : "  ") << juce::String (numberAt (coefficients, i), 6);
        const auto y = bounds.getY() + 66.0f + corner * 38.0f;
        drawText (g, kCornerLabels[corner], bounds.getX() + 18.0f, y, 90.0f, 16.0f,
                  cornerColour (corner), 9.0f);
        drawText (g, wordLine, bounds.getX() + 112.0f, y, 260.0f, 16.0f,
                  juce::Colour (0xffe9e2d6), 9.0f);
        drawText (g, coefficientLine, bounds.getX() + 382.0f, y,
                  bounds.getWidth() - 400.0f, 16.0f, juce::Colour (0xffaebdb9), 9.0f);
        drawText (g, "words 0..4", bounds.getX() + 112.0f, y + 16.0f, 120.0f, 13.0f,
                  juce::Colour (0xff66787c), 7.0f);
        drawText (g, "decoded [b0 b1 b2 a1 a2]", bounds.getX() + 382.0f, y + 16.0f,
                  190.0f, 13.0f, juce::Colour (0xff66787c), 7.0f);
    }

    const auto lastEdit = property (snapshot, "lastEdit");
    auto changed = property (lastEdit, "changed_words");
    if (! changed.isArray() || changed.size() == 0)
        changed = property (property (snapshot, "lastSourceApply"), "changedWords");
    drawText (g, "LAST EXACT CHANGE", bounds.getX() + 18.0f, bounds.getY() + 224.0f, 140.0f, 17.0f,
              juce::Colour (0xfff17c9c), 10.0f);
    if (changed.isArray() && changed.size() > 0)
    {
        juce::String changes;
        for (int i = 0; i < juce::jmin (changed.size(), 12); ++i)
        {
            const auto item = arrayItem (changed, i);
            changes << (i == 0 ? "" : "   ") << "C" << static_cast<int> (numberProperty (item, "corner_index"))
                    << "/S" << static_cast<int> (numberProperty (item, "lane_index") + 1)
                    << "/W" << static_cast<int> (numberProperty (item, "word_index"))
                    << " " << static_cast<int> (numberProperty (item, "before")) << " -> "
                    << static_cast<int> (numberProperty (item, "after"));
        }
        drawText (g, changes, bounds.getX() + 164.0f, bounds.getY() + 220.0f,
                  bounds.getWidth() - 182.0f, 42.0f, juce::Colour (0xffe9e2d6), 9.0f);
    }
    else
        drawText (g, "no applied edit yet", bounds.getX() + 164.0f, bounds.getY() + 224.0f,
                  bounds.getWidth() - 182.0f, 17.0f, juce::Colour (0xff8da0a0), 10.0f);

    const auto audit = property (installedScreen, "audit");
    const auto unstable = property (audit, "unstableMask");
    const auto nonfinite = property (audit, "nonfiniteMask");
    const auto targets = property (lastEdit, "targets");
    const auto target = arrayItem (targets, 0);
    const auto quant = property (target, "quantisation");
    drawText (g, "SAMPLED " + juce::String (static_cast<int> (numberProperty (audit, "morphPoints")))
                  + "x" + juce::String (static_cast<int> (numberProperty (audit, "qPoints")))
                  + "  /  unstable " + juce::String (trueCount (unstable))
                  + "  /  nonfinite " + juce::String (trueCount (nonfinite))
                  + "  /  max pole r " + juce::String (numberProperty (audit, "maximumPoleRadius"), 7)
                  + "  /  quant max " + juce::String (numberProperty (quant, "max_abs"), 8),
              bounds.getX() + 18.0f, bounds.getY() + 270.0f, bounds.getWidth() - 36.0f, 18.0f,
              static_cast<bool> (property (audit, "pass")) ? juce::Colour (0xff53d6ad)
                                                            : juce::Colour (0xffff8d7d), 9.0f);

    const auto chartTop = bounds.getY() + 310.0f;
    const auto gap = 12.0f;
    const auto chartWidth = (bounds.getWidth() - 48.0f - gap) * 0.5f;
    const auto chartHeight = bounds.getBottom() - chartTop - 18.0f;
    const auto stageChart = juce::Rectangle<float> (bounds.getX() + 18.0f, chartTop, chartWidth, chartHeight);
    const auto cascadeChart = juce::Rectangle<float> (stageChart.getRight() + gap, chartTop, chartWidth, chartHeight);
    const auto drawComparison = [this, &g] (const juce::Rectangle<float>& box, const juce::String& title,
                                             const juce::var& pair)
    {
        g.setColour (juce::Colour (0xff10191b));
        g.fillRect (box);
        g.setColour (juce::Colour (0xff33454a));
        g.drawRect (box, 1.0f);
        drawText (g, title, box.getX() + 10.0f, box.getY() + 7.0f, box.getWidth() - 20.0f, 16.0f,
                  juce::Colour (0xffe9e2d6), 9.0f);
        const auto graph = box.reduced (12.0f).withTrimmedTop (20.0f);
        const auto drawCurve = [&g, &graph] (const juce::var& curve, juce::Colour colour, float width)
        {
            const auto points = property (curve, "points");
            juce::Path path;
            for (int i = 0; i < points.size(); ++i)
            {
                const auto point = arrayItem (points, i);
                const auto hz = juce::jlimit (static_cast<double> (kMinHz), static_cast<double> (kMaxHz),
                                              numberProperty (point, "freq_hz", kMinHz));
                const auto x01 = std::log (hz / kMinHz) / std::log (kMaxHz / kMinHz);
                const auto x = graph.getX() + graph.getWidth() * static_cast<float> (x01);
                const auto db = juce::jlimit (static_cast<double> (kPlotMinDb), static_cast<double> (kPlotMaxDb),
                                              numberProperty (point, "db"));
                const auto y = juce::jmap (static_cast<float> (db), kPlotMinDb, kPlotMaxDb,
                                           graph.getBottom(), graph.getY());
                if (i == 0) path.startNewSubPath (x, y); else path.lineTo (x, y);
            }
            g.setColour (colour);
            g.strokePath (path, juce::PathStrokeType (width));
        };
        const auto zeroY = juce::jmap (0.0f, kPlotMinDb, kPlotMaxDb, graph.getBottom(), graph.getY());
        g.setColour (juce::Colour (0xff344448));
        g.drawHorizontalLine (juce::roundToInt (zeroY), graph.getX(), graph.getRight());
        drawCurve (property (pair, "before"), juce::Colour (0xffaeb8b7), 1.6f);
        drawCurve (property (pair, "after"), juce::Colour (0xfff2a65a), 2.1f);
    };
    if (target.isObject())
    {
        drawComparison (stageChart, "SELECTED STAGE / BEFORE + AFTER", property (target, "stageResponse"));
        drawComparison (cascadeChart, "FULL CASCADE / BEFORE + AFTER", property (target, "cascadeResponse"));
    }
    else
    {
        drawComparison (stageChart, "SELECTED STAGE / APPLY AN EDIT", juce::var());
        drawComparison (cascadeChart, "FULL CASCADE / APPLY AN EDIT", juce::var());
    }
}

void WorkstationEditor::drawControl (juce::Graphics& g, const juce::Rectangle<float>& bounds,
                                     const juce::String& label, bool active)
{
    g.setColour (active ? juce::Colour (0xff0f7861) : juce::Colour (0xff202c30));
    g.fillRect (bounds);
    g.setColour (active ? juce::Colour (0xff78c7b5) : juce::Colour (0xff607277));
    g.drawRect (bounds, 1.0f);
    drawText (g, label, bounds.getX() + 4.0f, bounds.getY() + 2.0f,
              bounds.getWidth() - 8.0f, bounds.getHeight() - 4.0f,
              juce::Colour (0xfff3eee5), 10.0f, juce::Justification::centred);
}

void WorkstationEditor::drawSlider (juce::Graphics& g, const juce::Rectangle<float>& bounds,
                                    const juce::String& label, double value)
{
    drawText (g, label, bounds.getX(), bounds.getY() + 3.0f, 58.0f, bounds.getHeight() - 6.0f,
              juce::Colour (0xffe9e2d6), 10.0f);
    const auto track = juce::Rectangle<float> (bounds.getX() + 68.0f, bounds.getCentreY() - 2.0f,
                                                bounds.getWidth() - 136.0f, 4.0f);
    g.setColour (juce::Colour (0xff102027));
    g.fillRect (track);
    const auto amount = static_cast<float> (juce::jlimit (0.0, 1.0, value));
    g.setColour (juce::Colour (0xff3c9fbe));
    g.fillRect (track.withWidth (track.getWidth() * amount));
    const auto knobX = track.getX() + track.getWidth() * amount;
    g.fillRect (knobX - 3.0f, track.getCentreY() - 6.0f, 6.0f, 12.0f);

    const auto valueBox = juce::Rectangle<float> (bounds.getRight() - 58.0f, bounds.getY(), 58.0f, bounds.getHeight());
    g.setColour (juce::Colour (0xff102027));
    g.fillRect (valueBox);
    g.setColour (juce::Colour (0xff71858a));
    g.drawRect (valueBox, 1.0f);
    drawText (g, juce::String (value, 3), valueBox.getX() + 3.0f, valueBox.getY() + 2.0f,
              valueBox.getWidth() - 6.0f, valueBox.getHeight() - 4.0f,
              juce::Colour (0xfff3eee5), 10.0f, juce::Justification::centred);
}

void WorkstationEditor::drawText (juce::Graphics& g, const juce::String& text, float x, float y, float w,
                                  float h, juce::Colour colour, float size, juce::Justification justification)
{
    g.setColour (colour);
    g.setFont (juce::Font (size, juce::Font::plain));
    g.drawFittedText (text, juce::roundToInt (x), juce::roundToInt (y), juce::roundToInt (w), juce::roundToInt (h),
                      justification, 1);
}

juce::Rectangle<float> WorkstationEditor::plotBounds() const
{
    return { 20.0f, 472.0f, static_cast<float> (getWidth()) - 390.0f,
             static_cast<float> (getHeight()) - 564.0f };
}

juce::Rectangle<float> WorkstationEditor::languagePickerBounds() const
{
    return { 20.0f, 82.0f, static_cast<float> (getWidth()) - 390.0f, 380.0f };
}

juce::Rectangle<float> WorkstationEditor::languageSelectorBounds() const
{
    const auto bounds = languagePickerBounds();
    return { bounds.getX() + 170.0f, bounds.getY() + 8.0f, 206.0f, 28.0f };
}

juce::Rectangle<float> WorkstationEditor::endpointBounds (bool high) const
{
    const auto selector = languageSelectorBounds();
    return { selector.getRight() + 6.0f + (high ? 58.0f : 0.0f), selector.getY(), 52.0f, selector.getHeight() };
}

juce::Rectangle<float> WorkstationEditor::sourceSectionBounds() const
{
    const auto high = endpointBounds (true);
    return { high.getRight() + 6.0f, high.getY(), 54.0f, high.getHeight() };
}

juce::Rectangle<float> WorkstationEditor::languageCornerBounds (int corner) const
{
    constexpr float gap = 6.0f;
    const auto available = languagePickerBounds().withTrimmedTop (48.0f).reduced (12.0f, 8.0f);
    const auto width = (available.getWidth() - gap) * 0.5f;
    const auto height = (available.getHeight() - gap) * 0.5f;
    const auto column = corner % 2;
    const auto row = corner / 2;
    return { available.getX() + static_cast<float> (column) * (width + gap),
             available.getY() + static_cast<float> (row) * (height + gap), width, height };
}

juce::Rectangle<float> WorkstationEditor::poseBounds (int corner) const
{
    constexpr float gap = 7.0f;
    const auto available = languagePickerBounds().withTrimmedTop (54.0f).reduced (10.0f, 7.0f);
    const auto width = (available.getWidth() - gap) * 0.5f;
    const auto height = (available.getHeight() - gap) * 0.5f;
    const auto column = corner % 2;
    const auto row = corner / 2;
    return { available.getX() + static_cast<float> (column) * (width + gap),
             available.getY() + static_cast<float> (row) * (height + gap), width, height };
}

juce::Rectangle<float> WorkstationEditor::zPlaneBounds (int corner) const
{
    const auto tile = poseBounds (corner);
    const auto side = juce::jmin (tile.getHeight() - 30.0f, 128.0f);
    return { tile.getX() + 9.0f, tile.getY() + 23.0f, side, side };
}

juce::Rectangle<float> WorkstationEditor::poseScaleBounds (int corner) const
{
    const auto tile = poseBounds (corner);
    const auto plane = zPlaneBounds (corner);
    return { plane.getRight() + 8.0f, tile.getBottom() - 48.0f,
             tile.getRight() - plane.getRight() - 16.0f, 21.0f };
}

juce::Rectangle<float> WorkstationEditor::poseIdentityBounds (int corner) const
{
    const auto scale = poseScaleBounds (corner);
    return { scale.getX(), scale.getBottom() + 4.0f, scale.getWidth(), 20.0f };
}

juce::Rectangle<float> WorkstationEditor::linkAllPosesBounds() const
{
    const auto bounds = languagePickerBounds();
    return { bounds.getRight() - 190.0f, bounds.getY() + 8.0f, 178.0f, 27.0f };
}

juce::Rectangle<float> WorkstationEditor::rootToolBounds (bool pole) const
{
    const auto bounds = languagePickerBounds();
    return { bounds.getRight() - (pole ? 338.0f : 266.0f), bounds.getY() + 8.0f,
             66.0f, 27.0f };
}

juce::Rectangle<float> WorkstationEditor::sourceFillBounds() const
{
    const auto section = sourceSectionBounds();
    return { section.getRight() + 6.0f, section.getY(), 80.0f, section.getHeight() };
}

juce::Rectangle<float> WorkstationEditor::languageMenuBounds() const
{
    const auto selector = languageSelectorBounds();
    const auto visible = juce::jmin (kSourceMenuRows, juce::jmax (0, sourceCount (snapshot) - sourceMenuOffset));
    return { selector.getX(), selector.getBottom(), selector.getWidth(),
             static_cast<float> (visible * 21 + 20) };
}

juce::Rectangle<float> WorkstationEditor::languageMenuItemBounds (int visibleRow) const
{
    const auto menu = languageMenuBounds();
    return { menu.getX() + 1.0f, menu.getY() + 1.0f + static_cast<float> (visibleRow * 21),
             menu.getWidth() - 2.0f, 21.0f };
}

juce::Rectangle<float> WorkstationEditor::recipeSelectorBounds() const
{
    const auto fill = sourceFillBounds();
    return { fill.getRight() + 8.0f, fill.getY(), 126.0f, fill.getHeight() };
}

juce::Rectangle<float> WorkstationEditor::recipeApplyBounds() const
{
    const auto selector = recipeSelectorBounds();
    return { selector.getRight() + 6.0f, selector.getY(), 84.0f, selector.getHeight() };
}

juce::Rectangle<float> WorkstationEditor::recipeMiniPlotBounds() const
{
    const auto apply = recipeApplyBounds();
    const auto right = languagePickerBounds().getRight() - 12.0f;
    return { apply.getRight() + 8.0f, apply.getY(), juce::jmax (72.0f, right - apply.getRight() - 8.0f),
             apply.getHeight() };
}

juce::Rectangle<float> WorkstationEditor::recipeMenuBounds() const
{
    const auto selector = recipeSelectorBounds();
    const auto visible = juce::jmin (kRecipeMenuRows, juce::jmax (0, recipeCount (snapshot) - recipeMenuOffset));
    return { selector.getX(), selector.getBottom(), selector.getWidth() + recipeApplyBounds().getWidth() + 6.0f,
             static_cast<float> (visible * 21 + 20) };
}

juce::Rectangle<float> WorkstationEditor::recipeMenuItemBounds (int visibleRow) const
{
    const auto menu = recipeMenuBounds();
    return { menu.getX() + 1.0f, menu.getY() + 1.0f + static_cast<float> (visibleRow * 21),
             menu.getWidth() - 2.0f, 21.0f };
}

juce::Rectangle<float> WorkstationEditor::headerControlBounds (int control) const
{
    if (control == 8)
        return { static_cast<float> (getWidth()) - 116.0f, 13.0f, 104.0f, 36.0f };
    return { 338.0f + static_cast<float> (control) * 80.0f, 13.0f, 75.0f, 36.0f };
}

juce::Rectangle<float> WorkstationEditor::railControlBounds (int control) const
{
    const auto rail = rightBounds();
    switch (control)
    {
        case 0: return { rail.getX() + 12.0f, rail.getY() + 10.0f, 134.0f, 32.0f };
        case 1: return { rail.getX() + 154.0f, rail.getY() + 10.0f, rail.getWidth() - 166.0f, 32.0f };
        case 2: return { rail.getX() + 12.0f, rail.getY() + 50.0f, 134.0f, 30.0f };
        case 3: return { rail.getX() + 154.0f, rail.getY() + 50.0f, rail.getWidth() - 166.0f, 30.0f };
        case 4: return { rail.getX() + 12.0f, rail.getY() + 88.0f, 134.0f, 30.0f };
        default: return { rail.getX() + 154.0f, rail.getY() + 88.0f, rail.getWidth() - 166.0f, 30.0f };
    }
}

juce::Rectangle<float> WorkstationEditor::fieldControlBounds (int field) const
{
    const auto rail = rightBounds();
    const auto width = (rail.getWidth() - 30.0f) * 0.5f;
    const auto column = field % 2;
    const auto row = field / 2;
    return { rail.getX() + 12.0f + static_cast<float> (column) * (width + 6.0f),
             rail.getY() + 288.0f + static_cast<float> (row) * 30.0f, width, 26.0f };
}

juce::Rectangle<float> WorkstationEditor::sliderBounds (int slider) const
{
    const auto footer = footerBounds();
    return { footer.getX() + 18.0f, footer.getY() + 5.0f + static_cast<float> (slider) * 32.0f,
             370.0f, 24.0f };
}

juce::Rectangle<float> WorkstationEditor::rightBounds() const
{
    return { static_cast<float> (getWidth()) - 350.0f, 82.0f, 330.0f, static_cast<float> (getHeight()) - 174.0f };
}

juce::Rectangle<float> WorkstationEditor::footerBounds() const
{
    return { 20.0f, static_cast<float> (getHeight()) - 82.0f, static_cast<float> (getWidth()) - 40.0f, 62.0f };
}

int WorkstationEditor::laneAtPlotPoint (juce::Point<float> point) const
{
    const auto chart = plotBounds().reduced (52.0f, 54.0f);
    const auto corners = property (installedScreen, "corners");
    const auto lanes = property (arrayItem (corners, selectedCorner), "lanes");
    const auto xT = juce::jlimit (0.0f, 1.0f, (point.x - chart.getX()) / chart.getWidth());
    const auto hz = kMinHz * std::pow (kMaxHz / kMinHz, static_cast<double> (xT));
    const auto targetDb = juce::jmap (point.y, chart.getBottom(), chart.getY(), kPlotMinDb, kPlotMaxDb);
    int bestLane = selectedLane;
    double bestDistance = std::numeric_limits<double>::max();
    for (int lane = 0; lane < lanes.size(); ++lane)
    {
        const auto points = property (property (arrayItem (lanes, lane), "response"), "points");
        for (int i = 1; i < points.size(); ++i)
        {
            const auto a = arrayItem (points, i - 1);
            const auto b = arrayItem (points, i);
            if (numberProperty (a, "freq_hz") <= hz && numberProperty (b, "freq_hz") >= hz)
            {
                const auto t = (hz - numberProperty (a, "freq_hz")) /
                               std::max (1.0, numberProperty (b, "freq_hz") - numberProperty (a, "freq_hz"));
                const auto db = numberProperty (a, "db") + t * (numberProperty (b, "db") - numberProperty (a, "db"));
                const auto distance = std::abs (db - targetDb);
                if (distance < bestDistance) { bestDistance = distance; bestLane = lane; }
                break;
            }
        }
    }
    return bestLane;
}

double WorkstationEditor::frequencyForX (float x) const
{
    const auto chart = plotBounds().reduced (52.0f, 54.0f);
    const auto t = juce::jlimit (0.0f, 1.0f, (x - chart.getX()) / chart.getWidth());
    return kMinHz * std::pow (kMaxHz / kMinHz, static_cast<double> (t));
}

double WorkstationEditor::radiusForY (float y) const
{
    const auto chart = plotBounds().reduced (52.0f, 54.0f);
    return juce::jlimit (0.0, 1.0, 1.0 - static_cast<double> ((y - chart.getY()) / chart.getHeight()));
}

double WorkstationEditor::realRootForY (float y) const
{
    const auto chart = plotBounds().reduced (52.0f, 54.0f);
    return juce::jlimit (-1.0, 1.0,
                         1.0 - 2.0 * static_cast<double> ((y - chart.getY()) / chart.getHeight()));
}

WorkstationEditor::DragTarget WorkstationEditor::dragTargetAt (int corner,
                                                               juce::Point<float> point) const
{
    const auto plane = zPlaneBounds (corner);
    if (! plane.expanded (18.0f).contains (point))
        return DragTarget::none;
    const auto corners = property (installedScreen, "corners");
    const auto lanes = property (arrayItem (corners, corner), "lanes");
    const auto stage = property (arrayItem (lanes, selectedLane), "stage");
    const auto root = property (stage, poleTool ? "pole" : "zero");
    double hz = 0.0, radius = 0.0;
    if (conjugateValues (root, hz, radius))
        return poleTool ? DragTarget::conjugatePole : DragTarget::conjugateZero;
    double a = 0.0, b = 0.0;
    if (realValues (root, a, b))
    {
        const auto distanceA = point.getDistanceFrom (realRootPoint (plane, a));
        const auto distanceB = point.getDistanceFrom (realRootPoint (plane, b));
        if (poleTool)
            return distanceA <= distanceB ? DragTarget::poleRootA : DragTarget::poleRootB;
        return distanceA <= distanceB ? DragTarget::zeroRootA : DragTarget::zeroRootB;
    }
    return poleTool ? DragTarget::conjugatePole : DragTarget::conjugateZero;
}

void WorkstationEditor::editRootFromPose (int corner, DragTarget target,
                                          juce::Point<float> point)
{
    const auto plane = zPlaneBounds (corner);
    const auto diskRadius = plane.getWidth() * 0.5;
    auto x = static_cast<double> (point.x - plane.getCentreX()) / diskRadius;
    auto y = std::abs (static_cast<double> (plane.getCentreY() - point.y) / diskRadius);
    const auto radius = std::sqrt (x * x + y * y);
    if (radius > 1.0)
    {
        x /= radius;
        y /= radius;
    }
    const auto storedRadius = juce::jlimit (0.0, 1.0, std::sqrt (x * x + y * y));
    const auto angle = juce::jlimit (0.0, juce::MathConstants<double>::pi, std::atan2 (y, x));
    const auto hz = angle / juce::MathConstants<double>::twoPi * kStageSampleRate;
    if (target == DragTarget::conjugatePole || target == DragTarget::conjugateZero)
        liveRoot = LiveRoot { corner, target == DragTarget::conjugatePole, hz, storedRadius };
    switch (target)
    {
        case DragTarget::conjugatePole: previewConjugateRoot (true, hz, storedRadius); break;
        case DragTarget::conjugateZero: previewConjugateRoot (false, hz, storedRadius); break;
        case DragTarget::poleRootA:
            editField = EditField::poleRootA;
            previewValue (juce::jlimit (-1.0, 1.0, x));
            break;
        case DragTarget::poleRootB:
            editField = EditField::poleRootB;
            previewValue (juce::jlimit (-1.0, 1.0, x));
            break;
        case DragTarget::zeroRootA:
            editField = EditField::zeroRootA;
            previewValue (juce::jlimit (-1.0, 1.0, x));
            break;
        case DragTarget::zeroRootB:
            editField = EditField::zeroRootB;
            previewValue (juce::jlimit (-1.0, 1.0, x));
            break;
        default: break;
    }
}

double WorkstationEditor::selectedFieldValue (int corner, DragTarget target) const
{
    const auto corners = property (installedScreen, "corners");
    const auto lanes = property (arrayItem (corners, corner), "lanes");
    const auto stage = property (arrayItem (lanes, selectedLane), "stage");
    if (target == DragTarget::scale)
        return numberProperty (property (stage, "scale"), "value", 1.0);
    return 0.0;
}

void WorkstationEditor::editFromPlot (juce::Point<float> point)
{
    if (! plotBounds().contains (point))
        return;
    double value = 0.0;
    switch (editField)
    {
        case EditField::zeroHz: value = frequencyForX (point.x); break;
        case EditField::zeroRadius: value = radiusForY (point.y); break;
        case EditField::zeroRootA:
        case EditField::zeroRootB: value = realRootForY (point.y); break;
        default: return;
    }
    previewValue (value);
}

void WorkstationEditor::mouseDown (const juce::MouseEvent& event)
{
    const auto point = event.position;
    if (recipeMenuOpen)
    {
        const auto visible = juce::jmin (kRecipeMenuRows, recipeCount (snapshot) - recipeMenuOffset);
        for (int row = 0; row < visible; ++row)
        {
            if (recipeMenuItemBounds (row).contains (point))
            {
                selectRecipe (recipeMenuOffset + row);
                return;
            }
        }
        recipeMenuOpen = false;
        repaint();
        return;
    }
    if (languageMenuOpen)
    {
        const auto visible = juce::jmin (kSourceMenuRows, sourceCount (snapshot) - sourceMenuOffset);
        for (int row = 0; row < visible; ++row)
        {
            if (languageMenuItemBounds (row).contains (point))
            {
                selectSource (sourceMenuOffset + row);
                return;
            }
        }
        languageMenuOpen = false;
        repaint();
        return;
    }
    if (evidenceOpen && languageSelectorBounds().contains (point))
    {
        languageMenuOpen = true;
        recipeMenuOpen = false;
        sourceMenuOffset = juce::jlimit (0, juce::jmax (0, sourceCount (snapshot) - kSourceMenuRows),
                                         selectedSource - kSourceMenuRows / 2);
        repaint();
        return;
    }
    if (evidenceOpen && recipeSelectorBounds().contains (point))
    {
        recipeMenuOpen = true;
        languageMenuOpen = false;
        recipeMenuOffset = juce::jlimit (0, juce::jmax (0, recipeCount (snapshot) - kRecipeMenuRows),
                                         selectedRecipe - kRecipeMenuRows / 2);
        repaint();
        return;
    }
    if (evidenceOpen && recipeApplyBounds().contains (point))
    {
        applyRecipe();
        return;
    }
    if (evidenceOpen && sourceFillBounds().contains (point))
    {
        fillCornerFromSource();
        return;
    }
    if (evidenceOpen && (endpointBounds (false).contains (point) || endpointBounds (true).contains (point)))
    {
        sourceHigh = endpointBounds (true).contains (point);
        status = sourceHigh ? "HIGH ENDPOINT SELECTED / 0 WORDS CHANGED" : "LOW ENDPOINT SELECTED / 0 WORDS CHANGED";
        repaint();
        return;
    }
    if (evidenceOpen && sourceSectionBounds().contains (point))
    {
        sourceSection = (sourceSection + 1) % 6;
        status = "DONOR SECTION S" + juce::String (sourceSection + 1) + " / 0 WORDS CHANGED";
        repaint();
        return;
    }
    if (evidenceOpen)
    {
        for (int corner = 0; corner < 4; ++corner)
        {
            if (languageCornerBounds (corner).contains (point))
            {
                selectCorner (corner);
                return;
            }
        }
    }

    for (int control = 0; control < kHeaderActionCount; ++control)
    {
        if (! headerControlBounds (control).contains (point))
            continue;

        switch (control)
        {
            case 0: newFilter(); break;
            case 1: openSession(); break;
            case 2: chooseActorRecording(); break;
            case 3:
                evidenceOpen = ! evidenceOpen;
                inspectOpen = false;
                languageMenuOpen = false;
                recipeMenuOpen = false;
                status = evidenceOpen ? "SOURCE WELL / STUDY ONLY" : "DIRECT STAGE AUTHORING";
                repaint();
                break;
            case 4: saveSession(); break;
            case 5: promoteBody(); break;
            case 6:
                if (authoring->undo())
                {
                    previewInstalled = false;
                    status = "UNDID EDIT";
                    installBody (false);
                }
                else showError (authoring->lastError());
                break;
            case 7:
                if (authoring->redo())
                {
                    previewInstalled = false;
                    status = "REDID EDIT";
                    installBody (false);
                }
                else showError (authoring->lastError());
                break;
            default:
                inspectOpen = ! inspectOpen;
                if (inspectOpen)
                    evidenceOpen = false;
                repaint();
                break;
        }
        return;
    }

    if (! evidenceOpen && (rootToolBounds (true).contains (point)
                            || rootToolBounds (false).contains (point)))
    {
        poleTool = rootToolBounds (true).contains (point);
        status = poleTool ? "POLE TOOL / DRAG IN ANY POSE" : "ZERO TOOL / DRAG IN ANY POSE";
        repaint();
        return;
    }

    if (! evidenceOpen && linkAllPosesBounds().contains (point))
    {
        linkAllPoses = ! linkAllPoses;
        status = linkAllPoses ? "ALL POSES / RELATIVE ROOT MOVE" : "ONE POSE";
        repaint();
        return;
    }

    if (! evidenceOpen)
    {
        for (int corner = 0; corner < 4; ++corner)
        {
            if (poseIdentityBounds (corner).contains (point))
            {
                selectCorner (corner);
                editField = EditField::identity;
                previewValue (1.0);
                return;
            }
            if (poseScaleBounds (corner).contains (point))
            {
                selectCorner (corner);
                draggingPose = corner;
                draggingRoot = DragTarget::scale;
                dragStartValue = selectedFieldValue (corner, DragTarget::scale);
                dragStartX = point.x;
                return;
            }
            if (poseBounds (corner).contains (point))
            {
                selectCorner (corner);
                const auto target = dragTargetAt (corner, point);
                if (target != DragTarget::none)
                {
                    draggingPose = corner;
                    draggingRoot = target;
                    const auto corners = property (installedScreen, "corners");
                    const auto lanes = property (arrayItem (corners, corner), "lanes");
                    const auto stage = property (arrayItem (lanes, selectedLane), "stage");
                    const auto root = property (
                        stage, target == DragTarget::conjugatePole ? "pole" : "zero");
                    if (! conjugateValues (root, dragStartHz, dragStartRadius))
                    {
                        dragStartHz = 0.0;
                        dragStartRadius = 0.0;
                    }
                    editRootFromPose (corner, target, point);
                }
                return;
            }
        }
    }

    for (int control = 0; control < 6; ++control)
    {
        if (! railControlBounds (control).contains (point))
            continue;
        switch (control)
        {
            case 0: setAudioMode (true); break;
            case 1: setAudioMode (false); break;
            case 2: setStageAudition (false); break;
            case 3: setStageAudition (true); break;
            case 4: applyPreview(); break;
            default: discardPreview(); break;
        }
        return;
    }

    for (int slider = 0; slider < 2; ++slider)
    {
        const auto bounds = sliderBounds (slider);
        if (bounds.contains (point))
        {
            const auto track = juce::Rectangle<float> (bounds.getX() + 68.0f, bounds.getY(),
                                                        bounds.getWidth() - 136.0f, bounds.getHeight());
            const auto value = juce::jlimit (0.0, 1.0,
                                             static_cast<double> ((point.x - track.getX()) / track.getWidth()));
            draggingSlider = slider;
            if (slider == 0) setMorph (value); else setQ (value);
            return;
        }
    }

    const auto rail = rightBounds();
    for (int lane = 0; lane < 6; ++lane)
    {
        const auto y = rail.getY() + 153.0f + lane * 28.0f;
        if (juce::Rectangle<float> (rail.getX() + 12.0f, y - 2.0f, rail.getWidth() - 24.0f, 28.0f).contains (point))
        {
            selectLane (lane);
            return;
        }
    }
}

void WorkstationEditor::mouseDrag (const juce::MouseEvent& event)
{
    if (draggingRoot != DragTarget::none && draggingPose >= 0)
    {
        if (draggingRoot == DragTarget::scale)
        {
            const auto fine = event.mods.isShiftDown() ? 0.25 : 1.0;
            const auto octaves = static_cast<double> (event.position.x - dragStartX) / 140.0 * fine;
            editField = EditField::scale;
            previewValue (juce::jlimit (0.0, 4.0, dragStartValue * std::pow (2.0, octaves)));
        }
        else
            editRootFromPose (draggingPose, draggingRoot, event.position);
        return;
    }
    if (draggingSlider >= 0)
    {
        const auto bounds = sliderBounds (draggingSlider);
        const auto track = juce::Rectangle<float> (bounds.getX() + 68.0f, bounds.getY(),
                                                    bounds.getWidth() - 136.0f, bounds.getHeight());
        const auto value = juce::jlimit (0.0, 1.0,
                                         static_cast<double> ((event.position.x - track.getX()) / track.getWidth()));
        if (draggingSlider == 0) setMorph (value); else setQ (value);
        return;
    }
    if (draggingPlot)
        editFromPlot (event.position);
}

void WorkstationEditor::mouseUp (const juce::MouseEvent&)
{
    performQueuedPreview();
    draggingPlot = false;
    draggingRoot = DragTarget::none;
    draggingPose = -1;
    draggingSlider = -1;
    if (screenRefreshQueued)
    {
        screenRefreshQueued = false;
        screenRefreshTicks = 0;
        updateInstalledScreen();
        repaint();
    }
    liveRoot.reset();
    stopTimer();
}

void WorkstationEditor::mouseWheelMove (const juce::MouseEvent& event,
                                        const juce::MouseWheelDetails& wheel)
{
    if (! evidenceOpen)
    {
        const auto corners = property (installedScreen, "corners");
        for (int corner = 0; corner < 4; ++corner)
        {
            if (poseScaleBounds (corner).contains (event.position))
            {
                selectCorner (corner);
                const auto current = selectedFieldValue (corner, DragTarget::scale);
                editField = EditField::scale;
                previewValue (juce::jlimit (0.0, 4.0,
                                            current * std::pow (2.0, wheel.deltaY * 0.08)));
                return;
            }
            if (! zPlaneBounds (corner).contains (event.position))
                continue;
            selectCorner (corner);
            const auto lanes = property (arrayItem (corners, corner), "lanes");
            const auto stage = property (arrayItem (lanes, selectedLane), "stage");
            const auto root = property (stage, poleTool ? "pole" : "zero");
            double hz = 0.0, radius = 0.0;
            if (conjugateValues (root, hz, radius))
                previewConjugateRoot (poleTool, hz,
                                      juce::jlimit (0.0, 1.0, radius + wheel.deltaY * 0.025));
            return;
        }
    }
    if (recipeMenuOpen && recipeMenuBounds().contains (event.position))
    {
        const auto direction = wheel.deltaY < 0.0f ? 3 : -3;
        recipeMenuOffset = juce::jlimit (0, juce::jmax (0, recipeCount (snapshot) - kRecipeMenuRows),
                                         recipeMenuOffset + direction);
        repaint();
        return;
    }
    if (! languageMenuOpen || ! languageMenuBounds().contains (event.position))
        return;
    const auto direction = wheel.deltaY < 0.0f ? 3 : -3;
    sourceMenuOffset = juce::jlimit (0, juce::jmax (0, sourceCount (snapshot) - kSourceMenuRows),
                                     sourceMenuOffset + direction);
    repaint();
}

void WorkstationEditor::updateParameter (const char* id, float value)
{
    if (auto* parameter = processor.apvts.getParameter (id))
        parameter->setValueNotifyingHost (parameter->convertTo0to1 (value));
}
