#include "TrenchShuttleControl.h"

namespace trench
{
namespace
{
    const juce::Colour kDrumTop    (0xffd8d6d1); // brushed-aluminium drum top
    const juce::Colour kDrumMid    (0xff7a7a78);
    const juce::Colour kDrumBottom (0xff1d1d1d);
    const juce::Colour kTrackInk   (0xff04070a); // recessed track
    const juce::Colour kCheekDark  (0xff0a0a0c); // cheek-plate body
}

TrenchShuttleControl::TrenchShuttleControl (juce::RangedAudioParameter& param)
    : parameter (param),
      attachment (param, [this] (float v) { onParameterChanged (v); }),
      defaultValue01 (param.getDefaultValue())
{
    setOpaque (false);
    setPaintingIsUnclipped (true);
    setMouseCursor (juce::MouseCursor::LeftRightResizeCursor);

    attachment.sendInitialUpdate();
}

TrenchShuttleControl::~TrenchShuttleControl() = default;

void TrenchShuttleControl::onParameterChanged (float newDenormValue)
{
    const auto v01 = clamp01 (toNorm (newDenormValue));
    if (! juce::approximatelyEqual (v01, currentValue01))
    {
        currentValue01 = v01;
        repaint();
    }
}

void TrenchShuttleControl::commitValue (float v01)
{
    v01 = clamp01 (v01);
    currentValue01 = v01;
    attachment.setValueAsPartOfGesture (toDenorm (v01));
    repaint();
}

void TrenchShuttleControl::mouseDown (const juce::MouseEvent& e)
{
    dragging = true;
    dragStartValue01 = currentValue01;
    dragStartX = e.x;
    attachment.beginGesture();
}

void TrenchShuttleControl::mouseDrag (const juce::MouseEvent& e)
{
    if (! dragging)
        return;

    const float gain = e.mods.isShiftDown() ? 0.25f : 1.0f;
    const float dx = static_cast<float> (e.x - dragStartX) / static_cast<float> (juce::jmax (1, getWidth()));
    commitValue (dragStartValue01 + dx * gain);
}

void TrenchShuttleControl::mouseUp (const juce::MouseEvent&)
{
    if (dragging)
    {
        dragging = false;
        attachment.endGesture();
    }
}

void TrenchShuttleControl::mouseDoubleClick (const juce::MouseEvent&)
{
    attachment.setValueAsCompleteGesture (toDenorm (defaultValue01));
}

void TrenchShuttleControl::mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& w)
{
    if (std::abs (w.deltaY) <= 0.0f)
        return;

    attachment.setValueAsCompleteGesture (toDenorm (clamp01 (currentValue01 + (w.deltaY > 0.0f ? 0.02f : -0.02f))));
}

float TrenchShuttleControl::toDenorm (float v01) const noexcept
{
    return parameter.getNormalisableRange().convertFrom0to1 (v01);
}

float TrenchShuttleControl::toNorm (float denorm) const noexcept
{
    return parameter.getNormalisableRange().convertTo0to1 (denorm);
}

float TrenchShuttleControl::clamp01 (float v) noexcept
{
    return juce::jlimit (0.0f, 1.0f, v);
}

void TrenchShuttleControl::paint (juce::Graphics& g)
{
    const auto slot = getLocalBounds();
    if (slot.isEmpty())
        return;

    const float v = juce::jlimit (0.0f, 1.0f, currentValue01);

    // ---- recessed track (the channel the drum slides in) ----
    const int trackH = juce::jmax (3, slot.getHeight() / 5);
    const auto track = juce::Rectangle<float> ((float) slot.getX() + 2.0f,
                                               (float) slot.getCentreY() - trackH * 0.5f,
                                               (float) slot.getWidth() - 4.0f, (float) trackH);
    g.setColour (kTrackInk);
    g.fillRoundedRectangle (track, trackH * 0.5f);
    g.setColour (juce::Colours::black.withAlpha (0.65f));
    g.drawLine (track.getX() + 2.0f, track.getY() + 0.5f, track.getRight() - 2.0f, track.getY() + 0.5f, 1.0f);
    g.setColour (style::primary().withAlpha (0.06f));
    g.drawLine (track.getX() + 2.0f, track.getBottom() - 0.5f, track.getRight() - 2.0f, track.getBottom() - 0.5f, 1.0f);

    // ---- the brushed-aluminium drum ----
    const int drumH = juce::jmax (slot.getHeight() - 1, trackH + 6);
    const int drumW = juce::jlimit (juce::jmax (14, drumH), slot.getWidth(),
                                    juce::roundToInt ((float) slot.getWidth() * 0.16f));
    const int travel = juce::jmax (0, slot.getWidth() - drumW);
    const auto drum  = juce::Rectangle<float> ((float) (slot.getX() + juce::roundToInt ((float) travel * v)),
                                               (float) slot.getCentreY() - drumH * 0.5f,
                                               (float) drumW, (float) drumH);
    const float corner = 2.0f;

    // drop shadow under the drum
    g.setColour (juce::Colours::black.withAlpha (0.45f));
    g.fillRoundedRectangle (drum.translated (0.0f, 2.0f), corner);

    // body — vertical aluminium gradient: light top → mid grey → dark bottom
    juce::ColourGradient body (kDrumTop,    0.0f, drum.getY(),
                               kDrumBottom, 0.0f, drum.getBottom(), false);
    body.addColour (0.50, kDrumMid);
    g.setGradientFill (body);
    g.fillRoundedRectangle (drum, corner);

    // cheek plates — dark vertical strips L+R with a bone catch-light on the inner edge
    const int cheekW = juce::jlimit (4, 8, drumW / 8);
    const auto leftCheek  = juce::Rectangle<float> (drum.getX(), drum.getY(), (float) cheekW, drum.getHeight());
    const auto rightCheek = juce::Rectangle<float> (drum.getRight() - cheekW, drum.getY(), (float) cheekW, drum.getHeight());
    g.setColour (kCheekDark);
    g.fillRect (leftCheek);
    g.fillRect (rightCheek);
    g.setColour (style::primary().withAlpha (0.20f));
    g.drawLine (leftCheek.getRight() - 0.5f, leftCheek.getY() + 2.0f, leftCheek.getRight() - 0.5f, leftCheek.getBottom() - 2.0f, 1.0f);
    g.drawLine (rightCheek.getX() + 0.5f, rightCheek.getY() + 2.0f, rightCheek.getX() + 0.5f, rightCheek.getBottom() - 2.0f, 1.0f);

    // knurl — fine 1-px vertical hatches across the grip face
    const auto grip = drum.reduced ((float) cheekW + 1.0f, 2.0f);
    if (! grip.isEmpty())
    {
        g.setColour (juce::Colours::black.withAlpha (0.35f));
        const int step = 4;
        for (float x = grip.getX() + 1.0f; x < grip.getRight(); x += (float) step)
            g.drawLine (x, grip.getY() + 1.0f, x, grip.getBottom() - 1.0f, 1.0f);
        g.setColour (style::primary().withAlpha (0.10f));
        for (float x = grip.getX() + 2.0f; x < grip.getRight(); x += (float) step)
            g.drawLine (x, grip.getY() + 1.0f, x, grip.getBottom() - 1.0f, 1.0f);
    }

    // top highlight + bottom shadow rims
    g.setColour (style::primary().withAlpha (0.35f));
    g.drawLine (drum.getX() + corner, drum.getY() + 0.5f, drum.getRight() - corner, drum.getY() + 0.5f, 1.0f);
    g.setColour (juce::Colours::black.withAlpha (0.55f));
    g.drawLine (drum.getX() + corner, drum.getBottom() - 0.5f, drum.getRight() - corner, drum.getBottom() - 0.5f, 1.0f);

    // ---- the indicator: a single phosphor-green tick — the ONLY coloured pixel ----
    const float tickH = drum.getHeight() * 0.62f;
    const auto tick = juce::Rectangle<float> (drum.getCentreX() - 1.0f,
                                              drum.getCentreY() - tickH * 0.5f,
                                              2.0f, tickH);
    g.setColour (style::accent().withAlpha (0.35f));
    g.fillRect (tick.expanded (1.0f, 0.0f)); // tiny halo
    g.setColour (style::accent());
    g.fillRect (tick);
}

}
