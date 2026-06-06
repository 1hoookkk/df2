#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "TrenchBodyRoster.h"
#include "BinaryData.h"

#include <cmath>

namespace
{
constexpr int kCleanInputMode = 0; // None
constexpr int kSpatialOff = 2;
}

//==============================================================================
PluginProcessor::PluginProcessor()
     : AudioProcessor (BusesProperties()
                      #if ! JucePlugin_IsMidiEffect
                       #if ! JucePlugin_IsSynth
                        .withInput  ("Input",  juce::AudioChannelSet::stereo(), true)
                       #endif
                        .withOutput ("Output", juce::AudioChannelSet::stereo(), true)
                      #endif
                        ),
       apvts (*this, nullptr, "TRENCH_STATE", TrenchParameters::createParameterLayout())
{
    // PL-2: a single startup path. Load whichever body the recall/host
    // selected (defaults to roster index 0 = No Filter via TrenchBodyRoster),
    // then always register the body listener and start the audition timer.
    // The old "if (kEnabled()) load kBody240 and return" branch was a frozen-
    // body null-parity-test mode; with kEnabled() now meaning "extras off"
    // it no longer makes sense to suppress roster body switching.
    //
    // forceCleanAudioUiState() still runs under kEnabled() to ensure extras-
    // build state restores cannot drag in stale slam / 5D / teleport values.
    if (trench::clean_audio::kEnabled())
        forceCleanAudioUiState();

    const int startIndex = juce::jlimit (0, juce::jmax (0, trench::bodyCount() - 1),
                                         (int) apvts.getRawParameterValue (ParamID::body)->load());
    pendingBodyIndex.store (startIndex, std::memory_order_relaxed);
    loadedBodyIndex.store (startIndex, std::memory_order_relaxed);
    lastLoadOk.store (dspBridge.loadCartridge (trench::bodyCartridgeJson (startIndex)),
                      std::memory_order_relaxed);

    dspBridge.setSpatialMode (kSpatialOff);
    dspBridge.setQSoundFallbackPan (1.0f);
    apvts.addParameterListener (ParamID::body, this);
    startTimer (400);
}

PluginProcessor::~PluginProcessor()
{
    stopTimer();
    // PL-2: the listener is always registered now (single startup path),
    // so the unconditional removal pairs with the constructor.
    apvts.removeParameterListener (ParamID::body, this);
    cancelPendingUpdate();
}

//==============================================================================
const juce::String PluginProcessor::getName() const { return JucePlugin_Name; }

bool PluginProcessor::acceptsMidi() const
{
   #if JucePlugin_WantsMidiInput
    return true;
   #else
    return false;
   #endif
}

bool PluginProcessor::producesMidi() const
{
   #if JucePlugin_ProducesMidiOutput
    return true;
   #else
    return false;
   #endif
}

bool PluginProcessor::isMidiEffect() const
{
   #if JucePlugin_IsMidiEffect
    return true;
   #else
    return false;
   #endif
}

double PluginProcessor::getTailLengthSeconds() const { return 0.0; }

int PluginProcessor::getNumPrograms() { return 1; }
int PluginProcessor::getCurrentProgram() { return 0; }
void PluginProcessor::setCurrentProgram (int index) { juce::ignoreUnused (index); }
const juce::String PluginProcessor::getProgramName (int index)
{
    juce::ignoreUnused (index);
    return trench::bodyDisplayName (getLoadedBodyIndex());
}
void PluginProcessor::changeProgramName (int index, const juce::String& newName)
{
    juce::ignoreUnused (index, newName);
}

//==============================================================================
void PluginProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    fixedRateIsland.prepare (sampleRate, samplesPerBlock, dspBridge);
    setLatencySamples (fixedRateIsland.getLatencySamples());

    dspBridge.setInputMode (kCleanInputMode);
    dspBridge.setSpatialMode (kSpatialOff);
    dspBridge.setQSoundFallbackPan (1.0f);
    lastInputModeSent = kCleanInputMode;

    teleportEngine.prepare (sampleRate);
    outputGain.reset (sampleRate, 0.02); // 20 ms ramp
    const float outDb = apvts.getRawParameterValue (ParamID::output)->load();
    outputGain.setCurrentAndTargetValue (juce::Decibels::decibelsToGain (outDb));
}

void PluginProcessor::releaseResources()
{
    dspBridge.reset();
}

bool PluginProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
  #if JucePlugin_IsMidiEffect
    juce::ignoreUnused (layouts);
    return true;
  #else
    if (layouts.getMainOutputChannelSet() != juce::AudioChannelSet::mono()
     && layouts.getMainOutputChannelSet() != juce::AudioChannelSet::stereo())
        return false;

   #if ! JucePlugin_IsSynth
    if (layouts.getMainOutputChannelSet() != layouts.getMainInputChannelSet())
        return false;
   #endif

    return true;
  #endif
}

void PluginProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midiMessages)
{
    juce::ignoreUnused (midiMessages);
    juce::ScopedNoDenormals noDenormals;

    for (auto ch = getTotalNumInputChannels(); ch < getTotalNumOutputChannels(); ++ch)
        buffer.clear (ch, 0, buffer.getNumSamples());

    // PL-3 safe-state. If the last cartridge load failed, or if a load swap is
    // in flight on the message thread (handleAsyncUpdate / timerCallback clear
    // lastLoadOk *before* calling into dspBridge), bypass with silence rather
    // than playing the previous body's coefficients against a new selection or
    // continuing on a half-loaded engine. The UI surfaces this via the
    // "BODY FAILED — bypass" chassis overlay driven by getLastLoadOk().
    if (! lastLoadOk.load (std::memory_order_acquire))
    {
        buffer.clear();
        return;
    }

    // PL-2: single signal path. TrenchParams default-initialises slamDrive=0
    // and fiveD=0 (TrenchDspBridge.h:23-24); in the shipping build those
    // parameters do not exist in the layout, so there is nothing to read and
    // nothing to force. Input mode is always read from the parameter (default
    // OFF) so a user who wants SLAM/EOS gets it without a runtime gate.
    TrenchParams params;
    params.morph = apvts.getRawParameterValue (ParamID::morph)->load();
    params.q     = apvts.getRawParameterValue (ParamID::q)->load();

    // SLAM — the Slam knob is the shipping input-character control. >0 engages
    // the Mackie desk-slam stage and sets its amount; 0 is a clean bypass, so a
    // resting plug-in adds no input colour. (The legacy inputMode choice param is
    // retained for the diagnostic FX pane only and is no longer read here.)
    params.slamDrive = apvts.getRawParameterValue (ParamID::slamDrive)->load();
    const int inMode = params.slamDrive > 0.001f ? 1 /*MackieDeskSlam*/ : kCleanInputMode;
    if (inMode != lastInputModeSent)
    {
        dspBridge.setInputMode (inMode);
        lastInputModeSent = inMode;
    }

    // 5D — QSound width. The choice (Off/Narrow/Wide/Full) maps to a depth and
    // engages the QSound spatial stage; Off is a true spatial bypass.
    static constexpr float kSpaceForChoice[] = { 0.0f, 0.33f, 0.66f, 1.0f };
    const int spaceChoice = juce::jlimit (0, 3,
        (int) apvts.getRawParameterValue (ParamID::fiveD)->load());
    params.fiveD = kSpaceForChoice[spaceChoice];
    dspBridge.setSpatialMode (spaceChoice > 0 ? 0 /*QSound*/ : kSpatialOff);

    auto channelPeak = [&buffer] (int channel)
    {
        if (channel >= buffer.getNumChannels() || buffer.getNumSamples() <= 0)
            return 0.0f;

        const auto* data = buffer.getReadPointer (channel);
        float peak = 0.0f;
        for (int i = 0; i < buffer.getNumSamples(); ++i)
            peak = juce::jmax (peak, std::abs (data[i]));

        return juce::jlimit (0.0f, 1.0f, peak);
    };

    auto smoothMeter = [] (std::atomic<float>& target, float next)
    {
        const float prev = target.load (std::memory_order_relaxed);
        const float smoothed = next > prev ? next : prev * 0.86f + next * 0.14f;
        target.store (smoothed, std::memory_order_relaxed);
    };

    smoothMeter (inputMeterL, channelPeak (0));
    smoothMeter (inputMeterR, channelPeak (1));

    // Teleport is excluded from the clean ground-truth path. Add it back only
    // after the fixed body -> Morph/Q -> cascade path is proven quiet. The
    // whole block lives behind TRENCH_PLAYER_EXTRAS so the shipping build
    // contains no Teleport code and cannot reference parameters that the
    // shipping parameter layout does not define.
#ifdef TRENCH_PLAYER_EXTRAS
    if (! trench::clean_audio::kEnabled())
    {
        const int   tMode = (int) apvts.getRawParameterValue (ParamID::teleportMode)->load();
        const float tAmt  = apvts.getRawParameterValue (ParamID::teleportAmount)->load();
        const float tRate = apvts.getRawParameterValue (ParamID::teleportRate)->load();
        const float tMD   = apvts.getRawParameterValue (ParamID::teleportMorphDepth)->load();
        const float tQD   = apvts.getRawParameterValue (ParamID::teleportQDepth)->load();

        float derivRms = 0.0f;
        if (tMode == 3 && buffer.getNumChannels() > 0 && buffer.getNumSamples() > 1)
            derivRms = trench::TeleportEngine::blockDerivRms (
                           buffer.getReadPointer (0), buffer.getNumSamples());

        const auto tp = teleportEngine.apply (tMode, tAmt, tRate, tMD, tQD,
                                              params.morph, params.q,
                                              derivRms, buffer.getNumSamples());
        params.morph = tp.morph;
        params.q     = tp.q;
    }
#endif // TRENCH_PLAYER_EXTRAS

    // Filter 00 is a real packed-word roster body, loaded through the same
    // cartridge path as every other entry. Its player behavior is an explicit
    // transparent bypass: do not run the DSP island while No Filter is active.
    if (! trench::bodyIsNoFilter (loadedBodyIndex.load (std::memory_order_relaxed)))
        fixedRateIsland.process (buffer, dspBridge, params);

    // Final user makeup gain — the only level control after the engine. AGC and
    // the saturate knee inside the engine are untouched; this is a transparent
    // trim so DAW level is never hostage to a cartridge's baked boost.
    const float outDb = apvts.getRawParameterValue (ParamID::output)->load();
    outputGain.setTargetValue (juce::Decibels::decibelsToGain (outDb));
    outputGain.applyGain (buffer, buffer.getNumSamples());

    // Feed the UI vectorscope with the post-filter stereo signal.
    if (buffer.getNumSamples() > 0)
    {
        const auto* postL = buffer.getReadPointer (0);
        const auto* postR = buffer.getNumChannels() > 1 ? buffer.getReadPointer (1) : postL;
        int wp = scopeWritePos.load (std::memory_order_relaxed);
        for (int i = 0; i < buffer.getNumSamples(); ++i)
        {
            scopeL[(size_t) wp].store (postL[i], std::memory_order_relaxed);
            scopeR[(size_t) wp].store (postR[i], std::memory_order_relaxed);
            wp = (wp + 1) & (kScopeLen - 1);
        }
        scopeWritePos.store (wp, std::memory_order_relaxed);
    }
}

int PluginProcessor::copyScopeSamples (float* outL, float* outR, int count) const noexcept
{
    if (outL == nullptr || outR == nullptr || count <= 0)
        return 0;

    count = juce::jmin (count, kScopeLen);
    const int wp = scopeWritePos.load (std::memory_order_relaxed);
    // Walk back `count` samples from the write head, emitting oldest -> newest.
    for (int i = 0; i < count; ++i)
    {
        const int idx = (wp - count + i) & (kScopeLen - 1);
        outL[i] = scopeL[(size_t) idx].load (std::memory_order_relaxed);
        outR[i] = scopeR[(size_t) idx].load (std::memory_order_relaxed);
    }
    return count;
}

//==============================================================================
void PluginProcessor::parameterChanged (const juce::String& parameterID, float newValue)
{
    // PL-2: body switching works in every build configuration. The previous
    // kEnabled() early return tied "extras off" to "body roster frozen" —
    // those were two orthogonal concerns conflated under one gate.
    if (parameterID == ParamID::body)
    {
        pendingBodyIndex.store (trench::wrapBodyIndex (juce::roundToInt (newValue)),
                                std::memory_order_relaxed);
        triggerAsyncUpdate(); // do the JSON parse/load on the message thread
    }
}

void PluginProcessor::handleAsyncUpdate()
{
    // PL-2: roster body switching runs in every configuration. Forge audition
    // hot-reload (timerCallback) stays kEnabled-gated because the watcher is
    // a diagnostic / Forge-coupled surface.
    const int want = pendingBodyIndex.load (std::memory_order_relaxed);
    if (want == loadedBodyIndex.load (std::memory_order_relaxed))
        return;

    // PL-3: enter bypass before touching the engine so the audio thread does
    // not play the previous body against a new selection mid-swap.
    lastLoadOk.store (false, std::memory_order_release);

    const auto json = trench::bodyCartridgeJson (want);
    const bool ok = json.isNotEmpty() && dspBridge.loadCartridge (json);
    lastLoadOk.store (ok, std::memory_order_release);
    // Reflect the user's selection even if the audition slot is empty, so the
    // strip and the watcher agree; the status line reports any load failure.
    loadedBodyIndex.store (want, std::memory_order_relaxed);
    if (trench::bodyIsAudition (want))
        auditionSlotMtime = trench::auditionSlotFile().getLastModificationTime();

    juce::Logger::writeToLog (juce::String ("body switch -> ")
                               + trench::bodyDisplayName (want)
                               + (ok ? " ok" : " FAIL"));
}

void PluginProcessor::timerCallback()
{
    // PL-2 / PL-4: Forge audition slot hot-reload is a diagnostic surface —
    // it watches a file the consumer never sees. Compiled in only with
    // TRENCH_PLAYER_DIAGNOSTICS; the shipping build does no file polling.
#ifndef TRENCH_PLAYER_DIAGNOSTICS
    return;
#else

    // Only the audition body listens to the Forge slot, and only while it is
    // the selected body — a normal body selection is never overridden.
    if (! trench::bodyIsAudition (loadedBodyIndex.load (std::memory_order_relaxed)))
        return;

    auto slot = trench::auditionSlotFile();
    if (! slot.existsAsFile())
        return;

    const auto t = slot.getLastModificationTime();
    if (t == auditionSlotMtime)
        return;
    auditionSlotMtime = t;

    const auto json = slot.loadFileAsString();
    if (json.isEmpty())
        return;
    // PL-3: bypass while the audition slot reload swaps coefficients in.
    lastLoadOk.store (false, std::memory_order_release);
    lastLoadOk.store (dspBridge.loadCartridge (json), std::memory_order_release);
#endif // TRENCH_PLAYER_DIAGNOSTICS
}

//==============================================================================
bool PluginProcessor::hasEditor() const { return true; }

juce::AudioProcessorEditor* PluginProcessor::createEditor()
{
    return new PluginEditor (*this);
}

//==============================================================================
void PluginProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    auto state = apvts.copyState();
#ifdef TRENCH_PLAYER_EXTRAS
    // PL-1: persist the runtime clean-audio toggle so a project recall
    // restores the same A/B position. The shipping build's `kEnabled()` is
    // constexpr-true and ignores any stored value, so cross-build state is
    // forward-compatible.
    state.setProperty ("clean_audio_enabled",
                       juce::var (trench::clean_audio::kEnabled()),
                       nullptr);
#endif
    std::unique_ptr<juce::XmlElement> xml (state.createXml());
    copyXmlToBinary (*xml, destData);
}

void PluginProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    std::unique_ptr<juce::XmlElement> xmlState (getXmlFromBinary (data, sizeInBytes));
    if (xmlState != nullptr && xmlState->hasTagName (apvts.state.getType()))
    {
        auto tree = juce::ValueTree::fromXml (*xmlState);
#ifdef TRENCH_PLAYER_EXTRAS
        if (tree.hasProperty ("clean_audio_enabled"))
            trench::clean_audio::setEnabled (static_cast<bool> (tree.getProperty ("clean_audio_enabled")));
#endif
        apvts.replaceState (std::move (tree));
    }

    if (trench::clean_audio::kEnabled())
        forceCleanAudioUiState();
}

void PluginProcessor::setParameterDenormalized (const char* parameterID, float value)
{
    if (auto* parameter = apvts.getParameter (parameterID))
    {
        const float normalized = parameter->convertTo0to1 (value);
        if (std::abs (parameter->getValue() - normalized) > 0.000001f)
            parameter->setValueNotifyingHost (normalized);
    }
}

void PluginProcessor::forceCleanAudioUiState()
{
    // PL-2: the shipping parameter layout omits slam / 5D / teleport so the
    // setParameterDenormalized calls for them noop (null param lookup). The
    // #ifdef just makes that explicit so the next reader doesn't wonder why
    // it dead-ends. body / inputMode / output exist in every build.
    setParameterDenormalized (ParamID::body, (float) trench::kNoFilterIndex);
    setParameterDenormalized (ParamID::inputMode, 0.0f);
    setParameterDenormalized (ParamID::output, 0.0f);
#ifdef TRENCH_PLAYER_EXTRAS
    setParameterDenormalized (ParamID::slamDrive, 0.0f);
    setParameterDenormalized (ParamID::fiveD, 0.0f);
    setParameterDenormalized (ParamID::teleportMode, 0.0f);
    setParameterDenormalized (ParamID::teleportAmount, 0.0f);
#endif
}

//==============================================================================
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new PluginProcessor();
}
