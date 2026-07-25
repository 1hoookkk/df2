// Renders the real PluginEditor to a PNG so the faceplate can be judged without
// launching a DAW. The render-to-PNG collab loop, as a target.

#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "TrenchBodyRoster.h"
#include "ui/TypeSelectorView.h"

#include <juce_gui_basics/juce_gui_basics.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>

namespace
{
template <typename ComponentType>
ComponentType* findChildOfType (juce::Component& root, const juce::String& title = {})
{
    if (auto* match = dynamic_cast<ComponentType*> (&root))
        if (title.isEmpty() || match->getTitle().equalsIgnoreCase (title))
            return match;

    for (int i = 0; i < root.getNumChildComponents(); ++i)
        if (auto* match = findChildOfType<ComponentType> (*root.getChildComponent (i), title))
            return match;

    return nullptr;
}

int changedPixelCount (const juce::Image& before, const juce::Image& after)
{
    if (! before.isValid() || ! after.isValid()
        || before.getBounds() != after.getBounds())
        return -1;

    int changed = 0;
    for (int y = 0; y < before.getHeight(); ++y)
        for (int x = 0; x < before.getWidth(); ++x)
            changed += before.getPixelAt (x, y) != after.getPixelAt (x, y) ? 1 : 0;
    return changed;
}
}

int main()
{
    juce::ScopedJuceInitialiser_GUI juceInit;

    PluginProcessor processor;
    processor.prepareToPlay (48000.0, 512);
    const bool keyModelPassed = processor.isKeyModelReady();
    std::printf ("KEY MODEL  embedded RTNeural load  %s\n", keyModelPassed ? "PASS" : "FAIL");

    // Render a real authored response instead of the identity default so the
    // face proof exercises the restored trace treatment. This changes only
    // the screenshot harness, never the plug-in's default state.
    trench::rescanBodyRoster();   // pull in Documents/TRENCH/bodies (incl. Filters/)
    int rosterCount = 0;
    const auto* roster = trench::bodyRoster (rosterCount);
    int proofBody = juce::jmin (1, rosterCount - 1);
    for (int i = 0; i < rosterCount; ++i)
        if (juce::String (roster[i].displayName).equalsIgnoreCase ("reece_dnb")
            || (proofBody <= 1 && juce::String (roster[i].displayName).equalsIgnoreCase ("Talker")))
            proofBody = i;
    if (auto* body = processor.apvts.getParameter (ParamID::body))
        body->setValueNotifyingHost (body->convertTo0to1 ((float) proofBody));
    if (auto* morph = processor.apvts.getParameter (ParamID::morph))
        morph->setValueNotifyingHost (0.68f);
    if (auto* q = processor.apvts.getParameter (ParamID::q))
        q->setValueNotifyingHost (0.30f);

    // The editor is a real child of a real (offscreen) window: VBlankAttachment and
    // the layout both want a peer, and a snapshot of a parentless component lies.
    auto* editor = processor.createEditorIfNeeded();
    juce::Component holder;
    holder.setSize (editor->getWidth(), editor->getHeight());
    holder.addAndMakeVisible (editor);
    holder.addToDesktop (juce::ComponentPeer::windowIsTemporary);
    holder.setVisible (true);

    // Let the layout settle and one frame of live data land. (This target sets
    // JUCE_MODAL_LOOPS_PERMITTED=1 so the pump is available; the plugin does not.)
    juce::MessageManager::getInstance()->runDispatchLoopUntil (1400);

    // RATE proof: the fixed-rate island resamples the host into the 39062.5 /
    // 78125 Hz coefficient domain. Every host rate must come back finite, and
    // the latency we REPORT must match the latency we actually add, or every
    // user's parallel routing is smeared and nobody can hear why.
    if (std::getenv ("TRENCH_RATE_ITER") != nullptr)
    {
        bool ratePass = true;
        if (auto* body = processor.apvts.getParameter (ParamID::body))
            body->setValueNotifyingHost (body->convertTo0to1 ((float) trench::kNoFilterIndex));
        juce::MessageManager::getInstance()->runDispatchLoopUntil (120);
        for (double rate : { 44100.0, 48000.0, 88200.0, 96000.0, 192000.0 })
        {
            constexpr int kBlock = 512;
            processor.prepareToPlay (rate, kBlock);
            const int reported = processor.getLatencySamples();
            // Drive an impulse through and find where it lands.
            const int total = juce::jmax (8 * kBlock, reported + 4 * kBlock);
            juce::AudioBuffer<float> run (2, total);
            run.clear();
            const int impulseAt = kBlock / 2;
            run.setSample (0, impulseAt, 1.0f);
            run.setSample (1, impulseAt, 1.0f);
            juce::MidiBuffer midi;
            for (int off = 0; off + kBlock <= total; off += kBlock)
            {
                juce::AudioBuffer<float> blk (run.getArrayOfWritePointers(), 2, off, kBlock);
                processor.processBlock (blk, midi);
            }
            int peakAt = -1;
            float peak = 0.0f;
            bool finite = true;
            for (int i = 0; i < total; ++i)
            {
                const float v = run.getSample (0, i);
                if (! std::isfinite (v)) { finite = false; break; }
                if (std::abs (v) > peak) { peak = std::abs (v); peakAt = i; }
            }
            const int measured = peakAt - impulseAt;
            const int err = std::abs (measured - reported);
            // One block of slack: the island only emits on filled FIFO boundaries.
            const bool ok = finite && peak > 1.0e-4f && err <= kBlock;
            ratePass = ratePass && ok;
            std::printf ("RATE %7.0f Hz  finite=%d  peak=%.4f  reported=%6d  measured=%6d  err=%5d  %s\n",
                         rate, (int) finite, peak, reported, measured, err, ok ? "PASS" : "FAIL");
        }
        std::printf ("HOST RATES   finite + honest latency at 44.1/48/88.2/96/192  %s\n",
                     ratePass ? "PASS" : "FAIL");
        return ratePass ? 0 : 1;
    }

    // TYPE proof: picking a body on the glass must load THAT body. The menu
    // item index and the host BODY parameter have to name the same thing.
    // TRENCH_TYPE_ITER=1 runs this alone (the slow blocks below are skipped).
    if (std::getenv ("TRENCH_TYPE_ITER") != nullptr)
    {
        bool selectPass = true;
        if (auto* type = findChildOfType<trench::ui::TypeSelectorView> (*editor))
        {
            int rosterN = 0;
            trench::bodyRoster (rosterN);
            for (int wanted : { 1, rosterN / 3, rosterN / 2, rosterN - 1 })
            {
                if (wanted <= 0 || wanted >= rosterN)
                    continue;
                type->previewBody (wanted);
                juce::MessageManager::getInstance()->runDispatchLoopUntil (80);
                const int loaded = processor.getLoadedBodyIndex();
                if (loaded != wanted)
                {
                    selectPass = false;
                    std::printf ("TYPE  picked %d \"%s\"  ->  loaded %d \"%s\"\n",
                                 wanted, trench::bodyDisplayName (wanted).toRawUTF8(),
                                 loaded,  trench::bodyDisplayName (loaded).toRawUTF8());
                }
            }
        }
        else
        {
            selectPass = false;
            std::printf ("TYPE  selector not found in the editor\n");
        }
        std::printf ("TYPE SELECT  picked body == loaded body  %s\n", selectPass ? "PASS" : "FAIL");

        // RANGE proof: the BODY parameter's range must not depend on how many
        // bodies this machine has, or a normalised automation lane means a
        // different filter on someone else's system.
        bool rangePass = false;
        if (auto* body = processor.apvts.getParameter (ParamID::body))
        {
            const auto range = body->getNormalisableRange();
            rangePass = juce::approximatelyEqual (range.end, (float) trench::kBodyParamMaxIndex);
            std::printf ("RANGE  body param 0..%g  roster %d\n", range.end, trench::bodyCount());
        }
        std::printf ("BODY RANGE   frozen, roster-independent  %s\n", rangePass ? "PASS" : "FAIL");

        // RECALL proof: a saved state must restore the body it named. The saved
        // INDEX is deliberately corrupted first - if recall still lands on the
        // right body, the id is doing the work, not the index.
        bool recallPass = false;
        {
            int rosterN = 0;
            trench::bodyRoster (rosterN);
            const int saved = juce::jlimit (1, rosterN - 1, rosterN / 2);
            const auto savedBase = trench::bodyBaseForIndex (saved);
            if (auto* body = processor.apvts.getParameter (ParamID::body))
                body->setValueNotifyingHost (body->convertTo0to1 ((float) saved));
            juce::MessageManager::getInstance()->runDispatchLoopUntil (80);

            juce::MemoryBlock blob;
            processor.getStateInformation (blob);
            if (auto xml = std::unique_ptr<juce::XmlElement> (
                    juce::AudioProcessor::getXmlFromBinary (blob.getData(), (int) blob.getSize())))
            {
                // point the stored index at a different body, keep the id
                for (auto* child : xml->getChildIterator())
                    if (child->getStringAttribute ("id") == ParamID::body)
                        child->setAttribute ("value", (double) ((saved + 7) % rosterN));
                juce::MemoryBlock tampered;
                juce::AudioProcessor::copyXmlToBinary (*xml, tampered);
                processor.setStateInformation (tampered.getData(), (int) tampered.getSize());
                juce::MessageManager::getInstance()->runDispatchLoopUntil (80);
            }
            const auto recalledBase = trench::bodyBaseForIndex (processor.getLoadedBodyIndex());
            recallPass = savedBase.isNotEmpty() && recalledBase == savedBase;
            std::printf ("RECALL  saved \"%s\"  ->  restored \"%s\"\n",
                         trench::bodyDisplayName (saved).toRawUTF8(),
                         trench::bodyDisplayName (processor.getLoadedBodyIndex()).toRawUTF8());
        }
        std::printf ("BODY RECALL  state restores the named body  %s\n", recallPass ? "PASS" : "FAIL");

        return (selectPass && rangePass && recallPass) ? 0 : 1;
    }

    // Load-bearing iteration path: render ONLY the modulation surface, fast.
    // TRENCH_MOD_ITER=1 skips every KEY/SLAM/gif/mix proof (the slow blocks) so
    // each modulation UI change round-trips in seconds.
    if (std::getenv ("TRENCH_MOD_ITER") != nullptr)
    {
        auto setP = [&] (const char* id, float v) {
            if (auto* p = processor.apvts.getParameter (id))
                p->setValueNotifyingHost (p->convertTo0to1 (v));
        };
        setP (ParamID::modOn, 1.0f);
        setP (ParamID::modTrigger, 1.0f);   // SYNC
        setP (ParamID::modDepth, 0.6f);
        setP (ParamID::modNote, 5.0f);      // 1/8
        juce::MessageManager::getInstance()->runDispatchLoopUntil (400);
        const auto save = [] (const juce::Image& img, const char* name)
        {
            auto f = juce::File::getCurrentWorkingDirectory().getChildFile (name);
            f.deleteFile();
            juce::FileOutputStream os (f);
            juce::PNGImageFormat().writeImageToStream (img, os);
            os.flush();
            std::printf ("MOD ITER wrote %s\n", f.getFullPathName().toRawUTF8());
        };
        save (holder.createComponentSnapshot (holder.getLocalBounds()), "trench_mod_iter.png");
        // AUTO (ENV follow) state: the chip reads "Modulation AUTO" lit.
        setP (ParamID::modTrigger, 0.0f);   // ENV
        juce::MessageManager::getInstance()->runDispatchLoopUntil (200);
        save (holder.createComponentSnapshot (holder.getLocalBounds()), "trench_mod_follow.png");
        // OFF state: dim lamp + explicit OFF word.
        setP (ParamID::modOn, 0.0f);
        juce::MessageManager::getInstance()->runDispatchLoopUntil (200);
        save (holder.createComponentSnapshot (holder.getLocalBounds()), "trench_mod_off.png");
        return 0;
    }

    // (SLAM first-run hint proof removed — the slamHint* API was refactored out
    // of GraphDisplay in a separate change; not part of the modulation render.)

    // SLAM-GESTURE proof: the glass is SLAM only now (rate lives on the chip).
    // Vertical drag must slam; a purely horizontal drag must NOT move SLAM.
    if (auto* hero = findChildOfType<trench::ui::GraphDisplay> (*editor))
    {
        auto* slam = processor.apvts.getParameter (ParamID::slamDrive);
        slam->setValueNotifyingHost (0.0f);
        const auto mk = [hero] (juce::Point<float> p)
        {
            const auto now = juce::Time::getCurrentTime();
            return juce::MouseEvent (juce::Desktop::getInstance().getMainMouseSource(), p,
                                     juce::ModifierKeys {}, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f,
                                     hero, hero, now, p, now, 0, false);
        };
        const auto c = hero->getLocalBounds().getCentre().toFloat();

        // Horizontal-only drag: no vertical travel, so SLAM must stay put.
        const float slamBefore = slam->getValue();
        hero->mouseDown (mk (c));
        hero->mouseDrag (mk (c.translated (102.0f, 0.0f)));
        const float slamAfterH = slam->getValue();
        hero->mouseUp (mk (c.translated (102.0f, 0.0f)));
        const bool horizInert = std::abs (slamAfterH - slamBefore) < 1.0e-4f;

        // Vertical pull: up = slam harder.
        hero->mouseDown (mk (c));
        hero->mouseDrag (mk (c.translated (1.0f, -90.0f)));
        const float slamAfterV = slam->getValue();
        hero->mouseUp (mk (c.translated (1.0f, -90.0f)));
        const bool vertSlams = slamAfterV > slamBefore + 0.05f;

        slam->setValueNotifyingHost (0.0f);
        std::printf ("SLAMDRAG  horiz-inert=%d vert-slams=%.3f  %s\n",
                     (int) horizInert, slamAfterV,
                     (horizInert && vertSlams) ? "PASS" : "FAIL");
    }

    // MOD-MOVES-EVERYTHING proof: armed SYNC modulation must swing the MORPH
    // wheel AND the response curve (both read the effective/modulated morph).
    // Two snapshots at different mod phases: the wheel reads differently and
    // the graph glass has visibly different pixels.
    if (auto* hero = findChildOfType<trench::ui::GraphDisplay> (*editor))
    {
        juce::AudioBuffer<float> buf (2, 512);
        juce::MidiBuffer midi;
        const auto setP = [&processor] (const char* id, float denorm)
        { if (auto* p = processor.apvts.getParameter (id)) p->setValueNotifyingHost (p->convertTo0to1 (denorm)); };
        const auto feed = [&] (int blocks)
        {
            for (int b = 0; b < blocks; ++b)
            {
                for (int ch = 0; ch < 2; ++ch)
                    for (int i = 0; i < 512; ++i)
                        buf.setSample (ch, i, 0.25f * std::sin (6.2831853f * 180.0f * (float) i / 48000.0f));
                processor.processBlock (buf, midi);
            }
        };
        const auto save = [] (const juce::Image& img, const char* file)
        {
            auto f = juce::File::getCurrentWorkingDirectory().getChildFile (file);
            f.deleteFile();
            juce::FileOutputStream os (f);
            juce::PNGImageFormat().writeImageToStream (img, os);
            os.flush();
        };

        setP (ParamID::morph, 0.5f);
        setP (ParamID::modDepth, 1.0f);
        setP (ParamID::modTrigger, 1.0f);   // SYNC
        setP (ParamID::modNote, 4.0f);      // 1/4 — fast phase so the wheel visibly moves
        setP (ParamID::modOn, 1.0f);

        feed (60);                          // settle the smoothers
        juce::MessageManager::getInstance()->runDispatchLoopUntil (60);
        const float mA = processor.getEffectiveMorphForUi();
        save (holder.createComponentSnapshot (holder.getLocalBounds()), "trench_modwheel_a.png");
        const auto curveA = hero->createComponentSnapshot (hero->getLocalBounds());

        // Advance until the effective morph is visibly elsewhere (a fixed
        // block count can land in the clamped crest of the same half-cycle).
        float mB = mA;
        for (int tries = 0; tries < 24 && std::abs (mB - mA) < 0.1f; ++tries)
        {
            feed (8);
            mB = processor.getEffectiveMorphForUi();
        }
        juce::MessageManager::getInstance()->runDispatchLoopUntil (60);
        save (holder.createComponentSnapshot (holder.getLocalBounds()), "trench_modwheel_b.png");
        const auto curveB = hero->createComponentSnapshot (hero->getLocalBounds());

        // Curve-moves check: the two graph snapshots must differ broadly (the
        // trace itself, not just a meter corner).
        int changedGlass = 0;
        for (int y = 0; y < curveA.getHeight(); y += 3)
            for (int x = 0; x < curveA.getWidth(); x += 3)
                if (curveA.getPixelAt (x, y) != curveB.getPixelAt (x, y))
                    ++changedGlass;
        const bool curveMoves = changedGlass > 60;

        setP (ParamID::modOn, 0.0f);
        feed (20);
        juce::MessageManager::getInstance()->runDispatchLoopUntil (60);
        const bool wheelMoved = std::abs (mB - mA) > 0.02f;
        std::printf ("MODWHEEL  effMorph A=%.3f B=%.3f wheel-moved=%d curve-pixels=%d  %s\n",
                     mA, mB, (int) wheelMoved, changedGlass,
                     (wheelMoved && curveMoves) ? "PASS" : "FAIL");
    }

    // MIX proof: the real thin wheel must announce itself as MIX on the glass,
    // and it must still write the dedicated dry/full-body parameter.
    bool mixProofPassed = false;
    if (auto* mixWheel = findChildOfType<trench::ui::ThinWheel> (*editor, "MIX"))
    {
        const auto pos = mixWheel->getLocalBounds().getCentre().toFloat();
        const auto now = juce::Time::getCurrentTime();
        juce::MouseEvent event (juce::Desktop::getInstance().getMainMouseSource(), pos,
                                juce::ModifierKeys {}, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f,
                                mixWheel, mixWheel, now, pos, now, 0, false);
        mixWheel->mouseDown (event);
        juce::MessageManager::getInstance()->runDispatchLoopUntil (30);

        const float mix = processor.apvts.getRawParameterValue (ParamID::amount)->load();
        const auto shot = holder.createComponentSnapshot (holder.getLocalBounds());
        auto mf = juce::File::getCurrentWorkingDirectory().getChildFile ("trench_face_mix.png");
        mf.deleteFile();
        juce::FileOutputStream mos (mf);
        juce::PNGImageFormat().writeImageToStream (shot, mos);
        mos.flush();
        mixProofPassed = mix > 0.45f && mix < 0.55f && mf.existsAsFile();
        std::printf ("MIX  wheel %.3f cue capture  %s\n",
                     mix, mixProofPassed ? "PASS" : "FAIL");
        mixWheel->mouseUp (event);
        if (auto* p = processor.apvts.getParameter (ParamID::amount))
            p->setValueNotifyingHost (1.0f);
    }

    // LIMIT reads the desk's TRUE pressure: the fraction of samples pushed
    // past the knee by SLAM. No slam = no limiting, whatever the level; a
    // slammed hot signal reads heavy; silence decays to 0.
    {
        juce::AudioBuffer<float> buf (2, 512);
        juce::MidiBuffer midi;
        const auto setSlam = [&] (float v)
        {
            if (auto* slam = processor.apvts.getParameter (ParamID::slamDrive))
                slam->setValueNotifyingHost (slam->convertTo0to1 (v));
        };
        const auto runLevel = [&] (float amp)
        {
            const int passes = amp == 0.0f ? 160 : 30;
            for (int pass = 0; pass < passes; ++pass)   // let the meter settle/clear
            {
                for (int ch = 0; ch < 2; ++ch)
                    for (int i = 0; i < 512; ++i)
                        buf.setSample (ch, i, amp * std::sin (6.2831853f * 220.0f * (float) i / 48000.0f));
                processor.processBlock (buf, midi);
            }
            std::printf ("  in amp %.2f -> out peak %.3f, LIMIT %.0f%%\n",
                         amp, buf.getMagnitude (0, 512), processor.getOutClipForUi() * 100.0f);
            return processor.getOutClipForUi();
        };
        setSlam (0.0f);
        const float noSlam = runLevel (0.8f);      // hot input, desk idle
        setSlam (1.0f);
        const float slammed = runLevel (0.8f);     // same input, desk floored
        setSlam (0.0f);
        const float cleared = runLevel (0.0f);     // silence decays the meter
        std::printf ("LIMIT  no-slam=%.0f%%   slammed=%.0f%%   cleared=%.0f%%   %s\n",
                     noSlam * 100.0f, slammed * 100.0f, cleared * 100.0f,
                     (noSlam < 0.05f && slammed > 0.08f && cleared < 0.02f) ? "PASS" : "FAIL");
    }

    // MOD proof — the trench::MorphMod law end-to-end through the real
    // processBlock. Standalone has no transport, so SYNC free-runs. The proof
    // reads the same effective-wheel values the face dances to: SYNC swings
    // the morph wheel around the user's anchor, depth=0 is an exact null while
    // armed, ENV lets the input play the wheel, and Q stays untouched when
    // modQDepth is 0.
    bool motionProofPassed = false;
    {
        juce::AudioBuffer<float> buf (2, 512);
        juce::MidiBuffer midi;
        const auto setParam = [&processor] (const char* id, float denorm)
        {
            if (auto* p = processor.apvts.getParameter (id))
                p->setValueNotifyingHost (p->convertTo0to1 (denorm));
        };
        const auto runBlocks = [&] (int blocks, float amp)
        {
            for (int pass = 0; pass < blocks; ++pass)
            {
                for (int ch = 0; ch < 2; ++ch)
                    for (int i = 0; i < 512; ++i)
                        buf.setSample (ch, i, amp * std::sin (6.2831853f * 220.0f * (float) i / 48000.0f));
                processor.processBlock (buf, midi);
            }
        };
        const auto morphSwing = [&] (int blocks)
        {
            float lo = 1.0f, hi = 0.0f;
            for (int pass = 0; pass < blocks; ++pass)
            {
                buf.clear();
                processor.processBlock (buf, midi);
                const float m = processor.getEffectiveMorphForUi();
                lo = std::min (lo, m);
                hi = std::max (hi, m);
            }
            return std::pair<float, float> (lo, hi);
        };

        // SYNC: the wheel swings around the placed anchor (0.5), full depth.
        setParam (ParamID::morph, 0.5f);
        setParam (ParamID::modDepth, 1.0f);
        setParam (ParamID::modTrigger, 1.0f);   // SYNC
        setParam (ParamID::modNote, 2.0f);      // 1 BAR
        setParam (ParamID::modOn, 1.0f);
        runBlocks (40, 0.0f);                        // let the smoothers settle
        const auto sweep = morphSwing (400);         // >2 full cycles at 120bpm
        const bool sweepPass = sweep.second - sweep.first > 0.3f
                            && sweep.first < 0.5f && sweep.second > 0.5f;
        std::printf ("MOD  SYNC anchor 0.500  swing %.3f..%.3f  %s\n",
                     sweep.first, sweep.second, sweepPass ? "PASS" : "FAIL");

        // MIX is exclusively the dry/full-body blend. Moving it must not alter
        // the modulation depth or stop the effective Morph wheel from moving.
        setParam (ParamID::amount, 0.0f);
        const auto dryMixSweep = morphSwing (400);
        const bool mixIsolationPass = dryMixSweep.second - dryMixSweep.first > 0.3f;
        std::printf ("MOD  MIX independent  swing %.3f..%.3f  %s\n",
                     dryMixSweep.first, dryMixSweep.second,
                     mixIsolationPass ? "PASS" : "FAIL");
        setParam (ParamID::amount, 1.0f);

        // Null contract: armed but depth 0 -> the wheel does not move.
        setParam (ParamID::modDepth, 0.0f);
        runBlocks (20, 0.0f);
        const auto nullSwing = morphSwing (100);
        const bool nullPass = nullSwing.second - nullSwing.first < 1.0e-4f;
        std::printf ("MOD  armed depth=0  swing %.3f..%.3f  %s\n",
                     nullSwing.first, nullSwing.second, nullPass ? "PASS" : "FAIL");

        // ENV: the input's own level plays the wheel, from a low anchor.
        setParam (ParamID::modDepth, 1.0f);
        setParam (ParamID::modTrigger, 0.0f);   // ENV
        setParam (ParamID::morph, 0.2f);
        runBlocks (30, 0.0f);
        const float followIdle = processor.getEffectiveMorphForUi();
        runBlocks (120, 0.8f);                  // loud: the envelope opens
        const float followHot = processor.getEffectiveMorphForUi();
        const bool followPass = followIdle < 0.25f && followHot > followIdle + 0.3f;
        std::printf ("MOD  ENV idle %.3f -> hot %.3f  %s\n",
                     followIdle, followHot, followPass ? "PASS" : "FAIL");

        // Q isolation: modQDepth stayed 0 throughout, so Q must be untouched.
        setParam (ParamID::modTrigger, 1.0f);   // SYNC again, still loud
        setParam (ParamID::q, 0.30f);
        runBlocks (60, 0.8f);
        const float effQ = processor.getEffectiveQForUi();
        const bool qPass = std::abs (effQ - 0.30f) < 1.0e-3f;
        std::printf ("MOD  Q untouched  eff %.4f vs 0.3000  %s\n",
                     effQ, qPass ? "PASS" : "FAIL");

        motionProofPassed = sweepPass && mixIsolationPass && nullPass && followPass && qPass;

        // Restore the harness state for the remaining proofs and beauty shots.
        setParam (ParamID::modOn, 0.0f);
        setParam (ParamID::modTrigger, 1.0f);
        setParam (ParamID::modDepth, 0.5f);
        setParam (ParamID::morph, 0.68f);
        setParam (ParamID::q, 0.30f);
        runBlocks (20, 0.0f);
    }

    // Let the async body load and the editor's next vblank publish the real
    // packed response before taking the proof image.
    juce::MessageManager::getInstance()->runDispatchLoopUntil (1400);

    // Exercise the actual WheelControl::mouseWheelMove path, then make the
    // audio thread publish a new packed-runtime snapshot and let the hero
    // display consume it. This is deliberately component-level: the proof
    // does not add a test-only setter to the production wheel or graph.
    bool wheelProofPassed = false;
    if (auto* morphWheel = findChildOfType<trench::ui::WheelControl> (*editor, "Morph");
        morphWheel != nullptr)
    {
        auto* qWheel = findChildOfType<trench::ui::WheelControl> (*editor, "Q");
        auto* hero = findChildOfType<trench::ui::GraphDisplay> (*editor);

        juce::AudioBuffer<float> silence (2, 512);
        juce::MidiBuffer midi;
        const auto publishAndPaint = [&]
        {
            for (int pass = 0; pass < 12; ++pass)
            {
                silence.clear();
                processor.processBlock (silence, midi);
            }
            juce::MessageManager::getInstance()->runDispatchLoopUntil (260);
        };

        // Keep the component gesture probe manual. A restored host state may
        // have MOD armed, which legitimately writes Morph while the harness
        // is trying to establish its before/after value.
        if (auto* mod = processor.apvts.getParameter (ParamID::modOn))
            mod->setValueNotifyingHost (0.0f);

        const auto readCoeffs = [&]
        {
            std::array<float, 30> coeffs {};
            float boost = 1.0f;
            const bool ok = processor.dspBridge.readUiSnapshot (coeffs.data(), boost);
            jassert (ok);
            return coeffs;
        };

        const auto turnAndProve = [&] (const char* name, trench::ui::WheelControl& wheel,
                                      const char* paramID)
        {
            auto* param = processor.apvts.getParameter (paramID);
            if (param == nullptr || hero == nullptr)
                return false;

            // Drain the asynchronous preset/body load before establishing the
            // controlled probe value; otherwise initialization can overwrite
            // the parameter during the gesture and make the test nondeterministic.
            publishAndPaint();
            // Establish headroom for an upward wheel gesture.
            param->setValueNotifyingHost (0.50f);
            publishAndPaint();
            const float valueBefore = param->getValue();
            const auto coeffsBefore = readCoeffs();
            const auto heroBefore = hero->createComponentSnapshot (hero->getLocalBounds());

            const auto pos = wheel.getLocalBounds().getCentre().toFloat();
            const auto now = juce::Time::getCurrentTime();
            juce::MouseEvent event (juce::Desktop::getInstance().getMainMouseSource(), pos,
                                    juce::ModifierKeys {}, 0.5f, 0.0f, 0.0f, 0.0f, 0.0f,
                                    &wheel, &wheel, now, pos, now, 0, false);
            juce::MouseWheelDetails details { 0.0f, 1.0f, false, false, false };
            wheel.mouseWheelMove (event, details);

            publishAndPaint();
            const float valueAfter = param->getValue();
            const auto coeffsAfter = readCoeffs();
            const auto heroAfter = hero->createComponentSnapshot (hero->getLocalBounds());

            float maxCoeffDelta = 0.0f;
            for (size_t i = 0; i < coeffsBefore.size(); ++i)
                maxCoeffDelta = std::max (maxCoeffDelta,
                                          std::abs (coeffsAfter[i] - coeffsBefore[i]));
            const int changedPixels = changedPixelCount (heroBefore, heroAfter);
            const bool passed = valueAfter > valueBefore
                                && maxCoeffDelta > 1.0e-7f
                                && changedPixels > 0;
            std::printf ("WHEEL  %s %.3f -> %.3f  packed max-delta %.7f  hero pixels %d  %s\n",
                         name, valueBefore, valueAfter, maxCoeffDelta, changedPixels,
                         passed ? "PASS" : "FAIL");
            return passed;
        };

        const bool morphPassed = turnAndProve ("Morph", *morphWheel, ParamID::morph);
        const bool qPassed = qWheel != nullptr && turnAndProve ("Q", *qWheel, ParamID::q);
        bool keySnapPassed = false;
        if (auto* keyBox = findChildOfType<trench::ui::KeySnapBox> (*editor);
            keyBox != nullptr)
        {
            auto* param = processor.apvts.getParameter (ParamID::keySnap);
            param->setValueNotifyingHost (param->convertTo0to1 (0.0f));

            // End-to-end passive suggestion proof: feed C-major windows through
            // processBlock, allow the message-thread detector to consume each
            // complete capture, then inspect the real UI state. The count runs
            // long so a clean three-window gate lands last even after the MOTION
            // proof's tone lingers in the detector's ~6 s analysis window.
            juce::AudioBuffer<float> chord (2, 512);
            juce::MidiBuffer chordMidi;
            juce::int64 chordSample = 0;
            const double frequencies[] = { 130.8128, 164.8138, 195.9977 };
            for (int window = 0; window < 8; ++window)
            {
                for (int block = 0; block < 565; ++block)
                {
                    for (int sample = 0; sample < chord.getNumSamples(); ++sample, ++chordSample)
                    {
                        double value = 0.0;
                        for (double frequency : frequencies)
                            for (int harmonic = 1; harmonic <= 5; ++harmonic)
                                value += std::sin (juce::MathConstants<double>::twoPi * frequency
                                                  * harmonic * (double) chordSample / 48000.0)
                                       / (double) harmonic;
                        for (int channel = 0; channel < chord.getNumChannels(); ++channel)
                            chord.setSample (channel, sample, (float) (value * 0.035));
                    }
                    processor.processBlock (chord, chordMidi);
                }
                juce::MessageManager::getInstance()->runDispatchLoopUntil (900);
            }
            keyBox->refreshSuggestion();
            publishAndPaint();
            const int suggestion = processor.getDetectedKeyForUi();
            const int alternative = processor.getDetectedAltKeyForUi();

            // Drive one fresh -1 -> result transition so the harness observes
            // the arrival motion itself rather than whichever point the live
            // vblank happened to catch while inference was completing.
            auto animatedPrimary = std::make_shared<int> (-1);
            keyBox->refreshSuggestion();
            *animatedPrimary = suggestion;
            keyBox->refreshSuggestion();
            const auto arrivingKeyAsset = keyBox->createComponentSnapshot (keyBox->getLocalBounds());
            juce::MessageManager::getInstance()->runDispatchLoopUntil (500);
            keyBox->refreshSuggestion();
            publishAndPaint();
            const auto settledKeyAsset = keyBox->createComponentSnapshot (keyBox->getLocalBounds());
            const int arrivalPixels = changedPixelCount (arrivingKeyAsset, settledKeyAsset);
            const bool suggestionPassed = suggestion >= 0 && alternative >= 0;
            std::printf ("KEY SUGGEST  primary=%d alternate=%d confidence=%.3f arrival pixels=%d  %s\n",
                         suggestion, alternative, processor.getKeyConfidenceForUi(),
                         arrivalPixels,
                         suggestionPassed ? "PASS" : "FAIL");
            {
                const auto suggestionImage = holder.createComponentSnapshot (holder.getLocalBounds(), true, 1.5f);
                auto suggestionFile = juce::File::getCurrentWorkingDirectory().getChildFile (
                    "trench_face_key_suggest.png");
                suggestionFile.deleteFile();
                juce::FileOutputStream suggestionStream (suggestionFile);
                juce::PNGImageFormat().writeImageToStream (suggestionImage, suggestionStream);
                suggestionStream.flush();
                std::printf ("KEY SUGGEST  wrote %s\n",
                             suggestionFile.getFullPathName().toRawUTF8());
            }
            const auto coeffsBefore = readCoeffs();

            // The whole cell is the one gesture: click takes the offered guess
            // (a second click would release it back to Off — no menus).
            const auto pos = keyBox->getLocalBounds().getCentre().toFloat();
            const auto now = juce::Time::getCurrentTime();
            juce::MouseEvent event (juce::Desktop::getInstance().getMainMouseSource(), pos,
                                    juce::ModifierKeys {}, 0.5f, 0.0f, 0.0f, 0.0f, 0.0f,
                                    keyBox, keyBox, now, pos, now, 0, false);
            keyBox->mouseDown (event);
            keyBox->mouseUp (event);
            publishAndPaint();

            const int selected = juce::roundToInt (param->convertFrom0to1 (param->getValue()));
            const auto coeffsAfter = readCoeffs();
            float maxCoeffDelta = 0.0f;
            for (size_t i = 0; i < coeffsBefore.size(); ++i)
                maxCoeffDelta = std::max (maxCoeffDelta,
                                          std::abs (coeffsAfter[i] - coeffsBefore[i]));
            keySnapPassed = keyModelPassed && suggestionPassed
                         && selected >= 1;
            std::printf ("KEY SNAP  guess cell -> %s  packed max-delta %.7f  %s\n",
                         param->getCurrentValueAsText().toRawUTF8(), maxCoeffDelta,
                         keySnapPassed ? "PASS" : "FAIL");
            // Transient-module proof: releasing the snap must retire the plate
            // from the face (it lives only while it has something to say).
            param->setValueNotifyingHost (param->convertTo0to1 (0.0f));
            for (int i = 0; i < 50; ++i)
                keyBox->refreshSuggestion();
            const auto chipGoneAsset = keyBox->createComponentSnapshot (keyBox->getLocalBounds());
            const int fadePixels = changedPixelCount (settledKeyAsset, chipGoneAsset);
            const bool fadePassed = juce::roundToInt (param->convertFrom0to1 (param->getValue())) == 0;
            std::printf ("KEY FADE  off -> plate retires  pixels=%d  %s\n",
                         fadePixels, fadePassed ? "PASS" : "FAIL");
            keySnapPassed = keySnapPassed && fadePassed;

            // The beauty shot keeps the snapped plate visible at top-right.
            param->setValueNotifyingHost (param->convertTo0to1 (13.0f));
        }
        else
        {
            std::printf ("KEY SNAP  component not found  FAIL\n");
        }
        wheelProofPassed = morphPassed && qPassed && keySnapPassed;

        // Key Snap deliberately stays at the confirmed first candidate so the
        // final proof image also shows the quiet locked-key state.
        if (auto* morph = processor.apvts.getParameter (ParamID::morph))
            morph->setValueNotifyingHost (0.68f);
        if (auto* q = processor.apvts.getParameter (ParamID::q))
            q->setValueNotifyingHost (0.30f);
        publishAndPaint();
    }
    else
    {
        std::printf ("WHEEL  Morph component not found  FAIL\n");
    }

    const auto img = holder.createComponentSnapshot (holder.getLocalBounds());
    auto f = juce::File::getCurrentWorkingDirectory().getChildFile ("trench_face.png");
    f.deleteFile();
    juce::FileOutputStream os (f);
    juce::PNGImageFormat().writeImageToStream (img, os);
    os.flush();

    // The same face at 150% — what an FL user on a 1.5x-DPI monitor actually sees.
    {
        const auto img150 = holder.createComponentSnapshot (holder.getLocalBounds(), true, 1.5f);
        auto f150 = juce::File::getCurrentWorkingDirectory().getChildFile ("trench_face_150.png");
        f150.deleteFile();
        juce::FileOutputStream os150 (f150);
        juce::PNGImageFormat().writeImageToStream (img150, os150);
        os150.flush();
        std::printf ("wrote %s (%d x %d)\n", f150.getFullPathName().toRawUTF8(),
                     img150.getWidth(), img150.getHeight());
    }

    // Glow-law proof: the same real editor at MORPH 0/25/50/75/100 — the
    // travelling packet must follow the value across the sweep.
    for (const int pct : { 0, 25, 50, 75, 100 })
    {
        if (auto* morph = processor.apvts.getParameter (ParamID::morph))
            morph->setValueNotifyingHost ((float) pct / 100.0f);
        juce::MessageManager::getInstance()->runDispatchLoopUntil (300);
        const auto shot = holder.createComponentSnapshot (holder.getLocalBounds());
        auto pf = juce::File::getCurrentWorkingDirectory()
                      .getChildFile ("trench_face_p" + juce::String (pct) + ".png");
        pf.deleteFile();
        juce::FileOutputStream pos (pf);
        juce::PNGImageFormat().writeImageToStream (shot, pos);
        pos.flush();
        std::printf ("wrote %s\n", pf.getFullPathName().toRawUTF8());
    }

    // Interaction-state proof for the glass control: the compact numeric amount
    // must ride the SLAM roof itself, never return as a detached status sentence.
    if (auto* slam = processor.apvts.getParameter (ParamID::slamDrive))
        slam->setValueNotifyingHost (0.58f);
    if (auto* morph = processor.apvts.getParameter (ParamID::morph))
        morph->setValueNotifyingHost (0.68f);
    juce::MessageManager::getInstance()->runDispatchLoopUntil (300);
    const auto slamShot = holder.createComponentSnapshot (holder.getLocalBounds());
    auto sf = juce::File::getCurrentWorkingDirectory().getChildFile ("trench_face_slam.png");
    sf.deleteFile();
    juce::FileOutputStream sos (sf);
    juce::PNGImageFormat().writeImageToStream (slamShot, sos);
    sos.flush();
    std::printf ("wrote %s\n", sf.getFullPathName().toRawUTF8());

    // Hover-state proof: SLAM discoverability appears only when the pointer is
    // over the glass, after transient numeric feedback has fully faded.
    juce::MessageManager::getInstance()->runDispatchLoopUntil (800);
    if (auto* hero = findChildOfType<trench::ui::GraphDisplay> (*editor))
    {
        const auto pos = hero->getLocalBounds().getCentre().toFloat();
        const auto now = juce::Time::getCurrentTime();
        juce::MouseEvent hoverEvent (juce::Desktop::getInstance().getMainMouseSource(), pos,
                                     juce::ModifierKeys {}, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f,
                                     hero, hero, now, pos, now, 0, false);
        hero->mouseEnter (hoverEvent);
        const auto hoverShot = holder.createComponentSnapshot (holder.getLocalBounds());
        auto hf = juce::File::getCurrentWorkingDirectory().getChildFile ("trench_face_slam_hover.png");
        hf.deleteFile();
        juce::FileOutputStream hos (hf);
        juce::PNGImageFormat().writeImageToStream (hoverShot, hos);
        hos.flush();
        hero->mouseExit (hoverEvent);
        std::printf ("wrote %s\n", hf.getFullPathName().toRawUTF8());
    }

    // GIF sweep: morph 0 -> 1 across many frames so the roller's travelling glow
    // (and the graph reacting) can be judged as MOTION, assembled into a gif.
    for (int i = 0; i <= 28; ++i)
    {
        const float v = (float) i / 28.0f;
        if (auto* morph = processor.apvts.getParameter (ParamID::morph))
            morph->setValueNotifyingHost (v);
        juce::MessageManager::getInstance()->runDispatchLoopUntil (110);
        const auto shot = holder.createComponentSnapshot (holder.getLocalBounds());
        auto pf = juce::File::getCurrentWorkingDirectory()
                      .getChildFile ("gifsweep_" + juce::String (i).paddedLeft ('0', 2) + ".png");
        pf.deleteFile();
        juce::FileOutputStream pos (pf);
        juce::PNGImageFormat().writeImageToStream (shot, pos);
        pos.flush();
    }
    if (auto* morph = processor.apvts.getParameter (ParamID::morph))
        morph->setValueNotifyingHost (0.68f);

    // SLAM-sweep GIF: drive SLAM 0 -> 1, capturing the Mackie harmonic crunch
    // spawning + buzzing on the trace.
    for (int i = 0; i <= 26; ++i)
    {
        if (auto* slam = processor.apvts.getParameter (ParamID::slamDrive))
            slam->setValueNotifyingHost ((float) i / 26.0f);
        juce::MessageManager::getInstance()->runDispatchLoopUntil (90);
        const auto shot = holder.createComponentSnapshot (holder.getLocalBounds());
        auto pf = juce::File::getCurrentWorkingDirectory()
                      .getChildFile ("slamsweep_" + juce::String (i).paddedLeft ('0', 2) + ".png");
        pf.deleteFile();
        juce::FileOutputStream pos (pf);
        juce::PNGImageFormat().writeImageToStream (shot, pos);
        pos.flush();
    }
    if (auto* slam = processor.apvts.getParameter (ParamID::slamDrive))
        slam->setValueNotifyingHost (0.0f);

    // MIX-wheel notch-travel proof: the thin wheel at 0 / 50 / 100 %. The
    // recessed notch must clip the bottom rim at 0 and the top rim at 100.
    for (const int pct : { 0, 50, 100 })
    {
        if (auto* amount = processor.apvts.getParameter (ParamID::amount))
            amount->setValueNotifyingHost ((float) pct / 100.0f);
        juce::MessageManager::getInstance()->runDispatchLoopUntil (200);
        const auto shot = holder.createComponentSnapshot (holder.getLocalBounds());
        auto pf = juce::File::getCurrentWorkingDirectory()
                      .getChildFile ("trench_face_mix" + juce::String (pct) + ".png");
        pf.deleteFile();
        juce::FileOutputStream pos (pf);
        juce::PNGImageFormat().writeImageToStream (shot, pos);
        pos.flush();
        std::printf ("wrote %s\n", pf.getFullPathName().toRawUTF8());
    }
    if (auto* amount = processor.apvts.getParameter (ParamID::amount))
        amount->setValueNotifyingHost (1.0f);

    holder.removeFromDesktop();
    processor.editorBeingDeleted (editor);
    delete editor;

    std::printf ("wrote %s (%d x %d)\n", f.getFullPathName().toRawUTF8(),
                 img.getWidth(), img.getHeight());
    return wheelProofPassed && mixProofPassed && motionProofPassed ? 0 : 2;
}
