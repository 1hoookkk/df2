#include "WorkstationEditor.h"

WorkstationLoop* gWorkstationLoop = nullptr;
#include <cmath>
#include <complex>
#include <algorithm>
#include <map>

namespace
{
constexpr double kEvalSampleRate = 39062.5;
constexpr float kMinHz = 20.0f;
constexpr float kMaxHz = 19530.0f; // remain below the 39.0625 kHz runtime Nyquist
constexpr float kMinDb = -60.0f;
constexpr float kMaxDb = 30.0f;
constexpr int kBinRowH = 20;
constexpr int kLaneRowH = 32;
constexpr int kTrayH = 96;
constexpr int kLanesH = 20 + 6 * kLaneRowH + 4;
constexpr int kDragThreshold = 3;

const juce::Colour kBg (0xff0a0d14);
const juce::Colour kPanel (0xff121924);
const juce::Colour kPanelDeep (0xff07090e);
const juce::Colour kBorder (0xff1e2d3d);
const juce::Colour kCyan (0xff00f0ff);
const juce::Colour kAmber (0xffffb547);
const juce::Colour kGreen (0xff00ff9d);
const juce::Colour kRed (0xffff5d5d);
const juce::Colour kText (0xffc9d8e4);
const juce::Colour kTextDim (0xff7e9bb2);
const juce::Colour kGridLabel (0xff4a6378);

const juce::Colour kLaneColours[6] = {
    juce::Colour (0xff5dd0ff), juce::Colour (0xff7dff9a), juce::Colour (0xffffd75d),
    juce::Colour (0xffff9d5d), juce::Colour (0xffd98cff), juce::Colour (0xffff6da8),
};

float stageMagDb (const float* c, double cosw, double sinw, double cos2w, double sin2w)
{
    const double numReal = c[0] + c[1] * cosw + c[2] * cos2w;
    const double numImag = -c[1] * sinw - c[2] * sin2w;
    const double denReal = 1.0 + c[3] * cosw + c[4] * cos2w;
    const double denImag = -c[3] * sinw - c[4] * sin2w;
    const double numMagSq = numReal * numReal + numImag * numImag;
    const double denMagSq = std::max (1e-12, denReal * denReal + denImag * denImag);
    return (float) (10.0 * std::log10 (std::max (1e-12, numMagSq / denMagSq)));
}

juce::File trenchDocsDir()
{
    return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory).getChildFile ("TRENCH");
}

// Documents may be OneDrive-redirected; older tools wrote to the local profile Documents.
juce::File trenchLocalDocsDir()
{
    return juce::File ("C:/Users/hooki/Documents/TRENCH");
}

const char* kCornerNames[4] = { "M0 / Q0", "M100 / Q0", "M0 / Q100", "M100 / Q100" };
const char* kCornerLabels[4] = { "M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100" };

void wordsFromBytes240 (const std::array<juce::uint8, 240>& bytes, juce::uint16 (&w)[4][6][5])
{
    int i = 0;
    for (int c = 0; c < 4; ++c)
        for (int s = 0; s < 6; ++s)
            for (int k = 0; k < 5; ++k)
            {
                w[c][s][k] = (juce::uint16) (bytes[(size_t) i] | (bytes[(size_t) i + 1] << 8));
                i += 2;
            }
}

}

WorkstationEditor::WorkstationEditor (PluginProcessor& p)
    : processor (p)
{
    {
        const double identityRoots[5] = { 0.0, 0.0, 0.0, 0.0, 1.0 };
        trench_stage_words_from_roots (identityRoots, identityWords);
    }

    addAndMakeVisible (binSearch);
    binSearch.setColour (juce::TextEditor::backgroundColourId, kPanelDeep);
    binSearch.setColour (juce::TextEditor::outlineColourId, kBorder);
    binSearch.setColour (juce::TextEditor::focusedOutlineColourId, kCyan.withAlpha (0.6f));
    binSearch.setColour (juce::TextEditor::textColourId, kText);
    binSearch.setColour (juce::CaretComponent::caretColourId, kCyan);
    binSearch.setFont (juce::FontOptions (11.0f));
    binSearch.setTextToShowWhenEmpty ("INDEX  name / family / role", kGridLabel);
    binSearch.onTextChange = [this]
    {
        binQuery = binSearch.getText().trim().toLowerCase();
        binScroll = 0;
        rebuildRows();
        repaint();
    };
    binSearch.onEscapeKey = [this]
    {
        binSearch.clear();
        grabKeyboardFocus();
    };

    addAndMakeVisible (nameField);
    nameField.setColour (juce::TextEditor::backgroundColourId, kPanelDeep);
    nameField.setColour (juce::TextEditor::outlineColourId, kBorder);
    nameField.setColour (juce::TextEditor::focusedOutlineColourId, kCyan.withAlpha (0.5f));
    nameField.setColour (juce::TextEditor::textColourId, kText);
    nameField.setColour (juce::CaretComponent::caretColourId, kCyan);
    nameField.setFont (juce::FontOptions (13.0f));
    nameField.setTextToShowWhenEmpty ("body name", kGridLabel);

    addChildComponent (propEditor);
    propEditor.setColour (juce::TextEditor::backgroundColourId, kPanelDeep);
    propEditor.setColour (juce::TextEditor::outlineColourId, kCyan.withAlpha (0.6f));
    propEditor.setColour (juce::TextEditor::focusedOutlineColourId, kCyan);
    propEditor.setColour (juce::TextEditor::textColourId, kText);
    propEditor.setColour (juce::CaretComponent::caretColourId, kCyan);
    propEditor.setFont (juce::FontOptions (12.0f));
    propEditor.setInputRestrictions (12, "0123456789.-");
    propEditor.onReturnKey = [this] { commitPropEdit(); };
    propEditor.onEscapeKey = [this] { editingProp = -1; propEditor.setVisible (false); };
    propEditor.onFocusLost = [this] { if (editingProp >= 0) commitPropEdit(); };

    addChildComponent (designerEditor);
    designerEditor.setColour (juce::TextEditor::backgroundColourId, kPanelDeep);
    designerEditor.setColour (juce::TextEditor::outlineColourId, kCyan.withAlpha (0.6f));
    designerEditor.setColour (juce::TextEditor::focusedOutlineColourId, kCyan);
    designerEditor.setColour (juce::TextEditor::textColourId, kText);
    designerEditor.setColour (juce::CaretComponent::caretColourId, kCyan);
    designerEditor.setFont (juce::FontOptions (11.0f));
    designerEditor.setInputRestrictions (12, "0123456789.-");
    designerEditor.onReturnKey = [this] { designerCommitEdit(); };
    designerEditor.onEscapeKey = [this] { dsEditField = -1; designerEditor.setVisible (false); };
    designerEditor.onFocusLost = [this] { if (dsEditField >= 0) designerCommitEdit(); };

    // firmware freq-code ladder: decode each type-1 pole through the real recipe
    {
        TrenchDesignerSection probe {};
        probe.type_id = 1;
        probe.low.gain = probe.high.gain = 64;
        for (int code = 0; code < 128; ++code)
        {
            probe.low.freq = probe.high.freq = code;
            juce::uint16 w[30] {};
            double roots[5] {};
            designerLadderHz[code] =
                (trench_designer_compile_corner (&probe, 1, 0.0, 0, w) == 0
                 && trench_stage_roots_from_words (w, roots) == 0)
                    ? roots[0]
                    : 0.0;
        }
    }

    setWantsKeyboardFocus (true);

    scanBin();

    if (const auto scriptPath = juce::SystemStats::getEnvironmentVariable ("TRENCH_WS_SCRIPT", {});
        scriptPath.isNotEmpty())
    {
        proofActions = juce::JSON::parse (juce::File (scriptPath));
        if (proofActions.isArray())
        {
            proofPending = true;
            proofDelayTicks = 45; // ~1.5 s after startup
        }
    }

    setSize (1280, 800);
    startTimerHz (30);
}

WorkstationEditor::~WorkstationEditor()
{
    stopTimer();
}

// ---------------------------------------------------------------- node index

void WorkstationEditor::scanBin()
{
    nodes.clear();
    sections.clear();
    refItems.clear();

    {
        // P2K biquads: the ROM extraction itself, 240-byte packed, engine-ready
        // (verified byte-identical to bodies/rom compiled-v1 jsons, 2026-07-24)
        Section section { NodeKind::P2k, "SOURCE / P2K POSES + STAGES", {}, false };
        const juce::File dir ("C:/Users/hooki/df2/ref/presets");
        auto files = dir.findChildFiles (juce::File::findFiles, false, "*.bin");
        std::sort (files.begin(), files.end(),
                   [] (const juce::File& a, const juce::File& b)
                   { return a.getFileName().compareIgnoreCase (b.getFileName()) < 0; });
        for (const auto& f : files)
        {
            if (f.getSize() != 240)
                continue;
            section.nodes.push_back ((int) nodes.size());
            nodes.push_back ({ NodeKind::P2k, f.getFileNameWithoutExtension(), f, true, -1 });
        }
        if (! section.nodes.empty())
            sections.push_back (std::move (section));
    }

    {
        // Measured/simulated material is evidence for authoring, not an already
        // packed four-pose donor. Keep the existing well names and source paths.
        Section section { NodeKind::MeasuredRail, "SOURCE / MEASURED RAILS", {}, false };
        struct RailSpec { const char* name; const char* relative; const char* note; };
        static const RailSpec rails[] = {
            { "DVTD VOCAL (44 rails)", "out/dvtd_rails/dvtd_rails_trench_runtime.json",
              "measured vocal-tract pole/zero rails @ 39062.5" },
            { "SONICOM HRTF (48 directions)", "out/hrtf_rails/hrtf_rails.json",
              "measured pinna/head directional pole/zero rails" },
            { "MODAL OBJECTS", "out/modal_rails/modal_rails.json",
              "simulated physical-modal pole/zero rails" },
            { "PHONONIC STRUCTURES", "out/phononic_rails/phononic_rails.json",
              "measured metamaterial trajectory rails" },
            { "CIRCUIT RESPONSES", "out/circuit_rails/circuit_rails.json",
              "circuit-response pole/zero rails" },
        };
        const juce::File root ("C:/Users/hooki/trench-filters");
        for (const auto& rail : rails)
        {
            const auto file = root.getChildFile (rail.relative);
            if (! file.existsAsFile())
                continue;
            Node node;
            node.kind = NodeKind::MeasuredRail;
            node.stem = rail.name;
            node.body = file;
            node.note = rail.note;
            section.nodes.push_back ((int) nodes.size());
            nodes.push_back (std::move (node));
        }
        if (! section.nodes.empty())
            sections.push_back (std::move (section));
    }

    {
        // Explicit operator ear picks from the df2 author-sheet handoff.
        // Reopen as programs only; never treat prior authored work as source.
        Section section { NodeKind::LabBody, "PROGRAMS / EAR PICKS", {}, false };
        const juce::File dir ("C:/Users/hooki/df2/dev/tmp/author_sheet");
        for (const char* name : { "VOWL_aa_to_iy", "PHON_SPLITTER", "FUZZ_B_RAZOR" })
        {
            const auto file = dir.getChildFile (juce::String (name) + ".body240");
            if (! file.existsAsFile() || file.getSize() != 240)
                continue;
            section.nodes.push_back ((int) nodes.size());
            nodes.push_back ({ NodeKind::LabBody, name, file, true, -1,
                               "operator ear pick; program only" });
        }
        if (! section.nodes.empty())
            sections.push_back (std::move (section));
    }

    {
        // The workstation's explicitly isolated usable set. Keep it collapsed
        // and program-only; discovery is not promotion.
        Section section { NodeKind::LabBody, "PROGRAMS / LAB", {}, false };
        const juce::File dir ("C:/Users/hooki/df2-workstation/dev/tmp/usable");
        auto files = dir.findChildFiles (juce::File::findFiles, false, "*.body240");
        std::sort (files.begin(), files.end(),
                   [] (const juce::File& a, const juce::File& b)
                   { return a.getFileName().compareIgnoreCase (b.getFileName()) < 0; });
        for (const auto& file : files)
        {
            if (file.getSize() != 240)
                continue;
            section.nodes.push_back ((int) nodes.size());
            nodes.push_back ({ NodeKind::LabBody, file.getFileNameWithoutExtension(), file,
                               true, -1, "workstation dev/tmp usable; program only" });
        }
        if (! section.nodes.empty())
            sections.push_back (std::move (section));
    }

    {
        // Saved bodies are one indexed program shelf. Family prefixes remain in
        // their names and are searchable; separate family shelves turned the
        // primary workflow back into a directory tree.
        std::map<juce::String, juce::File> byStem;
        for (const auto& dir : { trenchDocsDir().getChildFile ("bodies"), trenchLocalDocsDir().getChildFile ("bodies") })
        {
            if (! dir.isDirectory())
                continue;
            for (const auto& f : dir.findChildFiles (juce::File::findFiles, true, "*.body240"))
            {
                auto stem = f.getRelativePathFrom (dir).replaceCharacter ('\\', '/');
                stem = stem.upToLastOccurrenceOf (".", false, false);
                byStem[stem] = f;
            }
        }
        Section section { NodeKind::UserBody, "PROGRAMS / SAVED", {}, false };
        for (const auto& [stem, file] : byStem)
        {
            section.nodes.push_back ((int) nodes.size());
            nodes.push_back ({ NodeKind::UserBody, stem, file, true, -1 });
        }
        if (! section.nodes.empty())
            sections.push_back (std::move (section));
    }

    // Morph Designer flow: source first, then programs to reopen. All shelves
    // begin closed and the accordion exposes one thing at a time.
    const auto sectionRank = [] (const Section& section)
    {
        if (section.kind == NodeKind::P2k)                                                return 0;
        if (section.kind == NodeKind::MeasuredRail)                                       return 1;
        if (section.kind == NodeKind::LabBody && section.title.contains ("EAR PICKS")) return 2;
        if (section.kind == NodeKind::UserBody)                                           return 3;
        if (section.kind == NodeKind::LabBody)                                            return 4;
        return 5;
    };
    std::stable_sort (sections.begin(), sections.end(),
                      [&] (const Section& a, const Section& b)
                      { return sectionRank (a) < sectionRank (b); });

    rebuildRows();
    writeIndexJson();
}

void WorkstationEditor::rebuildRows()
{
    rows.clear();
    const bool searching = binQuery.isNotEmpty();
    const auto matchesQuery = [this] (const juce::String& text)
    {
        return text.toLowerCase().contains (binQuery);
    };
    for (int si = 0; si < (int) sections.size(); ++si)
    {
        const auto& section = sections[(size_t) si];
        if (! searching)
        {
            rows.push_back ({ true, si, -1 });
            if (! section.open)
                continue;
            for (int nodeIndex : section.nodes)
                rows.push_back ({ false, si, nodeIndex });
            continue;
        }

        std::vector<int> matches;
        const bool sectionMatch = matchesQuery (section.title);
        juce::String roleTerms;
        if (section.kind == NodeKind::UserBody)       roleTerms = "program saved body";
        if (section.kind == NodeKind::LabBody)        roleTerms = "program lab usable ear pick";
        if (section.kind == NodeKind::P2k)            roleTerms = "donor p2k biquad";
        if (section.kind == NodeKind::MeasuredRail)   roleTerms = "material measured rail evidence";
        if (section.kind == NodeKind::X3Ref)          roleTerms = "reference x3 ghost";
        const bool roleMatch = matchesQuery (roleTerms);
        for (int nodeIndex : section.nodes)
        {
            const auto& node = nodes[(size_t) nodeIndex];
            if (sectionMatch || roleMatch
                || matchesQuery (node.stem)
                || matchesQuery (node.note)
                || matchesQuery (node.body.getFullPathName()))
                matches.push_back (nodeIndex);
        }
        if (matches.empty())
            continue;
        rows.push_back ({ true, si, -1 });
        for (int nodeIndex : matches)
            rows.push_back ({ false, si, nodeIndex });
    }
}

void WorkstationEditor::writeIndexJson() const
{
    juce::Array<juce::var> out;
    static const char* kindNames[] = { "user_body", "lab_body", "p2k", "measured_rail", "x3_ref" };
    for (const auto& section : sections)
    {
        for (int nodeIndex : section.nodes)
        {
            const auto& node = nodes[(size_t) nodeIndex];
            auto* obj = new juce::DynamicObject();
            obj->setProperty ("stem", node.stem);
            obj->setProperty ("kind", kindNames[(int) node.kind]);
            obj->setProperty ("section", section.title);
            if (node.body != juce::File())
                obj->setProperty ("file", node.body.getFullPathName());
            if (node.refIndex >= 0)
                obj->setProperty ("ref", refItems[(size_t) node.refIndex].file.getFullPathName());
            if (node.note.isNotEmpty())
                obj->setProperty ("note", node.note);
            out.add (juce::var (obj));
        }
    }
    auto* root = new juce::DynamicObject();
    root->setProperty ("format", "trench-workstation-index-v1");
    root->setProperty ("nodes", out);
    trenchDocsDir().getChildFile ("index.json")
        .replaceWithText (juce::JSON::toString (juce::var (root)));
}

bool WorkstationEditor::nodeBytes (const Node& node, std::array<juce::uint8, 240>& out) const
{
    juce::MemoryBlock block;
    if (node.body == juce::File() || ! node.body.loadFileAsData (block) || block.getSize() != 240)
        return false;
    std::memcpy (out.data(), block.getData(), 240);
    return true;
}

void WorkstationEditor::loadProgram (int nodeIndex)
{
    if (nodeIndex < 0 || nodeIndex >= (int) nodes.size() || ! nodes[(size_t) nodeIndex].loadable)
        return;
    const auto& node = nodes[(size_t) nodeIndex];
    std::array<juce::uint8, 240> bytes {};
    if (! nodeBytes (node, bytes))
    {
        statusLine = "PROGRAM load failed: " + node.stem;
        repaint();
        return;
    }
    if (hasBody && dirty)
    {
        // switching away from unsaved work: stash it, never lose it
        auto dir = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                       .getChildFile ("TRENCH").getChildFile ("bodies").getChildFile ("AUTOSAVE");
        dir.createDirectory();
        const auto stash = dir.getChildFile (bodyName + "__autosave.body240");
        stash.replaceWithData (workingBytes.data(), 240);
        statusLine = "stashed unsaved work -> AUTOSAVE/" + stash.getFileName();
    }
    workingBytes = bytes;
    wordsFromBytes240 (workingBytes, words);
    hasBody = true;
    dirty = false;
    bodyName = node.stem;
    nameField.setText (node.stem, juce::dontSendNotification);
    std::fill (std::begin (muteBackupValid), std::end (muteBackupValid), false);

    // byte law: words -> pack must reproduce the loaded bytes exactly
    std::array<juce::uint8, 240> repacked {};
    if (trench_pack_body_from_corner_words (&words[0][0][0], 120, repacked.data()) != 0
        || repacked != workingBytes)
    {
        statusLine = "BYTE LAW VIOLATION on load: " + node.stem;
        hasBody = false;
        repaint();
        return;
    }

    loadedBytes = workingBytes;
    undoStack.clear();
    packAndInstall();
    statusLine = "PROGRAM <- " + node.stem;
    curvesStale = true;
    repaint();
}

// ---------------------------------------------------------------- undo / reset

void WorkstationEditor::pushUndo()
{
    if (! hasBody)
        return;
    std::array<juce::uint16, 120> snap;
    std::memcpy (snap.data(), &words[0][0][0], sizeof (juce::uint16) * 120);
    if (! undoStack.empty() && undoStack.back() == snap)
        return;
    undoStack.push_back (snap);
    redoStack.clear();
    if (undoStack.size() > 64)
        undoStack.erase (undoStack.begin());
}

void WorkstationEditor::undo()
{
    if (! hasBody || undoStack.empty())
    {
        statusLine = "nothing to undo";
        repaint();
        return;
    }
    {
        std::array<juce::uint16, 120> now;
        std::memcpy (now.data(), &words[0][0][0], sizeof (juce::uint16) * 120);
        redoStack.push_back (now);
    }
    std::memcpy (&words[0][0][0], undoStack.back().data(), sizeof (juce::uint16) * 120);
    undoStack.pop_back();
    std::fill (std::begin (muteBackupValid), std::end (muteBackupValid), false);
    dirty = true;
    packAndInstall();
    statusLine = "UNDO  (" + juce::String ((int) undoStack.size()) + " left)";
    repaint();
}

void WorkstationEditor::redo()
{
    if (! hasBody || redoStack.empty())
    {
        statusLine = "nothing to redo";
        repaint();
        return;
    }
    {
        std::array<juce::uint16, 120> now;
        std::memcpy (now.data(), &words[0][0][0], sizeof (juce::uint16) * 120);
        undoStack.push_back (now);
    }
    std::memcpy (&words[0][0][0], redoStack.back().data(), sizeof (juce::uint16) * 120);
    redoStack.pop_back();
    std::fill (std::begin (muteBackupValid), std::end (muteBackupValid), false);
    dirty = true;
    packAndInstall();
    statusLine = "REDO  (" + juce::String ((int) redoStack.size()) + " ahead)";
    repaint();
}

void WorkstationEditor::resetProgram()
{
    if (! hasBody)
        return;
    pushUndo();   // the flat slate is undoable
    for (int c = 0; c < 4; ++c)
        for (int stage = 0; stage < 6; ++stage)
            std::memcpy (words[c][stage], identityWords, sizeof (juce::uint16) * 5);
    std::fill (std::begin (muteBackupValid), std::end (muteBackupValid), false);
    dirty = true;
    packAndInstall();
    statusLine = "RESET -> flat line (all stages identity, all corners)";
    repaint();
}

void WorkstationEditor::loadSource (int nodeIndex)
{
    if (nodeIndex < 0 || nodeIndex >= (int) nodes.size() || ! nodes[(size_t) nodeIndex].loadable)
        return;
    const auto& node = nodes[(size_t) nodeIndex];
    if (node.kind != NodeKind::P2k)
    {
        statusLine = "DONOR accepts P2K BIQUADS only";
        repaint();
        return;
    }
    std::array<juce::uint8, 240> bytes {};
    if (! nodeBytes (node, bytes))
    {
        statusLine = "DONOR load failed: " + node.stem;
        repaint();
        return;
    }
    sourceBytes = bytes;
    wordsFromBytes240 (sourceBytes, sourceWords);
    hasSource = true;
    sourceName = node.stem;
    statusLine = "SOURCE <- " + node.stem + "  |  endpoints or filter stages";
    curvesStale = true;
    repaint();
}

bool WorkstationEditor::packAndInstall (bool certify)
{
    if (! hasBody)
        return false;
    if (trench_pack_body_from_corner_words (&words[0][0][0], 120, workingBytes.data()) != 0)
    {
        statusLine = "pack failed";
        return false;
    }
    if (! certify)
    {
        // drag-time light path: install for immediate feedback, certify on release
        processor.installBodyBytes (workingBytes.data(), 240);
        curvesStale = true;
        return true;
    }
    int pass = 0;
    double maxR = 0.0, failM = -1.0, failQ = -1.0;
    trench_certify_body (workingBytes.data(), 240, 9, 1.0, &pass, &maxR, &failM, &failQ);
    lastCertifyPass = (pass == 1);
    lastCertifyMaxR = maxR;
    if (! lastCertifyPass)
    {
        statusLine = juce::String::formatted ("UNSTABLE at morph %.2f q %.2f - not installed", failM, failQ);
        return false;
    }
    processor.installBodyBytes (workingBytes.data(), 240);
    curvesStale = true;
    return true;
}

bool WorkstationEditor::laneIsIdentity (const juce::uint16 (&w)[4][6][5], int lane) const
{
    for (int c = 0; c < 4; ++c)
        for (int k = 0; k < 5; ++k)
            if (w[c][lane][k] != identityWords[k])
                return false;
    return true;
}

void WorkstationEditor::toggleLaneOff (int lane)
{
    if (! hasBody || lane < 0 || lane >= 6)
        return;
    pushUndo();
    if (laneIsIdentity (words, lane))
    {
        if (! muteBackupValid[lane])
            return; // authored-identity lane: nothing to restore
        for (int c = 0; c < 4; ++c)
            std::memcpy (words[c][lane], muteBackup[lane][c], sizeof (juce::uint16) * 5);
        muteBackupValid[lane] = false;
        statusLine = "S" + juce::String (lane + 1) + " ON";
    }
    else
    {
        for (int c = 0; c < 4; ++c)
        {
            std::memcpy (muteBackup[lane][c], words[c][lane], sizeof (juce::uint16) * 5);
            std::memcpy (words[c][lane], identityWords, sizeof (juce::uint16) * 5);
        }
        muteBackupValid[lane] = true;
        statusLine = "S" + juce::String (lane + 1) + " OFF (identity)";
    }
    dirty = true;
    packAndInstall();
    repaint();
}

void WorkstationEditor::insertSourceLane()
{
    if (! hasBody || ! hasSource)
        return;
    pushUndo();
    for (int c = 0; c < 4; ++c)
        std::memcpy (words[c][selectedLane], sourceWords[c][sourceLane], sizeof (juce::uint16) * 5);
    muteBackupValid[selectedLane] = false;
    dirty = true;
    packAndInstall();
    statusLine = "INSERT " + sourceName + " S" + juce::String (sourceLane + 1)
               + " -> S" + juce::String (selectedLane + 1);
    repaint();
}

void WorkstationEditor::insertSourceLaneAtCorner()
{
    if (! hasBody || ! hasSource)
        return;
    pushUndo();
    std::memcpy (words[activeCorner][selectedLane], sourceWords[activeCorner][sourceLane],
                 sizeof (juce::uint16) * 5);
    muteBackupValid[selectedLane] = false;
    dirty = true;
    packAndInstall();
    statusLine = "INSERT " + sourceName + " S" + juce::String (sourceLane + 1)
               + " -> S" + juce::String (selectedLane + 1) + " @ " + kCornerLabels[activeCorner] + " ONLY";
    repaint();
}

void WorkstationEditor::moveLane (int from, int to)
{
    if (! hasBody || from == to || from < 0 || from >= 6 || to < 0 || to >= 6)
        return;
    pushUndo();
    // reorder: pull the lane out, shift the gap closed, drop it at the target.
    // legal because stage slot i stays paired across all 4 corners.
    const int step = (to > from) ? 1 : -1;
    for (int c = 0; c < 4; ++c)
    {
        juce::uint16 held[5];
        std::memcpy (held, words[c][from], sizeof held);
        for (int lane = from; lane != to; lane += step)
            std::memcpy (words[c][lane], words[c][lane + step], sizeof held);
        std::memcpy (words[c][to], held, sizeof held);
    }
    {
        juce::uint16 heldBackup[4][5];
        std::memcpy (heldBackup, muteBackup[from], sizeof heldBackup);
        const bool heldValid = muteBackupValid[from];
        for (int lane = from; lane != to; lane += step)
        {
            std::memcpy (muteBackup[lane], muteBackup[lane + step], sizeof heldBackup);
            muteBackupValid[lane] = muteBackupValid[lane + step];
        }
        std::memcpy (muteBackup[to], heldBackup, sizeof heldBackup);
        muteBackupValid[to] = heldValid;
    }
    if (selectedLane == from)
        selectedLane = to;
    dirty = true;
    packAndInstall();
    statusLine = "MOVE S" + juce::String (from + 1) + " -> S" + juce::String (to + 1);
    repaint();
}

void WorkstationEditor::copyPoseToCorner (int donorCorner, int corner)
{
    if (! hasSource || donorCorner < 0 || donorCorner > 3 || corner < 0 || corner > 3)
        return;

    // A bank pose is enough to begin. Seed the untouched corners from the same
    // measured/P2K body, then replace only the requested corner. This avoids an
    // invented "blank" body and gives RESET a real packed source.
    if (! hasBody)
    {
        std::memcpy (&words[0][0][0], &sourceWords[0][0][0], sizeof (juce::uint16) * 120);
        workingBytes = sourceBytes;
        loadedBytes = sourceBytes;
        hasBody = true;
        dirty = false;
        bodyName = sourceName;
        nameField.setText (sourceName, juce::dontSendNotification);
        undoStack.clear();
        pushUndo();
    }
    else
    {
        pushUndo();
    }

    for (int lane = 0; lane < 6; ++lane)
        std::memcpy (words[corner][lane], sourceWords[donorCorner][lane], sizeof (juce::uint16) * 5);
    std::fill (std::begin (muteBackupValid), std::end (muteBackupValid), false);
    dirty = true;
    packAndInstall();
    activeCorner = corner;      // select for editing; the XY puck never moves
    statusLine = "POSE " + sourceName + " " + kCornerLabels[donorCorner]
               + " -> " + kCornerLabels[corner];
    repaint();
}

bool WorkstationEditor::regenerateQLawEdge()
{
    if (! hasBody || ! hasQLaw)
        return false;

    juce::uint16 previous[2][6][5] {};
    std::memcpy (previous[0], words[2], sizeof previous);

    const auto transformed = [] (double current, double lawLo, double lawHi,
                                 bool frequency) -> double
    {
        if (! std::isfinite (current) || ! std::isfinite (lawLo) || ! std::isfinite (lawHi))
            return current;
        if (frequency)
        {
            if (current <= 0.0 || lawLo <= 0.0 || lawHi <= 0.0)
                return current;
            return juce::jlimit (0.0, (double) kMaxHz, current * lawHi / lawLo);
        }

        // Radii are transformed in bandwidth space: (1-r). This preserves the
        // source body's real tighten/loosen ratio instead of adding a generic
        // radius bump.
        if (current >= 0.0 && current < 1.0 && lawLo >= 0.0 && lawLo < 1.0
            && lawHi >= 0.0 && lawHi < 1.0 && (1.0 - lawLo) > 1.0e-9)
            return juce::jlimit (0.0, 0.9999,
                                 1.0 - (1.0 - current) * ((1.0 - lawHi) / (1.0 - lawLo)));

        if (std::abs (lawLo) > 1.0e-9)
            return current * lawHi / lawLo;
        return current;
    };

    for (int morph = 0; morph < 2; ++morph)
    {
        const int generated = morph + 2;
        for (int stage = 0; stage < 6; ++stage)
        {
            if (std::memcmp (words[morph][stage], identityWords, sizeof identityWords) == 0)
            {
                std::memcpy (words[generated][stage], identityWords, sizeof identityWords);
                continue;
            }

            double current[5] {}, lawLo[5] {}, lawHi[5] {};
            if (trench_stage_roots_from_words (words[morph][stage], current) != 0
                || trench_stage_roots_from_words (qLawWords[morph][stage], lawLo) != 0
                || trench_stage_roots_from_words (qLawWords[generated][stage], lawHi) != 0)
            {
                // A real-pair/degenerate source row has no safe conjugate-root
                // transform. Hold the authored endpoint rather than inventing.
                std::memcpy (words[generated][stage], words[morph][stage],
                             sizeof (juce::uint16) * 5);
                continue;
            }

            double out[5] {
                transformed (current[0], lawLo[0], lawHi[0], true),
                transformed (current[1], lawLo[1], lawHi[1], false),
                transformed (current[2], lawLo[2], lawHi[2], true),
                transformed (current[3], lawLo[3], lawHi[3], false),
                transformed (current[4], lawLo[4], lawHi[4], false),
            };
            if (trench_stage_words_from_roots (out, words[generated][stage]) != 0)
                std::memcpy (words[generated][stage], words[morph][stage],
                             sizeof (juce::uint16) * 5);
        }
    }

    if (! packAndInstall())
    {
        std::memcpy (words[2], previous[0], sizeof previous);
        packAndInstall();
        statusLine = "Q LAW rejected by packed-runtime stability gate";
        return false;
    }
    curvesStale = true;
    return true;
}

// MD-Q: generate the Q100 banks from the authored morph pair with the
// MEASURED ROM law (2026-07-25, all 51 P2K banks, both stage geometries):
// pole bandwidth x 0.375 (typed_vowl independently measured 0.356), gain
// UNTOUCHED (the manual's per-type gain claim is its wheel routing, not
// bank content), zeros hold, direction by pole/zero dominance (~25% of ROM
// stages loosen under Q), vocal-atlas corridor ceiling r 0.998.
void WorkstationEditor::applyMeasuredQLaw()
{
    if (! hasBody)
        return;
    pushUndo();
    constexpr double kBw = 0.375;
    constexpr double kCeil = 0.998;
    juce::uint16 previous[2][6][5] {};
    std::memcpy (previous[0], words[2], sizeof previous);
    int transposed = 0;
    for (int morph = 0; morph < 2; ++morph)
    {
        const int generated = morph + 2;
        for (int stage = 0; stage < 6; ++stage)
        {
            double roots[5] {};
            if (std::memcmp (words[morph][stage], identityWords, sizeof identityWords) == 0
                || trench_stage_roots_from_words (words[morph][stage], roots) != 0)
            {
                std::memcpy (words[generated][stage], words[morph][stage], sizeof (juce::uint16) * 5);
                continue;   // identity + real-pair rows keep a flat Q axis, honestly
            }
            const double k = (roots[1] >= roots[3]) ? kBw : 1.0 / kBw;
            roots[1] = juce::jmin (kCeil, 1.0 - (1.0 - roots[1]) * k);
            juce::uint16 encoded[5];
            if (trench_stage_words_from_roots (roots, encoded) == 0)
            {
                std::memcpy (words[generated][stage], encoded, sizeof encoded);
                ++transposed;
            }
            else
                std::memcpy (words[generated][stage], words[morph][stage], sizeof (juce::uint16) * 5);
        }
    }
    std::fill (std::begin (muteBackupValid), std::end (muteBackupValid), false);
    dirty = true;
    if (! packAndInstall())
    {
        std::memcpy (words[2], previous[0], sizeof previous);
        packAndInstall();
        statusLine = "MD-Q rejected by the stability gate - reverted";
    }
    else
        statusLine = "MD-Q: " + juce::String (transposed)
                   + " stage-ends transposed (bw x0.375 measured, zeros hold, ceiling r 0.998)";
    repaint();
}

void WorkstationEditor::useSourceAsQLaw()
{
    if (! hasBody || ! hasSource)
    {
        statusLine = "load two Morph endpoints before choosing a Q law";
        repaint();
        return;
    }
    pushUndo();
    std::memcpy (qLawWords, sourceWords, sizeof qLawWords);
    qLawName = sourceName;
    hasQLaw = true;
    if (regenerateQLawEdge())
    {
        dirty = true;
        statusLine = "Q LAW <- " + qLawName + "  |  generated Q100 from both Q0 endpoints";
    }
    repaint();
}

// ------------------------------------------------- numeric + pole-zero editing
// words are the truth: an edit goes roots -> encoder -> 5 words (the minifloat
// snap), and every display re-derives from those words.

void WorkstationEditor::setStageRoot (int field, double value)
{
    if (! hasBody)
        return;
    double roots[5] {};
    if (trench_stage_roots_from_words (words[activeCorner][selectedLane], roots) != 0)
    {
        // degenerate / real-pair rows have no conjugate reading: editing one
        // REPLACES it, starting from the identity row's roots (0,0,0,0,1)
        roots[0] = roots[1] = roots[2] = roots[3] = 0.0;
        roots[4] = 1.0;
        statusLine = "degenerate row recast as conjugate stage";
    }
    pushUndo();
    roots[juce::jlimit (0, 4, field)] = value;
    juce::uint16 encoded[5];
    if (trench_stage_words_from_roots (roots, encoded) != 0)
    {
        statusLine = "encode failed (out of range)";
        repaint();
        return;
    }
    std::memcpy (words[activeCorner][selectedLane], encoded, sizeof encoded);
    muteBackupValid[selectedLane] = false;
    dirty = true;
    packAndInstall();
    double snapped[5] {};
    if (trench_stage_roots_from_words (words[activeCorner][selectedLane], snapped) == 0)
        statusLine = juce::String::formatted ("S%d %s  pole %.0f Hz r %.4f   zero %.0f Hz r %.3f   scale %.3f",
                                              selectedLane + 1, kCornerLabels[activeCorner],
                                              snapped[0], snapped[1], snapped[2], snapped[3], snapped[4]);
    repaint();
}

void WorkstationEditor::setPoleZero (bool zero, double hz, double r, bool light)
{
    if (! hasBody)
        return;
    double roots[5] {};
    if (trench_stage_roots_from_words (words[activeCorner][selectedLane], roots) != 0)
    {
        // real-pair rows carry shelf/tilt character the pair editor cannot
        // express - replacing them silently caused huge jumps. Explicit
        // recast lives in PROPERTIES typing only.
        statusLine = "S" + juce::String (selectedLane + 1)
                   + " is a real-pair row - drag refused (type in 5-STAGE DETAIL to recast it)";
        repaint();
        return;
    }
    roots[zero ? 2 : 0] = juce::jlimit (0.0, kEvalSampleRate * 0.5, hz);
    roots[zero ? 3 : 1] = juce::jlimit (0.0, zero ? 1.0 : 0.99997, r);
    juce::uint16 encoded[5];
    if (trench_stage_words_from_roots (roots, encoded) != 0)
        return;
    std::memcpy (words[activeCorner][selectedLane], encoded, sizeof encoded);
    muteBackupValid[selectedLane] = false;
    dirty = true;
    packAndInstall (! light);
    repaint();
}

void WorkstationEditor::beginPropEdit (int field)
{
    if (! hasBody)
        return;
    double roots[5] {};
    if (trench_stage_roots_from_words (words[activeCorner][selectedLane], roots) != 0)
    {
        roots[0] = roots[1] = roots[2] = roots[3] = 0.0;
        roots[4] = 1.0;
    }
    editingProp = field;
    propEditor.setBounds (propValueArea (field));
    propEditor.setText (juce::String (roots[field], field == 0 || field == 2 ? 1 : 5), juce::dontSendNotification);
    propEditor.setVisible (true);
    propEditor.grabKeyboardFocus();
    propEditor.selectAll();
}

void WorkstationEditor::commitPropEdit()
{
    const int field = editingProp;
    editingProp = -1;
    const auto text = propEditor.getText();
    propEditor.setVisible (false);
    if (field >= 0 && text.isNotEmpty())
        setStageRoot (field, text.getDoubleValue());
}

// measured rails -> stage donors. Selection law = the proven hedz+hrtf recipe
// (dev/tmp/build_hedz_hrtf.py): complex in-band poles by descending r, paired
// with the nearest-in-log-frequency zero, unity peak scale COMPUTED, encoder-
// snapped. Rails' fitted r is already stability-capped by the fitter.
void WorkstationEditor::loadRail (const juce::File& file, const juce::String& name)
{
    const auto parsed = juce::JSON::parse (file);
    const auto* list = parsed.getArray();
    if (list == nullptr)
    {
        // trajectory rail (phononic): waypoints carry measured notches.
        // notch -> pair by the atlas law: zero r = alpha, pole r = exp(-pi*fwhm/sr).
        const auto* obj = parsed.getDynamicObject();
        const auto* wps = obj != nullptr ? obj->getProperty ("waypoints").getArray() : nullptr;
        if (wps == nullptr)
        {
            statusLine = name + ": unreadable rail";
            repaint();
            return;
        }
        railEntries.clear();
        for (const auto& wpVar : *wps)
        {
            const auto* wp = wpVar.getDynamicObject();
            if (wp == nullptr)
                continue;
            RailEntry entry;
            entry.name = "waypoint " + wp->getProperty ("waypoint").toString();
            if (const auto* notches = wp->getProperty ("notches").getArray())
            {
                for (const auto& nv : *notches)
                {
                    const auto* no = nv.getDynamicObject();
                    if (no == nullptr)
                        continue;
                    const double hz = (double) no->getProperty ("hz");
                    const double alpha = (double) no->getProperty ("alpha");
                    const double fwhm = (double) no->getProperty ("fwhm_hz");
                    if (hz < 200.0 || hz > kEvalSampleRate * 0.45)
                        continue;
                    RailPair pair { hz,
                                    juce::jlimit (0.5, 0.998, std::exp (-juce::MathConstants<double>::pi * fwhm / kEvalSampleRate)),
                                    hz,
                                    juce::jlimit (0.0, 1.0, alpha) };
                    entry.pairs.push_back (pair);
                }
            }
            std::sort (entry.pairs.begin(), entry.pairs.end(),
                       [] (const RailPair& a, const RailPair& b) { return a.poleHz < b.poleHz; });
            if (entry.pairs.size() > 6)
                entry.pairs.resize (6);
            if (! entry.pairs.empty())
                railEntries.push_back (std::move (entry));
        }
        if (railEntries.empty())
        {
            statusLine = name + ": no usable notches";
            repaint();
            return;
        }
        railSourceName = name;
        railFile = file;
        railActive = true;
        hasSource = false;
        selectRailEntry (0);
        return;
    }
    railEntries.clear();
    for (const auto& entryVar : *list)
    {
        const auto* obj = entryVar.getDynamicObject();
        if (obj == nullptr)
            continue;
        RailEntry entry;
        entry.name = obj->getProperty ("id").toString();
        if (const auto* cm = obj->getProperty ("coeffs_measured").getDynamicObject())
        {
            if (const auto* bArr = cm->getProperty ("b").getArray())
                for (const auto& v : *bArr) entry.bMeas.push_back ((double) v);
            if (const auto* aArr = cm->getProperty ("a").getArray())
                for (const auto& v : *aArr) entry.aMeas.push_back ((double) v);
        }
        std::vector<RailPair> poles;
        const auto polesVar = obj->getProperty ("poles");
        const auto zerosVar = obj->getProperty ("zeros");
        if (! polesVar.isArray())
            continue;
        struct Root { double hz, r; };
        std::vector<Root> zs;
        if (zerosVar.isArray())
            for (const auto& z : *zerosVar.getArray())
                if (const auto* zo = z.getDynamicObject())
                    if ((double) zo->getProperty ("hz") > 100.0)
                        zs.push_back ({ (double) zo->getProperty ("hz"),
                                        juce::jmin (1.0, (double) zo->getProperty ("r")) });
        for (const auto& pv : *polesVar.getArray())
        {
            const auto* po = pv.getDynamicObject();
            if (po == nullptr)
                continue;
            const double hz = (double) po->getProperty ("hz");
            const double r = (double) po->getProperty ("r");
            if (hz < 200.0 || hz > kEvalSampleRate * 0.45)
                continue;
            RailPair pair { hz, juce::jmin (0.998, r), hz, 0.5 };
            if (! zs.empty())
            {
                const auto& z = *std::min_element (zs.begin(), zs.end(),
                    [hz] (const Root& a, const Root& b)
                    { return std::abs (std::log (a.hz / hz)) < std::abs (std::log (b.hz / hz)); });
                pair.zeroHz = z.hz;
                pair.zeroR = z.r;
            }
            poles.push_back (pair);
        }
        // the fitter lists both conjugate halves: keep one per frequency
        std::sort (poles.begin(), poles.end(),
                   [] (const RailPair& a, const RailPair& b) { return a.poleHz < b.poleHz; });
        poles.erase (std::unique (poles.begin(), poles.end(),
                                  [] (const RailPair& a, const RailPair& b)
                                  { return std::abs (a.poleHz - b.poleHz) < 1.0; }),
                     poles.end());
        std::sort (poles.begin(), poles.end(),
                   [] (const RailPair& a, const RailPair& b) { return a.poleR > b.poleR; });
        if (poles.size() > 6)
            poles.resize (6);
        std::sort (poles.begin(), poles.end(),
                   [] (const RailPair& a, const RailPair& b) { return a.poleHz < b.poleHz; });
        entry.pairs = std::move (poles);
        if (! entry.pairs.empty())
            railEntries.push_back (std::move (entry));
    }
    if (railEntries.empty())
    {
        statusLine = name + ": no usable complex pairs";
        repaint();
        return;
    }
    railSourceName = name;
    railFile = file;
    railActive = true;
    hasSource = false;          // the tray shows one donor at a time
    selectRailEntry (0);
}

void WorkstationEditor::selectRailEntry (int index)
{
    if (railEntries.empty())
        return;
    railIndex = (index % (int) railEntries.size() + (int) railEntries.size()) % (int) railEntries.size();
    const auto& entry = railEntries[(size_t) railIndex];
    for (int chip = 0; chip < 6; ++chip)
    {
        railChipValid[chip] = chip < (int) entry.pairs.size();
        if (! railChipValid[chip])
            continue;
        const auto& pr = entry.pairs[(size_t) chip];
        // unity peak scale, computed from the pair (never chosen by hand)
        const double w0 = juce::MathConstants<double>::twoPi * pr.poleHz / kEvalSampleRate;
        const double wz = juce::MathConstants<double>::twoPi * pr.zeroHz / kEvalSampleRate;
        const std::complex<double> z1 (std::cos (-w0), std::sin (-w0));
        const auto z2 = z1 * z1;
        const auto num = 1.0 - 2.0 * pr.zeroR * std::cos (wz) * z1 + pr.zeroR * pr.zeroR * z2;
        const auto den = 1.0 - 2.0 * pr.poleR * std::cos (w0) * z1 + pr.poleR * pr.poleR * z2;
        const double scale = 1.0 / juce::jmax (1e-6, std::abs (num / den));
        const double roots[5] = { pr.poleHz, pr.poleR, pr.zeroHz, pr.zeroR, scale };
        railChipValid[chip] = trench_stage_words_from_roots (roots, railChipWords[chip]) == 0;
    }
    // the POSE: all pairs as one six-stage cascade, scales trimmed against the
    // entry's OWN measured response, residual reported honestly
    railPoseResidualDb = -1.0;
    for (int stage = 0; stage < 6; ++stage)
        std::memcpy (railPoseWords[stage], identityWords, sizeof identityWords);
    {
        const int n = juce::jmin (6, (int) entry.pairs.size());
        double scales[6] {};
        double roots[6][5] {};
        bool ok = n > 0;
        for (int stage = 0; stage < n && ok; ++stage)
        {
            const auto& pr = entry.pairs[(size_t) stage];
            const double w0 = juce::MathConstants<double>::twoPi * pr.poleHz / kEvalSampleRate;
            const double wz = juce::MathConstants<double>::twoPi * pr.zeroHz / kEvalSampleRate;
            const std::complex<double> z1 (std::cos (-w0), std::sin (-w0));
            const auto z2 = z1 * z1;
            const auto num = 1.0 - 2.0 * pr.zeroR * std::cos (wz) * z1 + pr.zeroR * pr.zeroR * z2;
            const auto den = 1.0 - 2.0 * pr.poleR * std::cos (w0) * z1 + pr.poleR * pr.poleR * z2;
            scales[stage] = 1.0 / juce::jmax (1e-6, std::abs (num / den));
            roots[stage][0] = pr.poleHz; roots[stage][1] = pr.poleR;
            roots[stage][2] = pr.zeroHz; roots[stage][3] = pr.zeroR;
        }
        const auto cascadeDb = [&] (double hz) -> double
        {
            const double w = juce::MathConstants<double>::twoPi * hz / kEvalSampleRate;
            const std::complex<double> z1 (std::cos (-w), std::sin (-w));
            const auto z2 = z1 * z1;
            double db = 0.0;
            for (int stage = 0; stage < n; ++stage)
            {
                const double w0 = juce::MathConstants<double>::twoPi * roots[stage][0] / kEvalSampleRate;
                const double wz = juce::MathConstants<double>::twoPi * roots[stage][2] / kEvalSampleRate;
                const auto num = 1.0 - 2.0 * roots[stage][3] * std::cos (wz) * z1 + roots[stage][3] * roots[stage][3] * z2;
                const auto den = 1.0 - 2.0 * roots[stage][1] * std::cos (w0) * z1 + roots[stage][1] * roots[stage][1] * z2;
                db += 20.0 * std::log10 (juce::jmax (1e-9, scales[stage] * std::abs (num / den)));
            }
            return db;
        };
        const auto measuredDb = [&] (double hz) -> double
        {
            if (entry.bMeas.empty() || entry.aMeas.empty())
                return 0.0;
            const double w = juce::MathConstants<double>::twoPi * hz / kEvalSampleRate;
            std::complex<double> nsum (0.0, 0.0), dsum (0.0, 0.0), zk (1.0, 0.0);
            const std::complex<double> z1 (std::cos (-w), std::sin (-w));
            for (size_t k = 0; k < entry.bMeas.size() || k < entry.aMeas.size(); ++k)
            {
                if (k < entry.bMeas.size()) nsum += entry.bMeas[k] * zk;
                if (k < entry.aMeas.size()) dsum += entry.aMeas[k] * zk;
                zk *= z1;
            }
            return 20.0 * std::log10 (juce::jmax (1e-9, std::abs (nsum) / juce::jmax (1e-12, std::abs (dsum))));
        };
        if (ok)
        {
            const bool haveMeasured = ! entry.bMeas.empty() && ! entry.aMeas.empty();
            constexpr int kFitPts = 96;
            double meanErr = 0.0;
            if (haveMeasured)
            {
                for (int i = 0; i < kFitPts; ++i)
                {
                    const double hz = 200.0 * std::pow (16000.0 / 200.0, (double) i / (kFitPts - 1));
                    meanErr += measuredDb (hz) - cascadeDb (hz);
                }
                meanErr /= kFitPts;
                // distribute the mean level correction across the stages
                const double perStage = std::pow (10.0, meanErr / 20.0 / n);
                for (int stage = 0; stage < n; ++stage)
                    scales[stage] *= perStage;
            }
            for (int stage = 0; stage < n && ok; ++stage)
            {
                roots[stage][4] = scales[stage];
                ok = trench_stage_words_from_roots (roots[stage], railPoseWords[stage]) == 0;
            }
            if (ok && haveMeasured)
            {
                double rss = 0.0;
                for (int i = 0; i < kFitPts; ++i)
                {
                    const double hz = 200.0 * std::pow (16000.0 / 200.0, (double) i / (kFitPts - 1));
                    const double e = measuredDb (hz) - cascadeDb (hz);
                    rss += e * e;
                }
                railPoseResidualDb = std::sqrt (rss / kFitPts);
            }
        }
    }
    statusLine = "RAIL " + railSourceName + "  " + entry.name
               + "  (" + juce::String (railIndex + 1) + "/" + juce::String ((int) railEntries.size()) + ")"
               + (railPoseResidualDb >= 0.0
                      ? "  |  pose fit residual " + juce::String (railPoseResidualDb, 1) + " dB (200-16k)"
                      : "");
    repaint();
}

void WorkstationEditor::applyRailPose (int corner)
{
    if (! hasBody || ! railActive || corner < 0 || corner > 3)
        return;
    pushUndo();
    for (int stage = 0; stage < 6; ++stage)
        std::memcpy (words[corner][stage], railPoseWords[stage], sizeof (juce::uint16) * 5);
    std::fill (std::begin (muteBackupValid), std::end (muteBackupValid), false);
    dirty = true;
    packAndInstall();
    activeCorner = corner;
    statusLine = "RAIL POSE " + railEntries[(size_t) railIndex].name + " -> " + kCornerLabels[corner]
               + (railPoseResidualDb >= 0.0
                      ? "  |  residual " + juce::String (railPoseResidualDb, 1) + " dB"
                      : "");
    repaint();
}

juce::Rectangle<int> WorkstationEditor::railPoseChipArea() const
{
    const auto b = trayArea();
    return { b.getX() + 8, b.getY() + 22, 96, 66 };
}

juce::Rectangle<int> WorkstationEditor::railFitArea() const
{
    const auto b = trayArea();
    return { b.getRight() - 148, b.getY() + 3, 44, 16 };
}

void WorkstationEditor::startRailFit()
{
    if (railFitting || railEntries.empty())
        return;
    railFitOut = juce::File::getSpecialLocation (juce::File::tempDirectory)
                     .getChildFile ("trench_rail_fit.json");
    railFitOut.deleteFile();
    juce::StringArray cmd { "C:/Users/hooki/AppData/Local/Programs/Python/Python310/python.exe",
                            "C:/Users/hooki/df2/tools/rail_fit_pose.py",
                            "--rail", railFile.getFullPathName(),
                            "--entry", railEntries[(size_t) railIndex].name,
                            "--out", railFitOut.getFullPathName() };
    if (railFitProcess.start (cmd))
    {
        railFitting = true;
        statusLine = "FORGE FIT running: " + railEntries[(size_t) railIndex].name
                   + "  (phase-aware, ~2-3 min; keep working)";
    }
    else
    {
        statusLine = "could not start the forge fitter";
    }
    repaint();
}

void WorkstationEditor::finishRailFit()
{
    railFitting = false;
    const auto parsed = juce::JSON::parse (railFitOut);
    const auto* obj = parsed.getDynamicObject();
    const auto* rows = obj != nullptr ? obj->getProperty ("words").getArray() : nullptr;
    if (rows == nullptr || rows->size() != 6)
    {
        statusLine = "forge fit failed - see rail_fit_pose output";
        repaint();
        return;
    }
    for (int stage = 0; stage < 6; ++stage)
    {
        const auto* row = (*rows)[stage].getArray();
        if (row == nullptr || row->size() != 5)
            continue;
        for (int k = 0; k < 5; ++k)
            railPoseWords[stage][k] = (juce::uint16) (int) (*row)[k];
    }
    railPoseResidualDb = -1.0;   // the fitter reports a NULL, not my residual metric
    statusLine = "FORGE FIT " + obj->getProperty ("entry").toString()
               + "  null " + juce::String ((double) obj->getProperty ("null_db"), 1)
               + " dB  -> POSE chip updated (drop it on a corner)";
    repaint();
}

void WorkstationEditor::insertRailStage (int chip, int lane, bool cornerOnly)
{
    if (! hasBody || ! railActive || chip < 0 || chip >= 6 || ! railChipValid[chip])
        return;
    pushUndo();
    for (int c = 0; c < 4; ++c)
    {
        if (cornerOnly && c != activeCorner)
            continue;
        std::memcpy (words[c][juce::jlimit (0, 5, lane)], railChipWords[chip], sizeof (juce::uint16) * 5);
    }
    muteBackupValid[juce::jlimit (0, 5, lane)] = false;
    dirty = true;
    packAndInstall();
    statusLine = "RAIL " + railEntries[(size_t) railIndex].name + " #" + juce::String (chip + 1)
               + " -> S" + juce::String (lane + 1) + (cornerOnly ? juce::String (" @ ") + kCornerLabels[activeCorner] : juce::String (" (all corners)"));
    repaint();
}

juce::Rectangle<int> WorkstationEditor::railPrevArea() const
{
    const auto b = trayArea();
    return { b.getRight() - 96, b.getY() + 3, 30, 16 };
}

juce::Rectangle<int> WorkstationEditor::railNextArea() const
{
    const auto b = trayArea();
    return { b.getRight() - 60, b.getY() + 3, 30, 16 };
}

void WorkstationEditor::saveWorkingBody()
{
    if (! hasBody)
        return;
    if (dirty && ! lastCertifyPass)
    {
        statusLine = "refusing to save an unstable body";
        repaint();
        return;
    }
    auto name = nameField.getText().trim();
    if (name.isEmpty())
        name = bodyName;
    const auto f = processor.forgeSaveBody (name);
    if (f.existsAsFile())
    {
        dirty = false;
        statusLine = "SAVED -> " + f.getFullPathName();
        scanBin();
    }
    else
    {
        statusLine = "save failed";
    }
    repaint();
}

void WorkstationEditor::loadReference (int refIndex)
{
    if (refIndex == activeRef)
    {
        activeRef = -1;
        refName.clear();
        repaint();
        return;
    }
    if (refIndex < 0 || refIndex >= (int) refItems.size())
        return;
    const auto parsed = juce::JSON::parse (refItems[(size_t) refIndex].file);
    const auto* obj = parsed.getDynamicObject();
    if (obj == nullptr)
        return;
    const auto freqs = obj->getProperty ("freqs_hz");
    const auto corners = obj->getProperty ("corners");
    if (! freqs.isArray() || corners.getDynamicObject() == nullptr)
        return;
    refFreqs.clear();
    for (const auto& v : *freqs.getArray())
        refFreqs.push_back ((float) (double) v);
    for (int c = 0; c < 4; ++c)
    {
        refCornerDb[(size_t) c].clear();
        const auto arr = corners.getDynamicObject()->getProperty (kCornerLabels[c]);
        if (arr.isArray())
            for (const auto& v : *arr.getArray())
                refCornerDb[(size_t) c].push_back ((float) (double) v);
    }
    activeRef = refIndex;
    refName = refItems[(size_t) refIndex].name;
    statusLine = "GHOST <- X3 " + refName;
    repaint();
}

// ---------------------------------------------------------------- parameters

float WorkstationEditor::paramValue (const char* paramID) const
{
    if (auto* param = processor.apvts.getParameter (paramID))
        return param->getValue();
    return 0.0f;
}

void WorkstationEditor::setParamValue (const char* paramID, float normalized)
{
    if (auto* param = processor.apvts.getParameter (paramID))
        param->setValueNotifyingHost (juce::jlimit (0.0f, 1.0f, normalized));
}

void WorkstationEditor::jumpToPose (int corner)
{
    activeCorner = juce::jlimit (0, 3, corner);
    setParamValue (ParamID::morph, (activeCorner == 1 || activeCorner == 3) ? 1.0f : 0.0f);
    setParamValue (ParamID::q, activeCorner >= 2 ? 1.0f : 0.0f);
}

// ---------------------------------------------------------------- probing

void WorkstationEditor::refreshCurves()
{
    const float morph = paramValue (ParamID::morph);
    const float q = paramValue (ParamID::q);
    lastProbedMorph = morph;
    lastProbedQ = q;
    curvesStale = false;

    const auto probeLanes = [] (const std::array<juce::uint8, 240>& bytes, float m, float qq,
                                std::array<std::array<float, kNumPlotPoints>, 6>& laneDb,
                                std::array<float, kNumPlotPoints>& sumDb,
                                float* coeffsOut = nullptr,
                                juce::uint32* unstableOut = nullptr,
                                juce::uint32* nonfiniteOut = nullptr) -> bool
    {
        // mask-aware probe: an unstable stage still DRAWS (and is flagged);
        // only nonfinite stages are excluded so they cannot poison the sum
        double biquad[30] {};
        double maxR = 0.0;
        juce::uint32 unstable = 0, nonfinite = 0;
        if (trench_packed_probe (bytes.data(), 240,
                                 (double) juce::jlimit (0.0f, 1.0f, m),
                                 (double) juce::jlimit (0.0f, 1.0f, qq),
                                 biquad, &maxR, &unstable, &nonfinite) != 0)
            return false;
        if (unstableOut != nullptr)  *unstableOut = unstable;
        if (nonfiniteOut != nullptr) *nonfiniteOut = nonfinite;
        float coeffs[30] {};
        for (int i = 0; i < 30; ++i)
            coeffs[i] = (float) biquad[i];
        if (coeffsOut != nullptr)
            std::memcpy (coeffsOut, coeffs, sizeof coeffs);
        for (int i = 0; i < kNumPlotPoints; ++i)
        {
            const float normX = (float) i / (float) (kNumPlotPoints - 1);
            const double hz = kMinHz * std::pow (kMaxHz / kMinHz, normX);
            const double w = juce::MathConstants<double>::twoPi * hz / kEvalSampleRate;
            const double cosw = std::cos (w), sinw = std::sin (w);
            const double cos2w = std::cos (2.0 * w), sin2w = std::sin (2.0 * w);
            float sum = 0.0f;
            for (int s = 0; s < 6; ++s)
            {
                if ((nonfinite & (1u << s)) != 0)
                {
                    laneDb[(size_t) s][(size_t) i] = 0.0f;
                    continue;
                }
                const float db = stageMagDb (&coeffs[s * 5], cosw, sinw, cos2w, sin2w);
                laneDb[(size_t) s][(size_t) i] = db;
                sum += db;
            }
            sumDb[(size_t) i] = sum;
        }
        return true;
    };

    programProbeOk = hasBody && probeLanes (workingBytes, morph, q, programLaneDb, programSumDb,
                                            programCoeffs, &programUnstableMask, &programNonfiniteMask);
    sourceProbeOk = hasSource && probeLanes (sourceBytes, morph, q, sourceLaneDb, sourceSumDb);

    // drag-time: hero + lanes only; corner minis catch up on release
    if (dragKind == DragKind::PZ)
        return;

    // corner minis: cascade sum only, still from the packed runtime
    std::array<std::array<float, kNumPlotPoints>, 6> scratch;
    for (int c = 0; c < 4; ++c)
    {
        const float m = (c == 1 || c == 3) ? 1.0f : 0.0f;
        const float qq = (c >= 2) ? 1.0f : 0.0f;
        cornerProbeOk[c] = hasBody && probeLanes (workingBytes, m, qq, cornerLaneDb[(size_t) c], cornerSumDb[(size_t) c]);
    }
    for (int c = 0; c < 4; ++c)
    {
        const float m = (c == 1 || c == 3) ? 1.0f : 0.0f;
        const float qq = (c >= 2) ? 1.0f : 0.0f;
        sourcePoseOk[c] = hasSource && probeLanes (sourceBytes, m, qq, scratch, sourcePoseDb[(size_t) c]);
    }
}

void WorkstationEditor::timerCallback()
{
    if (proofPending && --proofDelayTicks <= 0)
    {
        proofPending = false;
        runProofScript();
    }
    if (railFitting && ! railFitProcess.isRunning())
        finishRailFit();
    const float morph = paramValue (ParamID::morph);
    const float q = paramValue (ParamID::q);
    if (curvesStale
        || ! juce::approximatelyEqual (morph, lastProbedMorph)
        || ! juce::approximatelyEqual (q, lastProbedQ))
    {
        refreshCurves();
        repaint();
    }
}

// ---------------------------------------------------------------- proof harness

int WorkstationEditor::findNodeByStem (const juce::String& stem) const
{
    for (int i = 0; i < (int) nodes.size(); ++i)
        if (nodes[(size_t) i].stem == stem)
            return i;
    return -1;
}

void WorkstationEditor::runProofScript()
{
    const auto* actions = proofActions.getArray();
    if (actions == nullptr)
        return;
    for (const auto& actionVar : *actions)
    {
        const auto* obj = actionVar.getDynamicObject();
        if (obj == nullptr)
            continue;
        const auto action = obj->getProperty ("action").toString();
        if (action == "program")
            loadProgram (findNodeByStem (obj->getProperty ("stem").toString()));
        else if (action == "source")
            loadSource (findNodeByStem (obj->getProperty ("stem").toString()));
        else if (action == "selectLane")
            selectedLane = juce::jlimit (0, 5, (int) obj->getProperty ("lane"));
        else if (action == "sourceLane")
            sourceLane = juce::jlimit (0, 5, (int) obj->getProperty ("lane"));
        else if (action == "insert")
            insertSourceLane();
        else if (action == "rail") // measured rail -> tray
        {
            const auto name = obj->getProperty ("name").toString();
            for (const auto& node : nodes)
                if (node.kind == NodeKind::MeasuredRail && node.stem.containsIgnoreCase (name))
                {
                    loadRail (node.body, node.stem);
                    break;
                }
            if (obj->hasProperty ("entry"))
                selectRailEntry ((int) obj->getProperty ("entry"));
        }
        else if (action == "railpose")
            applyRailPose (juce::jlimit (0, 3, (int) obj->getProperty ("corner")));
        else if (action == "raildrop")
            insertRailStage (juce::jlimit (0, 5, (int) obj->getProperty ("chip")),
                             juce::jlimit (0, 5, (int) obj->getProperty ("lane")),
                             (int) obj->getProperty ("cornerOnly") != 0);
        else if (action == "dropCorner") // donor stage -> active corner only
        {
            sourceLane = juce::jlimit (0, 5, (int) obj->getProperty ("donorLane"));
            selectedLane = juce::jlimit (0, 5, (int) obj->getProperty ("lane"));
            insertSourceLaneAtCorner();
        }
        else if (action == "drop") // tray chip -> lane row (the drag-and-drop path)
        {
            sourceLane = juce::jlimit (0, 5, (int) obj->getProperty ("donorLane"));
            selectedLane = juce::jlimit (0, 5, (int) obj->getProperty ("lane"));
            insertSourceLane();
        }
        else if (action == "move") // lane drag-to-rearrange
            moveLane (juce::jlimit (0, 5, (int) obj->getProperty ("from")),
                      juce::jlimit (0, 5, (int) obj->getProperty ("to")));
        else if (action == "prop") // numeric root edit, minifloat-snapped (pushes its own undo)
            setStageRoot (juce::jlimit (0, 4, (int) obj->getProperty ("field")),
                          (double) obj->getProperty ("value"));
        else if (action == "pz")   // native pole-zero drag endpoint
        {
            pushUndo();
            setPoleZero ((bool) obj->getProperty ("zero"),
                         (double) obj->getProperty ("hz"), (double) obj->getProperty ("r"));
        }
        else if (action == "undo")
            undo();
        else if (action == "reset")
            resetProgram();
        else if (action == "redo")
            redo();
        else if (action == "mdq")
            applyMeasuredQLaw();
        else if (action == "pzopen")
            pzWindowOpen = ! obj->hasProperty ("open") || (int) obj->getProperty ("open") != 0;
        else if (action == "click") // synthetic UI click through the real hit tests
        {
            const juce::Point<int> at ((int) obj->getProperty ("x"), (int) obj->getProperty ("y"));
            auto& source = juce::Desktop::getInstance().getMainMouseSource();
            const juce::MouseEvent ev (source, at.toFloat(), juce::ModifierKeys(),
                                       0.0f, 0.0f, 0.0f, 0.0f, 0.0f,
                                       this, this, juce::Time::getCurrentTime(),
                                       at.toFloat(), juce::Time::getCurrentTime(), 1, false);
            mouseDown (ev);
            mouseUp (ev);
        }
        else if (action == "off")
            toggleLaneOff (juce::jlimit (0, 5, (int) obj->getProperty ("lane")));
        else if (action == "ghost")
        {
            for (int i = 0; i < (int) refItems.size(); ++i)
                if (refItems[(size_t) i].name == obj->getProperty ("name").toString())
                {
                    loadReference (i);
                    break;
                }
        }
        else if (action == "pose")
            jumpToPose ((int) obj->getProperty ("corner"));
        else if (action == "xy")
        {
            setParamValue (ParamID::morph, (float) (double) obj->getProperty ("m"));
            setParamValue (ParamID::q, (float) (double) obj->getProperty ("q"));
        }
        else if (action == "filter")
        {
            binQuery = obj->getProperty ("text").toString().trim().toLowerCase();
            binSearch.setText (binQuery, juce::dontSendNotification);
            binScroll = 0;
            rebuildRows();
            repaint();
        }
        else if (action == "posefrom") // donor pose chip -> grid corner
            copyPoseToCorner (juce::jlimit (0, 3, (int) obj->getProperty ("donorCorner")),
                              juce::jlimit (0, 3, (int) obj->getProperty ("corner")));
        else if (action == "designer")   // open/close the Designer panel
        {
            const bool wantOpen = ! obj->hasProperty ("open") || (int) obj->getProperty ("open") != 0;
            if (designerOpen != wantOpen)
                toggleDesigner();
        }
        else if (action == "dpage")
        {
            designerPage = juce::jlimit (0, 1, (int) obj->getProperty ("page"));
            designerRefreshJourney();
        }
        else if (action == "dtype")
        {
            dsections[designerPage][juce::jlimit (0, 5, (int) obj->getProperty ("stage"))].type =
                juce::jlimit (0, 4, (int) obj->getProperty ("type"));
            designerApply();
        }
        else if (action == "dset")       // fields: typed 0 FREQ 1 GAIN; FREE 0 pHz 1 pR 2 scale 3 zHz 4 zR
        {
            designerSetField (juce::jlimit (0, 5, (int) obj->getProperty ("stage")),
                              juce::jlimit (0, 1, (int) obj->getProperty ("row")),
                              juce::jlimit (0, 4, (int) obj->getProperty ("field")),
                              (double) obj->getProperty ("value"));
            designerApply();
        }
        else if (action == "dshift")
        {
            designerShift = juce::jlimit (-32, 31, (int) obj->getProperty ("value"));
            designerApply();
        }
        else if (action == "dtemplate")
            designerSetTemplate (juce::jlimit (0, 7, (int) obj->getProperty ("index")));
        else if (action == "dmotif")
            designerApplyMotif (juce::jlimit (0, 5, (int) obj->getProperty ("stage")),
                                juce::jlimit (0, 4, (int) obj->getProperty ("motif")));
        else if (action == "dsketch")
            designerSketchQ100();
        else if (action == "dfamily")
        {
            designerFamily = juce::jlimit (0, 1, (int) obj->getProperty ("family"));
            designerJourneyPass = designerJourneyGate();
        }
        else if (action == "ddump")   // proof: working bytes, pre-frame, byte-comparable
        {
            juce::File out (obj->getProperty ("path").toString());
            out.deleteFile();
            out.replaceWithData (workingBytes.data(), workingBytes.size());
        }
        else if (action == "dsave")
        {
            if (obj->hasProperty ("name"))
                nameField.setText (obj->getProperty ("name").toString(), juce::dontSendNotification);
            designerSaveBody();
        }
        else if (action == "save")
        {
            nameField.setText (obj->getProperty ("name").toString(), juce::dontSendNotification);
            saveWorkingBody();
        }
        else if (action == "shot")
        {
            refreshCurves();
            const auto image = createComponentSnapshot (getLocalBounds());
            juce::File out (obj->getProperty ("path").toString());
            out.deleteFile();
            juce::FileOutputStream stream (out);
            if (stream.openedOk())
                juce::PNGImageFormat().writeImageToStream (image, stream);
        }
        else if (action == "loop")
        {
            if (gWorkstationLoop != nullptr
                && gWorkstationLoop->loadFile (juce::File (obj->getProperty ("path").toString())))
                statusLine = "LOOP <- " + gWorkstationLoop->loopName();
        }
        else if (action == "play")
        {
            if (gWorkstationLoop != nullptr)
                gWorkstationLoop->setPlaying ((int) obj->getProperty ("on") != 0);
        }
        else if (action == "quit")
        {
            juce::JUCEApplication::getInstance()->systemRequestedQuit();
            return;
        }
    }
    repaint();
}

// ---------------------------------------------------------------- layout

juce::Rectangle<int> WorkstationEditor::headerArea() const { return getLocalBounds().removeFromTop (64); }
juce::Rectangle<int> WorkstationEditor::footerArea() const { return getLocalBounds().removeFromBottom (24); }

juce::Rectangle<int> WorkstationEditor::binArea() const
{
    auto b = getLocalBounds();
    b.removeFromTop (64);
    b.removeFromBottom (24);
    return b.removeFromLeft (240);
}

juce::Rectangle<int> WorkstationEditor::binSearchArea() const
{
    return binArea().reduced (5, 4).removeFromTop (22);
}

juce::Rectangle<int> WorkstationEditor::binListArea() const
{
    auto b = binArea();
    b.removeFromTop (30);
    return b;
}

juce::Rectangle<int> WorkstationEditor::propertiesArea() const
{
    auto b = getLocalBounds();
    b.removeFromTop (64);
    b.removeFromBottom (24);
    return b.removeFromRight (220);
}

juce::Rectangle<int> WorkstationEditor::centreArea() const
{
    auto b = getLocalBounds();
    b.removeFromTop (64);
    b.removeFromBottom (24);
    b.removeFromLeft (240);
    b.removeFromRight (220);
    return b;
}

juce::Rectangle<int> WorkstationEditor::lanesArea() const
{
    return centreArea().removeFromBottom (kLanesH);
}

juce::Rectangle<int> WorkstationEditor::trayArea() const
{
    auto b = centreArea();
    b.removeFromBottom (kLanesH);
    return b.removeFromBottom (kTrayH);
}

juce::Rectangle<int> WorkstationEditor::heroArea() const
{
    auto b = centreArea();
    b.removeFromBottom (kLanesH);
    b.removeFromBottom (kTrayH);
    b.removeFromLeft (juce::jmin (b.getHeight(), 320));
    return b;
}

juce::Rectangle<int> WorkstationEditor::gridArea() const
{
    auto b = centreArea();
    b.removeFromBottom (kLanesH);
    b.removeFromBottom (kTrayH);
    auto r = b.removeFromLeft (juce::jmin (b.getHeight(), 320));
    const int side = juce::jmin (r.getWidth(), r.getHeight()) - 12;
    return r.withSizeKeepingCentre (side, side);
}

juce::Rectangle<int> WorkstationEditor::gridCellArea (int corner) const
{
    // x = morph (0 left, 100 right), y = Q (0 bottom, 100 top)
    const auto g = gridArea().reduced (2);
    const int w = g.getWidth() / 2, h = g.getHeight() / 2;
    const bool m100 = (corner == 1 || corner == 3);
    const bool q100 = (corner >= 2);
    return { g.getX() + (m100 ? w : 0), g.getY() + (q100 ? 0 : h), w, h };
}

juce::Rectangle<int> WorkstationEditor::binRowArea (int visibleRow) const
{
    const auto b = binListArea().reduced (1);
    return { b.getX(), b.getY() + visibleRow * kBinRowH, b.getWidth(), kBinRowH };
}

juce::Rectangle<int> WorkstationEditor::laneRowArea (int lane) const
{
    const auto b = lanesArea().reduced (1);
    return { b.getX(), b.getY() + 20 + lane * kLaneRowH, b.getWidth(), kLaneRowH };
}

juce::Rectangle<int> WorkstationEditor::laneMiniArea (int lane) const
{
    const auto r = laneRowArea (lane);
    return { r.getX() + 34, r.getY() + 2, kLaneRowH - 4, kLaneRowH - 4 };
}

juce::Rectangle<int> WorkstationEditor::laneMiniEndArea (int lane) const
{
    const auto r = laneRowArea (lane);
    return { r.getX() + 66, r.getY() + 2, kLaneRowH - 4, kLaneRowH - 4 };
}

juce::Rectangle<int> WorkstationEditor::trayPoseChipArea (int corner) const
{
    const auto b = trayArea();
    return { b.getX() + 8 + corner * 74, b.getY() + 22, 66, 66 };
}

juce::Rectangle<int> WorkstationEditor::trayChipArea (int lane) const
{
    const auto b = trayArea();
    return { b.getX() + 8 + 4 * 74 + 24 + lane * 74, b.getY() + 22, 66, 66 };
}

juce::Rectangle<int> WorkstationEditor::trayCloseArea() const
{
    const auto b = trayArea();
    return { b.getRight() - 24, b.getY() + 3, 18, 16 };
}

juce::Rectangle<int> WorkstationEditor::nameBoxArea() const   { return { 208, 18, 190, 28 } ; }
juce::Rectangle<int> WorkstationEditor::saveButtonArea() const { return { 406, 18, 116, 28 }; }
juce::Rectangle<int> WorkstationEditor::undoButtonArea() const { return { 530, 10, 64, 20 }; }
juce::Rectangle<int> WorkstationEditor::resetButtonArea() const { return { 530, 34, 64, 20 }; }
juce::Rectangle<int> WorkstationEditor::playButtonArea() const { return { 740, 18, 74, 28 }; }
juce::Rectangle<int> WorkstationEditor::chainButtonArea() const { return { 820, 18, 74, 28 }; }
juce::Rectangle<int> WorkstationEditor::redoButtonArea() const { return { 598, 10, 64, 20 }; }

juce::Rectangle<int> WorkstationEditor::propValueArea (int field) const
{
    const auto b = propertiesArea();
    return { b.getX() + 84, b.getY() + 32 + field * 22, b.getWidth() - 96, 16 };
}

juce::Rectangle<int> WorkstationEditor::pzWindowArea() const
{
    auto c = centreArea().reduced (40, 16);
    const int side = juce::jmin (c.getWidth(), c.getHeight());
    return c.withSizeKeepingCentre (side + 120, side);
}

juce::Rectangle<int> WorkstationEditor::pzCloseArea() const
{
    const auto w = pzWindowArea();
    return { w.getRight() - 26, w.getY() + 4, 20, 18 };
}

juce::Rectangle<int> WorkstationEditor::pzOpenButtonArea() const
{
    const auto b = propertiesArea();
    return { b.getX() + 12, b.getY() + 32 + 5 * 22 + 8, b.getWidth() - 24, 24 };
}

juce::Point<float> WorkstationEditor::pzPointFor (double hz, double r) const
{
    const auto a = pzWindowArea().toFloat();
    const float scale = a.getHeight() * 0.5f - 44.0f;
    const double w = juce::MathConstants<double>::twoPi * hz / kEvalSampleRate;
    const float rr = (float) juce::jmin (r, 1.08) * scale;
    return { a.getCentreX() + rr * (float) std::cos (w),
             a.getCentreY() - rr * (float) std::sin (w) };
}

// roots of one runtime biquad: pole from (1, a1, a2), zero from (b0, b1, b2)
bool WorkstationEditor::biquadRoots (const float* c, bool zero, double& hz, double& r)
{
    double p2, p1, p0;
    if (zero)
    {
        if (std::abs (c[0]) < 1e-12)
            return false;
        p2 = 1.0; p1 = c[1] / c[0]; p0 = c[2] / c[0];
    }
    else
    {
        p2 = 1.0; p1 = c[3]; p0 = c[4];
    }
    const double disc = p1 * p1 - 4.0 * p2 * p0;
    if (disc >= 0.0)
    {
        const double r1 = (-p1 + std::sqrt (disc)) * 0.5;
        const double r2 = (-p1 - std::sqrt (disc)) * 0.5;
        const double loc = std::abs (r1) > std::abs (r2) ? r1 : r2;
        r = std::abs (loc);
        hz = loc >= 0.0 ? 0.0 : kEvalSampleRate * 0.5;
        return true;
    }
    r = std::sqrt (p0);
    hz = std::acos (juce::jlimit (-1.0, 1.0, -p1 / (2.0 * r))) / juce::MathConstants<double>::twoPi * kEvalSampleRate;
    return true;
}

void WorkstationEditor::resized()
{
    binSearch.setBounds (binSearchArea());
    nameField.setBounds (nameBoxArea());
}

juce::Rectangle<int> WorkstationEditor::mdqButtonArea() const
{
    return { 598, 34, 64, 20 };
}

juce::Rectangle<int> WorkstationEditor::pzLockArea() const
{
    return { 666, 34, 64, 20 };
}

juce::Rectangle<int> WorkstationEditor::qLawButtonArea() const
{
    const auto b = trayArea();
    return { b.getRight() - 154, b.getY() + 2, 126, 17 };
}

// ---------------------------------------------------------------- paint

float WorkstationEditor::xForFrequency (double hz, float plotLeft, float plotWidth) const
{
    const float normX = (float) (std::log (hz / kMinHz) / std::log (kMaxHz / kMinHz));
    return plotLeft + normX * plotWidth;
}

float WorkstationEditor::yForDb (float db, float plotTop, float plotHeight) const
{
    const float normY = (std::clamp (db, kMinDb, kMaxDb) - kMinDb) / (kMaxDb - kMinDb);
    return plotTop + plotHeight * (1.0f - normY);
}

void WorkstationEditor::drawFlatButton (juce::Graphics& g, juce::Rectangle<int> r, const juce::String& label,
                                        bool active, bool enabled) const
{
    const auto rf = r.toFloat();
    g.setColour (active ? kBorder : kPanelDeep);
    g.fillRect (rf);
    g.setColour (active ? kCyan.withAlpha (0.8f) : kBorder);
    g.drawRect (rf, 1.0f);
    g.setColour (! enabled ? kGridLabel : (active ? kCyan : kTextDim));
    g.setFont (juce::FontOptions (11.0f).withStyle ("Bold"));
    g.drawText (label, r, juce::Justification::centred);
}

void WorkstationEditor::drawMiniPlot (juce::Graphics& g, juce::Rectangle<float> r, const float* db, int n,
                                      juce::Colour curve, juce::Colour outline, float outlineThickness) const
{
    g.setColour (kPanelDeep);
    g.fillRect (r);
    const auto inner = r.reduced (2.0f);

    // Every response plot shares the hero's fixed dB scale. Independent
    // autoranging makes identical packed responses look different and defeats
    // visual comparison between a donor, a grid corner, and the live cascade.
    const auto yFor = [&] (float v)
    {
        const float norm = (std::clamp (v, kMinDb, kMaxDb) - kMinDb) / (kMaxDb - kMinDb);
        return inner.getY() + inner.getHeight() * (1.0f - norm);
    };

    g.setColour (juce::Colour (0x30ffffff));
    g.drawHorizontalLine (juce::roundToInt (yFor (0.0f)), inner.getX(), inner.getRight());
    if (db != nullptr && n > 1)
    {
        juce::Path path;
        for (int i = 0; i < n; ++i)
        {
            const float x = inner.getX() + ((float) i / (float) (n - 1)) * inner.getWidth();
            const float y = yFor (db[i]);
            if (i == 0)
                path.startNewSubPath (x, y);
            else
                path.lineTo (x, y);
        }
        g.setColour (curve);
        g.strokePath (path, juce::PathStrokeType (1.0f));
    }
    g.setColour (outline);
    g.drawRect (r, outlineThickness);
}

void WorkstationEditor::paint (juce::Graphics& g)
{
    g.fillAll (kBg);
    drawHeader (g);
    drawBin (g);
    drawHero (g);
    drawGrid (g);
    drawTray (g);
    drawLanes (g);
    drawProperties (g);
    drawFooter (g);
    drawPzWindow (g);
    drawDesigner (g);
    drawDragGhost (g);
}

void WorkstationEditor::drawHeader (juce::Graphics& g)
{
    const auto b = headerArea().toFloat();
    g.setColour (kPanel);
    g.fillRect (b);
    g.setColour (kBorder);
    g.drawRect (b, 1.0f);
    g.setColour (kCyan);
    g.setFont (juce::FontOptions (18.0f).withStyle ("Bold"));
    g.drawText ("TRENCH WORKSTATION", b.getX() + 14.0f, b.getY() + 10.0f, 185.0f, 24.0f, juce::Justification::left);
    g.setColour (kTextDim);
    g.setFont (juce::FontOptions (10.0f));
    g.drawText ("BODY AUTHORING", b.getX() + 14.0f, b.getY() + 36.0f, 185.0f, 14.0f, juce::Justification::left);

    drawFlatButton (g, saveButtonArea(), "SAVE .BODY240", false, hasBody);
    drawFlatButton (g, undoButtonArea(), "UNDO", false, hasBody && ! undoStack.empty());
    drawFlatButton (g, resetButtonArea(), "RESET", false, hasBody);
    drawFlatButton (g, redoButtonArea(), "REDO", false, hasBody && ! redoStack.empty());
    drawFlatButton (g, mdqButtonArea(), "MD-Q", false, hasBody);
    drawFlatButton (g, chainButtonArea(),
                    processor.isWorkstationBodySolo() ? "SOLO" : "CHAIN",
                    ! processor.isWorkstationBodySolo(), true);
    drawFlatButton (g, pzLockArea(),
                    pzLock == 1 ? "POLES" : (pzLock == 2 ? "ZEROS" : "P + Z"),
                    pzLock != 0, true);
    drawFlatButton (g, designerButtonArea(), "DESIGNER", designerOpen, true);
    {
        const bool haveLoop = gWorkstationLoop != nullptr && gWorkstationLoop->loopName().isNotEmpty();
        const bool on = haveLoop && gWorkstationLoop->isPlaying();
        drawFlatButton (g, playButtonArea(), on ? "STOP" : "PLAY", on, gWorkstationLoop != nullptr);
        g.setColour (kTextDim);
        g.setFont (juce::FontOptions (9.0f));
        g.drawText (haveLoop ? gWorkstationLoop->loopName() : "drop a wav to audition",
                    playButtonArea().getX() - 20, playButtonArea().getBottom() + 1, 120, 11,
                    juce::Justification::centred);
    }

}

void WorkstationEditor::drawBin (juce::Graphics& g)
{
    const auto b = binArea().toFloat();
    g.setColour (kPanelDeep);
    g.fillRect (b);
    g.setColour (kBorder);
    g.drawRect (b, 1.0f);

    g.saveState();
    g.reduceClipRegion (binListArea().reduced (1));

    for (int visible = 0;; ++visible)
    {
        const int rowIndex = visible + binScroll;
        if (rowIndex >= (int) rows.size())
            break;
        const auto r = binRowArea (visible).toFloat();
        if (r.getY() > b.getBottom())
            break;
        const auto& row = rows[(size_t) rowIndex];

        if (row.isSection)
        {
            const auto& section = sections[(size_t) row.section];
            const bool shownOpen = binQuery.isNotEmpty() || section.open;
            juce::Colour roleColour = kTextDim;
            if (section.kind == NodeKind::LabBody)       roleColour = kCyan;
            if (section.kind == NodeKind::P2k)           roleColour = kAmber;
            if (section.kind == NodeKind::MeasuredRail)  roleColour = kGreen;
            if (section.kind == NodeKind::X3Ref)         roleColour = kAmber.withAlpha (0.75f);
            g.setColour (kPanel);
            g.fillRect (r);
            g.setColour (roleColour.withAlpha (shownOpen ? 0.95f : 0.45f));
            g.fillRect (r.getX(), r.getY() + 3.0f, 2.0f, r.getHeight() - 6.0f);
            g.setColour (shownOpen ? roleColour : kTextDim);
            g.setFont (juce::FontOptions (10.0f).withStyle ("Bold"));
            g.drawText (juce::String (shownOpen ? "v " : "> ") + section.title
                            + "  (" + juce::String ((int) section.nodes.size()) + ")",
                        r.reduced (8.0f, 0.0f), juce::Justification::centredLeft);
            continue;
        }

        const auto& node = nodes[(size_t) row.node];
        if (row.node == selectedNode)
        {
            g.setColour (kBorder);
            g.fillRect (r);
        }
        if (node.kind == NodeKind::X3Ref && node.refIndex == activeRef)
        {
            g.setColour (kAmber.withAlpha (0.18f));
            g.fillRect (r);
        }

        juce::Colour rowColour = node.loadable ? kText : kGridLabel;
        if (node.kind == NodeKind::MeasuredRail)
            rowColour = kGreen.withAlpha (0.75f);
        if (node.kind == NodeKind::X3Ref)
            rowColour = (node.refIndex == activeRef) ? kAmber : kTextDim;
        g.setColour (rowColour);
        g.setFont (juce::FontOptions (11.0f));
        g.drawText (node.stem, r.reduced (14.0f, 0.0f), juce::Justification::centredLeft);
    }
    g.restoreState();
}

void WorkstationEditor::drawHero (juce::Graphics& g)
{
    const auto b = heroArea().toFloat();
    g.setColour (kPanelDeep);
    g.fillRect (b);
    g.setColour (kBorder);
    g.drawRect (b, 1.0f);

    const auto plot = b.reduced (6.0f, 6.0f).withTrimmedTop (14.0f);
    g.setColour (kTextDim);
    g.setFont (juce::FontOptions (10.0f).withStyle ("Bold"));
    g.drawText ("2 - CASCADE  " + (hasBody ? bodyName + (dirty ? " *" : "") : juce::String ("-"))
                    + (hasBody ? "     drag o=pole x=zero  |  SHIFT poles only  ALT zeros only" : juce::String()),
                b.getX() + 8.0f, b.getY() + 2.0f, b.getWidth() - 16.0f, 12.0f, juce::Justification::left);

    // grid
    g.setFont (juce::FontOptions (9.0f));
    for (double f : { 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0 })
    {
        const float x = xForFrequency (f, plot.getX(), plot.getWidth());
        g.setColour (juce::Colour (0x14ffffff));
        g.drawVerticalLine (juce::roundToInt (x), plot.getY(), plot.getBottom());
        g.setColour (kGridLabel);
        juce::String label = (f >= 1000.0) ? juce::String (f / 1000.0, 0) + "k" : juce::String (f, 0);
        g.drawText (label, juce::roundToInt (x - 16.0f), juce::roundToInt (plot.getBottom() - 12.0f), 32, 11, juce::Justification::centred);
    }
    for (float db : { -48.0f, -36.0f, -24.0f, -12.0f, 0.0f, 12.0f, 24.0f })
    {
        const float y = yForDb (db, plot.getY(), plot.getHeight());
        g.setColour (db == 0.0f ? juce::Colour (0x4000f0ff) : juce::Colour (0x10ffffff));
        g.drawHorizontalLine (juce::roundToInt (y), plot.getX(), plot.getRight());
    }

    if (! programProbeOk)
    {
        g.setColour (kGridLabel);
        g.setFont (juce::FontOptions (11.0f));
        g.drawText (hasBody ? "probe refused this pose (packed decode failed) - UNDO or edit"
                            : "double-click a BIN body to open",
                    plot, juce::Justification::centred);
        return;
    }

    const auto strokeCurve = [&] (const float* db, juce::Colour colour, float thickness)
    {
        juce::Path path;
        for (int i = 0; i < kNumPlotPoints; ++i)
        {
            const float x = plot.getX() + ((float) i / (float) (kNumPlotPoints - 1)) * plot.getWidth();
            const float y = yForDb (db[i], plot.getY(), plot.getHeight());
            if (i == 0)
                path.startNewSubPath (x, y);
            else
                path.lineTo (x, y);
        }
        g.setColour (colour);
        g.strokePath (path, juce::PathStrokeType (thickness));
    };

    // ghost overlay: decoded X3 corner silhouette
    if (activeRef >= 0 && ! refFreqs.empty())
    {
        const auto& ghost = refCornerDb[(size_t) activeCorner];
        if (ghost.size() == refFreqs.size())
        {
            juce::Path path;
            bool started = false;
            for (size_t i = 0; i < refFreqs.size(); ++i)
            {
                const float x = xForFrequency (refFreqs[i], plot.getX(), plot.getWidth());
                const float y = yForDb (ghost[i], plot.getY(), plot.getHeight());
                if (! started) { path.startNewSubPath (x, y); started = true; }
                else path.lineTo (x, y);
            }
            g.setColour (kAmber.withAlpha (0.75f));
            const float dashes[2] = { 5.0f, 4.0f };
            juce::Path dashed;
            juce::PathStrokeType (1.6f).createDashedStroke (dashed, path, dashes, 2);
            g.fillPath (dashed);
        }
    }

    // Thin, unsmoothed polyline: the display should read as the packed filter,
    // not as a stylised approximation of it.
    strokeCurve (programSumDb.data(), kCyan, 1.25f);

    // full pole-zero transparency: every stage's pair is either ON the cascade
    // (pole = ring you can grab, zero = small x at its notch) or named in the
    // sentinel row (identity / DC / Nyquist / degenerate) with an edge tick.
    juce::String sentinels;
    const auto curveYAt = [&] (double hz)
    {
        const float normX = (float) (std::log (juce::jlimit ((double) kMinHz, (double) kMaxHz, hz) / kMinHz)
                                     / std::log (kMaxHz / kMinHz));
        const int bin = juce::jlimit (0, kNumPlotPoints - 1, juce::roundToInt (normX * (kNumPlotPoints - 1)));
        return yForDb (programSumDb[(size_t) bin], plot.getY(), plot.getHeight());
    };
    const auto edgeTick = [&] (int stage, bool nyquist)
    {
        const float ex = nyquist ? plot.getRight() - 2.0f : plot.getX() + 2.0f;
        const float ey = curveYAt (nyquist ? (double) kMaxHz : (double) kMinHz);
        juce::Path tri;
        tri.addTriangle (ex, ey - 5.0f, ex, ey + 5.0f, ex + (nyquist ? -7.0f : 7.0f), ey);
        g.setColour (kLaneColours[stage].withAlpha (0.9f));
        g.fillPath (tri);
    };
    for (int stage = 0; stage < 6; ++stage)
    {
        if (hasBody && laneIsIdentity (words, stage))
        {
            sentinels << "S" << (stage + 1) << " off   ";
            continue;
        }
        const bool sel = (stage == selectedLane);
        double hz = 0.0, r = 0.0;
        for (int isZero = 0; isZero < 2; ++isZero)
        {
            if (! biquadRoots (&programCoeffs[stage * 5], isZero == 1, hz, r))
            {
                sentinels << "S" << (stage + 1) << (isZero ? " z" : " p") << "?   ";
                continue;
            }
            const bool atDc = hz < kMinHz, atNyq = hz > kMaxHz;
            if (atDc || atNyq)
            {
                sentinels << "S" << (stage + 1) << (isZero ? " z@" : " p@") << (atNyq ? "NYQ   " : "DC   ");
                edgeTick (stage, atNyq);
                continue;
            }
            const float hx = xForFrequency (hz, plot.getX(), plot.getWidth());
            const float hy = curveYAt (hz);
            g.setColour (kLaneColours[stage].withAlpha (sel ? 1.0f : 0.75f));
            if (isZero == 0)
            {
                g.drawEllipse (hx - (sel ? 7.0f : 5.0f), hy - (sel ? 7.0f : 5.0f),
                               sel ? 14.0f : 10.0f, sel ? 14.0f : 10.0f, sel ? 2.0f : 1.4f);
            }
            else
            {
                const float sz = sel ? 4.5f : 3.5f;
                g.drawLine (hx - sz, hy - sz, hx + sz, hy + sz, sel ? 1.6f : 1.1f);
                g.drawLine (hx - sz, hy + sz, hx + sz, hy - sz, sel ? 1.6f : 1.1f);
            }
        }
    }
    juce::String alarms;
    for (int stage = 0; stage < 6; ++stage)
    {
        if ((programNonfiniteMask & (1u << stage)) != 0)
            alarms << "S" << (stage + 1) << " NONFINITE   ";
        else if ((programUnstableMask & (1u << stage)) != 0)
            alarms << "S" << (stage + 1) << " UNSTABLE   ";
    }
    if (alarms.isNotEmpty())
    {
        g.setColour (kRed);
        g.setFont (juce::FontOptions (9.0f).withStyle ("Bold"));
        g.drawText (alarms.trimEnd(), plot.getX() + 4.0f, plot.getY() + 2.0f,
                    plot.getWidth() - 8.0f, 11.0f, juce::Justification::left);
    }
    if (sentinels.isNotEmpty())
    {
        g.setColour (kGridLabel);
        g.setFont (juce::FontOptions (9.0f).withStyle ("Bold"));
        g.drawText ("SENTINEL  " + sentinels.trimEnd(),
                    plot.getX() + 4.0f, plot.getY() + 2.0f, plot.getWidth() - 8.0f, 11.0f,
                    juce::Justification::right);
    }
}

void WorkstationEditor::drawGrid (juce::Graphics& g)
{
    const auto b = gridArea().toFloat();
    g.setColour (kPanel);
    g.fillRect (b);

    for (int corner = 0; corner < 4; ++corner)
    {
        const auto r = gridCellArea (corner).toFloat();
        const bool active = (corner == activeCorner);
        drawMiniPlot (g, r.reduced (1.0f),
                      cornerProbeOk[corner] ? cornerSumDb[(size_t) corner].data() : nullptr,
                      kNumPlotPoints, kCyan,
                      active ? kAmber : kBorder, active ? 1.6f : 1.0f);
        if (dragActive && dragKind == DragKind::PoseChip && corner == dropTargetCorner)
        {
            g.setColour (kGreen.withAlpha (0.2f));
            g.fillRect (r);
            g.setColour (kGreen);
            g.drawRect (r, 1.5f);
        }
        g.setColour (active ? kAmber : kGridLabel);
        g.setFont (juce::FontOptions (8.0f).withStyle ("Bold"));
        g.drawText (kCornerNames[corner], r.reduced (5.0f, 3.0f),
                    corner >= 2 ? juce::Justification::topLeft : juce::Justification::bottomLeft);
    }

    // XY puck: the live morph/Q pose
    const float m = paramValue (ParamID::morph);
    const float q = paramValue (ParamID::q);
    const auto inner = gridArea().reduced (2).toFloat();
    const float px = inner.getX() + m * inner.getWidth();
    const float py = inner.getBottom() - q * inner.getHeight();
    g.setColour (kCyan);
    g.drawEllipse (px - 7.0f, py - 7.0f, 14.0f, 14.0f, 2.0f);
    g.setColour (kCyan.withAlpha (0.35f));
    g.fillEllipse (px - 4.0f, py - 4.0f, 8.0f, 8.0f);

    g.setColour (kBorder);
    g.drawRect (b, 1.0f);
    g.setColour (kPanel.withAlpha (0.9f));
    g.fillRect (b.getX() + 4.0f, b.getY() + 3.0f, 96.0f, 13.0f);
    g.setColour (kTextDim);
    g.setFont (juce::FontOptions (10.0f).withStyle ("Bold"));
    g.drawText ("1 - POSES / XY", b.getX() + 8.0f, b.getY() + 3.0f, 100.0f, 13.0f, juce::Justification::left);
}

void WorkstationEditor::drawTray (juce::Graphics& g)
{
    if (railActive)
    {
        const auto b = trayArea().toFloat();
        g.setColour (kPanel);
        g.fillRect (b);
        g.setColour (kBorder);
        g.drawRect (b, 1.0f);
        g.setColour (kTextDim);
        g.setFont (juce::FontOptions (10.0f).withStyle ("Bold"));
        const auto& entry = railEntries[(size_t) railIndex];
        g.drawText ("3 - MATERIAL  " + railSourceName + "   " + entry.name
                        + "   (" + juce::String (railIndex + 1) + "/" + juce::String ((int) railEntries.size())
                        + ")   drag a measured pair onto a stage row (CTRL = this corner only)",
                    b.getX() + 8.0f, b.getY() + 3.0f, b.getWidth() - 110.0f, 14.0f, juce::Justification::left);
        drawFlatButton (g, railPrevArea(), "<", false, true);
        drawFlatButton (g, railNextArea(), ">", false, true);
        drawFlatButton (g, railFitArea(), railFitting ? "..." : "FIT", railFitting, ! railFitting);

        // THE POSE: the whole measured entry as one six-stage corner
        {
            const auto pr = railPoseChipArea().toFloat();
            std::array<float, kNumPlotPoints> db {};
            for (int i = 0; i < kNumPlotPoints; ++i)
            {
                const double hz = kMinHz * std::pow (kMaxHz / kMinHz, (double) i / (kNumPlotPoints - 1));
                const double w = juce::MathConstants<double>::twoPi * hz / kEvalSampleRate;
                const double cw = std::cos (w), sw = std::sin (w), c2w = std::cos (2.0 * w), s2w = std::sin (2.0 * w);
                float sum = 0.0f;
                for (int stage = 0; stage < 6; ++stage)
                {
                    double roots[5] {};
                    if (trench_stage_roots_from_words (railPoseWords[stage], roots) != 0)
                        continue;
                    const double w0 = juce::MathConstants<double>::twoPi * roots[0] / kEvalSampleRate;
                    const double wz = juce::MathConstants<double>::twoPi * roots[2] / kEvalSampleRate;
                    float c[5] = { (float) roots[4],
                                   (float) (-2.0 * roots[3] * std::cos (wz) * roots[4]),
                                   (float) (roots[3] * roots[3] * roots[4]),
                                   (float) (-2.0 * roots[1] * std::cos (w0)),
                                   (float) (roots[1] * roots[1]) };
                    sum += stageMagDb (c, cw, sw, c2w, s2w);
                }
                db[(size_t) i] = sum;
            }
            drawMiniPlot (g, pr.withTrimmedBottom (12.0f), db.data(), kNumPlotPoints,
                          kAmber, kAmber.withAlpha (0.7f), 1.5f);
            g.setColour (kAmber);
            g.setFont (juce::FontOptions (8.0f).withStyle ("Bold"));
            g.drawText ("POSE -> grid" + (railPoseResidualDb >= 0.0
                             ? "  (" + juce::String (railPoseResidualDb, 1) + " dB)" : juce::String()),
                        juce::roundToInt (pr.getX()), juce::roundToInt (pr.getBottom()) - 11,
                        juce::roundToInt (pr.getWidth()) + 20, 10, juce::Justification::centredLeft);
        }
        g.setColour (kGridLabel);
        g.setFont (juce::FontOptions (12.0f));
        g.drawText ("x", trayCloseArea(), juce::Justification::centred);

        for (int chip = 0; chip < 6; ++chip)
        {
            const auto r = trayChipArea (chip).toFloat();
            if (! railChipValid[chip])
            {
                g.setColour (kPanelDeep);
                g.fillRect (r.withTrimmedBottom (12.0f));
                g.setColour (kBorder);
                g.drawRect (r.withTrimmedBottom (12.0f), 1.0f);
                continue;
            }
            // chip curve straight from the snapped words (the shipping decode)
            double roots[5] {};
            std::array<float, kNumPlotPoints> db {};
            if (trench_stage_roots_from_words (railChipWords[chip], roots) == 0)
            {
                const double w0 = juce::MathConstants<double>::twoPi * roots[0] / kEvalSampleRate;
                const double wz = juce::MathConstants<double>::twoPi * roots[2] / kEvalSampleRate;
                float c[5] = { (float) roots[4],
                               (float) (-2.0 * roots[3] * std::cos (wz) * roots[4]),
                               (float) (roots[3] * roots[3] * roots[4]),
                               (float) (-2.0 * roots[1] * std::cos (w0)),
                               (float) (roots[1] * roots[1]) };
                for (int i = 0; i < kNumPlotPoints; ++i)
                {
                    const double hz = kMinHz * std::pow (kMaxHz / kMinHz, (double) i / (kNumPlotPoints - 1));
                    const double w = juce::MathConstants<double>::twoPi * hz / kEvalSampleRate;
                    db[(size_t) i] = stageMagDb (c, std::cos (w), std::sin (w), std::cos (2.0 * w), std::sin (2.0 * w));
                }
            }
            drawMiniPlot (g, r.withTrimmedBottom (12.0f), db.data(), kNumPlotPoints,
                          kLaneColours[chip].withAlpha (0.95f), kBorder, 1.0f);
            g.setColour (kLaneColours[chip]);
            g.setFont (juce::FontOptions (8.0f).withStyle ("Bold"));
            g.drawText (juce::String (juce::roundToInt (roots[0])) + " Hz",
                        juce::roundToInt (r.getX()), juce::roundToInt (r.getBottom()) - 11,
                        juce::roundToInt (r.getWidth()), 10, juce::Justification::centred);
        }
        return;
    }
    if (! hasSource)
    {
        const auto b = trayArea().toFloat();
        g.setColour (kPanel);
        g.fillRect (b);
        g.setColour (kBorder);
        g.drawRect (b, 1.0f);
        g.setColour (kTextDim);
        g.setFont (juce::FontOptions (10.0f).withStyle ("Bold"));
        g.drawText ("3 - MATERIAL", b.getX() + 8.0f, b.getY() + 3.0f, 200.0f, 14.0f, juce::Justification::left);
        g.setColour (kGridLabel);
        g.setFont (juce::FontOptions (11.0f));
        g.drawText ("click a source in the LIBRARY: a P2K skin (poses + stages) or a measured rail - its material lands here as draggable chips",
                    b.reduced (20.0f, 0.0f), juce::Justification::centred);
        return;
    }
    const auto b = trayArea().toFloat();
    g.setColour (kPanel);
    g.fillRect (b);
    g.setColour (kBorder);
    g.drawRect (b, 1.0f);

    g.setColour (kTextDim);
    g.setFont (juce::FontOptions (10.0f).withStyle ("Bold"));
    g.drawText ("3 - MATERIAL  " + sourceName + "   POSES -> grid   |   STAGES -> stage row (all corners; CTRL = this corner only)",
                b.getX() + 8.0f, b.getY() + 3.0f, b.getWidth() - 40.0f, 14.0f, juce::Justification::left);
    g.setColour (kGridLabel);
    g.setFont (juce::FontOptions (12.0f));
    g.drawText ("x", trayCloseArea(), juce::Justification::centred);

    for (int corner = 0; corner < 4; ++corner)
    {
        const auto r = trayPoseChipArea (corner).toFloat();
        drawMiniPlot (g, r.withTrimmedBottom (12.0f),
                      sourcePoseOk[corner] ? sourcePoseDb[(size_t) corner].data() : nullptr,
                      kNumPlotPoints, kAmber.withAlpha (0.9f), kBorder, 1.0f);
        g.setColour (kAmber);
        g.setFont (juce::FontOptions (8.0f).withStyle ("Bold"));
        g.drawText (kCornerNames[corner], juce::roundToInt (r.getX()) - 3, juce::roundToInt (r.getBottom()) - 11,
                    juce::roundToInt (r.getWidth()) + 6, 10, juce::Justification::centred);
    }

    for (int lane = 0; lane < 6; ++lane)
    {
        const auto r = trayChipArea (lane).toFloat();
        const bool identity = laneIsIdentity (sourceWords, lane);
        const bool selected = (lane == sourceLane);
        drawMiniPlot (g, r.withTrimmedBottom (12.0f),
                      sourceProbeOk && ! identity ? sourceLaneDb[(size_t) lane].data() : nullptr,
                      kNumPlotPoints,
                      kAmber.withAlpha (identity ? 0.25f : 0.9f),
                      selected ? kAmber : kBorder, selected ? 1.5f : 1.0f);
        double donorRoots[5] {};
        juce::String chipLabel = identity ? juce::String ("-")
            : (trench_stage_roots_from_words (sourceWords[activeCorner][lane], donorRoots) == 0
                   ? juce::String (juce::roundToInt (donorRoots[0])) + " Hz"
                   : juce::String ("pair"));
        g.setColour (identity ? kGridLabel : kAmber);
        g.setFont (juce::FontOptions (8.0f).withStyle ("Bold"));
        g.drawText (chipLabel,
                    juce::roundToInt (r.getX()), juce::roundToInt (r.getBottom()) - 11,
                    juce::roundToInt (r.getWidth()), 10, juce::Justification::centred);
    }
}

void WorkstationEditor::drawLanes (juce::Graphics& g)
{
    const auto b = lanesArea().toFloat();
    g.setColour (kPanel);
    g.fillRect (b);
    g.setColour (kBorder);
    g.drawRect (b, 1.0f);

    g.setColour (kTextDim);
    g.setFont (juce::FontOptions (10.0f).withStyle ("Bold"));
    g.drawText ("4 - FILTER STAGES  -  select one, drag to reorder  |  editing "
                    + juce::String (kCornerNames[activeCorner]),
                b.getX() + 8.0f, b.getY() + 3.0f, b.getWidth() - 16.0f, 14.0f,
                juce::Justification::left);

    for (int lane = 0; lane < 6; ++lane)
    {
        const auto r = laneRowArea (lane).toFloat();
        if (lane == selectedLane)
        {
            g.setColour (kBorder.withAlpha (0.7f));
            g.fillRect (r);
        }
        // drop target feedback while dragging
        if (dragActive && lane == dropTargetLane)
        {
            g.setColour ((dragKind == DragKind::Chip ? kGreen : kCyan).withAlpha (0.18f));
            g.fillRect (r);
            g.setColour (dragKind == DragKind::Chip ? kGreen : kCyan);
            g.drawRect (r, 1.0f);
        }
        const bool off = hasBody && laneIsIdentity (words, lane);

        g.setColour (kLaneColours[lane].withAlpha (hasBody ? 1.0f : 0.35f));
        g.fillRect (r.getX() + 6.0f, r.getY() + 5.0f, 4.0f, r.getHeight() - 10.0f);

        g.setColour (lane == selectedLane ? kText : kTextDim);
        g.setFont (juce::FontOptions (11.0f).withStyle ("Bold"));
        g.drawText ("S" + juce::String (lane + 1), r.getX() + 14.0f, r.getY(), 20.0f, r.getHeight(), juce::Justification::centredLeft);

        // every stage is a START and an END: both endpoints of the active Q side
        const int qBase = activeCorner >= 2 ? 2 : 0;
        for (int side = 0; side < 2; ++side)
        {
            const int corner = qBase + side;
            const bool editingThis = (corner == activeCorner && lane == selectedLane);
            drawMiniPlot (g, (side == 0 ? laneMiniArea (lane) : laneMiniEndArea (lane)).toFloat(),
                          cornerProbeOk[corner] && ! off ? cornerLaneDb[(size_t) corner][(size_t) lane].data() : nullptr,
                          kNumPlotPoints,
                          kLaneColours[lane].withAlpha (off ? 0.25f : 0.9f),
                          editingThis ? kAmber : (lane == selectedLane ? kLaneColours[lane] : kBorder),
                          editingThis ? 1.5f : 1.0f);
        }

        auto onRect = juce::Rectangle<float> (r.getX() + 104.0f, r.getY() + 7.0f, 34.0f, r.getHeight() - 14.0f);
        g.setColour (! hasBody ? kGridLabel.withAlpha (0.4f) : (off ? kGridLabel : kGreen));
        g.drawRect (onRect, 1.0f);
        g.setFont (juce::FontOptions (9.0f).withStyle ("Bold"));
        g.drawText (off ? "OFF" : "ON", onRect, juce::Justification::centred);

        if (hasBody)
        {
            double roots[5] {};
            juce::String summary;
            if (off)
                summary = "identity";
            else if (trench_stage_roots_from_words (words[activeCorner][lane], roots) == 0)
                summary = juce::String::formatted ("pole %.0f Hz r %.4f   zero %.0f Hz r %.3f   scale %.3f",
                                                   roots[0], roots[1], roots[2], roots[3], roots[4]);
            else
                summary = "real-pair / degenerate row";
            g.setColour (kTextDim);
            g.setFont (juce::FontOptions (10.0f));
            g.drawText (summary, r.getX() + 148.0f, r.getY(), r.getWidth() - 162.0f, r.getHeight(), juce::Justification::centredLeft);
        }
    }
}

void WorkstationEditor::drawDragGhost (juce::Graphics& g)
{
    if (! dragActive)
        return;
    const auto r = juce::Rectangle<float> ((float) dragPos.x - 18.0f, (float) dragPos.y - 18.0f, 36.0f, 36.0f);
    const int lane = dragIndex;
    const bool pose = dragKind == DragKind::PoseChip;
    const juce::Colour colour = pose ? kAmber : kLaneColours[juce::jlimit (0, 5, lane)];
    const float* db = nullptr;
    if (pose && dragIndex >= 0 && sourcePoseOk[juce::jlimit (0, 3, dragIndex)])
        db = sourcePoseDb[(size_t) juce::jlimit (0, 3, dragIndex)].data();
    else if (dragKind == DragKind::RailChip)
        db = nullptr;
    else if (dragKind == DragKind::Chip && sourceProbeOk)
        db = sourceLaneDb[(size_t) lane].data();
    else if (dragKind == DragKind::Lane && programProbeOk)
        db = programLaneDb[(size_t) lane].data();
    drawMiniPlot (g, r, db, kNumPlotPoints, colour, colour.withAlpha (0.9f), 1.5f);
}

void WorkstationEditor::drawProperties (juce::Graphics& g)
{
    const auto b = propertiesArea().toFloat();
    g.setColour (kPanel);
    g.fillRect (b);
    g.setColour (kBorder);
    g.drawRect (b, 1.0f);

    g.setColour (kTextDim);
    g.setFont (juce::FontOptions (10.0f).withStyle ("Bold"));
    g.drawText ("5 - STAGE DETAIL  S" + juce::String (selectedLane + 1) + " @ " + kCornerNames[activeCorner],
                b.getX() + 10.0f, b.getY() + 6.0f, b.getWidth() - 20.0f, 14.0f, juce::Justification::left);

    if (! hasBody)
        return;

    double roots[5] {};
    const int rc = trench_stage_roots_from_words (words[activeCorner][selectedLane], roots);

    static const char* fieldNames[5] = { "POLE Hz", "POLE r", "ZERO Hz", "ZERO r", "SCALE" };
    if (rc == 0)
    {
        for (int field = 0; field < 5; ++field)
        {
            const auto vr = propValueArea (field);
            g.setColour (kGridLabel);
            g.setFont (juce::FontOptions (10.0f));
            g.drawText (fieldNames[field], b.getX() + 12.0f, (float) vr.getY(), 70.0f, 16.0f, juce::Justification::left);
            if (field == editingProp)
                continue;   // the inline editor overlays this value
            g.setColour (kText);
            g.setFont (juce::FontOptions (12.0f));
            g.drawText (juce::String (roots[field], field == 0 || field == 2 ? 1 : 5),
                        vr.toFloat(), juce::Justification::left);
        }
    }
    else
    {
        g.setColour (kTextDim);
        g.setFont (juce::FontOptions (11.0f));
        g.drawFittedText ("row is a real-pair / degenerate form (no conjugate roots)",
                          juce::Rectangle<int> ((int) b.getX() + 12, (int) b.getY() + 32, (int) b.getWidth() - 24, 40),
                          juce::Justification::topLeft, 3);
    }


    g.setColour (kGridLabel);
    g.setFont (juce::FontOptions (9.0f));
    juce::String hex;
    for (int k = 0; k < 5; ++k)
        hex << juce::String::toHexString (words[activeCorner][selectedLane][k]).paddedLeft ('0', 4) << (k < 4 ? " " : "");
    g.drawText ("words  " + hex, b.getX() + 12.0f, (float) pzOpenButtonArea().getBottom() + 10.0f,
                b.getWidth() - 24.0f, 14.0f, juce::Justification::left);
}

void WorkstationEditor::drawPzWindow (juce::Graphics& g)
{
    if (! pzWindowOpen)
        return;
    const auto a = pzWindowArea().toFloat();
    g.setColour (kBg.withAlpha (0.6f));
    g.fillRect (getLocalBounds().toFloat());
    g.setColour (kPanel);
    g.fillRect (a);
    g.setColour (kCyan.withAlpha (0.6f));
    g.drawRect (a, 1.0f);

    g.setColour (kTextDim);
    g.setFont (juce::FontOptions (10.0f).withStyle ("Bold"));
    g.drawText ("PZ EDITOR  L" + juce::String (selectedLane + 1) + " @ " + kCornerNames[activeCorner]
                    + "   (runtime pose - drag any pole x / zero o)",
                a.getX() + 10.0f, a.getY() + 5.0f, a.getWidth() - 44.0f, 14.0f, juce::Justification::left);
    g.setColour (kGridLabel);
    g.setFont (juce::FontOptions (13.0f));
    g.drawText ("x", pzCloseArea(), juce::Justification::centred);

    const float scale = a.getHeight() * 0.5f - 44.0f;
    g.setColour (juce::Colour (0x30ffffff));
    g.drawEllipse (a.getCentreX() - scale, a.getCentreY() - scale, scale * 2.0f, scale * 2.0f, 1.2f);
    g.drawHorizontalLine (juce::roundToInt (a.getCentreY()), a.getX() + 6.0f, a.getRight() - 6.0f);
    // frequency spokes off the runtime grid
    g.setFont (juce::FontOptions (8.0f));
    for (double f : { 100.0, 500.0, 1000.0, 5000.0, 10000.0 })
    {
        const double w = juce::MathConstants<double>::twoPi * f / kEvalSampleRate;
        const float x = a.getCentreX() + scale * (float) std::cos (w);
        const float y = a.getCentreY() - scale * (float) std::sin (w);
        g.setColour (juce::Colour (0x18ffffff));
        g.drawLine (a.getCentreX(), a.getCentreY(), x, y, 1.0f);
        g.setColour (kGridLabel);
        g.drawText ((f >= 1000.0 ? juce::String (f / 1000.0, 0) + "k" : juce::String (f, 0)),
                    juce::roundToInt (x - 14 + 16.0f * std::cos (w)), juce::roundToInt (y - 5 - 12.0f * std::sin (w)),
                    28, 10, juce::Justification::centred);
    }

    // the handles come from the RUNTIME probe (interpolated biquads at this pose)
    for (int lane = 0; lane < 6; ++lane)
    {
        if (! programProbeOk)
            break;
        const bool sel = (lane == selectedLane);
        const auto colour = kLaneColours[lane].withAlpha (sel ? 1.0f : 0.4f);
        g.setColour (colour);
        double hz = 0.0, r = 0.0;
        for (int isZero = 0; isZero < 2; ++isZero)
        {
            if (! biquadRoots (&programCoeffs[lane * 5], isZero == 1, hz, r))
                continue;
            for (int mirror = 0; mirror < 2; ++mirror)
            {
                auto pt = pzPointFor (hz, r);
                if (mirror)
                    pt.y = 2.0f * a.getCentreY() - pt.y;
                const float sz = sel ? 6.0f : 4.0f;
                if (isZero == 0)
                {
                    g.drawLine (pt.x - sz, pt.y - sz, pt.x + sz, pt.y + sz, sel ? 1.8f : 1.2f);
                    g.drawLine (pt.x - sz, pt.y + sz, pt.x + sz, pt.y - sz, sel ? 1.8f : 1.2f);
                }
                else
                    g.drawEllipse (pt.x - sz, pt.y - sz, sz * 2.0f, sz * 2.0f, sel ? 1.8f : 1.2f);
            }
        }
    }

    // readout: the authored words of the selected lane at this corner
    double roots[5] {};
    if (trench_stage_roots_from_words (words[activeCorner][selectedLane], roots) == 0)
    {
        g.setColour (kText);
        g.setFont (juce::FontOptions (11.0f));
        g.drawText (juce::String::formatted ("authored: pole %.0f Hz r %.4f   zero %.0f Hz r %.3f   scale %.3f",
                                             roots[0], roots[1], roots[2], roots[3], roots[4]),
                    a.getX() + 10.0f, a.getBottom() - 20.0f, a.getWidth() - 20.0f, 14.0f, juce::Justification::left);
    }
}

void WorkstationEditor::drawFooter (juce::Graphics& g)
{
    const auto b = footerArea().toFloat();
    g.setColour (kPanel);
    g.fillRect (b);
    g.setColour (kBorder);
    g.drawRect (b, 1.0f);
    g.setFont (juce::FontOptions (10.0f));
    g.setColour (hasBody && dirty && ! lastCertifyPass ? kRed : kGreen);
    juce::String left = statusLine;
    if (hasBody)
        left << "   |   maxR " << juce::String (lastCertifyMaxR, 5)
             << (lastCertifyPass ? " PASS" : " FAIL");
    g.drawText (left, b.getX() + 10.0f, b.getY(), b.getWidth() - 20.0f, b.getHeight(), juce::Justification::centredLeft);
}

// ---------------------------------------------------------------- input

void WorkstationEditor::mouseDown (const juce::MouseEvent& e)
{
    const auto pos = e.getPosition();
    dragKind = DragKind::None;
    dragActive = false;
    dropTargetLane = -1;
    dropTargetCorner = -1;

    if (designerOpen)
    {
        designerMouseDown (pos);
        return;
    }
    if (designerButtonArea().contains (pos))
    {
        toggleDesigner();
        return;
    }

    if (gridArea().contains (pos) && ! pzWindowOpen)
    {
        // params move only on a real drag; a click selects the edit corner and
        // leaves the puck exactly where it sits (centre parking is legal)
        dragKind = DragKind::XY;
        dragActive = false;
        dragIndex = -1;
        dragPos = pos;
        for (int corner = 0; corner < 4; ++corner)
            if (gridCellArea (corner).contains (pos))
                dragIndex = corner;
        return;
    }

    if (saveButtonArea().contains (pos))
    {
        saveWorkingBody();
        return;
    }
    if (undoButtonArea().contains (pos))
    {
        undo();
        return;
    }
    if (resetButtonArea().contains (pos))
    {
        resetProgram();
        return;
    }
    if (redoButtonArea().contains (pos))
    {
        redo();
        return;
    }
    if (mdqButtonArea().contains (pos))
    {
        applyMeasuredQLaw();
        return;
    }
    if (pzLockArea().contains (pos))
    {
        pzLock = (pzLock + 1) % 3;   // free -> poles only -> zeros only
        statusLine = pzLock == 1 ? "editing POLES only (zeros locked)"
                   : pzLock == 2 ? "editing ZEROS only (poles locked)"
                                 : "poles and zeros both editable";
        repaint();
        return;
    }
    if (playButtonArea().contains (pos))
    {
        if (gWorkstationLoop != nullptr)
            gWorkstationLoop->setPlaying (! gWorkstationLoop->isPlaying());
        repaint();
        return;
    }
    if (chainButtonArea().contains (pos))
    {
        // CHAIN = audition what actually ships; SOLO = the surgical body path
        processor.setWorkstationBodySolo (! processor.isWorkstationBodySolo());
        statusLine = processor.isWorkstationBodySolo()
                         ? "SOLO: body only (no AGC/sat/slam) - surgical listening"
                         : "CHAIN: full shipping path (gain budget + mix + AGC + sat)";
        repaint();
        return;
    }

    if (pzWindowOpen)
    {
        if (pzCloseArea().contains (pos) || ! pzWindowArea().contains (pos))
        {
            pzWindowOpen = false;
            repaint();
            return;
        }
        // grab the nearest runtime pole/zero handle (any lane, either mirror)
        const auto af = pzWindowArea().toFloat();
        float best = 20.0f;
        int bestLane = -1;
        bool bestZero = false;
        for (int lane = 0; lane < 6 && programProbeOk; ++lane)
        {
            double hz = 0.0, r = 0.0;
            for (int isZero = 0; isZero < 2; ++isZero)
            {
                if ((e.mods.isShiftDown() && isZero == 1) || (e.mods.isAltDown() && isZero == 0)
                    || (pzLock == 1 && isZero == 1) || (pzLock == 2 && isZero == 0))
                    continue;   // SHIFT/lock = poles only, ALT/lock = zeros only
                if (! biquadRoots (&programCoeffs[lane * 5], isZero == 1, hz, r))
                    continue;
                auto pt = pzPointFor (hz, r);
                for (int mirror = 0; mirror < 2; ++mirror)
                {
                    const float py = mirror ? 2.0f * af.getCentreY() - pt.y : pt.y;
                    const float d = juce::Point<float> ((float) pos.x, (float) pos.y).getDistanceFrom ({ pt.x, py });
                    if (d < best)
                    {
                        best = d;
                        bestLane = lane;
                        bestZero = (isZero == 1);
                    }
                }
            }
        }
        if (bestLane >= 0)
        {
            selectedLane = bestLane;
            pushUndo();
            dragKind = DragKind::PZ;
            pzDragZero = bestZero;
            dragActive = true;
            dragPos = pos;
        }
        repaint();
        return;
    }

    if (heroArea().contains (pos) && hasBody && programProbeOk && ! pzWindowOpen)
    {
        // grab the nearest handle on the cascade: pole ring OR zero x
        const auto plot = heroArea().toFloat().reduced (6.0f, 6.0f).withTrimmedTop (14.0f);
        float best = 16.0f;
        int bestStage = -1;
        bool bestZero = false;
        for (int stage = 0; stage < 6; ++stage)
        {
            for (int isZero = 0; isZero < 2; ++isZero)
            {
                if ((e.mods.isShiftDown() && isZero == 1) || (e.mods.isAltDown() && isZero == 0)
                    || (pzLock == 1 && isZero == 1) || (pzLock == 2 && isZero == 0))
                    continue;   // SHIFT/lock = poles only, ALT/lock = zeros only
                double hz = 0.0, r = 0.0;
                if (! biquadRoots (&programCoeffs[stage * 5], isZero == 1, hz, r) || hz < kMinHz || hz > kMaxHz)
                    continue;
                const float x = xForFrequency (hz, plot.getX(), plot.getWidth());
                const float normX = (float) (std::log (hz / kMinHz) / std::log (kMaxHz / kMinHz));
                const int bin = juce::jlimit (0, kNumPlotPoints - 1, juce::roundToInt (normX * (kNumPlotPoints - 1)));
                const float y = yForDb (programSumDb[(size_t) bin], plot.getY(), plot.getHeight());
                const float d = juce::Point<float> ((float) pos.x, (float) pos.y).getDistanceFrom ({ x, y });
                if (d < best)
                {
                    best = d;
                    bestStage = stage;
                    bestZero = (isZero == 1);
                }
            }
        }
        if (bestStage >= 0)
        {
            selectedLane = bestStage;
            double roots[5] {};
            if (trench_stage_roots_from_words (words[activeCorner][selectedLane], roots) != 0)
            {
                statusLine = "S" + juce::String (selectedLane + 1)
                           + " is a real-pair row at " + kCornerLabels[activeCorner]
                           + " - not pair-draggable (type in 5-STAGE DETAIL to recast)";
                repaint();
                return;
            }
            pushUndo();
            pzDragZero = bestZero;
            heroDragStartR = roots[bestZero ? 3 : 1];
            heroDragStartY = pos.y;
            // designing in the middle: shift the whole trajectory (both
            // endpoints of the active Q side move by the same delta)
            heroBoth = false;
            const float morphNow = paramValue (ParamID::morph);
            if (morphNow > 0.05f && morphNow < 0.95f)
            {
                const int qBase = activeCorner >= 2 ? 2 : 0;
                heroBoth = trench_stage_roots_from_words (words[qBase][selectedLane], heroOrigRoots[0]) == 0
                        && trench_stage_roots_from_words (words[qBase + 1][selectedLane], heroOrigRoots[1]) == 0;
                const auto plotf = heroArea().toFloat().reduced (6.0f, 6.0f).withTrimmedTop (14.0f);
                const float nx = juce::jlimit (0.0f, 1.0f, ((float) pos.x - plotf.getX()) / plotf.getWidth());
                heroGrabHz = kMinHz * std::pow (kMaxHz / kMinHz, nx);
            }
            dragKind = DragKind::HeroPole;
            dragActive = true;
            dragPos = pos;
            repaint();
        }
        return;
    }

    if (propertiesArea().contains (pos) && hasBody)
    {
        for (int field = 0; field < 5; ++field)
        {
            if (propValueArea (field).contains (pos))
            {
                beginPropEdit (field);
                return;
            }
        }
        return;
    }

    if (binListArea().contains (pos))
    {
        const int visible = (pos.y - (binListArea().getY() + 1)) / kBinRowH;
        const int rowIndex = visible + binScroll;
        if (rowIndex < 0 || rowIndex >= (int) rows.size())
            return;
        const auto& row = rows[(size_t) rowIndex];
        if (row.isSection)
        {
            const int targetSection = row.section;
            if (binQuery.isNotEmpty())
            {
                binQuery.clear();
                binSearch.setText ({}, juce::dontSendNotification);
            }
            const bool willOpen = ! sections[(size_t) targetSection].open;
            for (auto& section : sections)
                section.open = false;
            sections[(size_t) targetSection].open = willOpen;
            rebuildRows();
            for (int i = 0; i < (int) rows.size(); ++i)
            {
                if (rows[(size_t) i].isSection && rows[(size_t) i].section == targetSection)
                {
                    const int visibleRows = juce::jmax (1, binListArea().getHeight() / kBinRowH);
                    binScroll = juce::jlimit (0, juce::jmax (0, (int) rows.size() - visibleRows), i);
                    break;
                }
            }
            repaint();
            return;
        }
        const auto& node = nodes[(size_t) row.node];
        selectedNode = row.node;
        // one law: single-click = MATERIAL (donor tray), double-click = PROGRAM.
        // browsing sources must never replace the working body.
        if (node.kind == NodeKind::X3Ref)
            loadReference (node.refIndex);
        else if (node.kind == NodeKind::MeasuredRail)
            loadRail (node.body, node.stem);
        else
            loadSource (row.node);
        repaint();
        return;
    }

    if (railActive && trayArea().contains (pos))
    {
        if (trayCloseArea().contains (pos))
        {
            railActive = false;
            statusLine = "rail tray closed";
            repaint();
            return;
        }
        if (railPrevArea().contains (pos)) { selectRailEntry (railIndex - 1); return; }
        if (railNextArea().contains (pos)) { selectRailEntry (railIndex + 1); return; }
        if (railFitArea().contains (pos))
        {
            startRailFit();
            return;
        }
        if (railPoseChipArea().contains (pos))
        {
            dragKind = DragKind::PoseChip;   // rail pose rides the pose-chip path
            dragIndex = -100;                // sentinel: rail pose, not donor corner
            dragPos = pos;
            repaint();
            return;
        }
        for (int chip = 0; chip < 6; ++chip)
        {
            if (trayChipArea (chip).contains (pos) && railChipValid[chip])
            {
                dragKind = DragKind::RailChip;
                dragIndex = chip;
                dragPos = pos;
                repaint();
                return;
            }
        }
        return;
    }

    if (hasSource && trayArea().contains (pos))
    {
        if (trayCloseArea().contains (pos))
        {
            hasSource = false;
            sourceProbeOk = false;
            statusLine = "donor tray closed";
            repaint();
            return;
        }
        for (int corner = 0; corner < 4; ++corner)
        {
            if (trayPoseChipArea (corner).contains (pos))
            {
                dragKind = DragKind::PoseChip;
                dragIndex = corner;
                dragPos = pos;
                repaint();
                return;
            }
        }
        for (int lane = 0; lane < 6; ++lane)
        {
            if (trayChipArea (lane).contains (pos) && ! laneIsIdentity (sourceWords, lane))
            {
                sourceLane = lane;
                dragKind = DragKind::Chip;
                dragIndex = lane;
                dragPos = pos;
                repaint();
                return;
            }
        }
        return;
    }

    if (lanesArea().contains (pos))
    {
        for (int lane = 0; lane < 6; ++lane)
        {
            const auto r = laneRowArea (lane);
            if (! r.contains (pos))
                continue;
            const int localX = pos.x - r.getX();
            if (localX >= 104 && localX < 138)
                toggleLaneOff (lane);
            else if (laneMiniArea (lane).contains (pos) || laneMiniEndArea (lane).contains (pos))
            {
                // pick the stage AND the endpoint you are designing; puck stays
                selectedLane = lane;
                const int qBase = activeCorner >= 2 ? 2 : 0;
                activeCorner = qBase + (laneMiniEndArea (lane).contains (pos) ? 1 : 0);
                curvesStale = true;
            }
            else
            {
                selectedLane = lane;
                if (hasBody)
                {
                    dragKind = DragKind::Lane;
                    dragIndex = lane;
                    dragPos = pos;
                }
            }
            repaint();
            return;
        }
        return;
    }
}

void WorkstationEditor::mouseDrag (const juce::MouseEvent& e)
{
    if (dragKind == DragKind::None)
        return;
    dragPos = e.getPosition();
    if (dragKind == DragKind::XY)
    {
        if (! dragActive && e.getDistanceFromDragStart() > kDragThreshold)
            dragActive = true;
        const auto inner = gridArea().reduced (2).toFloat();
        const float m = juce::jlimit (0.0f, 1.0f, ((float) e.getPosition().x - inner.getX()) / inner.getWidth());
        const float q = juce::jlimit (0.0f, 1.0f, (inner.getBottom() - (float) e.getPosition().y) / inner.getHeight());
        setParamValue (ParamID::morph, m);
        setParamValue (ParamID::q, q);
        repaint();
        return;
    }
    if (dragKind == DragKind::HeroPole)
    {
        const auto plot = heroArea().toFloat().reduced (6.0f, 6.0f).withTrimmedTop (14.0f);
        const float normX = juce::jlimit (0.0f, 1.0f, ((float) e.getPosition().x - plot.getX()) / plot.getWidth());
        const double hz = kMinHz * std::pow (kMaxHz / kMinHz, normX);
        const double bwFactor = std::exp ((double) (e.getPosition().y - heroDragStartY) * 0.02);
        if (heroBoth)
        {
            // trajectory shift: same frequency RATIO + bandwidth factor to both ends
            const double ratio = hz / juce::jmax (1.0, heroGrabHz);
            const int qBase = activeCorner >= 2 ? 2 : 0;
            const int fi = pzDragZero ? 2 : 0, ri = pzDragZero ? 3 : 1;
            for (int end = 0; end < 2; ++end)
            {
                double roots[5];
                std::memcpy (roots, heroOrigRoots[end], sizeof roots);
                roots[fi] = juce::jlimit (0.0, kEvalSampleRate * 0.5, roots[fi] * ratio);
                roots[ri] = juce::jlimit (0.0, pzDragZero ? 1.0 : 0.998,
                                          1.0 - (1.0 - roots[ri]) * bwFactor);
                juce::uint16 encoded[5];
                if (trench_stage_words_from_roots (roots, encoded) == 0)
                    std::memcpy (words[qBase + end][selectedLane], encoded, sizeof encoded);
            }
            muteBackupValid[selectedLane] = false;
            dirty = true;
            packAndInstall (false);
            repaint();
            return;
        }
        const double r = juce::jlimit (0.0, pzDragZero ? 1.0 : 0.998,
            1.0 - (1.0 - heroDragStartR) * bwFactor);
        setPoleZero (pzDragZero, hz, r, true);
        return;
    }
    if (dragKind == DragKind::PZ)
    {
        const auto af = pzWindowArea().toFloat();
        const float scale = af.getHeight() * 0.5f - 44.0f;
        const float dx = ((float) dragPos.x - af.getCentreX()) / scale;
        const float dy = (af.getCentreY() - (float) dragPos.y) / scale;
        const double r = std::hypot (dx, dy);
        const double hz = std::atan2 (std::abs (dy), (double) dx) / juce::MathConstants<double>::twoPi * kEvalSampleRate;
        setPoleZero (pzDragZero, hz, r, true);   // light: no certify per mouse-move
        return;
    }
    if (! dragActive && e.getDistanceFromDragStart() > kDragThreshold)
        dragActive = true;
    if (dragActive)
    {
        // Endpoint chips seek the Morph edge; stage payloads seek stage rows.
        dropTargetCorner = -1;
        if (dragKind == DragKind::PoseChip)
        {
            for (int corner = 0; corner < 4; ++corner)
                if (gridCellArea (corner).contains (dragPos))
                    dropTargetCorner = corner;
            repaint();
            return;
        }
        dropTargetLane = -1;
        const auto lanes = lanesArea().expanded (0, 24);
        if (lanes.contains (dragPos))
        {
            int bestLane = 0;
            int bestDist = 1 << 30;
            for (int lane = 0; lane < 6; ++lane)
            {
                const int d = std::abs (laneRowArea (lane).getCentreY() - dragPos.y);
                if (d < bestDist)
                {
                    bestDist = d;
                    bestLane = lane;
                }
            }
            dropTargetLane = bestLane;
        }
        repaint();
    }
}

void WorkstationEditor::mouseUp (const juce::MouseEvent& e)
{
    if (dragKind == DragKind::XY)
    {
        if (! dragActive && dragIndex >= 0)
        {
            activeCorner = dragIndex;   // click = pick the edit corner, puck stays put
            curvesStale = true;
        }
        dragKind = DragKind::None;
        dragActive = false;
        dragIndex = -1;
        repaint();
        return;
    }
    if (dragKind == DragKind::PoseChip)
    {
        if (dragIndex == -100)
        {
            if (dropTargetCorner >= 0)
                applyRailPose (dropTargetCorner);
            else if (! dragActive)
                applyRailPose (activeCorner);
        }
        else if (dropTargetCorner >= 0)
            copyPoseToCorner (dragIndex, dropTargetCorner);
        else if (! dragActive)
            copyPoseToCorner (dragIndex, activeCorner);
        dragKind = DragKind::None;
        dragActive = false;
        dropTargetCorner = -1;
        repaint();
        return;
    }
    if (dragKind == DragKind::PZ || dragKind == DragKind::HeroPole)
    {
        dragKind = DragKind::None;
        dragActive = false;
        packAndInstall();      // the full certify the drag skipped
        curvesStale = true;    // corner minis catch up
        repaint();
        return;
    }
    if (dragActive && dropTargetLane >= 0)
    {
        // dropping ON an endpoint mini targets just that endpoint corner
        bool endpointDrop = false;
        {
            const int qBase = activeCorner >= 2 ? 2 : 0;
            if (laneMiniArea (dropTargetLane).contains (dragPos))
            {
                activeCorner = qBase;
                endpointDrop = true;
            }
            else if (laneMiniEndArea (dropTargetLane).contains (dragPos))
            {
                activeCorner = qBase + 1;
                endpointDrop = true;
            }
        }
        if (dragKind == DragKind::RailChip)
        {
            insertRailStage (dragIndex, dropTargetLane, endpointDrop || e.mods.isCtrlDown());
        }
        else if (dragKind == DragKind::Chip)
        {
            selectedLane = dropTargetLane;
            if (endpointDrop || e.mods.isCtrlDown())
                insertSourceLaneAtCorner();   // one endpoint - start/end design
            else
                insertSourceLane();           // all 4 corners - the hybrid swap
        }
        else if (dragKind == DragKind::Lane)
        {
            moveLane (dragIndex, dropTargetLane);
        }
    }
    dragKind = DragKind::None;
    dragActive = false;
    dropTargetLane = -1;
    repaint();
}

void WorkstationEditor::mouseDoubleClick (const juce::MouseEvent& e)
{
    if (! binListArea().contains (e.getPosition()))
        return;
    const int visible = (e.getPosition().y - (binListArea().getY() + 1)) / kBinRowH;
    const int rowIndex = visible + binScroll;
    if (rowIndex < 0 || rowIndex >= (int) rows.size())
        return;
    const auto& row = rows[(size_t) rowIndex];
    if (! row.isSection && nodes[(size_t) row.node].loadable)
    {
        selectedNode = row.node;
        const auto kind = nodes[(size_t) row.node].kind;
        if (kind != NodeKind::X3Ref && kind != NodeKind::MeasuredRail)
            loadProgram (row.node);
        else if (kind == NodeKind::P2k)
            loadSource (row.node);
    }
}

// ------------------------------------------------------------ THE DESIGNER
// MD ergonomics + P2K reach: parameter-space sections compiled through the
// firmware word recipe (trench-core designer.rs). Every edit recompiles,
// certifies, installs — the fence replaced by a net.

namespace
{
struct DesignerMotif { const char* label; double oct; double zeroR; };
// ROM zero-grammar census (sweet-spot atlas, 777 lanes / 33 ROM bodies):
// tooth n=164, trailing n=93, leading n=227, far rail n=238 (~3 oct measured),
// true notch n=153. Starting points only — every field stays editable.
const DesignerMotif kDesignerMotifs[5] = {
    { "TOOTH        0 oct   r .95", 0.0, 0.95 },
    { "TRAILING  -0.6 oct   r .97", -0.6, 0.97 },
    { "LEADING   +0.9 oct   r .94", 0.9, 0.94 },
    { "FAR RAIL    +3 oct   r .95", 3.0, 0.95 },
    { "TRUE NOTCH +1.7 oct  r 1.0", 1.7, 1.0 },
};
const char* kDesignerTypeNames[5] = { "OFF", "EQ", "LP", "HP", "FREE" };
constexpr int kDesignerTypeFree = 4;
// one MD ladder step = ~68.4 cents; FREE freq wheel travels this grid
const double kDesignerLadderRatio = std::pow (2.0, 68.4 / 1200.0);

static_assert (sizeof (TrenchDesignerRow) == 48, "FFI row layout drifted");
static_assert (sizeof (TrenchDesignerSection) == 104, "FFI section layout drifted");
}

juce::Rectangle<int> WorkstationEditor::designerButtonArea() const { return { 734, 34, 84, 20 }; }
juce::Rectangle<int> WorkstationEditor::designerArea() const      { return { 140, 70, 1000, 660 }; }
juce::Rectangle<int> WorkstationEditor::designerCloseArea() const
{
    const auto p = designerArea();
    return { p.getRight() - 26, p.getY() + 4, 20, 18 };
}
juce::Rectangle<int> WorkstationEditor::designerPageArea (int page) const
{
    const auto p = designerArea();
    return { p.getX() + 10 + page * 84, p.getY() + 28, 80, 20 };
}
juce::Rectangle<int> WorkstationEditor::designerTemplateArea() const
{
    const auto p = designerArea();
    return { p.getX() + 186, p.getY() + 28, 110, 20 };
}
juce::Rectangle<int> WorkstationEditor::designerSketchArea() const
{
    const auto p = designerArea();
    return { p.getX() + 302, p.getY() + 28, 150, 20 };
}
juce::Rectangle<int> WorkstationEditor::designerShiftArea() const
{
    const auto p = designerArea();
    return { p.getX() + 458, p.getY() + 28, 90, 20 };
}
juce::Rectangle<int> WorkstationEditor::designerJourneyArea() const
{
    const auto p = designerArea();
    return { p.getX() + 10, p.getY() + 54, p.getWidth() - 20, 168 };
}
juce::Rectangle<int> WorkstationEditor::designerStageRowArea (int stage) const
{
    const auto p = designerArea();
    return { p.getX() + 10, p.getY() + 230 + stage * 66, p.getWidth() - 20, 64 };
}
juce::Rectangle<int> WorkstationEditor::designerShapeArea (int stage) const
{
    const auto r = designerStageRowArea (stage);
    return { r.getX() + 26, r.getY() + 20, 56, 24 };
}
juce::Rectangle<int> WorkstationEditor::designerMotifArea (int stage) const
{
    const auto r = designerStageRowArea (stage);
    return { r.getX() + 86, r.getY() + 20, 52, 24 };
}
juce::Rectangle<int> WorkstationEditor::designerCellArea (int stage, int row, int field) const
{
    const auto r = designerStageRowArea (stage);
    static const int widths[5] = { 130, 70, 70, 130, 70 };
    int x = r.getX() + 172;
    for (int f = 0; f < field; ++f)
        x += widths[f] + 6;
    const int y = r.getY() + (row == 0 ? 7 : 35);
    return { x, y, widths[field], 22 };
}

int WorkstationEditor::designerCodeForHz (double hz) const
{
    int best = 0;
    double bestErr = 1.0e12;
    for (int code = 0; code < 128; ++code)
    {
        const double err = std::abs (std::log (juce::jmax (1.0, designerLadderHz[code]) / juce::jmax (1.0, hz)));
        if (err < bestErr) { bestErr = err; best = code; }
    }
    return best;
}

// field ids — types 1..3: 0 FREQ code, 1 GAIN. FREE: 0 pole Hz, 1 pole r,
// 2 scale, 3 zero Hz, 4 zero r.
double WorkstationEditor::designerFieldValue (int stage, int row, int field) const
{
    const auto& s = dsections[designerPage][stage];
    const auto& rw = row == 0 ? s.lo : s.hi;
    if (s.type != kDesignerTypeFree)
        return field == 0 ? rw.freq : rw.gain;
    switch (field)
    {
        case 0: return rw.poleHz;
        case 1: return rw.poleR;
        case 2: return rw.scale;
        case 3: return rw.zeroHz;
        default: return rw.zeroR;
    }
}

void WorkstationEditor::designerSetField (int stage, int row, int field, double value)
{
    auto& s = dsections[designerPage][stage];
    auto& rw = row == 0 ? s.lo : s.hi;
    if (s.type != kDesignerTypeFree)
    {
        if (field == 0)
            rw.freq = value > 127.5 ? designerCodeForHz (value) : juce::jlimit (0, 127, juce::roundToInt (value));
        else
            rw.gain = juce::jlimit (0, 127, juce::roundToInt (value));
        return;
    }
    switch (field)
    {
        case 0: rw.poleHz = juce::jlimit (20.0, (double) kMaxHz, value); break;
        case 1: rw.poleR = juce::jlimit (0.0, 0.9995, value); break;
        case 2: rw.scale = juce::jlimit (0.0, 4.0, value); break;
        case 3: rw.zeroHz = juce::jlimit (20.0, (double) kMaxHz, value); break;
        default: rw.zeroR = juce::jlimit (0.0, 1.0, value); break;
    }
}

void WorkstationEditor::toggleDesigner()
{
    designerOpen = ! designerOpen;
    binSearch.setVisible (! designerOpen);   // the panel is the whole surface
    if (designerOpen)
    {
        if (nameField.getText().trim().isEmpty())
            nameField.setText ("DESIGNER", juce::dontSendNotification);
        designerApply();
    }
    else
    {
        dsEditField = -1;
        designerEditor.setVisible (false);
    }
    repaint();
}

void WorkstationEditor::designerApply()
{
    if (! designerOpen)
        return;
    TrenchDesignerSection ffi[2][6] {};
    for (int page = 0; page < 2; ++page)
        for (int stage = 0; stage < 6; ++stage)
        {
            const auto& s = dsections[page][stage];
            auto& d = ffi[page][stage];
            d.type_id = s.type;
            const DesignerRowState* rows[2] = { &s.lo, &s.hi };
            TrenchDesignerRow* out[2] = { &d.low, &d.high };
            for (int r = 0; r < 2; ++r)
            {
                out[r]->freq = rows[r]->freq;
                out[r]->gain = rows[r]->gain;
                out[r]->pole_hz = rows[r]->poleHz;
                out[r]->pole_r = rows[r]->poleR;
                out[r]->zero_hz = rows[r]->zeroHz;
                out[r]->zero_r = rows[r]->zeroR;
                out[r]->scale = rows[r]->scale;
            }
        }
    std::array<juce::uint8, 240> bytes {};
    if (trench_designer_body (ffi[0], ffi[1], 6, designerShift, bytes.data()) != 0)
    {
        statusLine = "DESIGNER compile failed";
        repaint();
        return;
    }
    if (hasBody)
        pushUndo();
    wordsFromBytes240 (bytes, words);
    std::fill (std::begin (muteBackupValid), std::end (muteBackupValid), false);
    hasBody = true;
    dirty = true;
    if (bodyName.isEmpty())
        bodyName = "DESIGNER";
    packAndInstall();   // certify + install: the net runs on every edit
    designerRefreshJourney();
    repaint();
}

void WorkstationEditor::designerRefreshJourney()
{
    designerJourneyOk = hasBody;
    if (! hasBody)
        return;
    const double q = designerPage == 1 ? 1.0 : 0.0;
    for (int k = 0; k < 5; ++k)
    {
        double biquad[30] {};
        double maxR = 0.0;
        juce::uint32 unstable = 0, nonfinite = 0;
        if (trench_packed_probe (workingBytes.data(), 240, k / 4.0, q,
                                 biquad, &maxR, &unstable, &nonfinite) != 0)
        {
            designerJourneyOk = false;
            return;
        }
        float coeffs[30];
        for (int i = 0; i < 30; ++i)
            coeffs[i] = (float) biquad[i];
        float crown = kMinDb;
        for (int i = 0; i < kNumPlotPoints; ++i)
        {
            const double hz = kMinHz * std::pow (kMaxHz / kMinHz, (double) i / (kNumPlotPoints - 1));
            const double w = juce::MathConstants<double>::twoPi * hz / kEvalSampleRate;
            const double cosw = std::cos (w), sinw = std::sin (w);
            const double cos2w = std::cos (2.0 * w), sin2w = std::sin (2.0 * w);
            float sum = 0.0f;
            for (int s = 0; s < 6; ++s)
                if ((nonfinite & (1u << s)) == 0)
                    sum += stageMagDb (&coeffs[s * 5], cosw, sinw, cos2w, sin2w);
            designerJourneyDb[(size_t) k][(size_t) i] = sum;
            crown = juce::jmax (crown, sum);
        }
        designerJourneyCrown[k] = crown;
    }
    designerJourneyPass = designerJourneyGate();
}

juce::Rectangle<int> WorkstationEditor::designerFamilyArea() const
{
    const auto p = designerArea();
    return { p.getX() + 554, p.getY() + 28, 100, 20 };
}
juce::Rectangle<int> WorkstationEditor::designerSaveArea() const
{
    const auto p = designerArea();
    return { p.getRight() - 130, p.getY() + 28, 120, 20 };
}

bool WorkstationEditor::designerJourneyGate() const
{
    // family-aware: RIDE tolerates late-building crowns (the real 303 fails a
    // naive mid-crest gate); ARCH is the journey law — middles out-crest ends.
    const float end = juce::jmin (designerJourneyCrown[0], designerJourneyCrown[4]);
    const float midMax = juce::jmax (designerJourneyCrown[1], designerJourneyCrown[2],
                                     designerJourneyCrown[3]);
    if (designerFamily == 0)
        return designerJourneyCrown[1] >= end - 3.0f
            && designerJourneyCrown[2] >= end - 3.0f
            && designerJourneyCrown[3] >= end - 3.0f;
    return midMax > juce::jmax (designerJourneyCrown[0], designerJourneyCrown[4]);
}

void WorkstationEditor::designerFrameL10()
{
    // the watcher's L10 law: per corner, crowns to +2/+8/+25/+27 via SCALE
    // words spread over ACTIVE rows only — framing identity rows is the
    // silent-body trap.
    static const double kCrownTargets[4] = { 2.0, 8.0, 25.0, 27.0 };
    for (int c = 0; c < 4; ++c)
    {
        std::vector<int> active;
        for (int s = 0; s < 6; ++s)
            if (std::memcmp (words[c][s], identityWords, sizeof identityWords) != 0)
                active.push_back (s);
        if (active.empty())
            continue;
        for (int iter = 0; iter < 6; ++iter)   // encode() quantizes; converge
        {
            std::array<juce::uint8, 240> bytes {};
            if (trench_pack_body_from_corner_words (&words[0][0][0], 120, bytes.data()) != 0)
                return;
            double biquad[30] {};
            double maxR = 0.0;
            juce::uint32 unstable = 0, nonfinite = 0;
            if (trench_packed_probe (bytes.data(), 240, (c == 1 || c == 3) ? 1.0 : 0.0,
                                     c >= 2 ? 1.0 : 0.0, biquad, &maxR, &unstable, &nonfinite) != 0)
                return;
            float coeffs[30];
            for (int i = 0; i < 30; ++i)
                coeffs[i] = (float) biquad[i];
            float crown = kMinDb;
            for (int i = 0; i < kNumPlotPoints; ++i)
            {
                const double hz = kMinHz * std::pow (kMaxHz / kMinHz, (double) i / (kNumPlotPoints - 1));
                const double w = juce::MathConstants<double>::twoPi * hz / kEvalSampleRate;
                float sum = 0.0f;
                for (int s = 0; s < 6; ++s)
                    sum += stageMagDb (&coeffs[s * 5], std::cos (w), std::sin (w),
                                       std::cos (2.0 * w), std::sin (2.0 * w));
                crown = juce::jmax (crown, sum);
            }
            const double delta = kCrownTargets[c] - crown;
            if (std::abs (delta) <= 0.1)
                break;
            const double g = std::pow (10.0, delta / (20.0 * (double) active.size()));
            for (int s : active)
                words[c][s][4] = trench_packed_encode (trench_packed_decode (words[c][s][4]) * g);
        }
    }
}

void WorkstationEditor::designerSaveBody()
{
    if (! hasBody)
        return;
    pushUndo();
    juce::uint16 before[4][6][5];
    std::memcpy (before, words, sizeof before);
    designerFrameL10();
    if (! packAndInstall())   // framing changed bytes: re-certify or revert
    {
        std::memcpy (words, before, sizeof before);
        packAndInstall();
        statusLine = "L10 framing rejected by the stability gate - reverted, not saved";
        repaint();
        return;
    }
    designerRefreshJourney();
    auto name = nameField.getText().trim();
    if (name.isEmpty())
        name = "DESIGNER";
    const auto f = processor.forgeSaveBody (name);
    statusLine = f.existsAsFile()
        ? (juce::String ("FRAMED+CERTIFIED -> ") + f.getFullPathName()
           + (designerJourneyPass ? "" : "   [journey " + juce::String (designerFamily == 0 ? "RIDE" : "ARCH") + " FAIL - ear decides]"))
        : "save failed";
    if (f.existsAsFile())
    {
        dirty = false;
        scanBin();
    }
    repaint();
}

void WorkstationEditor::designerSketchQ100()
{
    // the measured MD-Q law (bw x0.375, zeros hold, ceiling r 0.998) applied
    // to the compiled Q0 pose, landed as hand-editable FREE sections. A
    // sketch, never the ship value.
    TrenchDesignerSection ffi[6] {};
    for (int stage = 0; stage < 6; ++stage)
    {
        const auto& s = dsections[0][stage];
        auto& d = ffi[stage];
        d.type_id = s.type;
        const DesignerRowState* rows[2] = { &s.lo, &s.hi };
        TrenchDesignerRow* out[2] = { &d.low, &d.high };
        for (int r = 0; r < 2; ++r)
        {
            out[r]->freq = rows[r]->freq;
            out[r]->gain = rows[r]->gain;
            out[r]->pole_hz = rows[r]->poleHz;
            out[r]->pole_r = rows[r]->poleR;
            out[r]->zero_hz = rows[r]->zeroHz;
            out[r]->zero_r = rows[r]->zeroR;
            out[r]->scale = rows[r]->scale;
        }
    }
    for (int morph = 0; morph < 2; ++morph)
    {
        juce::uint16 corner[30] {};
        if (trench_designer_compile_corner (ffi, 6, (double) morph, designerShift, corner) != 0)
            return;
        for (int stage = 0; stage < 6; ++stage)
        {
            auto& target = dsections[1][stage];
            if (dsections[0][stage].type == 0)
            {
                target.type = 0;
                continue;
            }
            double roots[5] {};
            if (std::memcmp (&corner[stage * 5], identityWords, sizeof identityWords) == 0
                || trench_stage_roots_from_words (&corner[stage * 5], roots) != 0)
            {
                target = dsections[0][stage];   // real-pair rows keep a flat Q axis, honestly
                continue;
            }
            target.type = kDesignerTypeFree;
            auto& rw = morph == 0 ? target.lo : target.hi;
            rw.poleHz = roots[0];
            rw.poleR = juce::jmin (0.998, 1.0 - (1.0 - roots[1]) * 0.375);
            rw.zeroHz = roots[2];
            rw.zeroR = roots[3];
            rw.scale = roots[4];
        }
    }
    designerPage = 1;
    designerTemplateName.clear();
    statusLine = "Q100 SKETCH: MD-Q bw x0.375 -> FREE sections (hand-edit from here)";
    designerApply();
}

void WorkstationEditor::designerApplyMotif (int stage, int motif)
{
    auto& s = dsections[designerPage][stage];
    if (s.type != kDesignerTypeFree || motif < 0 || motif >= 5)
        return;
    const auto& m = kDesignerMotifs[motif];
    for (auto* rw : { &s.lo, &s.hi })
    {
        rw->zeroHz = juce::jlimit (20.0, (double) kMaxHz, rw->poleHz * std::pow (2.0, m.oct));
        rw->zeroR = m.zeroR;
    }
    statusLine = juce::String ("S") + juce::String (stage + 1) + " zero motif: " + m.label;
    designerApply();
}

void WorkstationEditor::designerSetTemplate (int index)
{
    for (auto& page : dsections)
        for (auto& s : page)
            s = DesignerSectionState {};
    designerShift = 0;
    auto eq = [this] (int stage, double loHz, int loGain, double hiHz, int hiGain, int type = 1)
    {
        auto& s = dsections[0][stage];
        s.type = type;
        s.lo.freq = designerCodeForHz (loHz);
        s.lo.gain = loGain;
        s.hi.freq = designerCodeForHz (hiHz);
        s.hi.gain = hiGain;
    };
    switch (index)
    {
        case 0: designerTemplateName = "BASS RIDE 110-330";
            eq (0, 110.0, 104, 330.0, 104);
            eq (1, 110.0, 92, 330.0, 92, 2);
            break;
        case 1: designerTemplateName = "SUB>GROWL RISER 30-1000";
            eq (0, 30.0, 102, 1000.0, 102, 2);
            eq (1, 30.0, 98, 1000.0, 98);
            break;
        case 2: designerTemplateName = "MID-CLIMAX ARCH 30-2200-300";
            eq (0, 30.0, 106, 2200.0, 106);
            eq (1, 2200.0, 96, 300.0, 96);
            break;
        case 3: designerTemplateName = "PARKED SQUELCH 370-400";
            eq (0, 370.0, 112, 400.0, 112);
            eq (1, 370.0, 84, 400.0, 84);
            break;
        case 4: designerTemplateName = "HF DROPPER 9700-100";
            eq (0, 9700.0, 104, 100.0, 104, 2);
            eq (1, 9700.0, 88, 100.0, 88);
            break;
        case 5: designerTemplateName = "MID DESCENDER 4000-1500";
            eq (0, 4000.0, 102, 1500.0, 102);
            break;
        case 6: designerTemplateName = "VOWEL ARCH OUT-AND-HOME";
            eq (0, 300.0, 102, 2200.0, 102);
            eq (1, 2200.0, 102, 300.0, 102);
            eq (2, 300.0, 88, 300.0, 88);
            break;
        case 7:
        {
            designerTemplateName = "ATTIC-STACK 303";
            // the TRENCH-303 slot table (dev/tmp/journey01/build_trench_303.py):
            // pole M0/M100 Hz, bw M0/M100 Hz, zero M0/M100 Hz, zero r
            static const double slots[6][7] = {
                { 72.0, 242.0, 430.0, 26.0, 2500.0, 1300.0, 0.93 },
                { 430.0, 1300.0, 270.0, 330.0, 12800.0, 3900.0, 0.87 },
                { 12200.0, 3900.0, 660.0, 1900.0, 14500.0, 6100.0, 0.86 },
                { 14400.0, 6100.0, 780.0, 1500.0, 16800.0, 16500.0, 0.90 },
                { 16600.0, 7800.0, 400.0, 380.0, 3600.0, 16800.0, 0.995 },
                { 95.0, 95.0, 1400.0, 1400.0, 460.0, 410.0, 0.955 },
            };
            const auto rOfBw = [] (double bw) { return juce::jmin (0.999, std::exp (-juce::MathConstants<double>::pi * bw / kEvalSampleRate)); };
            for (int page = 0; page < 2; ++page)
                for (int stage = 0; stage < 6; ++stage)
                {
                    auto& s = dsections[page][stage];
                    s.type = kDesignerTypeFree;
                    const double qTight = page == 1 ? 0.375 : 1.0;
                    const double drift = page == 1 ? 1.06 : 1.0;
                    DesignerRowState* rows[2] = { &s.lo, &s.hi };
                    for (int r = 0; r < 2; ++r)
                    {
                        rows[r]->poleHz = juce::jlimit (20.0, (double) kMaxHz, slots[stage][r] * drift);
                        rows[r]->poleR = rOfBw (slots[stage][2 + r] * qTight);
                        rows[r]->zeroHz = juce::jlimit (20.0, (double) kMaxHz, slots[stage][4 + r]);
                        rows[r]->zeroR = slots[stage][6];
                        rows[r]->scale = 1.0;
                    }
                }
            break;
        }
        default: return;
    }
    designerPage = 0;
    statusLine = "TEMPLATE " + designerTemplateName + " (re-tune from here)";
    designerApply();
}

void WorkstationEditor::designerShowShapeMenu (int stage)
{
    juce::PopupMenu menu;
    for (int t = 0; t < 5; ++t)
        menu.addItem (t + 1, kDesignerTypeNames[t], true, dsections[designerPage][stage].type == t);
    menu.showMenuAsync (juce::PopupMenu::Options().withTargetScreenArea (
                            localAreaToGlobal (designerShapeArea (stage))),
                        [this, stage] (int result)
                        {
                            if (result <= 0)
                                return;
                            dsections[designerPage][stage].type = result - 1;
                            designerApply();
                        });
}

void WorkstationEditor::designerShowMotifMenu (int stage)
{
    if (dsections[designerPage][stage].type != kDesignerTypeFree)
        return;
    juce::PopupMenu menu;
    for (int i = 0; i < 5; ++i)
        menu.addItem (i + 1, kDesignerMotifs[i].label);
    menu.showMenuAsync (juce::PopupMenu::Options().withTargetScreenArea (
                            localAreaToGlobal (designerMotifArea (stage))),
                        [this, stage] (int result)
                        {
                            if (result > 0)
                                designerApplyMotif (stage, result - 1);
                        });
}

void WorkstationEditor::designerShowTemplateMenu()
{
    juce::PopupMenu menu;
    const char* names[8] = { "BASS RIDE 110-330", "SUB>GROWL RISER 30-1000",
                             "MID-CLIMAX ARCH 30-2200-300", "PARKED SQUELCH 370-400",
                             "HF DROPPER 9700-100", "MID DESCENDER 4000-1500",
                             "VOWEL ARCH OUT-AND-HOME", "ATTIC-STACK 303" };
    for (int i = 0; i < 8; ++i)
        menu.addItem (i + 1, names[i]);
    menu.showMenuAsync (juce::PopupMenu::Options().withTargetScreenArea (
                            localAreaToGlobal (designerTemplateArea())),
                        [this] (int result)
                        {
                            if (result > 0)
                                designerSetTemplate (result - 1);
                        });
}

void WorkstationEditor::designerBeginEdit (int stage, int row, int field)
{
    dsEditStage = stage;
    dsEditRow = row;
    dsEditField = field;
    const bool typed = dsections[designerPage][stage].type != kDesignerTypeFree;
    const double v = designerFieldValue (stage, row, field);
    designerEditor.setBounds (designerCellArea (stage, row, field));
    designerEditor.setText (typed ? juce::String ((int) v)
                                  : juce::String (v, field == 0 || field == 3 ? 1 : 4),
                            juce::dontSendNotification);
    designerEditor.setVisible (true);
    designerEditor.grabKeyboardFocus();
    designerEditor.selectAll();
}

void WorkstationEditor::designerCommitEdit()
{
    const int stage = dsEditStage, row = dsEditRow, field = dsEditField;
    dsEditField = -1;
    const auto text = designerEditor.getText();
    designerEditor.setVisible (false);
    if (stage >= 0 && field >= 0 && text.isNotEmpty())
    {
        designerSetField (stage, row, field, text.getDoubleValue());
        designerApply();
    }
}

bool WorkstationEditor::designerMouseDown (juce::Point<int> pos)
{
    if (designerCloseArea().contains (pos) || ! designerArea().contains (pos))
    {
        toggleDesigner();
        return true;
    }
    for (int page = 0; page < 2; ++page)
        if (designerPageArea (page).contains (pos))
        {
            designerPage = page;
            designerRefreshJourney();
            repaint();
            return true;
        }
    if (designerTemplateArea().contains (pos))
    {
        designerShowTemplateMenu();
        return true;
    }
    if (designerSketchArea().contains (pos))
    {
        designerSketchQ100();
        return true;
    }
    if (designerFamilyArea().contains (pos))
    {
        designerFamily = 1 - designerFamily;
        designerJourneyPass = designerJourneyGate();
        repaint();
        return true;
    }
    if (designerSaveArea().contains (pos))
    {
        designerSaveBody();
        return true;
    }
    for (int stage = 0; stage < 6; ++stage)
    {
        if (designerShapeArea (stage).contains (pos))
        {
            designerShowShapeMenu (stage);
            return true;
        }
        if (dsections[designerPage][stage].type == kDesignerTypeFree
            && designerMotifArea (stage).contains (pos))
        {
            designerShowMotifMenu (stage);
            return true;
        }
        const int fields = dsections[designerPage][stage].type == kDesignerTypeFree ? 5 : 2;
        if (dsections[designerPage][stage].type != 0)
            for (int row = 0; row < 2; ++row)
                for (int field = 0; field < fields; ++field)
                    if (designerCellArea (stage, row, field).contains (pos))
                    {
                        designerBeginEdit (stage, row, field);
                        return true;
                    }
    }
    return true;   // modal: swallow clicks inside the panel
}

void WorkstationEditor::drawDesigner (juce::Graphics& g)
{
    if (! designerOpen)
        return;
    const auto p = designerArea().toFloat();
    // opaque: the Designer is the front door — no stale workstation lore behind it
    g.setColour (kBg);
    g.fillRect (getLocalBounds().toFloat());
    g.setColour (kPanel);
    g.fillRect (p);
    g.setColour (kCyan.withAlpha (0.7f));
    g.drawRect (p, 1.0f);

    drawFlatButton (g, designerCloseArea(), "X", false, true);

    drawFlatButton (g, designerPageArea (0), "Q0 POSE", designerPage == 0, true);
    drawFlatButton (g, designerPageArea (1), "Q100 POSE", designerPage == 1, true);
    drawFlatButton (g, designerTemplateArea(), "TEMPLATE", false, true);
    drawFlatButton (g, designerSketchArea(), "SKETCH Q100 x0.375", false, true);
    drawFlatButton (g, designerShiftArea(), "SHIFT " + juce::String (designerShift), false, true);
    drawFlatButton (g, designerFamilyArea(), designerFamily == 0 ? "FAM RIDE" : "FAM ARCH",
                    designerFamily == 1, true);
    drawFlatButton (g, designerSaveArea(), "SAVE (L10)", false, hasBody);

    // JOURNEY strip: five packed-runtime curves M0..M100, fixed -60..+30 scale
    const auto j = designerJourneyArea().toFloat();
    g.setColour (kPanelDeep);
    g.fillRect (j);
    const auto inner = j.reduced (2.0f);
    const float zeroY = inner.getY() + inner.getHeight() * (1.0f - (0.0f - kMinDb) / (kMaxDb - kMinDb));
    g.setColour (juce::Colour (0x30ffffff));
    g.drawHorizontalLine (juce::roundToInt (zeroY), inner.getX(), inner.getRight());
    if (designerJourneyOk)
        for (int k = 0; k < 5; ++k)
        {
            juce::Path path;
            for (int i = 0; i < kNumPlotPoints; ++i)
            {
                const float x = inner.getX() + ((float) i / (kNumPlotPoints - 1)) * inner.getWidth();
                const float norm = (std::clamp (designerJourneyDb[(size_t) k][(size_t) i], kMinDb, kMaxDb) - kMinDb)
                                 / (kMaxDb - kMinDb);
                const float y = inner.getY() + inner.getHeight() * (1.0f - norm);
                if (i == 0) path.startNewSubPath (x, y);
                else path.lineTo (x, y);
            }
            g.setColour (kCyan.withAlpha (0.25f + 0.1875f * (float) k));
            g.strokePath (path, juce::PathStrokeType (k == 4 ? 1.4f : 1.0f));
        }
    g.setColour (kBorder);
    g.drawRect (j, 1.0f);
    g.setColour (kTextDim);
    g.setFont (juce::FontOptions (9.0f));
    juce::String crowns = "JOURNEY  M0..M100 @ " + juce::String (designerPage == 1 ? "Q100" : "Q0") + "   crowns ";
    for (int k = 0; k < 5; ++k)
        crowns += juce::String (designerJourneyCrown[k], 1) + (k < 4 ? " / " : " dB");
    if (designerJourneyOk)
    {
        crowns += juce::String ("   ") + (designerFamily == 0 ? "RIDE " : "ARCH ")
                + (designerJourneyPass ? "PASS" : "FAIL");
    }
    g.drawText (crowns, (int) j.getX() + 6, (int) j.getY() + 3, (int) j.getWidth() - 12, 12,
                juce::Justification::left);
    g.drawText (lastCertifyPass ? "CERTIFIED maxR " + juce::String (lastCertifyMaxR, 4) : statusLine,
                (int) j.getX() + 6, (int) j.getBottom() - 15, (int) j.getWidth() - 12, 12,
                juce::Justification::left);

    // six stage rows
    for (int stage = 0; stage < 6; ++stage)
    {
        const auto r = designerStageRowArea (stage).toFloat();
        g.setColour (kPanelDeep);
        g.fillRect (r);
        g.setColour (kBorder);
        g.drawRect (r, 1.0f);
        g.setColour (kLaneColours[stage]);
        g.setFont (juce::FontOptions (11.0f).withStyle ("Bold"));
        g.drawText ("S" + juce::String (stage + 1), (int) r.getX() + 4, (int) r.getY() + 24, 20, 16,
                    juce::Justification::left);
        const auto& s = dsections[designerPage][stage];
        drawFlatButton (g, designerShapeArea (stage), kDesignerTypeNames[s.type], s.type != 0, true);
        if (s.type == kDesignerTypeFree)
            drawFlatButton (g, designerMotifArea (stage), "MOTIF", false, true);
        if (s.type == 0)
            continue;
        g.setColour (kGridLabel);
        g.setFont (juce::FontOptions (9.0f));
        g.drawText ("LO", (int) r.getX() + 148, (int) r.getY() + 11, 20, 14, juce::Justification::left);
        g.drawText ("HI", (int) r.getX() + 148, (int) r.getY() + 39, 20, 14, juce::Justification::left);
        const int fields = s.type == kDesignerTypeFree ? 5 : 2;
        for (int row = 0; row < 2; ++row)
            for (int field = 0; field < fields; ++field)
            {
                const auto cell = designerCellArea (stage, row, field);
                g.setColour (kBg);
                g.fillRect (cell);
                g.setColour (kBorder);
                g.drawRect (cell, 1);
                const auto& rw = row == 0 ? s.lo : s.hi;
                juce::String text;
                if (s.type != kDesignerTypeFree)
                    text = field == 0
                         ? "F " + juce::String (rw.freq) + "  " + juce::String (designerLadderHz[juce::jlimit (0, 127, rw.freq)], 0) + " Hz"
                         : "G " + juce::String (rw.gain);
                else
                    switch (field)
                    {
                        case 0: text = "P " + juce::String (rw.poleHz, 1) + " Hz"; break;
                        case 1: text = "r " + juce::String (rw.poleR, 4); break;
                        case 2: text = "s " + juce::String (rw.scale, 2); break;
                        case 3: text = "Z " + juce::String (rw.zeroHz, 1) + " Hz"; break;
                        default: text = "zr " + juce::String (rw.zeroR, 3); break;
                    }
                g.setColour (kText);
                g.setFont (juce::FontOptions (10.0f));
                g.drawText (text, cell.reduced (4, 0), juce::Justification::left);
            }
    }
}

bool WorkstationEditor::keyPressed (const juce::KeyPress& key)
{
    if (key == juce::KeyPress ('f', juce::ModifierKeys::ctrlModifier, 0))
    {
        binSearch.grabKeyboardFocus();
        binSearch.selectAll();
        return true;
    }
    if (key == juce::KeyPress ('z', juce::ModifierKeys::ctrlModifier, 0))
    {
        undo();
        return true;
    }
    if (key == juce::KeyPress ('y', juce::ModifierKeys::ctrlModifier, 0)
        || key == juce::KeyPress ('z', juce::ModifierKeys::ctrlModifier | juce::ModifierKeys::shiftModifier, 0))
    {
        redo();
        return true;
    }
    if (key == juce::KeyPress::escapeKey && designerOpen)
    {
        toggleDesigner();
        return true;
    }
    if (key == juce::KeyPress::escapeKey && pzWindowOpen)
    {
        pzWindowOpen = false;
        repaint();
        return true;
    }
    return false;
}

void WorkstationEditor::mouseWheelMove (const juce::MouseEvent& e, const juce::MouseWheelDetails& wheel)
{
    if (designerOpen)
    {
        const auto pos = e.getPosition();
        const int dir = wheel.deltaY > 0.0f ? 1 : -1;
        if (designerShiftArea().contains (pos))
        {
            designerShift = juce::jlimit (-32, 31, designerShift + dir);
            designerApply();
            return;
        }
        for (int stage = 0; stage < 6; ++stage)
        {
            const auto& s = dsections[designerPage][stage];
            if (s.type == 0)
                continue;
            const int fields = s.type == kDesignerTypeFree ? 5 : 2;
            for (int row = 0; row < 2; ++row)
                for (int field = 0; field < fields; ++field)
                    if (designerCellArea (stage, row, field).contains (pos))
                    {
                        const double v = designerFieldValue (stage, row, field);
                        double next = v;
                        if (s.type != kDesignerTypeFree)
                            next = v + dir;                                   // one ladder step / gain tick
                        else if (field == 0 || field == 3)
                            next = v * std::pow (kDesignerLadderRatio, dir);  // ~68.4 c/step
                        else if (field == 2)
                            next = v + 0.05 * dir;
                        else
                            next = v + 0.005 * dir;
                        designerSetField (stage, row, field, next);
                        designerApply();
                        return;
                    }
        }
        return;
    }
    if (! binListArea().contains (e.getPosition()))
        return;
    const int visibleRows = juce::jmax (1, binListArea().getHeight() / kBinRowH);
    binScroll = juce::jlimit (0, juce::jmax (0, (int) rows.size() - visibleRows),
                              binScroll - juce::roundToInt (wheel.deltaY * 3.0f));
    repaint();
}

bool WorkstationEditor::isInterestedInFileDrag (const juce::StringArray& files)
{
    for (const auto& f : files)
        if (f.endsWithIgnoreCase (".wav") || f.endsWithIgnoreCase (".aif") || f.endsWithIgnoreCase (".aiff")
            || f.endsWithIgnoreCase (".flac") || f.endsWithIgnoreCase (".mp3"))
            return true;
    return false;
}

void WorkstationEditor::filesDropped (const juce::StringArray& files, int, int)
{
    if (gWorkstationLoop == nullptr || files.isEmpty())
        return;
    if (gWorkstationLoop->loadFile (juce::File (files[0])))
    {
        gWorkstationLoop->setPlaying (true);
        statusLine = "LOOP <- " + gWorkstationLoop->loopName() + "  (looping through the working body)";
    }
    else
    {
        statusLine = "could not read " + files[0];
    }
    repaint();
}
