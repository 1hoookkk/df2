#pragma once
#include <juce_audio_formats/juce_audio_formats.h>
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
    juce::WavAudioFormat wav;
    std::unique_ptr<juce::AudioFormatWriter> writer (
        wav.createWriterFor (os.get(), sampleRate,
                             (unsigned int) take.getNumChannels(), 24, meta, 0));
    if (writer == nullptr)
        return false;
    os.release();
    const bool ok = writer->writeFromAudioSampleBuffer (take, 0, take.getNumSamples());
    writer.reset();
    return ok;
}
}
