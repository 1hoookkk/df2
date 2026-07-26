#pragma once
#include <juce_audio_formats/juce_audio_formats.h>
#include <cmath>
namespace trench
{
struct TakeTags
{
    juce::String description { "TRENCH take" };
    double bpm = 0.0;
    int beats = 0;
    bool oneShot = true;
};
inline bool writeTakeWav (const juce::File& file,
                          const juce::AudioBuffer<float>& take,
                          double sampleRate,
                          const TakeTags& tags)
{
    if (take.getNumChannels() <= 0 || take.getNumSamples() <= 0 || sampleRate <= 0.0)
        return false;
    juce::StringPairArray meta;
    meta.set (juce::WavAudioFormat::bwavOriginator, "TRENCH");
    meta.set (juce::WavAudioFormat::bwavDescription, tags.description);
    const auto now = juce::Time::getCurrentTime();
    meta.set (juce::WavAudioFormat::bwavOriginationDate, now.formatted ("%Y-%m-%d"));
    meta.set (juce::WavAudioFormat::bwavOriginationTime, now.formatted ("%H-%M-%S"));
    meta.set (juce::WavAudioFormat::acidOneShot, tags.oneShot ? "1" : "0");
    if (! tags.oneShot)
    {
        if (tags.bpm > 0.0)
            meta.set (juce::WavAudioFormat::acidTempo, juce::String (tags.bpm));
        if (tags.beats > 0)
            meta.set (juce::WavAudioFormat::acidBeats, juce::String (tags.beats));
    }
    auto created = file.getParentDirectory().createDirectory();
    juce::ignoreUnused (created);
    file.deleteFile();
    std::unique_ptr<juce::FileOutputStream> os (file.createOutputStream());
    if (os == nullptr)
        return false;
    // 20-BIT RESAMPLE (E-MU Ultra workflow). The sampler offers 20-bit for internal
    // resampling specifically to keep the bounce pristine - the grit is meant to come
    // later, from the desk, not from the capture. WAV has no 20-bit format, so we
    // quantise to 20 bits of real resolution and store it in a 24-bit container.
    // TPDF dither at 1 LSB so the truncation floor is noise, not distortion.
    juce::AudioBuffer<float> bounce;
    bounce.makeCopyOf (take);
    {
        constexpr double kSteps = 524288.0;          // 2^19, i.e. 20-bit signed
        juce::Random rnd (0x7727);
        for (int ch = 0; ch < bounce.getNumChannels(); ++ch)
        {
            auto* d = bounce.getWritePointer (ch);
            for (int i = 0; i < bounce.getNumSamples(); ++i)
            {
                const double dither = (rnd.nextDouble() - rnd.nextDouble()) / kSteps;
                const double q = std::round (((double) d[i] + dither) * kSteps) / kSteps;
                d[i] = (float) juce::jlimit (-1.0, 1.0, q);
            }
        }
    }
    juce::WavAudioFormat wav;
    std::unique_ptr<juce::AudioFormatWriter> writer (
        wav.createWriterFor (os.get(), sampleRate,
                             (unsigned int) take.getNumChannels(), 24, meta, 0));
    if (writer == nullptr)
        return false;
    os.release();
    const bool ok = writer->writeFromAudioSampleBuffer (bounce, 0, bounce.getNumSamples());
    writer.reset();
    return ok;
}
}
