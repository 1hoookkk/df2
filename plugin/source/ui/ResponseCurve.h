#pragma once
#include <juce_graphics/juce_graphics.h>
#include <cmath>
#include <complex>
#include <vector>
namespace trench::ui
{
inline std::vector<juce::Point<float>> responseCurvePoints (
    const float coeffs[30], float boost, double sr,
    juce::Rectangle<float> rect, double dbTop, double dbBot, int N = 96)
{
    std::vector<juce::Point<float>> pts;
    if (rect.isEmpty() || sr <= 0.0 || N < 2 || dbTop <= dbBot)
        return pts;
    const double fLo = 20.0, fHi = juce::jmin (20000.0, sr * 0.5 - 1.0);
    if (fHi <= fLo)
        return pts;
    pts.reserve ((size_t) N);
    for (int i = 0; i < N; ++i)
    {
        const double frac = (double) i / (double) (N - 1);
        const double f = fLo * std::pow (fHi / fLo, frac);
        const double w = 2.0 * juce::MathConstants<double>::pi * f / sr;
        const std::complex<double> zinv = std::exp (std::complex<double> (0.0, -w));
        double mag = (double) boost;
        bool ok = true;
        for (int s = 0; s < 6; ++s)
        {
            const double b0 = coeffs[s * 5 + 0], b1 = coeffs[s * 5 + 1], b2 = coeffs[s * 5 + 2];
            const double a1 = coeffs[s * 5 + 3], a2 = coeffs[s * 5 + 4];
            const auto num = b0 + b1 * zinv + b2 * zinv * zinv;
            const auto den = 1.0 + a1 * zinv + a2 * zinv * zinv;
            const double da = std::abs (den);
            if (! std::isfinite (da) || da < 1.0e-9) { ok = false; break; }
            mag *= std::abs (num) / da;
        }
        if (! ok || ! std::isfinite (mag))
            continue;
        const double db = 20.0 * std::log10 (juce::jmax (mag, 1.0e-6));
        const double yt = juce::jlimit (-0.06, 1.06, (dbTop - db) / (dbTop - dbBot));
        pts.push_back ({ (float) (rect.getX() + frac * rect.getWidth()),
                         (float) (rect.getY() + yt * rect.getHeight()) });
    }
    return pts;
}
}
