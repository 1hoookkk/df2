#include "PluginEditor.h"
#include "BinaryData.h"
#include "TrenchBodyRoster.h"

using namespace trench::ui;

// FORGE drawer width: opening the Forge EXTENDS the window to the right by this much
// (a side drawer), instead of overlaying the plugin. Window width is kEditorWidth, or
// kEditorWidth + kForgeWidth while the Forge is open.
static constexpr int kForgeWidth = 372;

PluginEditor::PluginEditor (PluginProcessor& p)
    : AudioProcessorEditor (&p),
      processor (p)
{
    // Lay-it-out-by-hand: overlay any hand-edited ui_layout.json (and drop a starter
    // file with the current layout if none exists) before building the views.
    reloadLayoutFromDisk();

    auto panel = juce::ImageCache::getFromMemory (BinaryData::df2_panel_shadow_png,
                                                  BinaryData::df2_panel_shadow_pngSize);
    auto strip = juce::ImageCache::getFromMemory (BinaryData::thumbwheel_runtime_strip_129_149x40_png,
                                                  BinaryData::thumbwheel_runtime_strip_129_149x40_pngSize);
    auto grid  = juce::ImageCache::getFromMemory (BinaryData::display_log_grid_png,
                                                  BinaryData::display_log_grid_pngSize);

    faceplate    = std::make_unique<FaceplateView> (panel, theme);
    graph        = std::make_unique<GraphDisplay> (grid, theme, processor.apvts, ParamID::slamDrive);
    slotPad      = std::make_unique<SlotPad> (theme);
    motionSelector = std::make_unique<MotionSelector> (processor.apvts, theme);
    timeSelector   = std::make_unique<TimeSelector> (processor.apvts, theme);
    fiveDTag     = std::make_unique<FiveDTag> (processor.apvts, theme);
    takeView     = std::make_unique<TakeView> (theme);
    moveView     = std::make_unique<MoveView> (processor, theme, grid);
    // ROUTE matrix editor is shelved for V1 (RouteView.h kept on disk) — PLAY only until
    // the default gestures sound good. The 4x4 matrix uses factory defaults in state.

    // Pages: SlotPad 1 = Player curve, 2 = Versions tray. Pressing 2 rerolls a fresh
    // tray of versions of the sound that just played.
    slotPad->onSelect = [this] (int p)
    {
        setPage (p == 1 ? 1 : 0);
    };
    // Press a version -> audition it live: install its body AND adopt its Morph/Q point
    // so what you hear (and the wheels) match the take. Persists.
    takeView->onAudition = [this] (int idx)
    {
        if (idx < 0 || idx >= (int) tray.size())
            return;
        const auto& v = tray[(size_t) idx];
        processor.installBodyBytes (v.bytes.data(), 240);
        const auto setNorm = [this] (const char* id, float norm)
        {
            if (auto* p = processor.apvts.getParameter (id))
                p->setValueNotifyingHost (juce::jlimit (0.0f, 1.0f, norm));
        };
        setNorm (ParamID::morph, v.morph);
        setNorm (ParamID::q, v.q);
        setNorm (ParamID::slamDrive, v.slam);
        setNorm (ParamID::fiveD, v.qsound ? 1.0f : 0.0f);
    };
    // Page 2 is a real page: selecting a slot auditions it, but stays on Page 2
    // until the user presses 1.
    takeView->onConfirm = [] (int) {};
    // Drag a version -> keep it: capture the rolling WET buffer (what you actually
    // heard auditioning) and hand it to the OS so it drops straight into FL. No offline
    // render — the take is the real heard output.
    takeView->onKeep = [this] (int, juce::Component* source)
    {
        const auto f = processor.captureSmartTake();
        if (f.existsAsFile())
            juce::DragAndDropContainer::performExternalDragDropOfFiles (
                { f.getFullPathName() }, false, source, nullptr);
    };
    typeSelector = std::make_unique<TypeSelectorView> (processor.apvts, theme);
    typeSelector->onSeed       = [this] { processor.seedCurrentBody(); };
    typeSelector->onExportBody = [this] { processor.exportCurrentBody(); };
    // SOUND rails: upper aperture = MORPH, lower aperture = Q. SLAM is no longer a
    // rail — it is driven by dragging the screen canvas (see GraphDisplay), so the
    // old Q/SLAM label toggle is retired.
    morphWheel   = std::make_unique<WheelControl> (processor.apvts, ParamID::morph, strip, theme);
    secondaryWheel = std::make_unique<WheelControl> (processor.apvts, ParamID::q, strip, theme);
    morphReadout = std::make_unique<ValueReadout> ("morphReadout", theme);
    secondaryReadout = std::make_unique<ValueReadout> ("qReadout", theme);
    amountFader  = std::make_unique<AmountFader> (processor.apvts, theme);
    labels       = std::make_unique<LabelsLayer> (theme);
    decalsLayer  = std::make_unique<DecalsLayer> (theme);

    // z-order: faceplate (back) -> screen -> controls -> labels -> decals
    addAndMakeVisible (*faceplate);
    addAndMakeVisible (*graph);
    addAndMakeVisible (*takeView);     // page 2 overlay; visibility toggled by setPage
    addChildComponent (*moveView);     // page 2 (MOVE/PLAY) screen; shown by setPage
    addChildComponent (*slotPad);      // pager RETIRED everywhere (Tyson: no pages)
    addAndMakeVisible (*motionSelector); // MOTION: Off/Riser/Breathe/Adlib Chop/Wobble
    addAndMakeVisible (*timeSelector);   // TIME: musical division, shares the old Modulation row
    addAndMakeVisible (*fiveDTag);       // 5D (QSound Space) switch, seated below Motion/Time
    addAndMakeVisible (*typeSelector);
    addAndMakeVisible (*morphWheel);
    addAndMakeVisible (*secondaryWheel);
    addAndMakeVisible (*morphReadout);
    addAndMakeVisible (*secondaryReadout);
    addAndMakeVisible (*amountFader);
    addAndMakeVisible (*labels);
    addAndMakeVisible (*decalsLayer);   // front-most: free text/boxes/lines

   #ifdef TRENCH_FORGE
    // FORGE: in-plugin filter builder — DEV-ONLY (TRENCH_FORGE flag, OFF by default so it
    // NEVER ships). Toggled by the FORGE button; compiles 6 typed table-gated lanes via the
    // typed compiler and auditions live.
    forge = std::make_unique<ForgeView>();
    forge->onAudition = [this] (std::vector<double> cards) { processor.forgeAuditionTyped (cards); };
    forge->onSave     = [this] (juce::String name) { processor.forgeSaveBody (name); };
    forge->onClose    = [this] { if (forge) { forge->setVisible (false); setSize (kEditorWidth, kEditorHeight); } };
    addChildComponent (*forge);   // hidden until toggled

    forgeBtn = std::make_unique<juce::TextButton> ("FORGE");
    forgeBtn->onClick = [this]
    {
        if (forge == nullptr) return;
        const bool open = ! forge->isVisible();
        forge->setVisible (open);
        setSize (open ? kEditorWidth + kForgeWidth : kEditorWidth, kEditorHeight);  // extend the window to the side
    };
    addAndMakeVisible (*forgeBtn);
   #endif

    setResizable (false, false);
    setSize (kEditorWidth, kEditorHeight);

    // Live data (curve + readouts) on the display refresh. No timer and no
    // whole-editor repaint — each view repaints itself only when its input
    // changes, so an idle editor does no work.
    vblank = std::make_unique<juce::VBlankAttachment> (this, [this] { onFrame(); });

    setPage (0);   // start on the Player curve; hides the variant bank

   #ifdef TRENCH_PLAYER_DIAGNOSTICS
    startTimer (350);   // hand-edit hot-reload poll (dev builds only — release never ticks)
    rigPanel = std::make_unique<trench::ui::RigPanel> (processor, theme);
    addAndMakeVisible (*rigPanel);   // voicing rig — pick SPACE/PAN by ear, write the numbers down
    authorView = std::make_unique<trench::ui::AuthorView> (processor, theme);
    // The lab lives in its OWN floating window (separate panel), toggled by the
    // rig's LAB button. authorView is the window's content; not a child here.
    rigPanel->onToggleLab = [this]
    {
        if (labWindow == nullptr)
            labWindow = std::make_unique<trench::ui::LabWindow> (authorView.get());
        labWindow->setVisible (! labWindow->isVisible());
        if (labWindow->isVisible()) labWindow->toFront (true);
    };
    resized();   // rigPanel is built after setSize — lay it out now
   #endif
}

PluginEditor::~PluginEditor()
{
   #ifdef TRENCH_PLAYER_DIAGNOSTICS
    labWindow.reset();   // close the lab window before its content (authorView) frees
   #endif
}

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
        f.replaceWithText (currentLayout.toJson());   // starter = the current layout
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

    // Re-overlay the hand-edited file and re-lay-out live — no rebuild.
    currentLayout = trench::UiLayout::fromJson (f.loadFileAsString());
    layoutComponents();
    repaint();
   #endif
}

void PluginEditor::resized()
{
    layoutComponents();
   #ifdef TRENCH_FORGE
    if (forgeBtn != nullptr)   // toggle sits at the bottom-right of the MAIN UI (the seam)
        forgeBtn->setBounds (kEditorWidth - 58, kEditorHeight - 22, 54, 18);
    if (forge != nullptr && forge->isVisible())   // Forge docks in the right-side drawer strip
        forge->setBounds (kEditorWidth, 0, getWidth() - kEditorWidth, kEditorHeight);
   #endif
}

void PluginEditor::layoutComponents()
{
    // Whole-UI typeface + weight, hand-editable live from ui_layout.json.
    trench::ui::uiFontFamily()  = currentLayout.string ("fontFamily", trench::ui::kUiFontName);
    trench::ui::uiBoldEnabled() = currentLayout.param ("fontBold", 0.0) > 0.5;

    // The main UI stays in its fixed kEditorWidth region (left); the FORGE drawer extends
    // the window to the right, so these full-bleed layers must NOT follow getLocalBounds()
    // (that would stretch the faceplate across the drawer).
    const juce::Rectangle<int> base { 0, 0, kEditorWidth, kEditorHeight };
    faceplate->setBounds (base);
    labels->setBounds (base);
    labels->toFront (false);
    decalsLayer->toFront (false);

    const auto rectOf = [this] (const char* id) { return theme.rect (id).toNearestInt(); };
    graph->setBounds (rectOf ("spectrumGrid"));
    takeView->setBounds (rectOf ("spectrumGrid"));
    moveView->setBounds (rectOf ("spectrumGrid"));
    slotPad->setBounds (rectOf ("slotPad"));
    // MOTION + TIME share the old single-row "modulateTag" slot, side by side —
    // no new panel real estate, matching the "panel stays simple" law.
    {
        const auto row = rectOf ("modulateTag");
        const int half = row.getWidth() / 2;
        motionSelector->setBounds (row.withWidth (half));
        timeSelector->setBounds (row.withX (row.getX() + half).withWidth (row.getWidth() - half));
    }
    fiveDTag->setBounds (rectOf ("fiveDTag"));
    typeSelector->setBounds (rectOf ("typeSelector"));
    morphWheel->setBounds (rectOf ("morphWheel"));
    secondaryWheel->setBounds (rectOf ("qWheel"));
    morphReadout->setBounds (rectOf ("morphReadout"));
    secondaryReadout->setBounds (rectOf ("qReadout"));
    // AMOUNT fader — the right utility column. Left edge aligned to the readout boxes'
    // right edge; below the display; above the lower-right cutout; fully inside the panel.
    {
        const auto mr  = rectOf ("morphReadout");
        const auto qr  = rectOf ("qReadout");
        const auto scr = rectOf ("spectrumGrid");
        const int fx   = mr.getRight() + 26;
        const int fw   = 44;
        const int fTop = scr.getBottom() + 18;   // air below the display
        const int fBot = qr.getBottom() + 34;    // tall — run down toward (above) the cutout
        amountFader->setBounds (fx, fTop, fw, juce::jmax (120, fBot - fTop));
    }

    decalsLayer->setBounds (base);
   #ifdef TRENCH_PLAYER_DIAGNOSTICS
    if (rigPanel != nullptr)
        rigPanel->setBounds (40, 652, 440, 78);   // bare lower third, dev builds only
    // authorView is content of the floating LabWindow — not laid out here.
   #endif

    // Per-element opacity (layout "opacity" field) — fade any control.
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
    // Per display refresh: push live engine state into the views. Each view
    // no-ops when its input is unchanged, so an idle UI does no repainting.
    //
    // Read the lock-free snapshot the audio thread publishes — never the live
    // engine. On a rare torn read we keep the previous frame's curve.
    float coeffs[30] = {};
    float boost = 1.0f;
    if (processor.dspBridge.readUiSnapshot (coeffs, boost))
    {
        const double sr = processor.getSampleRate() > 0.0 ? processor.getSampleRate() : 48000.0;
        graph->updateFromCoeffs (coeffs, boost, sr);
        moveView->updateFromCoeffs (coeffs, boost, sr);
    }
    graph->setSlamMeter (processor.dspBridge.slamOutClipFrac());

    const auto read = [this] (const char* paramID)
    {
        if (auto* v = processor.apvts.getRawParameterValue (paramID))
            return juce::jlimit (0.0f, 1.0f, v->load());
        return 0.0f;
    };
    const bool motionOn = read (ParamID::motionOn) > 0.5f;
    // GraphDisplay reads motionOn/motionTile/motionDiv live for its own MOTION/TIME
    // readout — no push needed from here.

    if (currentPage == 1)
    {
        // MOVE: upper rail = MOVE, lower rail = TIME (FREE or synced value text).
        const float moveAmount = read (ParamID::moveTension);
        morphWheel->setDisplayOverride (false, moveAmount);
        morphReadout->setNormalised (moveAmount);

        if (auto* tp = processor.apvts.getParameter (ParamID::moveTime))
            secondaryWheel->setDisplayOverride (false, tp->getValue());
        const int timeIdx = (int) processor.apvts.getRawParameterValue (ParamID::moveTime)->load();
        secondaryReadout->setText (trench::gestureTimeName (
            (trench::GestureTime) juce::jlimit (0, trench::kNumGestureTimes - 1, timeIdx)));
        moveView->refresh();
    }
    else
    {
        // SOUND: upper rail = MORPH, lower rail = Q. SLAM is driven by the canvas.
        const bool moveOn = read (ParamID::moveOn) > 0.5f;
        const bool moving = (motionOn || moveOn) && processor.isMorphModulatedForUi();
        const float morphValue = moving ? processor.getEffectiveMorphForUi() : read (ParamID::morph);
        morphWheel->setDisplayOverride (moving, morphValue);
        morphReadout->setNormalised (morphValue);

        const bool qMoving = (motionOn || moveOn) && processor.isQModulatedForUi();
        const float qValue = qMoving ? processor.getEffectiveQForUi() : read (ParamID::q);
        secondaryWheel->setDisplayOverride (qMoving, qValue);
        secondaryReadout->setNormalised (qValue);
    }

    const bool morphActive = morphWheel->isMouseOverOrDragging (true) || morphReadout->isMouseOverOrDragging (true);
    const bool secondaryActive = secondaryWheel->isMouseOverOrDragging (true) || secondaryReadout->isMouseOverOrDragging (true);
    morphReadout->setActive (morphActive);
    secondaryReadout->setActive (secondaryActive);
}

void PluginEditor::setPage (int page)
{
    currentPage = juce::jlimit (0, 1, page);
    const bool move = (currentPage == 1);   // pages retired; path kept for compat

    graph->setVisible (! move);
    moveView->setVisible (move);            // V1: MOVE = PLAY only (ROUTE shelved)
    takeView->setVisible (false);           // Take/variant tray is not a V1 page
    motionSelector->setVisible (true);
    timeSelector->setVisible (true);
    fiveDTag->setVisible (true);
    slotPad->setActive (currentPage);

    // Page-specific rails + labels: SOUND = MORPH + Q/SLAM, MOVE = MOVE/TIME.
    morphWheel->setParameter (processor.apvts,
                              move ? juce::String (ParamID::moveTension) : juce::String (ParamID::morph));
    if (move)
    {
        secondaryWheel->setParameter (processor.apvts, ParamID::moveTime);
        labels->setRailLabels ("MOVE", "TIME");
        moveView->refresh();
    }
    else
    {
        labels->setRailLabels ("MORPH (%)", "Q (%)");   // target refs' wording; SLAM lives on the canvas
        secondaryWheel->setParameter (processor.apvts, ParamID::q);
    }
}

void PluginEditor::refreshTake()
{
    tray = processor.buildTakeTray (12);
    takeView->setSlots (tray);
    takeView->setSelected (0);   // slot 01 = AS HEARD, selected by default
}
