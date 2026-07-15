#include "PluginEditor.h"
#include "BinaryData.h"
#include "TrenchBodyRoster.h"

using namespace trench::ui;

PluginEditor::PluginEditor (PluginProcessor& p)
    : AudioProcessorEditor (&p),
      processor (p)
{
    // Lay-it-out-by-hand: overlay any hand-edited ui_layout.json (and drop a starter
    // file with the current layout if none exists) before building the views.
    reloadLayoutFromDisk();

    // Back-to-beige rewrite (2026-07-10): the plate is Tyson's beige art (its
    // baked recesses ARE the wells); ivory windows + glass are painted in code;
    // the wheels are the real rendered sculpt strip ("these look good").
    // The CLASSIC BEIGE plate — home. Components paint their bone faces into
    // its baked wells.
    // The CLASSIC BEIGE plate — home. Components paint their bone faces into
    // its baked wells.
    auto panel = juce::ImageCache::getFromMemory (BinaryData::df2_panel_beige_png,
                                                  BinaryData::df2_panel_beige_pngSize);
    // The wheels: the iron twin-row roller, Blender-rendered at ACTUAL SIZE with
    // the deep smoked-cobalt position glow baked per frame (X3 law: trailing bar through the
    // fin gaps). Frames draw 1:1 and overhang the recut wells; frame count
    // derives from strip width; travel = 10 fin pitches, no wrap.
    auto strip = juce::ImageCache::getFromMemory (BinaryData::trench_roller_strip_png,
                                                  BinaryData::trench_roller_strip_pngSize);
    faceplate    = std::make_unique<FaceplateView> (panel, theme);
    faceplate->setBufferedToImage (true);   // the static plate is cached, not re-rasterized per frame
    graph        = std::make_unique<GraphDisplay> (theme, processor.apvts, ParamID::slamDrive);
    slotPad      = std::make_unique<SlotPad> (theme);
    moveChip = std::make_unique<MoveChip> (processor.apvts, theme);
    takeView     = std::make_unique<TakeView> (theme);
    moveView     = std::make_unique<MoveView> (processor, theme);
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
    const auto runSeed = [this]
    {
        if (processor.seedCurrentBody())
        {
            graph->playSeedPulse();
            moveChip->flashSiblingLabel();
        }
    };
    typeSelector->onSeed       = runSeed;
    typeSelector->onExportBody = [this] { processor.exportCurrentBody(); };
    // SOUND rails: upper aperture = MORPH, lower aperture = Q. SLAM is no longer a
    // rail — it is driven by dragging the screen canvas (see GraphDisplay), so the
    // old Q/SLAM label toggle is retired.
    morphWheel   = std::make_unique<WheelControl> (processor.apvts, ParamID::morph, strip, theme);
    // Alt-drag Morph teaches a USER motion (MOVE chip's "USER · 1 BAR"). The
    // wheel still moves/plays normally under Alt -- this just also records it.
    morphWheel->onAltDragStart  = [this] { processor.beginUserMotionRecording(); };
    morphWheel->onAltDragSample = [this] (float v) { processor.addUserMotionSample (v); };
    morphWheel->onAltDragEnd    = [this] { processor.endUserMotionRecording(); };
    secondaryWheel = std::make_unique<WheelControl> (processor.apvts, ParamID::q, strip, theme);
    morphReadout = std::make_unique<ValueReadout> ("morphReadout", theme);
    secondaryReadout = std::make_unique<ValueReadout> ("qReadout", theme);
    // Bind so the readouts are real controls too: scroll / type / right-click menu.
    morphReadout->bindParameter (processor.apvts.getParameter (ParamID::morph));
    secondaryReadout->bindParameter (processor.apvts.getParameter (ParamID::q));
    amountFader  = std::make_unique<AmountFader> (processor.apvts, theme);
    seedButton   = std::make_unique<SeedButton> (theme);
    seedButton->onSeed = runSeed;
    takeButton   = std::make_unique<TakeButton> (theme);
    // Same real-heard-audio drag pattern as takeView->onKeep above -- no
    // offline render, the take is what you actually just heard.
    takeButton->onDragTake = [this] (juce::Component* source)
    {
        const auto f = processor.captureSmartTake();
        if (f.existsAsFile())
            juce::DragAndDropContainer::performExternalDragDropOfFiles (
                { f.getFullPathName() }, false, source, nullptr);
    };
    fiveDButton  = std::make_unique<FiveDButton> (processor.apvts, theme);
    labels       = std::make_unique<LabelsLayer> (theme);
    decalsLayer  = std::make_unique<DecalsLayer> (theme);

    // z-order: faceplate (back) -> screen -> controls -> labels -> decals
    addAndMakeVisible (*faceplate);
    addAndMakeVisible (*graph);
    addAndMakeVisible (*takeView);     // page 2 overlay; visibility toggled by setPage
    addChildComponent (*moveView);     // page 2 (MOVE/PLAY) screen; shown by setPage
    addChildComponent (*slotPad);      // pager RETIRED everywhere (Tyson: no pages)
    addAndMakeVisible (*moveChip); // curated MOVE status chip -- added after graph, paints on top
    addAndMakeVisible (*typeSelector);
    addAndMakeVisible (*morphWheel);
    addAndMakeVisible (*secondaryWheel);
    addAndMakeVisible (*morphReadout);
    addAndMakeVisible (*secondaryReadout);
    // AMOUNT is a key control, so it stays visible. It will read "pasted on"
    // until the plate art grows a milled slot for it (see faceplate regen) — a
    // code fader on bare metal always does; the recess is the real fix.
    // The reference face is intentionally only TYPE + glass + MORPH/Q. These
    // utilities remain wired for the future utility drawer/host surface, but
    // do not float on the luxury lower third.
    addChildComponent (*amountFader);
    addChildComponent (*seedButton);
    addChildComponent (*takeButton);
    addChildComponent (*fiveDButton);
    addAndMakeVisible (*labels);
    addAndMakeVisible (*decalsLayer);   // front-most: free text/boxes/lines

    setResizable (false, false);
    setSize (kEditorWidth, kEditorHeight);

    // Don't hold keyboard focus — so keystrokes fall through to the host and the
    // user can play notes on their keyboard without clicking out of the plugin.
    setWantsKeyboardFocus (false);

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
}

void PluginEditor::layoutComponents()
{
    // Whole-UI typeface + weight, hand-editable live from ui_layout.json.
    trench::ui::uiFontFamily() = currentLayout.string ("fontFamily", trench::ui::kUiFontName);
    trench::ui::uiEmphasisFontFamily() = currentLayout.string ("fontFamilyEmphasis",
                                                                trench::ui::kUiEmphasisFontName);
    trench::ui::uiBoldEnabled() = currentLayout.param ("fontBold", 0.0) > 0.5;

    // The product faceplate stays at its authored size; the workstation is a separate app.
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
    // One small status chip, top-left INSIDE the screen, over the curve.
    // The screen itself (GraphDisplay) draws only the curve; this chip is a
    // separate component layered on top (added after graph -> paints front).
    {
        const auto scr = rectOf ("spectrumGrid");
        // One deliberate screen control: the dim Modulation-style tag parked
        // bottom-left on the glass, exactly where the reference builds put it.
        moveChip->setBounds (scr.getX() + 14, scr.getBottom() - 28, 178, 18);
    }
    typeSelector->setBounds (rectOf ("typeSelector"));
    morphWheel->setBounds (rectOf ("morphWheel"));
    secondaryWheel->setBounds (rectOf ("qWheel"));
    morphReadout->setBounds (rectOf ("morphReadout"));
    secondaryReadout->setBounds (rectOf ("qReadout"));
    amountFader->setBounds ({});
    seedButton->setBounds ({});
    takeButton->setBounds ({});
    fiveDButton->setBounds ({});

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
    graph->setSlamMeter (processor.getOutClipForUi());

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
        // The wheels follow the EFFECTIVE values whenever any engine modulates
        // them — the processor's divergence flag is the single source of truth,
        // so MOTION/MOVE visibly drive the wheels with no gate to go stale.
        const bool moving = processor.isMorphModulatedForUi();
        const float morphValue = moving ? processor.getEffectiveMorphForUi() : read (ParamID::morph);
        morphWheel->setDisplayOverride (moving, morphValue);
        morphReadout->setNormalised (morphValue);

        const bool qMoving = processor.isQModulatedForUi();
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
    moveChip->setVisible (true);
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
        labels->setRailLabels ("MORPH (%)", "Q (%)");
        secondaryWheel->setParameter (processor.apvts, ParamID::q);
    }
}

void PluginEditor::refreshTake()
{
    tray = processor.buildTakeTray (12);
    takeView->setSlots (tray);
    takeView->setSelected (0);   // slot 01 = AS HEARD, selected by default
}
