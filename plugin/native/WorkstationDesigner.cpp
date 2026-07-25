// Split from WorkstationEditor.cpp 2026-07-25 — no logic changes.
// THE TRENCH DESIGNER panel: state, compile-on-edit, gates, drawing.
#include "WorkstationTheme.h"

// ------------------------------------------------------------ THE DESIGNER
// MD ergonomics + P2K reach: parameter-space sections compiled through the
// firmware word recipe (trench-core designer.rs). Every edit recompiles,
// certifies, installs — the fence replaced by a net.


juce::Rectangle<int> WorkstationEditor::designerButtonArea() const { return { 906, 18, 100, 28 }; }
juce::Rectangle<int> WorkstationEditor::detailButtonArea() const   { return { 666, 10, 64, 20 }; }
juce::Rectangle<int> WorkstationEditor::designerArea() const      { return getLocalBounds().reduced (8); }
juce::Rectangle<int> WorkstationEditor::designerCloseArea() const
{
    const auto p = designerArea();
    return { p.getRight() - 26, p.getY() + 6, 20, 18 };
}
juce::Rectangle<int> WorkstationEditor::designerPageArea (int page) const
{
    const auto p = designerArea();
    return { p.getX() + 10 + page * 84, p.getY() + 32, 80, 20 };
}
juce::Rectangle<int> WorkstationEditor::designerTemplateArea() const
{
    const auto p = designerArea();
    return { p.getX() + 186, p.getY() + 32, 110, 20 };
}
juce::Rectangle<int> WorkstationEditor::designerSketchArea() const
{
    const auto p = designerArea();
    return { p.getX() + 302, p.getY() + 32, 110, 20 };
}
juce::Rectangle<int> WorkstationEditor::designerUndoArea() const
{
    const auto p = designerArea();
    return { p.getX() + 418, p.getY() + 32, 64, 20 };
}
juce::Rectangle<int> WorkstationEditor::designerRedoArea() const
{
    const auto p = designerArea();
    return { p.getX() + 486, p.getY() + 32, 64, 20 };
}
juce::Rectangle<int> WorkstationEditor::designerJourneyArea() const
{
    const auto p = designerArea();
    return { p.getX() + 10, p.getY() + 58, p.getWidth() - 20, 168 };
}
juce::Rectangle<int> WorkstationEditor::designerStageRowArea (int stage) const
{
    const auto p = designerArea();
    return { p.getX() + 10, p.getY() + 234 + stage * 66, p.getWidth() - 20, 64 };
}
juce::Rectangle<int> WorkstationEditor::designerShapeArea (int stage) const
{
    const auto r = designerStageRowArea (stage);
    return { r.getX() + 26, r.getY() + 20, 90, 24 };
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

// section-level undo: one snapshot per gesture, restored through a full apply
void WorkstationEditor::designerPushUndo()
{
    DesignerSnapshot snap;
    std::memcpy (snap.sections, dsections, sizeof snap.sections);
    snap.shift = designerShift;
    snap.page = designerPage;
    dsUndoStack.push_back (snap);
    if (dsUndoStack.size() > 64)
        dsUndoStack.erase (dsUndoStack.begin());
    dsRedoStack.clear();
}

void WorkstationEditor::designerUndo()
{
    if (dsUndoStack.empty())
        return;
    DesignerSnapshot cur;
    std::memcpy (cur.sections, dsections, sizeof cur.sections);
    cur.shift = designerShift;
    cur.page = designerPage;
    dsRedoStack.push_back (cur);
    const auto snap = dsUndoStack.back();
    dsUndoStack.pop_back();
    std::memcpy (dsections, snap.sections, sizeof dsections);
    designerShift = snap.shift;
    designerPage = snap.page;
    designerApply();
}

void WorkstationEditor::designerRedo()
{
    if (dsRedoStack.empty())
        return;
    DesignerSnapshot cur;
    std::memcpy (cur.sections, dsections, sizeof cur.sections);
    cur.shift = designerShift;
    cur.page = designerPage;
    dsUndoStack.push_back (cur);
    const auto snap = dsRedoStack.back();
    dsRedoStack.pop_back();
    std::memcpy (dsections, snap.sections, sizeof dsections);
    designerShift = snap.shift;
    designerPage = snap.page;
    designerApply();
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

void WorkstationEditor::designerApply (bool certifyNow)
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
    if (hasBody && certifyNow)
        pushUndo();   // one undo step per gesture, not per scrub tick
    wordsFromBytes240 (bytes, words);
    std::fill (std::begin (muteBackupValid), std::end (muteBackupValid), false);
    hasBody = true;
    dirty = true;
    if (bodyName.isEmpty())
        bodyName = "DESIGNER";
    designerFrameL10();            // you HEAR the framed level, always (L10 law)
    packAndInstall (certifyNow);   // the net; scrub ticks take the light path
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
            {
                if ((nonfinite & (1u << s)) != 0)
                    continue;
                const float db = stageMagDb (&coeffs[s * 5], cosw, sinw, cos2w, sin2w);
                sum += db;
                if (k == 0)
                    designerStageDb[0][(size_t) s][(size_t) i] = db;   // LO end
                else if (k == 4)
                    designerStageDb[1][(size_t) s][(size_t) i] = db;   // HI end
            }
            designerJourneyDb[(size_t) k][(size_t) i] = sum;
            crown = juce::jmax (crown, sum);
        }
        designerJourneyCrown[k] = crown;
    }
    designerJourneyPass = designerJourneyGate();
    if (designerGhostValid)
        for (int k = 0; k < 5; ++k)
        {
            double biquad[30] {};
            double maxR = 0.0;
            juce::uint32 unstable = 0, nonfinite = 0;
            if (trench_packed_probe (designerGhostBytes.data(), 240, k / 4.0, q,
                                     biquad, &maxR, &unstable, &nonfinite) != 0)
                break;
            float coeffs[30];
            for (int i = 0; i < 30; ++i)
                coeffs[i] = (float) biquad[i];
            for (int i = 0; i < kNumPlotPoints; ++i)
            {
                const double hz = kMinHz * std::pow (kMaxHz / kMinHz, (double) i / (kNumPlotPoints - 1));
                const double w = juce::MathConstants<double>::twoPi * hz / kEvalSampleRate;
                float sum = 0.0f;
                for (int s = 0; s < 6; ++s)
                    if ((nonfinite & (1u << s)) == 0)
                        sum += stageMagDb (&coeffs[s * 5], std::cos (w), std::sin (w),
                                           std::cos (2.0 * w), std::sin (2.0 * w));
                designerGhostDb[(size_t) k][(size_t) i] = sum;
            }
        }
}

juce::Rectangle<int> WorkstationEditor::designerFamilyArea() const
{
    const auto p = designerArea();
    return { p.getX() + 556, p.getY() + 32, 100, 20 };
}
juce::Rectangle<int> WorkstationEditor::designerSaveArea() const
{
    const auto p = designerArea();
    return { p.getRight() - 130, p.getY() + 32, 120, 20 };
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
    const auto f = processor.forgeSaveBody (name, true);
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

juce::Rectangle<int> WorkstationEditor::designerImportArea() const
{
    const auto p = designerArea();
    return { p.getX() + 662, p.getY() + 32, 90, 20 };
}

// The photograph enters the Designer: the working body's four corners land as
// hand-editable FREE sections (extract -> caricature -> frame -> ear). Rows
// that don't decode to conjugate roots stay OFF and are named in the status.
void WorkstationEditor::designerImportWorking()
{
    designerPushUndo();
    if (! hasBody)
    {
        statusLine = "IMPORT: load a body first (BIN), then open the Designer";
        repaint();
        return;
    }
    juce::String skipped;
    for (int page = 0; page < 2; ++page)
        for (int stage = 0; stage < 6; ++stage)
        {
            auto& sec = dsections[page][stage];
            sec = DesignerSectionState {};
            const int corners[2] = { page * 2, page * 2 + 1 };   // (M0,M100) of this Q page
            bool ok = true;
            DesignerRowState rows[2];
            for (int r = 0; r < 2 && ok; ++r)
            {
                const auto* w = words[corners[r]][stage];
                if (std::memcmp (w, identityWords, sizeof identityWords) == 0)
                {
                    ok = false;   // identity lane -> OFF
                    break;
                }
                double roots[5] {};
                if (trench_stage_roots_from_words (w, roots) != 0)
                {
                    ok = false;
                    skipped += " S" + juce::String (stage + 1) + (page == 0 ? "Q0" : "Q100");
                    break;
                }
                rows[r].poleHz = roots[0];
                rows[r].poleR = roots[1];
                rows[r].zeroHz = roots[2];
                rows[r].zeroR = roots[3];
                rows[r].scale = roots[4];
            }
            if (ok)
            {
                sec.type = kDesignerTypeFree;
                sec.lo = rows[0];
                sec.hi = rows[1];
            }
        }
    designerTemplateName.clear();
    statusLine = "IMPORT <- " + bodyName
               + (skipped.isEmpty() ? "  (all stages editable)" : "  (kept OFF:" + skipped + ")");
    designerApply();
    designerGhostBytes = workingBytes;   // the photograph, kept as the A/B ghost
    designerGhostValid = true;
    designerRefreshJourney();
    repaint();
}

// The cheat: drop a wav, hear it through its own framed body seconds later.
// Voice = ARMA fit of two poses of the file (early -> M0, late -> M100),
// strongest in-band resonances on S2..S5. Frame = the measured hedz frame:
// S1 TILT rail + S6 traveling NOTCH. Everything lands editable.
void WorkstationEditor::designerWrapWav (const juce::File& file)
{
    juce::AudioFormatManager fm;
    fm.registerBasicFormats();
    std::unique_ptr<juce::AudioFormatReader> reader (fm.createReaderFor (file));
    if (reader == nullptr || reader->lengthInSamples < 256)
    {
        statusLine = "WRAP: could not read " + file.getFileName();
        repaint();
        return;
    }
    const int total = (int) juce::jmin<juce::int64> (reader->lengthInSamples, 8 * 65536);
    juce::AudioBuffer<float> buf (1, total);
    reader->read (&buf, 0, total, 0, true, false);

    struct Fitted { double poleHz, poleR, zeroHz, zeroR, scale; };
    const auto fitPose = [&] (int start, int len) -> std::vector<Fitted>
    {
        std::vector<double> mono ((size_t) len);
        const float* s = buf.getReadPointer (0) + start;
        for (int i = 0; i < len; ++i)
            mono[(size_t) i] = (double) s[i];
        double coeffs[30] {};
        std::vector<Fitted> out;
        if (trench_fit_corner_arma (mono.data(), mono.size(), reader->sampleRate, kEvalSampleRate, coeffs) != 0)
            return out;
        for (int st = 0; st < 6; ++st)
        {
            const double* c = &coeffs[st * 5];
            const juce::uint16 w[5] = {
                trench_packed_encode ((c[0] - c[1]) / 4.0), trench_packed_encode (c[1]),
                trench_packed_encode ((c[2] - c[3]) / 4.0), trench_packed_encode (c[3]),
                trench_packed_encode (c[4] / 4.0) };
            double roots[5] {};
            if (trench_stage_roots_from_words (w, roots) != 0)
                continue;   // real-pair rows don't join the voice
            if (roots[0] < 60.0 || roots[0] > 16000.0 || roots[1] <= 0.0)
                continue;
            out.push_back ({ roots[0], juce::jmin (roots[1], 0.9990),
                             juce::jlimit (20.0, (double) kMaxHz, roots[2]),
                             juce::jlimit (0.0, 1.0, roots[3]),
                             juce::jlimit (0.0, 4.0, roots[4]) });
        }
        std::sort (out.begin(), out.end(), [] (const Fitted& a, const Fitted& b) { return a.poleR > b.poleR; });
        if (out.size() > 4)
            out.resize (4);
        std::sort (out.begin(), out.end(), [] (const Fitted& a, const Fitted& b) { return a.poleHz < b.poleHz; });
        return out;
    };
    const auto m0 = fitPose (0, total / 2);
    const auto m100 = fitPose (total / 2, total - total / 2);
    if (m0.empty() || m100.empty())
    {
        statusLine = "WRAP: fit found no usable resonances in " + file.getFileName();
        repaint();
        return;
    }

    designerPushUndo();
    for (auto& page : dsections)
        for (auto& s : page)
            s = DesignerSectionState {};
    // frame: the measured hedz skeleton (P2k_013 decode) — re-tune from here
    auto frame = [this] (int stage, int motif, double p0, double r0, double z0, double d0,
                         double p1, double r1, double z1, double d1)
    {
        auto& s = dsections[0][stage];
        s.type = kDesignerTypeFree;
        s.motif = motif;
        s.lo = { 64, 64, p0, r0, z0, d0, 1.0 };
        s.hi = { 64, 64, p1, r1, z1, d1, 1.0 };
    };
    frame (0, 3, 9320.9, 0.9753, 346.7, 0.935, 8376.0, 0.9622, 1710.7, 0.944);   // TILT rail
    frame (5, 4, 199.4, 0.9912, 6396.3, 1.0, 1789.2, 0.9966, 17313.0, 1.0);      // traveling NOTCH
    // voice: measured resonances, early pose -> M0, late pose -> M100
    const size_t nv = juce::jmin (m0.size(), m100.size(), (size_t) 4);
    for (size_t v = 0; v < nv; ++v)
    {
        auto& s = dsections[0][1 + (int) v];
        s.type = kDesignerTypeFree;
        s.motif = -1;
        const auto& a = m0[v];
        const auto& b = m100[v];
        s.lo = { 64, 64, a.poleHz, a.poleR, a.zeroHz, a.zeroR, 1.0 };
        s.hi = { 64, 64, b.poleHz, b.poleR, b.zeroHz, b.zeroR, 1.0 };
    }
    designerGhostValid = false;
    designerTemplateName = "WRAP " + file.getFileNameWithoutExtension();
    bodyName = file.getFileNameWithoutExtension();
    nameField.setText (bodyName, juce::dontSendNotification);
    designerPage = 0;
    designerApply();
    designerSketchQ100();   // pushes its own undo step; hand-edit from here
    statusLine = "WRAP <- " + file.getFileName() + "  (" + juce::String ((int) nv)
               + " measured voices + hedz frame; re-tune and SAVE)";
    repaint();
}

void WorkstationEditor::designerSketchQ100()
{
    designerPushUndo();
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
    s.motif = motif;
    const auto& m = kDesignerMotifs[motif];
    for (auto* rw : { &s.lo, &s.hi })
    {
        rw->zeroHz = juce::jlimit (20.0, (double) kMaxHz, rw->poleHz * std::pow (2.0, m.oct));
        rw->zeroR = m.zeroR;
    }
    statusLine = juce::String ("S") + juce::String (stage + 1) + " shape: " + m.label;
    designerApply();
}

void WorkstationEditor::designerSetTemplate (int index)
{
    designerPushUndo();
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
    designerGhostValid = false;
    statusLine = "TEMPLATE " + designerTemplateName + " (re-tune from here)";
    designerApply();
}

// SHAPE speaks P2K: firmware types plus the five census stage roles. Picking
// a census shape is a pole+zero section with the measured zero relation
// applied — every slider stays editable.
void WorkstationEditor::designerShowShapeMenu (int stage)
{
    const auto& s = dsections[designerPage][stage];
    juce::PopupMenu menu;
    for (int t = 0; t < 4; ++t)
        menu.addItem (t + 1, kDesignerTypeNames[t], true, s.type == t);
    menu.addSeparator();
    for (int i = 0; i < 5; ++i)
        menu.addItem (5 + i, kDesignerMotifs[i].label, true,
                      s.type == kDesignerTypeFree && s.motif == i);
    menu.showMenuAsync (juce::PopupMenu::Options().withTargetScreenArea (
                            localAreaToGlobal (designerShapeArea (stage))),
                        [this, stage] (int result)
                        {
                            if (result <= 0)
                                return;
                            designerPushUndo();
                            auto& sec = dsections[designerPage][stage];
                            if (result <= 4)
                            {
                                sec.type = result - 1;
                                sec.motif = -1;
                                designerApply();
                            }
                            else
                            {
                                sec.type = kDesignerTypeFree;
                                designerApplyMotif (stage, result - 5);
                            }
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
        designerPushUndo();
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
    if (designerUndoArea().contains (pos))
    {
        designerUndo();
        return true;
    }
    if (designerRedoArea().contains (pos))
    {
        designerRedo();
        return true;
    }
    if (designerImportArea().contains (pos))
    {
        designerImportWorking();
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
        const int fields = dsections[designerPage][stage].type == kDesignerTypeFree ? 5 : 2;
        if (dsections[designerPage][stage].type != 0)
            for (int row = 0; row < 2; ++row)
                for (int field = 0; field < fields; ++field)
                    if (designerCellArea (stage, row, field).contains (pos))
                    {
                        // scrub slider: drag adjusts, double-click types
                        dsDragStage = stage;
                        dsDragRow = row;
                        dsDragField = field;
                        dsDragStartVal = designerFieldValue (stage, row, field);
                        dsDragStartX = pos.x;
                        dsDragMoved = false;
                        return true;
                    }
    }
    return true;   // modal: swallow clicks inside the panel
}

bool WorkstationEditor::designerMouseDrag (juce::Point<int> pos)
{
    if (! designerOpen)
        return false;
    if (dsDragField < 0)
        return true;
    const int dx = pos.x - dsDragStartX;
    if (! dsDragMoved && std::abs (dx) < kDragThreshold)
        return true;
    if (! dsDragMoved)
        designerPushUndo();
    dsDragMoved = true;
    const auto& s = dsections[designerPage][dsDragStage];
    double v = dsDragStartVal;
    if (s.type != kDesignerTypeFree)
        v = dsDragStartVal + dx / (dsDragField == 0 ? 6.0 : 4.0);   // ladder steps / gain ticks
    else if (dsDragField == 0 || dsDragField == 3)
        v = dsDragStartVal * std::pow (kDesignerLadderRatio, dx / 8.0);   // ~68.4 c per 8 px
    else if (dsDragField == 2)
        v = dsDragStartVal + dx * 0.01;
    else
        v = dsDragStartVal + dx * 0.0005;   // radius: fine
    designerSetField (dsDragStage, dsDragRow, dsDragField, v);
    designerApply (false);   // light while scrubbing; full certify on release
    return true;
}

bool WorkstationEditor::designerMouseUp()
{
    if (! designerOpen)
        return false;
    if (dsDragField >= 0 && dsDragMoved)
        designerApply();   // gesture done: certify + undo step
    dsDragField = -1;
    dsDragMoved = false;
    return true;
}

bool WorkstationEditor::designerMouseDoubleClick (juce::Point<int> pos)
{
    if (! designerOpen)
        return false;
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
                    designerBeginEdit (stage, row, field);
                    return true;
                }
    }
    return true;
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
    drawFlatButton (g, designerSketchArea(), "AUTO Q100", false, true);
    drawFlatButton (g, designerUndoArea(), "UNDO", false, ! dsUndoStack.empty());
    drawFlatButton (g, designerRedoArea(), "REDO", false, ! dsRedoStack.empty());
    drawFlatButton (g, designerImportArea(), "IMPORT", false, hasBody);
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
    if (designerJourneyOk && designerGhostValid)   // the photograph, behind the caricature
        for (int k = 0; k < 5; ++k)
        {
            juce::Path path;
            for (int i = 0; i < kNumPlotPoints; i += 2)
            {
                const float x = inner.getX() + ((float) i / (kNumPlotPoints - 1)) * inner.getWidth();
                const float norm = (std::clamp (designerGhostDb[(size_t) k][(size_t) i], kMinDb, kMaxDb) - kMinDb)
                                 / (kMaxDb - kMinDb);
                const float y = inner.getY() + inner.getHeight() * (1.0f - norm);
                if (i == 0) path.startNewSubPath (x, y);
                else path.lineTo (x, y);
            }
            g.setColour (juce::Colour (0x40aab4be));
            g.strokePath (path, juce::PathStrokeType (1.0f));
        }
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
        drawFlatButton (g, designerShapeArea (stage),
                        s.type == kDesignerTypeFree && s.motif >= 0 ? kDesignerMotifs[s.motif].label
                                                                    : kDesignerTypeNames[s.type],
                        s.type != 0, true);
        if (s.type == 0)
            continue;
        g.setColour (kGridLabel);
        g.setFont (juce::FontOptions (9.0f));
        // rows are the MORPH corner poses of this Q page: 2 pages x 2 rows = the P2K 4-corner grid
        g.drawText ("M0", (int) r.getX() + 142, (int) r.getY() + 11, 28, 14, juce::Justification::left);
        g.drawText ("M100", (int) r.getX() + 142, (int) r.getY() + 39, 28, 14, juce::Justification::left);
        const int fields = s.type == kDesignerTypeFree ? 5 : 2;
        const auto hzNorm = [] (double hz)
        {
            return (float) juce::jlimit (0.0, 1.0, std::log (juce::jmax (hz, 20.0) / 20.0)
                                                   / std::log ((double) kMaxHz / 20.0));
        };
        for (int row = 0; row < 2; ++row)
            for (int field = 0; field < fields; ++field)
            {
                const auto cell = designerCellArea (stage, row, field);
                const auto& rw = row == 0 ? s.lo : s.hi;
                // slider cell: label + value + fill bar (drag scrubs, dbl-click types)
                juce::String label, value;
                float norm = 0.0f;
                if (s.type != kDesignerTypeFree)
                {
                    if (field == 0)
                    {
                        label = "FREQ";
                        value = juce::String (designerLadderHz[juce::jlimit (0, 127, rw.freq)], 0) + " Hz";
                        norm = (float) rw.freq / 127.0f;
                    }
                    else
                    {
                        label = "GAIN";
                        value = juce::String (rw.gain);
                        norm = (float) rw.gain / 127.0f;
                    }
                }
                else
                    switch (field)
                    {
                        case 0: label = "FREQ";  value = juce::String (rw.poleHz, 0) + " Hz";
                                norm = hzNorm (rw.poleHz); break;
                        case 1: label = "RES";   value = juce::String (rw.poleR, 3);
                                norm = (float) juce::jlimit (0.0, 1.0, (rw.poleR - 0.7) / 0.3); break;
                        case 2: label = "LEVEL"; value = juce::String (rw.scale, 2);
                                norm = (float) juce::jlimit (0.0, 1.0, rw.scale / 2.0); break;
                        case 3: label = "ZERO";  value = juce::String (rw.zeroHz, 0) + " Hz";
                                norm = hzNorm (rw.zeroHz); break;
                        default: label = "DEPTH"; value = juce::String (rw.zeroR, 3);
                                 norm = (float) juce::jlimit (0.0, 1.0, rw.zeroR); break;
                    }
                g.setColour (kBg);
                g.fillRect (cell);
                g.setColour (kCyan.withAlpha (0.14f));
                g.fillRect (cell.getX() + 1, cell.getY() + 1,
                            juce::roundToInt (norm * (float) (cell.getWidth() - 2)), cell.getHeight() - 2);
                g.setColour (kBorder);
                g.drawRect (cell, 1);
                g.setColour (kGridLabel);
                g.setFont (juce::FontOptions (8.0f));
                g.drawText (label, cell.reduced (4, 0), juce::Justification::left);
                g.setColour (kText);
                g.setFont (juce::FontOptions (10.0f));
                g.drawText (value, cell.reduced (4, 0), juce::Justification::right);
            }

        // stage anatomy: LO end dim, HI end in the stage colour — the travel
        if (designerJourneyOk)
        {
            const auto cellsRight = designerCellArea (stage, 0, 4).getRight();
            juce::Rectangle<float> mini ((float) cellsRight + 10.0f, r.getY() + 4.0f,
                                         r.getRight() - (float) cellsRight - 16.0f, r.getHeight() - 8.0f);
            if (mini.getWidth() > 40.0f)
            {
                g.setColour (kPanelDeep);
                g.fillRect (mini);
                const auto inner = mini.reduced (2.0f);
                const float zy = inner.getY() + inner.getHeight() * (1.0f - (0.0f - kMinDb) / (kMaxDb - kMinDb));
                g.setColour (juce::Colour (0x28ffffff));
                g.drawHorizontalLine (juce::roundToInt (zy), inner.getX(), inner.getRight());
                for (int end = 0; end < 2; ++end)
                {
                    juce::Path path;
                    for (int i = 0; i < kNumPlotPoints; i += 4)
                    {
                        const float x = inner.getX() + ((float) i / (kNumPlotPoints - 1)) * inner.getWidth();
                        const float nv = (std::clamp (designerStageDb[(size_t) end][(size_t) stage][(size_t) i],
                                                      kMinDb, kMaxDb) - kMinDb) / (kMaxDb - kMinDb);
                        const float y = inner.getY() + inner.getHeight() * (1.0f - nv);
                        if (i == 0) path.startNewSubPath (x, y);
                        else path.lineTo (x, y);
                    }
                    g.setColour (end == 0 ? kLaneColours[stage].withAlpha (0.35f) : kLaneColours[stage]);
                    g.strokePath (path, juce::PathStrokeType (end == 0 ? 1.0f : 1.3f));
                }
                g.setColour (kBorder);
                g.drawRect (mini, 1.0f);
            }
        }
    }
}

