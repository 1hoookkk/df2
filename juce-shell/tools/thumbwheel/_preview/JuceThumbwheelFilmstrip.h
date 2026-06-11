#pragma once

#include <JuceHeader.h>
#include <cmath>

inline void drawThumbwheelFilmstrip(juce::Graphics& g,
                                    const juce::Image& strip,
                                    juce::Rectangle<int> dst,
                                    float normalisedValue)
{
    constexpr int numFrames = 129;
    int frameWidth = strip.getWidth() / numFrames;
    int frameHeight = strip.getHeight();
    int frame = juce::jlimit(0, numFrames - 1, (int) std::round(normalisedValue * (numFrames - 1)));
    juce::Rectangle<int> src { frame * frameWidth, 0, frameWidth, frameHeight };
    g.drawImage(strip, dst.getX(), dst.getY(), dst.getWidth(), dst.getHeight(),
                src.getX(), src.getY(), src.getWidth(), src.getHeight());
}
