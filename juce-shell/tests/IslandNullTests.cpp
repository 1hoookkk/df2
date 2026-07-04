// IslandNullTests — measures what the FixedRateTrenchIsland SRC path
// (host 48k -> 39062.5 -> 48k, juce::LagrangeInterpolator both ways, no
// anti-alias filter) does to a DRY signal.
//
// Dry path here = the island driven with a TrenchDspBridge that has NO
// cartridge loaded. That is a bit-exact passthrough:
//   - trench-core FilterEngine::process_block returns untouched when
//     cartridge.is_none() (trench-core/src/engine.rs:381-384)
//   - biteDriveBlock(bite=0) is an exact-unity early return (BiteStage.h:30)
//   - slamOutputPressureBlockStereo(slam=0) is an exact-unity early return
//     (SlamStage.h:115)
// So every deviation measured below is the resampler island itself.
//
// Probes (all written to dev/tmp/sound_probe/island/):
//   (a) 20 Hz - 20 kHz log sine sweep @48k  -> per-octave magnitude deviation
//       + fine HF band deviations + time-aligned null depth
//   (b) impulse                             -> latency (samples)
//   (c) 10k + 15k two-tone                  -> THD+N-ish (energy at non-input
//       bins) + top alias/IMD spurs

#include <catch2/catch_all.hpp>

#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_dsp/juce_dsp.h>

#include "TrenchRates.h"
#include "dsp/FixedRateTrenchIsland.h"
#include "dsp/TrenchDspBridge.h"

#include <cmath>
#include <cstdio>
#include <vector>

namespace
{
constexpr double kHostRate = 48000.0;
constexpr int    kBlock    = 512;

const char* kOutDir = "C:/Users/hooki/df2/dev/tmp/sound_probe/island";

// Push a mono signal through the island (duplicated to both channels) with a
// fresh island + passthrough bridge; returns the left-channel output stream.
std::vector<float> runIsland (const std::vector<float>& in)
{
    TrenchDspBridge bridge; // NO cartridge loaded -> engine passthrough
    trench::FixedRateTrenchIsland island;
    island.prepare (kHostRate, kBlock, bridge);
    // The island must REPORT its pipeline latency (the old implementation
    // returned 0 while delaying ~516 samples — unreported = host PDC combing).
    REQUIRE (island.getLatencySamples() > 0);

    TrenchParams params; // morph/q/slam/fiveD/bite all 0 -> unity stages

    std::vector<float> out;
    out.reserve (in.size());

    juce::AudioBuffer<float> buf (2, kBlock);
    for (size_t pos = 0; pos < in.size(); pos += (size_t) kBlock)
    {
        const int n = (int) std::min<size_t> ((size_t) kBlock, in.size() - pos);
        buf.clear();
        for (int i = 0; i < n; ++i)
        {
            buf.setSample (0, i, in[pos + (size_t) i]);
            buf.setSample (1, i, in[pos + (size_t) i]);
        }
        juce::AudioBuffer<float> view (buf.getArrayOfWritePointers(), 2, n);
        island.process (view, bridge, params);
        for (int i = 0; i < n; ++i)
        {
            REQUIRE (std::isfinite (view.getSample (0, i)));
            out.push_back (view.getSample (0, i));
        }
    }
    return out;
}

void writeWav (const juce::String& name, const std::vector<float>& x)
{
    juce::File f = juce::File (kOutDir).getChildFile (name);
    f.getParentDirectory().createDirectory();
    f.deleteFile();

    juce::WavAudioFormat fmt;
    auto os = f.createOutputStream();
    REQUIRE (os != nullptr);
    std::unique_ptr<juce::AudioFormatWriter> w (
        fmt.createWriterFor (os.get(), kHostRate, 1, 32, {}, 0)); // 32-bit float
    REQUIRE (w != nullptr);
    os.release(); // writer owns the stream

    juce::AudioBuffer<float> b (1, (int) x.size());
    std::copy (x.begin(), x.end(), b.getWritePointer (0));
    REQUIRE (w->writeFromAudioSampleBuffer (b, 0, b.getNumSamples()));
}

// Real power spectrum |X(k)|^2 of x zero-padded to 2^order.
std::vector<double> powerSpectrum (const std::vector<float>& x, int order,
                                   bool hannWindow, size_t start, size_t count)
{
    const int size = 1 << order;
    juce::dsp::FFT fft (order);
    std::vector<float> td ((size_t) size * 2, 0.0f);

    const size_t n = std::min (count, x.size() > start ? x.size() - start : 0);
    for (size_t i = 0; i < n && i < (size_t) size; ++i)
    {
        float v = x[start + i];
        if (hannWindow)
            v *= 0.5f - 0.5f * std::cos (2.0 * juce::MathConstants<double>::pi
                                         * (double) i / (double) (count - 1));
        td[i] = v;
    }

    fft.performRealOnlyForwardTransform (td.data(), true);

    std::vector<double> p ((size_t) size / 2 + 1, 0.0);
    for (size_t k = 0; k <= (size_t) size / 2; ++k)
    {
        const double re = td[k * 2];
        const double im = td[k * 2 + 1];
        p[k] = re * re + im * im;
    }
    return p;
}

double bandPower (const std::vector<double>& p, double fLo, double fHi, int fftSize)
{
    const double binHz = kHostRate / (double) fftSize;
    const int k0 = juce::jmax (1, (int) std::ceil (fLo / binHz));
    const int k1 = juce::jmin ((int) p.size() - 1, (int) std::floor (fHi / binHz));
    double s = 0.0;
    for (int k = k0; k <= k1; ++k)
        s += p[(size_t) k];
    return s;
}

// x sampled at (n - D) via 64-tap Hann-windowed sinc, D = M + fr.
std::vector<float> fractionalDelay (const std::vector<float>& x, double D)
{
    const int M = (int) std::floor (D);
    const double fr = D - (double) M;
    constexpr int taps = 64, c = 31;

    double h[taps];
    for (int k = 0; k < taps; ++k)
    {
        const double t = (double) (k - c) - fr;
        const double sinc = (std::abs (t) < 1e-12)
                              ? 1.0
                              : std::sin (juce::MathConstants<double>::pi * t)
                                    / (juce::MathConstants<double>::pi * t);
        const double w = 0.5 - 0.5 * std::cos (2.0 * juce::MathConstants<double>::pi
                                               * (double) k / (double) (taps - 1));
        h[k] = sinc * w;
    }

    std::vector<float> y (x.size(), 0.0f);
    for (size_t n = 0; n < x.size(); ++n)
    {
        double acc = 0.0;
        for (int k = 0; k < taps; ++k)
        {
            const long long idx = (long long) n - (long long) M - (long long) (k - c);
            if (idx >= 0 && idx < (long long) x.size())
                acc += h[k] * (double) x[(size_t) idx];
        }
        y[n] = (float) acc;
    }
    return y;
}

double rms (const std::vector<float>& x, size_t a, size_t b)
{
    double s = 0.0;
    size_t n = 0;
    for (size_t i = a; i < b && i < x.size(); ++i, ++n)
        s += (double) x[i] * (double) x[i];
    return n > 0 ? std::sqrt (s / (double) n) : 0.0;
}
} // namespace

TEST_CASE ("Island dry path: sweep, impulse, two-tone measurements", "[island]")
{
    juce::ScopedJuceInitialiser_GUI juceInit;
    std::printf ("\n=== FixedRateTrenchIsland dry-path probe (48k -> 39062.5 -> 48k) ===\n");

    // ------------------------------------------------------------------ (b)
    // Impulse first: it gives the integer latency used to align the sweep.
    const size_t impLen = 48000;
    const size_t impPos = 10000;
    std::vector<float> imp (impLen, 0.0f);
    imp[impPos] = 1.0f;

    const auto impOut = runIsland (imp);
    writeWav ("impulse_in.wav", imp);
    writeWav ("impulse_out.wav", impOut);

    size_t peakIdx = 0;
    float peakVal = 0.0f;
    for (size_t i = 0; i < impOut.size(); ++i)
        if (std::abs (impOut[i]) > std::abs (peakVal)) { peakVal = impOut[i]; peakIdx = i; }

    const long long latencyInt = (long long) peakIdx - (long long) impPos;
    std::printf ("[impulse] peak=%.6f at sample %lld -> latency = %lld samples (%.2f ms @48k)\n",
                 (double) peakVal, (long long) peakIdx, latencyInt,
                 1000.0 * (double) latencyInt / kHostRate);
    {
        // Reported latency must match the measured impulse delay (±64 samples
        // of slack for kernel centring) — the old island reported 0 while
        // delaying ~516 samples, which comb-filtered any host parallel path.
        TrenchDspBridge b2;
        trench::FixedRateTrenchIsland i2;
        i2.prepare (kHostRate, kBlock, b2);
        const int reported = i2.getLatencySamples();
        std::printf ("[impulse] island.getLatencySamples() reports %d (measured %lld)\n",
                     reported, latencyInt);
        REQUIRE (std::abs ((long long) reported - latencyInt) <= 64);
    }
    REQUIRE (std::abs (peakVal) > 0.1f);

    // IR spread: samples within +-64 of peak above -60 dBFS.
    int ringTaps = 0;
    for (long long i = (long long) peakIdx - 64; i <= (long long) peakIdx + 64; ++i)
        if (i >= 0 && i < (long long) impOut.size()
            && std::abs (impOut[(size_t) i]) > 1.0e-3f)
            ++ringTaps;
    std::printf ("[impulse] taps above -60 dBFS within +-64 of peak: %d\n", ringTaps);

    // ------------------------------------------------------------------ (a)
    // 20 Hz - 20 kHz exponential sweep, 4 s @ 48k, 1 s of flush silence.
    const double sweepSecs = 4.0, f1 = 20.0, f2 = 20000.0;
    const size_t sweepN = (size_t) (kHostRate * sweepSecs);
    const size_t totalN = sweepN + 48000;
    std::vector<float> sweep (totalN, 0.0f);
    {
        const double T = sweepSecs, L = std::log (f2 / f1);
        for (size_t n = 0; n < sweepN; ++n)
        {
            const double t = (double) n / kHostRate;
            const double ph = 2.0 * juce::MathConstants<double>::pi * f1 * T / L
                              * (std::exp (t / T * L) - 1.0);
            double a = 0.5;
            const double fade = 480.0; // 10 ms edge fades
            if ((double) n < fade)                a *= (double) n / fade;
            if ((double) n > (double) sweepN - fade)
                a *= ((double) sweepN - (double) n) / fade;
            sweep[n] = (float) (a * std::sin (ph));
        }
    }

    const auto sweepOut = runIsland (sweep);
    writeWav ("sweep_in.wav", sweep);
    writeWav ("sweep_out.wav", sweepOut);

    // Per-octave magnitude deviation via long-FFT band power ratios.
    constexpr int sweepOrder = 18; // 262144
    const auto pIn  = powerSpectrum (sweep,    sweepOrder, false, 0, totalN);
    const auto pOut = powerSpectrum (sweepOut, sweepOrder, false, 0, totalN);

    std::printf ("[sweep] per-octave magnitude deviation, output vs input (dB):\n");
    const double octaveCenters[] = { 31.25, 62.5, 125.0, 250.0, 500.0,
                                     1000.0, 2000.0, 4000.0, 8000.0, 16000.0 };
    for (double fc : octaveCenters)
    {
        const double lo = fc / std::sqrt (2.0), hi = fc * std::sqrt (2.0);
        const double pi_ = bandPower (pIn,  lo, hi, 1 << sweepOrder);
        const double po_ = bandPower (pOut, lo, hi, 1 << sweepOrder);
        std::printf ("  %8.1f Hz : %+7.3f dB\n", fc,
                     10.0 * std::log10 (po_ / juce::jmax (1e-30, pi_)));
    }

    std::printf ("[sweep] fine HF bands (1/6 octave) deviation (dB):\n");
    const double fineCenters[] = { 10000.0, 12500.0, 14000.0, 15000.0, 16000.0,
                                   17000.0, 18000.0, 19000.0, 19500.0 };
    for (double fc : fineCenters)
    {
        const double lo = fc * std::pow (2.0, -1.0 / 12.0);
        const double hi = fc * std::pow (2.0,  1.0 / 12.0);
        const double pi_ = bandPower (pIn,  lo, hi, 1 << sweepOrder);
        const double po_ = bandPower (pOut, lo, hi, 1 << sweepOrder);
        std::printf ("  %8.1f Hz : %+7.3f dB\n", fc,
                     10.0 * std::log10 (po_ / juce::jmax (1e-30, pi_)));
    }

    // Null depth: scan total delay D around the impulse-measured latency in
    // 1/32-sample steps, sinc-delay the input, minimise residual RMS.
    {
        const size_t a = 24000, b = juce::jmin (totalN, (size_t) 216000);
        double bestD = (double) latencyInt, bestNull = 1e9;
        for (int s = -32; s <= 32; ++s)
        {
            const double D = (double) latencyInt + (double) s / 32.0;
            const auto d = fractionalDelay (sweep, D);
            double e = 0.0, r = 0.0;
            for (size_t i = a; i < b; i += 4) // decimated scan
            {
                const double diff = (double) sweepOut[i] - (double) d[i];
                e += diff * diff;
                r += (double) d[i] * (double) d[i];
            }
            const double nullDb = 10.0 * std::log10 (e / juce::jmax (1e-30, r));
            if (nullDb < bestNull) { bestNull = nullDb; bestD = D; }
        }

        // Full-resolution null at the best fractional delay.
        const auto d = fractionalDelay (sweep, bestD);
        std::vector<float> resid (totalN, 0.0f);
        for (size_t i = 0; i < totalN; ++i)
            resid[i] = sweepOut[i] - d[i];
        writeWav ("sweep_null_residual.wav", resid);

        const double nullDb = 20.0 * std::log10 (rms (resid, a, b)
                                                 / juce::jmax (1e-30, rms (d, a, b)));
        std::printf ("[sweep] best-fit delay D = %.4f samples; full-band null depth = %.2f dB\n",
                     bestD, nullDb);

        // Band-limited null (< 18 kHz) via spectra of residual vs reference.
        const auto pRes = powerSpectrum (resid, sweepOrder, false, 0, totalN);
        const auto pRef = powerSpectrum (d,     sweepOrder, false, 0, totalN);
        const double nullLtNyq = 10.0 * std::log10 (
            bandPower (pRes, 20.0, 18000.0, 1 << sweepOrder)
            / juce::jmax (1e-30, bandPower (pRef, 20.0, 18000.0, 1 << sweepOrder)));
        std::printf ("[sweep] null depth restricted to 20 Hz-18 kHz = %.2f dB\n", nullLtNyq);
    }

    // ------------------------------------------------------------------ (c)
    // Two-tone: bin-centred 9999.02 Hz + 15000 Hz (65536-pt analysis @48k).
    constexpr int ttOrder = 16;
    constexpr int ttFft   = 1 << ttOrder;   // 65536
    const int k1 = 13653;                   // 9999.0234 Hz
    const int k2 = 20480;                   // 15000.0000 Hz
    const double ttF1 = (double) k1 * kHostRate / (double) ttFft;
    const double ttF2 = (double) k2 * kHostRate / (double) ttFft;

    const size_t ttLen = 131072;
    std::vector<float> tt (ttLen, 0.0f);
    for (size_t n = 0; n < ttLen; ++n)
        tt[n] = (float) (0.35 * std::sin (2.0 * juce::MathConstants<double>::pi * ttF1 * (double) n / kHostRate)
                       + 0.35 * std::sin (2.0 * juce::MathConstants<double>::pi * ttF2 * (double) n / kHostRate));

    const auto ttOut = runIsland (tt);
    writeWav ("twotone_in.wav", tt);
    writeWav ("twotone_out.wav", ttOut);

    // Steady-state window well past the ~latency and edge transients.
    const auto pTone = powerSpectrum (ttOut, ttOrder, true, 32768, (size_t) ttFft);
    const double binHz = kHostRate / (double) ttFft;

    auto sumBins = [&] (int kc, int half)
    {
        double s = 0.0;
        for (int k = juce::jmax (1, kc - half); k <= juce::jmin ((int) pTone.size() - 1, kc + half); ++k)
            s += pTone[(size_t) k];
        return s;
    };

    const int guard = 8; // Hann leakage guard
    const double sigP = sumBins (k1, guard) + sumBins (k2, guard);
    double nonSigP = 0.0;
    const int kMin = (int) std::ceil (20.0 / binHz);
    for (int k = kMin; k < (int) pTone.size(); ++k)
    {
        if (std::abs (k - k1) <= guard || std::abs (k - k2) <= guard)
            continue;
        nonSigP += pTone[(size_t) k];
    }
    const double thdn = 10.0 * std::log10 (nonSigP / juce::jmax (1e-30, sigP));
    std::printf ("[two-tone] tones %.2f Hz + %.2f Hz; THD+N-ish (non-input-bin energy / tone energy) = %.2f dB\n",
                 ttF1, ttF2, thdn);

    // Top spurs outside the tone regions, in dBc vs the stronger tone bin.
    const double toneRef = juce::jmax (sumBins (k1, guard), sumBins (k2, guard));
    struct Spur { double f, dbc; };
    std::vector<Spur> spurs;
    for (int k = kMin + 2; k < (int) pTone.size() - 2; ++k)
    {
        if (std::abs (k - k1) <= guard + 4 || std::abs (k - k2) <= guard + 4)
            continue;
        const double v = pTone[(size_t) k];
        if (v > pTone[(size_t) k - 1] && v >= pTone[(size_t) k + 1]
            && v > pTone[(size_t) k - 2] && v >= pTone[(size_t) k + 2])
            spurs.push_back ({ (double) k * binHz, 10.0 * std::log10 (v / juce::jmax (1e-30, toneRef)) });
    }
    std::sort (spurs.begin(), spurs.end(), [] (const Spur& x, const Spur& y) { return x.dbc > y.dbc; });
    std::printf ("[two-tone] top spurs (dBc vs stronger tone):\n");
    for (size_t i = 0; i < spurs.size() && i < 8; ++i)
        std::printf ("  %9.2f Hz : %7.2f dBc\n", spurs[i].f, spurs[i].dbc);

    std::printf ("=== end island dry-path probe ===\n\n");
    SUCCEED();
}
