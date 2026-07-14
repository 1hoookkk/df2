// Renders the real PluginEditor to a PNG so the faceplate can be judged without
// launching a DAW. The render-to-PNG collab loop, as a target.

#include "PluginProcessor.h"
#include "PluginEditor.h"

#include <juce_gui_basics/juce_gui_basics.h>

int main()
{
    juce::ScopedJuceInitialiser_GUI juceInit;

    PluginProcessor processor;
    processor.prepareToPlay (48000.0, 512);

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
    juce::MessageManager::getInstance()->runDispatchLoopUntil (400);

    // The LIMIT readout is new (the old one read a clipper that no longer exists).
    // Prove it tracks the real output: silence reads 0, a slammed signal reads hot.
    {
        juce::AudioBuffer<float> buf (2, 512);
        juce::MidiBuffer midi;
        const auto runLevel = [&] (float amp)
        {
            for (int pass = 0; pass < 8; ++pass)   // let the meter settle
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
    }

    const auto img = holder.createComponentSnapshot (holder.getLocalBounds());
    auto f = juce::File::getCurrentWorkingDirectory().getChildFile ("trench_face.png");
    f.deleteFile();
    juce::FileOutputStream os (f);
    juce::PNGImageFormat().writeImageToStream (img, os);
    os.flush();

    holder.removeFromDesktop();
    processor.editorBeingDeleted (editor);
    delete editor;

    std::printf ("wrote %s (%d x %d)\n", f.getFullPathName().toRawUTF8(),
                 img.getWidth(), img.getHeight());
    return 0;
}
