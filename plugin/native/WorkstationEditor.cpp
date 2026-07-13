#include "WorkstationEditor.h"

#include "parameters/TrenchParameters.h"

#include <juce_core/juce_core.h>

#include <algorithm>
#include <cmath>
#include <cstring>
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
    size_t workstation_state_cartridge_json (WorkstationState*, unsigned char*, size_t);
    int workstation_state_current_body (WorkstationState*, unsigned char*, size_t);
    int workstation_state_pending_body (WorkstationState*, unsigned char*, size_t);
    int workstation_state_select (WorkstationState*, size_t corner, size_t lane);
    int workstation_state_new_filter (WorkstationState*);
    int workstation_state_make_filter (WorkstationState*);
    int workstation_state_preview_field (WorkstationState*, int field, double value, int allCorners);
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
constexpr const char* kCornerLabels[] = { "M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100" };

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
        const auto text = read ([this] (unsigned char* out, size_t size) {
            return workstation_state_last_error (state, out, size);
        });
        return juce::String::fromUTF8 (reinterpret_cast<const char*> (text.data()), static_cast<int> (text.size()));
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

    bool newFilter() { return workstation_state_new_filter (state) == 0; }
    bool makeFilter() { return workstation_state_make_filter (state) == 0; }
    bool preview (int field, double value, bool allCorners)
    {
        return workstation_state_preview_field (state, field, value, allCorners ? 1 : 0) == 0;
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
    std::vector<unsigned char> read (Function&& function)
    {
        const auto size = function (nullptr, 0);
        if (size == kFfiError)
            return {};
        std::vector<unsigned char> data (size);
        if (size != 0 && function (data.data(), data.size()) == kFfiError)
            return {};
        return data;
    }

    template <typename Function>
    juce::String text (Function&& function)
    {
        const auto data = read (std::forward<Function> (function));
        return data.empty() ? juce::String() : juce::String::fromUTF8 (reinterpret_cast<const char*> (data.data()), static_cast<int> (data.size()));
    }

    WorkstationState* state = nullptr;
    juce::File root;
};

WorkstationEditor::WorkstationEditor (PluginProcessor& p)
    : processor (p),
      authoring (std::make_unique<AuthoringBridge> (juce::File (TRENCH_WORKSTATION_REPO_ROOT)))
{
    setOpaque (true);

    for (auto* button : { &newFilterButton, &makeButton, &saveButton, &promoteButton,
                          &undoButton, &redoButton, &applyButton, &cancelButton,
                          &inspectButton, &bodySoloButton, &productButton,
                          &allCornersButton })
    {
        addAndMakeVisible (*button);
        button->setColour (juce::TextButton::buttonColourId, juce::Colour (0xff27343a));
        button->setColour (juce::TextButton::textColourOffId, juce::Colour (0xfff3eee5));
        button->setColour (juce::TextButton::buttonOnColourId, juce::Colour (0xff0f7861));
    }
    for (auto& button : fieldButtons)
    {
        addAndMakeVisible (button);
        button.setColour (juce::TextButton::buttonColourId, juce::Colour (0xff27343a));
        button.setColour (juce::TextButton::textColourOffId, juce::Colour (0xfff3eee5));
        button.setColour (juce::TextButton::buttonOnColourId, juce::Colour (0xff0f7861));
    }
    fieldButtons[0].setButtonText ("POLE / HZ");
    fieldButtons[1].setButtonText ("POLE / RADIUS");
    fieldButtons[2].setButtonText ("ZERO / HZ");
    fieldButtons[3].setButtonText ("ZERO / RADIUS");
    fieldButtons[4].setButtonText ("SCALE");

    newFilterButton.onClick = [this] { newFilter(); };
    makeButton.onClick = [this] { makeFilter(); };
    saveButton.onClick = [this] { saveSession(); };
    promoteButton.onClick = [this] { promoteBody(); };
    undoButton.onClick = [this]
    {
        if (authoring->undo())
        {
            previewInstalled = false;
            installBody (false);
            refresh (false);
            status = "undid edit";
        }
        else showError (authoring->lastError());
    };
    redoButton.onClick = [this]
    {
        if (authoring->redo())
        {
            previewInstalled = false;
            installBody (false);
            refresh (false);
            status = "redid edit";
        }
        else showError (authoring->lastError());
    };
    applyButton.onClick = [this] { applyPreview(); };
    cancelButton.onClick = [this] { discardPreview(); };
    inspectButton.onClick = [this]
    {
        inspectOpen = ! inspectOpen;
        inspectButton.setButtonText (inspectOpen ? "CLOSE INSPECT" : "INSPECT");
        resized();
        repaint();
    };
    bodySoloButton.onClick = [this] { setAudioMode (true); };
    productButton.onClick = [this] { setAudioMode (false); };
    allCornersButton.onClick = [this]
    {
        allCorners = ! allCorners;
        allCornersButton.setButtonText (allCorners ? "ALL 4 POSES" : "ONE POSE");
        repaint();
    };

    for (int i = 0; i < 5; ++i)
    {
        fieldButtons[i].onClick = [this, i] { chooseField (static_cast<EditField> (i)); };
    }
    chooseField (editField);

    morphSlider.setSliderStyle (juce::Slider::LinearHorizontal);
    morphSlider.setTextBoxStyle (juce::Slider::TextBoxRight, false, 64, 22);
    morphSlider.setRange (0.0, 1.0, 0.001);
    morphSlider.setValue (morph, juce::dontSendNotification);
    morphSlider.onValueChange = [this] { setMorph (morphSlider.getValue()); };
    addAndMakeVisible (morphSlider);

    qSlider.setSliderStyle (juce::Slider::LinearHorizontal);
    qSlider.setTextBoxStyle (juce::Slider::TextBoxRight, false, 64, 22);
    qSlider.setRange (0.0, 1.0, 0.001);
    qSlider.setValue (q, juce::dontSendNotification);
    qSlider.onValueChange = [this] { setQ (qSlider.getValue()); };
    addAndMakeVisible (qSlider);

    if (! authoring->valid())
        showError ("authoring library failed to open");
    else if (authoring->newFilter())
    {
        installBody (false);
        refresh (false);
        status = "new filter: drag the plot or press MAKE";
    }
    else
        showError (authoring->lastError());

    processor.setWorkstationBodySolo (true);
    startTimerHz (12);
}

WorkstationEditor::~WorkstationEditor()
{
    stopTimer();
}

void WorkstationEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colour (0xff101719));
    g.setColour (juce::Colour (0xffe9e2d6));
    g.fillRect (0, 0, getWidth(), 64);
    drawText (g, "TRENCH", 24.0f, 14.0f, 150.0f, 26.0f, juce::Colour (0xff102027), 23.0f, juce::Justification::left);
    drawText (g, "FILTER MAKER", 176.0f, 21.0f, 150.0f, 18.0f, juce::Colour (0xff0f7861), 11.0f);
    drawText (g, bodySolo ? "BODY PATH" : "PRODUCT PATH", getWidth() - 250.0f, 21.0f, 220.0f, 18.0f,
              bodySolo ? juce::Colour (0xff0f7861) : juce::Colour (0xffaa5b2a), 11.0f,
              juce::Justification::right);

    const auto plot = plotBounds();
    const auto rail = rightBounds();
    const auto footer = footerBounds();
    drawResponse (g, plot);
    drawRightRail (g, rail);

    g.setColour (juce::Colour (0xff213136));
    g.fillRect (footer);
    drawText (g, "MORPH", footer.getX() + 18.0f, footer.getY() + 9.0f, 72.0f, 18.0f, juce::Colour (0xffe9e2d6), 11.0f);
    drawText (g, "Q", footer.getX() + 18.0f, footer.getY() + 43.0f, 72.0f, 18.0f, juce::Colour (0xffe9e2d6), 11.0f);
    drawText (g, "drag the response to author the selected field · click a trace to select its lane",
              footer.getX() + 520.0f, footer.getY() + 25.0f, footer.getWidth() - 540.0f, 22.0f,
              juce::Colour (0xffaebdb9), 11.0f, juce::Justification::right);

    if (inspectOpen)
        drawInspect (g, juce::Rectangle<float> (plot.getX() + 24.0f, plot.getY() + 28.0f,
                                                plot.getWidth() - 48.0f, plot.getHeight() - 56.0f));
}

void WorkstationEditor::resized()
{
    const int top = 13;
    int x = 344;
    const int gap = 6;
    const int width = 92;
    for (auto* button : { &newFilterButton, &makeButton, &saveButton, &promoteButton,
                          &undoButton, &redoButton })
    {
        button->setBounds (x, top, width, 36);
        x += width + gap;
    }
    inspectButton.setBounds (getWidth() - 116, top, 104, 36);

    const auto rail = rightBounds().toNearestInt();
    int y = rail.getY() + 10;
    bodySoloButton.setBounds (rail.getX() + 12, y, 134, 32);
    productButton.setBounds (rail.getX() + 154, y, rail.getWidth() - 166, 32);
    y += 48;
    allCornersButton.setBounds (rail.getX() + 12, y, rail.getWidth() - 24, 30);
    y += 38;
    applyButton.setBounds (rail.getX() + 12, y, 98, 30);
    cancelButton.setBounds (rail.getX() + 116, y, 98, 30);
    const int fieldTop = rail.getY() + 370;
    const int fieldWidth = (rail.getWidth() - 30) / 2;
    for (int i = 0; i < 5; ++i)
    {
        const int column = i % 2;
        const int row = i / 2;
        fieldButtons[i].setBounds (rail.getX() + 12 + column * (fieldWidth + 6),
                                   fieldTop + row * 30, fieldWidth, 26);
    }

    const auto footer = footerBounds().toNearestInt();
    morphSlider.setBounds (footer.getX() + 78, footer.getY() + 7, 300, 24);
    qSlider.setBounds (footer.getX() + 78, footer.getY() + 41, 300, 24);
}

void WorkstationEditor::timerCallback()
{
    refresh (false);
}

void WorkstationEditor::refresh (bool installPending)
{
    if (! authoring->valid())
        return;

    std::array<unsigned char, 240> body {};
    const bool gotBody = installPending ? authoring->pendingBody (body) :
                                          processor.copyCurrentBodyBytes (body.data(), body.size());
    if (gotBody)
    {
        installedBody = body;
        if (installPending && previewInstalled)
            processor.installBodyBytes (installedBody.data(), installedBody.size());
        processor.probeCurrentBodyForUi (static_cast<float> (morph), static_cast<float> (q),
                                         installedCoefficients.data(), installedBoost);
        juce::String screenJson;
        if (authoring->screenForBody (installedBody, screenJson))
            installedScreen = juce::JSON::parse (screenJson);
    }
    const auto snapshotJson = authoring->snapshot();
    if (! snapshotJson.isEmpty())
        snapshot = juce::JSON::parse (snapshotJson);
    repaint();
}

void WorkstationEditor::installBody (bool pending)
{
    std::array<unsigned char, 240> body {};
    const bool ok = pending ? authoring->pendingBody (body) : authoring->currentBody (body);
    if (! ok || ! processor.installBodyBytes (body.data(), body.size()))
    {
        showError (authoring->lastError().isNotEmpty() ? authoring->lastError() : "processor rejected body bytes");
        return;
    }
    installedBody = body;
    previewInstalled = pending;
    processor.probeCurrentBodyForUi (static_cast<float> (morph), static_cast<float> (q),
                                     installedCoefficients.data(), installedBoost);
    juce::String screenJson;
    if (authoring->screenForBody (installedBody, screenJson))
        installedScreen = juce::JSON::parse (screenJson);
    repaint();
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
        refresh (false);
    }
    else showError (authoring->lastError());
}

void WorkstationEditor::selectLane (int lane)
{
    if (authoring->select (selectedCorner, lane))
    {
        selectedLane = lane;
        refresh (false);
    }
    else showError (authoring->lastError());
}

void WorkstationEditor::chooseField (EditField field)
{
    editField = field;
    for (int i = 0; i < 5; ++i)
        fieldButtons[i].setToggleState (i == static_cast<int> (editField), juce::dontSendNotification);
    repaint();
}

void WorkstationEditor::previewValue (double value)
{
    if (! authoring->preview (static_cast<int> (editField), value, allCorners))
    {
        showError (authoring->lastError());
        return;
    }
    error.clear();
    previewInstalled = true;
    installBody (true);
    status = "preview · APPLY keeps the edit";
    refresh (false);
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
        installBody (false);
        refresh (false);
        status = "edit kept in the source session";
        error.clear();
    }
    else showError (authoring->lastError());
}

void WorkstationEditor::discardPreview()
{
    if (authoring->discardPreview())
    {
        previewInstalled = false;
        installBody (false);
        refresh (false);
        status = "preview discarded";
        error.clear();
    }
    else showError (authoring->lastError());
}

void WorkstationEditor::makeFilter()
{
    if (authoring->makeFilter())
    {
        previewInstalled = false;
        installBody (false);
        refresh (false);
        status = "starter filter made through the canonical edit path";
        error.clear();
    }
    else showError (authoring->lastError());
}

void WorkstationEditor::newFilter()
{
    if (authoring->newFilter())
    {
        previewInstalled = false;
        installBody (false);
        refresh (false);
        status = "new identity filter · choose a field and drag";
        error.clear();
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
    status = "saved source session: " + name + ".session.json";
    error.clear();
    repaint();
}

void WorkstationEditor::promoteBody()
{
    if (! authoring->validate())
    {
        showError (authoring->lastError());
        return;
    }
    const auto name = safeFileStem (stringProperty (property (snapshot, "screen"), "name"));
    const auto directory = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                               .getChildFile ("TRENCH").getChildFile ("bodies");
    if (! directory.createDirectory().wasOk())
    {
        showError ("could not create the TRENCH body bank");
        return;
    }
    const auto bodyFile = directory.getChildFile (name + ".body240");
    const auto cartridgeFile = directory.getChildFile (name + ".cart.json");
    if (! bodyFile.replaceWithData (installedBody.data(), installedBody.size())
        || ! cartridgeFile.replaceWithText (authoring->cartridge()))
    {
        showError ("could not promote body and cartridge");
        return;
    }
    status = "PROMOTED " + name + " · exact 240-byte body + cartridge · reopen TRENCH to select it";
    error.clear();
    repaint();
}

void WorkstationEditor::setAudioMode (bool solo)
{
    bodySolo = solo;
    processor.setWorkstationBodySolo (bodySolo);
    status = bodySolo ? "BODY SOLO · packed six-stage body at unity" : "PRODUCT · complete PluginProcessor path";
    repaint();
}

void WorkstationEditor::setMorph (double value)
{
    morph = juce::jlimit (0.0, 1.0, value);
    if (! authoring->setMorphQ (morph, q))
        showError (authoring->lastError());
    updateParameter (ParamID::morph, static_cast<float> (morph));
    refresh (false);
}

void WorkstationEditor::setQ (double value)
{
    q = juce::jlimit (0.0, 1.0, value);
    if (! authoring->setMorphQ (morph, q))
        showError (authoring->lastError());
    updateParameter (ParamID::q, static_cast<float> (q));
    refresh (false);
}

void WorkstationEditor::drawResponse (juce::Graphics& g, const juce::Rectangle<float>& bounds)
{
    g.setColour (juce::Colour (0xff172226));
    g.fillRoundedRectangle (bounds, 4.0f);
    g.setColour (juce::Colour (0xff33454a));
    g.drawRoundedRectangle (bounds, 4.0f, 1.0f);

    const auto chart = bounds.reduced (52.0f, 54.0f);
    const auto toX = [&chart] (double hz)
    {
        const auto t = std::log (juce::jlimit (static_cast<double> (kMinHz), static_cast<double> (kMaxHz), hz) / kMinHz)
                       / std::log (kMaxHz / kMinHz);
        return chart.getX() + static_cast<float> (t) * chart.getWidth();
    };
    const auto toY = [&chart] (double db)
    {
        const auto t = (juce::jlimit (static_cast<double> (kPlotMinDb), static_cast<double> (kPlotMaxDb), db) - kPlotMaxDb)
                       / (kPlotMinDb - kPlotMaxDb);
        return chart.getY() + static_cast<float> (t) * chart.getHeight();
    };

    g.setFont (11.0f);
    for (const auto db : { -36.0, -18.0, 0.0, 18.0, 36.0 })
    {
        const auto y = toY (db);
        g.setColour (db == 0.0 ? juce::Colour (0xff607277) : juce::Colour (0xff2a393e));
        g.drawHorizontalLine (juce::roundToInt (y), chart.getX(), chart.getRight());
        drawText (g, juce::String (static_cast<int> (db)) + " dB", bounds.getX() + 8.0f, y - 8.0f,
                  42.0f, 16.0f, juce::Colour (0xff91a3a4), 10.0f, juce::Justification::right);
    }
    for (const auto hz : { 20.0, 200.0, 2000.0, 16000.0 })
    {
        const auto x = toX (hz);
        g.setColour (juce::Colour (0xff2a393e));
        g.drawVerticalLine (juce::roundToInt (x), chart.getY(), chart.getBottom());
        drawText (g, hz >= 1000.0 ? juce::String (hz / 1000.0, 1) + "k" : juce::String (static_cast<int> (hz)),
                  x - 24.0f, chart.getBottom() + 8.0f, 48.0f, 16.0f, juce::Colour (0xff91a3a4), 10.0f,
                  juce::Justification::centred);
    }

    drawText (g, "PACKED RUNTIME RESPONSE", bounds.getX() + 18.0f, bounds.getY() + 15.0f,
              250.0f, 22.0f, juce::Colour (0xffe9e2d6), 14.0f);
    drawText (g, "four poses · six corresponding lanes · no normalization", bounds.getX() + 18.0f,
              bounds.getY() + 37.0f, 390.0f, 16.0f, juce::Colour (0xff8da0a0), 10.0f);

    const auto screen = installedScreen;
    const auto corners = property (screen, "corners");
    for (int corner = 0; corner < 4; ++corner)
    {
        const auto cornerObject = arrayItem (corners, corner);
        const auto curve = property (cornerObject, "response");
        const auto points = property (curve, "points");
        juce::Path path;
        bool started = false;
        for (int i = 0; i < points.size(); ++i)
        {
            const auto point = arrayItem (points, i);
            const auto x = toX (numberProperty (point, "freq_hz"));
            const auto y = toY (numberProperty (point, "db"));
            if (! started) { path.startNewSubPath (x, y); started = true; }
            else path.lineTo (x, y);
        }
        g.setColour (corner == selectedCorner ? juce::Colour (0xffd4d7c3).withAlpha (0.8f)
                                               : juce::Colour (0xff829194).withAlpha (0.3f));
        g.strokePath (path, juce::PathStrokeType (corner == selectedCorner ? 2.0f : 1.0f));
    }

    const auto selectedCornerObject = arrayItem (corners, selectedCorner);
    const auto selectedLanes = property (selectedCornerObject, "lanes");
    for (int lane = 0; lane < 6; ++lane)
    {
        const auto laneObject = arrayItem (selectedLanes, lane);
        const auto points = property (property (laneObject, "response"), "points");
        juce::Path path;
        bool started = false;
        for (int i = 0; i < points.size(); ++i)
        {
            const auto point = arrayItem (points, i);
            const auto x = toX (numberProperty (point, "freq_hz"));
            const auto y = toY (numberProperty (point, "db"));
            if (! started) { path.startNewSubPath (x, y); started = true; }
            else path.lineTo (x, y);
        }
        g.setColour (laneColour (lane).withAlpha (lane == selectedLane ? 0.95f : 0.23f));
        g.strokePath (path, juce::PathStrokeType (lane == selectedLane ? 1.7f : 0.8f));
    }

    const auto current = property (screen, "currentResponse");
    const auto points = property (current, "points");
    juce::Path response;
    bool started = false;
    for (int i = 0; i < points.size(); ++i)
    {
        const auto point = arrayItem (points, i);
        const auto x = toX (numberProperty (point, "freq_hz"));
        const auto y = toY (numberProperty (point, "db"));
        if (! started) { response.startNewSubPath (x, y); started = true; }
        else response.lineTo (x, y);
    }
    g.setColour (juce::Colour (0xfff2a65a));
    g.strokePath (response, juce::PathStrokeType (2.5f));

    // The geometry band makes the authored pole/zero movement visible without
    // pretending that root radius is a dB coordinate. The numeric values stay
    // in the selected-lane rail and the packed response stays authoritative.
    g.setColour (juce::Colour (0xff53656a));
    g.drawHorizontalLine (juce::roundToInt (chart.getBottom() - 22.0f), chart.getX(), chart.getRight());
    for (int corner = 0; corner < 4; ++corner)
    {
        const auto lanes = property (arrayItem (corners, corner), "lanes");
        for (int lane = 0; lane < 6; ++lane)
        {
            const auto stage = property (arrayItem (lanes, lane), "stage");
            for (const auto rootName : { "pole", "zero" })
            {
                const auto root = property (stage, rootName);
                const auto hz = numberProperty (root, "hz", -1.0);
                if (hz < 0.0)
                    continue;
                const auto markerX = toX (hz);
                const auto markerY = chart.getBottom() - 22.0f + static_cast<float> (lane - 2) * 3.2f;
                g.setColour ((std::strcmp (rootName, "pole") == 0 ? juce::Colour (0xff76c7c0)
                                                                       : juce::Colour (0xfff17c9c))
                                 .withAlpha (corner == selectedCorner ? 0.9f : 0.35f));
                g.fillEllipse (markerX - 2.5f, markerY - 2.5f, 5.0f, 5.0f);
            }
        }
    }
    drawText (g, "pole", chart.getRight() - 110.0f, chart.getBottom() - 42.0f, 42.0f, 16.0f,
              juce::Colour (0xff76c7c0), 10.0f);
    drawText (g, "zero", chart.getRight() - 62.0f, chart.getBottom() - 42.0f, 42.0f, 16.0f,
              juce::Colour (0xfff17c9c), 10.0f);
}

void WorkstationEditor::drawRightRail (juce::Graphics& g, const juce::Rectangle<float>& bounds)
{
    g.setColour (juce::Colour (0xff172226));
    g.fillRoundedRectangle (bounds, 4.0f);
    g.setColour (juce::Colour (0xff33454a));
    g.drawRoundedRectangle (bounds, 4.0f, 1.0f);
    drawText (g, "MAKE", bounds.getX() + 16.0f, bounds.getY() + 86.0f, 100.0f, 18.0f,
              juce::Colour (0xffe9e2d6), 12.0f);
    drawText (g, "explicit target", bounds.getX() + 16.0f, bounds.getY() + 108.0f, 120.0f, 16.0f,
              juce::Colour (0xff8da0a0), 10.0f);

    const auto poseY = bounds.getY() + 122.0f;
    for (int corner = 0; corner < 4; ++corner)
    {
        const int column = corner % 2;
        const int row = corner / 2;
        const auto box = juce::Rectangle<float> (bounds.getX() + 12.0f + column * 142.0f,
                                                 poseY + row * 36.0f, 132.0f, 28.0f);
        g.setColour (corner == selectedCorner ? juce::Colour (0xff0f7861) : juce::Colour (0xff27343a));
        g.fillRoundedRectangle (box, 3.0f);
        drawText (g, kCornerLabels[corner], box.getX() + 8.0f, box.getY() + 6.0f, box.getWidth() - 16.0f, 16.0f,
                  juce::Colour (0xfff3eee5), 10.0f);
    }
    drawText (g, "LANES", bounds.getX() + 16.0f, poseY + 86.0f, 70.0f, 16.0f, juce::Colour (0xffe9e2d6), 11.0f);
    drawText (g, "click trace or rail", bounds.getX() + 88.0f, poseY + 86.0f, 160.0f, 16.0f,
              juce::Colour (0xff8da0a0), 10.0f, juce::Justification::right);
    for (int lane = 0; lane < 6; ++lane)
    {
        const auto y = poseY + 108.0f + lane * 24.0f;
        g.setColour (lane == selectedLane ? laneColour (lane) : laneColour (lane).withAlpha (0.42f));
        g.fillRoundedRectangle (bounds.getX() + 16.0f, y, bounds.getWidth() - 32.0f, 17.0f, 2.0f);
        drawText (g, "L" + juce::String (lane + 1), bounds.getX() + 24.0f, y + 2.0f, 36.0f, 13.0f,
                  juce::Colour (0xff102027), 10.0f);
        const auto corners = property (installedScreen, "corners");
        const auto corner = arrayItem (corners, selectedCorner);
        const auto lanes = property (corner, "lanes");
        const auto stage = property (arrayItem (lanes, lane), "stage");
        drawText (g, static_cast<bool> (property (stage, "identity")) ? "IDENTITY" : "ACTIVE", bounds.getX() + 66.0f, y + 2.0f,
                  100.0f, 13.0f, juce::Colour (0xff102027), 9.0f);
    }

    const auto selectedStage = property (property (snapshot, "screen"), "selectedStage");
    const auto pole = property (selectedStage, "pole");
    const auto zero = property (selectedStage, "zero");
    const auto scale = property (selectedStage, "scale");
    const auto valueY = bounds.getBottom() - 118.0f;
    drawText (g, "SELECTED L" + juce::String (selectedLane + 1) + " · " + kCornerLabels[selectedCorner],
              bounds.getX() + 16.0f, valueY - 56.0f, bounds.getWidth() - 32.0f, 18.0f,
              juce::Colour (0xffe9e2d6), 11.0f);
    drawText (g, "P " + stringProperty (pole, "hz") + " Hz / r " + juce::String (numberProperty (pole, "radius"), 4),
              bounds.getX() + 16.0f, valueY - 36.0f, bounds.getWidth() - 32.0f, 17.0f,
              juce::Colour (0xff76c7c0), 10.0f);
    drawText (g, "Z " + stringProperty (zero, "hz") + " Hz / r " + juce::String (numberProperty (zero, "radius"), 4),
              bounds.getX() + 16.0f, valueY - 18.0f, bounds.getWidth() - 32.0f, 17.0f,
              juce::Colour (0xfff17c9c), 10.0f);
    drawText (g, "SCALE " + stringProperty (scale, "display"), bounds.getX() + 16.0f, valueY,
              bounds.getWidth() - 32.0f, 17.0f, juce::Colour (0xfff2a65a), 10.0f);
    drawText (g, error.isEmpty() ? status : error, bounds.getX() + 16.0f, bounds.getBottom() - 38.0f,
              bounds.getWidth() - 32.0f, 28.0f, error.isEmpty() ? juce::Colour (0xffaebdb9) : juce::Colour (0xffff8d7d), 9.0f);
}

void WorkstationEditor::drawInspect (juce::Graphics& g, const juce::Rectangle<float>& bounds)
{
    g.setColour (juce::Colour (0xee0a1012));
    g.fillRoundedRectangle (bounds, 4.0f);
    g.setColour (juce::Colour (0xffe9e2d6));
    g.drawRoundedRectangle (bounds, 4.0f, 1.0f);
    drawText (g, "INSPECT · exact packed/runtime consequence", bounds.getX() + 18.0f, bounds.getY() + 14.0f,
              bounds.getWidth() - 36.0f, 20.0f, juce::Colour (0xffe9e2d6), 13.0f);
    const auto stage = property (property (snapshot, "screen"), "selectedStage");
    const auto words = property (stage, "packedWords");
    const auto coefficients = property (stage, "runtimeCoefficients");
    drawText (g, "packed words", bounds.getX() + 18.0f, bounds.getY() + 52.0f, 100.0f, 17.0f,
              juce::Colour (0xff76c7c0), 10.0f);
    juce::String wordLine;
    for (int i = 0; i < words.size(); ++i)
        wordLine << (i == 0 ? "" : "  ") << juce::String (static_cast<int> (words[i]));
    drawText (g, wordLine, bounds.getX() + 126.0f, bounds.getY() + 52.0f, bounds.getWidth() - 144.0f, 17.0f,
              juce::Colour (0xffe9e2d6), 10.0f);
    drawText (g, "decoded [b0 b1 b2 a1 a2]", bounds.getX() + 18.0f, bounds.getY() + 78.0f, 170.0f, 17.0f,
              juce::Colour (0xfff2a65a), 10.0f);
    juce::String coefficientLine;
    for (int i = 0; i < coefficients.size(); ++i)
        coefficientLine << (i == 0 ? "" : "  ") << juce::String (numberAt (coefficients, i), 5);
    drawText (g, coefficientLine, bounds.getX() + 194.0f, bounds.getY() + 78.0f,
              bounds.getWidth() - 212.0f, 17.0f, juce::Colour (0xffe9e2d6), 10.0f);

    const auto lastEdit = property (snapshot, "lastEdit");
    const auto changed = property (lastEdit, "changed_words");
    drawText (g, "last exact change", bounds.getX() + 18.0f, bounds.getY() + 118.0f, 130.0f, 17.0f,
              juce::Colour (0xfff17c9c), 10.0f);
    if (changed.isArray() && changed.size() > 0)
    {
        juce::String changes;
        for (int i = 0; i < juce::jmin (changed.size(), 8); ++i)
        {
            const auto item = arrayItem (changed, i);
            changes << (i == 0 ? "" : "   ") << "C" << static_cast<int> (numberProperty (item, "corner_index"))
                    << "/L" << static_cast<int> (numberProperty (item, "lane_index"))
                    << "/W" << static_cast<int> (numberProperty (item, "word_index"))
                    << " " << static_cast<int> (numberProperty (item, "before")) << "→"
                    << static_cast<int> (numberProperty (item, "after"));
        }
        drawText (g, changes, bounds.getX() + 160.0f, bounds.getY() + 118.0f,
                  bounds.getWidth() - 178.0f, 34.0f, juce::Colour (0xffe9e2d6), 10.0f);
    }
    else
        drawText (g, "no applied edit yet", bounds.getX() + 160.0f, bounds.getY() + 118.0f,
                  bounds.getWidth() - 178.0f, 17.0f, juce::Colour (0xff8da0a0), 10.0f);
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
    return { 20.0f, 82.0f, static_cast<float> (getWidth()) - 390.0f, static_cast<float> (getHeight()) - 174.0f };
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

void WorkstationEditor::editFromPlot (juce::Point<float> point)
{
    if (! plotBounds().contains (point))
        return;
    double value = 0.0;
    switch (editField)
    {
        case EditField::poleHz:
        case EditField::zeroHz: value = frequencyForX (point.x); break;
        case EditField::poleRadius:
        case EditField::zeroRadius: value = radiusForY (point.y); break;
        case EditField::scale:
        {
            const auto chart = plotBounds().reduced (52.0f, 54.0f);
            value = juce::jlimit (0.0, 4.0, 4.0 * (1.0 - static_cast<double> ((point.y - chart.getY()) / chart.getHeight())));
            break;
        }
    }
    previewValue (value);
}

void WorkstationEditor::mouseDown (const juce::MouseEvent& event)
{
    const auto point = event.position;
    const auto rail = rightBounds();
    const auto poseY = rail.getY() + 156.0f;
    for (int corner = 0; corner < 4; ++corner)
    {
        const int column = corner % 2;
        const int row = corner / 2;
        const auto box = juce::Rectangle<float> (rail.getX() + 12.0f + column * 142.0f,
                                                 poseY + row * 36.0f, 132.0f, 28.0f);
        if (box.contains (point))
        {
            selectCorner (corner);
            return;
        }
    }
    for (int lane = 0; lane < 6; ++lane)
    {
        const auto y = poseY + 108.0f + lane * 24.0f;
        if (juce::Rectangle<float> (rail.getX() + 12.0f, y - 3.0f, rail.getWidth() - 24.0f, 23.0f).contains (point))
        {
            selectLane (lane);
            return;
        }
    }
    if (plotBounds().contains (point))
    {
        selectLane (laneAtPlotPoint (point));
        draggingPlot = true;
        editFromPlot (point);
    }
}

void WorkstationEditor::mouseDrag (const juce::MouseEvent& event)
{
    if (draggingPlot)
        editFromPlot (event.position);
}

void WorkstationEditor::mouseUp (const juce::MouseEvent&) { draggingPlot = false; }

void WorkstationEditor::updateParameter (const char* id, float value)
{
    if (auto* parameter = processor.apvts.getParameter (id))
        parameter->setValueNotifyingHost (parameter->convertTo0to1 (value));
}
