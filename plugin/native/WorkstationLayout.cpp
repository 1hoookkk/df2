// Split from WorkstationEditor.cpp 2026-07-25 — no logic changes.
// ALL classic-surface geometry lives here — one file to reshape the app.
#include "WorkstationTheme.h"

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
    if (! detailOpen)
        return {};   // data on demand: the monitor gets the width
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
    b.removeFromRight (detailOpen ? 220 : 0);
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

