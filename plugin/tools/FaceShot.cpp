// Renders the real PluginEditor to a PNG so the faceplate can be judged without
// launching a DAW. The render-to-PNG collab loop, as a target.

#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "TrenchBodyRoster.h"

#include <juce_gui_basics/juce_gui_basics.h>

#include <algorithm>
#include <array>
#include <cmath>

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
    int rosterCount = 0;
    const auto* roster = trench::bodyRoster (rosterCount);
    int proofBody = juce::jmin (1, rosterCount - 1);
    for (int i = 0; i < rosterCount; ++i)
        if (juce::String (roster[i].displayName).equalsIgnoreCase ("Talker"))
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

    // The LIMIT readout is new (the old one read a clipper that no longer exists).
    // Prove it tracks the real output: silence reads 0, a slammed signal reads hot.
    {
        juce::AudioBuffer<float> buf (2, 512);
        juce::MidiBuffer midi;
        const auto runLevel = [&] (float amp)
        {
            const int passes = amp == 0.0f ? 160 : 8;
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
        const float quiet = runLevel (0.02f);
        const float slammed = runLevel (4.0f);
        std::printf ("LIMIT  quiet=%.0f%%   slammed=%.0f%%   %s\n",
                     quiet * 100.0f, slammed * 100.0f,
                     (quiet < 0.10f && slammed > 0.5f) ? "PASS" : "FAIL");

        // Return the live meter to idle before the beauty shot. The hot pass
        // above is proof output, not part of the intended face composition.
        runLevel (0.0f);
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
        // have MOVE armed, which legitimately writes Morph while the harness
        // is trying to establish its before/after value.
        if (auto* motion = processor.apvts.getParameter (ParamID::motionOn))
            motion->setValueNotifyingHost (0.0f);

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

            // End-to-end passive suggestion proof: feed four C-major windows
            // through processBlock, allow the message-thread detector to
            // consume each complete capture, then inspect the real UI state.
            juce::AudioBuffer<float> chord (2, 512);
            juce::MidiBuffer chordMidi;
            juce::int64 chordSample = 0;
            const double frequencies[] = { 130.8128, 164.8138, 195.9977 };
            for (int window = 0; window < 4; ++window)
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
            auto animatedSecondary = std::make_shared<int> (-1);
            keyBox->setSuggestionProviders (
                [animatedPrimary] { return *animatedPrimary; },
                [animatedSecondary] { return *animatedSecondary; });
            keyBox->refreshSuggestion();
            const auto listeningAssetA = keyBox->createComponentSnapshot (keyBox->getLocalBounds());
            juce::MessageManager::getInstance()->runDispatchLoopUntil (140);
            keyBox->refreshSuggestion();
            const auto listeningAssetB = keyBox->createComponentSnapshot (keyBox->getLocalBounds());
            const int listeningPixels = changedPixelCount (listeningAssetA, listeningAssetB);
            *animatedPrimary = suggestion;
            *animatedSecondary = alternative;
            keyBox->refreshSuggestion();
            const auto arrivingKeyAsset = keyBox->createComponentSnapshot (keyBox->getLocalBounds());
            juce::MessageManager::getInstance()->runDispatchLoopUntil (500);
            keyBox->refreshSuggestion();
            publishAndPaint();
            const auto settledKeyAsset = keyBox->createComponentSnapshot (keyBox->getLocalBounds());
            const int arrivalPixels = changedPixelCount (arrivingKeyAsset, settledKeyAsset);
            const bool suggestionPassed = suggestion == 0 && alternative >= 0
                                          && listeningPixels > 0 && arrivalPixels > 0;
            std::printf ("KEY SUGGEST  primary=%d alternate=%d confidence=%.3f listening pixels=%d arrival pixels=%d  %s\n",
                         suggestion, alternative, processor.getKeyConfidenceForUi(),
                         listeningPixels, arrivalPixels,
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

            // The first falling tile is the selection itself: one click, no
            // secondary confirmation menu or tracking mode.
            const auto pos = juce::Point<float> (17.0f, 25.0f);
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
                         && selected == 13 && maxCoeffDelta > 1.0e-7f;
            std::printf ("KEY SNAP  first tile -> %s  packed max-delta %.7f  %s\n",
                         param->getCurrentValueAsText().toRawUTF8(), maxCoeffDelta,
                         keySnapPassed ? "PASS" : "FAIL");
            keyBox->setSuggestionProviders (
                [&processor] { return processor.getDetectedKeyForUi(); },
                [&processor] { return processor.getDetectedAltKeyForUi(); });
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

    holder.removeFromDesktop();
    processor.editorBeingDeleted (editor);
    delete editor;

    std::printf ("wrote %s (%d x %d)\n", f.getFullPathName().toRawUTF8(),
                 img.getWidth(), img.getHeight());
    return wheelProofPassed ? 0 : 2;
}
