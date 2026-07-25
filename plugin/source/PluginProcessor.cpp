#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "TrenchBodyRoster.h"
#include "dsp/SlamStage.h"
#include "BinaryData.h"
#include <cmath>
#include <cstring>
namespace
{
constexpr int kCleanInputMode = 0;
constexpr int kMackieDeskSlam = 1;
constexpr float kIntoFilterDriveScale = 0.10f;
constexpr int kSpatialOff = 2;
}
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
    if (trench::clean_audio::kEnabled())
        forceCleanAudioUiState();
    const int startIndex = juce::jlimit (0, juce::jmax (0, trench::bodyCount() - 1),
                                         (int) apvts.getRawParameterValue (ParamID::body)->load());
    pendingBodyIndex.store (startIndex, std::memory_order_relaxed);
    loadedBodyIndex.store (startIndex, std::memory_order_relaxed);
    {
        const auto spec = trench::bodyBakedReactSpec (startIndex);
        bakedReactMode.store (spec.mode, std::memory_order_relaxed);
        bakedReactCutoff.store (spec.cutoffHz, std::memory_order_relaxed);
        bakedDetState1[0] = bakedDetState1[1] = bakedDetState2[0] = bakedDetState2[1] = 0.0f;
    }
    const auto startJson = trench::bodyCartridgeJson (startIndex);
    storeLoadedBodyBehavior (startIndex, startJson);
    juce::MemoryBlock startRaw;
    if (trench::bodyRawBytes (startIndex, startRaw))
    {
        const bool ok = dspBridge.loadCartridgeBytes (startRaw);
        currentBodyBytes = startRaw;
        rosterBodyBytes = currentBodyBytes;
        lastLoadOk.store (ok, std::memory_order_relaxed);
    }
    else
    {
        lastLoadOk.store (startJson.isNotEmpty() && dspBridge.loadCartridge (startJson),
                          std::memory_order_relaxed);
        captureCurrentBodyBytes (startJson);
    }
    dspBridge.setSpatialMode (kSpatialOff);
    dspBridge.setQSoundFallbackPan (1.0f);
    {
        int modelBytes = 0;
        const auto* modelJson = BinaryData::getNamedResource ("key_model_rtneural_json", modelBytes);
        const bool modelReady = keyDetector.loadModel (modelJson, (size_t) juce::jmax (0, modelBytes));
        juce::Logger::writeToLog (juce::String ("key model -> ") + (modelReady ? "ready" : "FAILED"));
    }
    apvts.addParameterListener (ParamID::body, this);
    apvts.addParameterListener (ParamID::hdMode, this);
    morphParamForGesture = apvts.getParameter (ParamID::morph);
    slamParamForGesture  = apvts.getParameter (ParamID::slamDrive);
    startTimer (400);
}
PluginProcessor::~PluginProcessor()
{
    stopTimer();
    apvts.removeParameterListener (ParamID::body, this);
    apvts.removeParameterListener (ParamID::hdMode, this);
    cancelPendingUpdate();
}
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
    return "TRENCH";
}
void PluginProcessor::changeProgramName (int index, const juce::String& newName)
{
    juce::ignoreUnused (index, newName);
}
float PluginProcessor::mapMorphForLoadedBody (float morph) const noexcept
{
    return trench::applyMorphTaper (
        static_cast<trench::MorphTaper> (loadedMorphTaper.load (std::memory_order_relaxed)),
        morph);
}
float PluginProcessor::mapSecondaryForLoadedBody (float q) const noexcept
{
    return juce::jlimit (0.0f, 1.0f, q);
}
void PluginProcessor::storeLoadedBodyBehavior (int bodyIndex, const juce::String& cartridgeJson)
{
    const auto behavior = trench::bodyBehaviorFromCartridgeJson (bodyIndex, cartridgeJson);
    loadedSecondaryTarget.store (static_cast<int> (behavior.secondaryTarget), std::memory_order_relaxed);
    loadedMorphTaper.store (static_cast<int> (behavior.morphTaper), std::memory_order_relaxed);
}
void PluginProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    const bool hd = apvts.getRawParameterValue (ParamID::hdMode)->load() > 0.5f;
    hdModeApplied = hd;
    fixedRateIsland.prepare (sampleRate, samplesPerBlock, dspBridge,
                             hd ? TrenchRates::emuInternalRateHd : TrenchRates::emuInternalRate);
    setLatencySamples (fixedRateIsland.getLatencySamples());
    dspBridge.setInputMode (kCleanInputMode);
    dspBridge.setSpatialMode (kSpatialOff);
    dspBridge.setQSoundFallbackPan (1.0f);
    lastInputModeSent = kCleanInputMode;
    morphMod.prepare (sampleRate);
    outputGain.reset (sampleRate, 0.02);
    const float outDb = apvts.getRawParameterValue (ParamID::output)->load();
    outputGain.setCurrentAndTargetValue (juce::Decibels::decibelsToGain (outDb));
    smoothedMorph = apvts.getRawParameterValue (ParamID::morph)->load();
    smoothedQ = apvts.getRawParameterValue (ParamID::q)->load();
    effectiveMorphForUi.store (smoothedMorph, std::memory_order_relaxed);
    effectiveQForUi.store (smoothedQ, std::memory_order_relaxed);
    morphModulatedForUi.store (false, std::memory_order_relaxed);
    qModulatedForUi.store (false, std::memory_order_relaxed);
    motionInputEnv = 0.0f;
    controlSmoothersPrimed = true;
    captureRing.prepare (sampleRate, kCaptureMaxSeconds);
    dryRing.prepare (sampleRate, kCaptureMaxSeconds);
    punchBlend.prepare (sampleRate, fixedRateIsland.getLatencySamples(), samplesPerBlock);
    punchBlend.setLatency (fixedRateIsland.getLatencySamples());
    keyDetector.prepare (sampleRate);
}
void PluginProcessor::releaseResources()
{
    dspBridge.reset();
    keyDetector.reset();
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
    if (! lastLoadOk.load (std::memory_order_acquire))
    {
        buffer.clear();
        return;
    }
    const bool bodySolo = workstationBodySolo.load (std::memory_order_acquire);
    if (bodySolo != lastWorkstationBodySolo)
    {
        dspBridge.setInputMode (kCleanInputMode);
        lastInputModeSent = kCleanInputMode;
        dspBridge.setSpatialMode (kSpatialOff);
        dspBridge.setAgcEnabled (! bodySolo);
        dspBridge.setSaturationEnabled (! bodySolo);
        lastWorkstationBodySolo = bodySolo;
    }
    if (bodySolo)
    {
        TrenchParams params;
        params.morph = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::morph)->load());
        params.q = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::q)->load());
        params.amount = 1.0f;
        params.slamDrive = 0.0f;
        params.fiveD = 0.0f;
        params.bite = 0.0f;
        fixedRateIsland.process (buffer, dspBridge, params);
        dspBridge.publishUiSnapshot();
        return;
    }
    if (demoMode.load (std::memory_order_relaxed) && juce::JUCEApplicationBase::isStandaloneApp())
    {
        float inPk = 0.0f;
        for (int ch = 0; ch < juce::jmin (2, buffer.getNumChannels()); ++ch)
        {
            const auto* d = buffer.getReadPointer (ch);
            for (int i = 0; i < buffer.getNumSamples(); ++i)
                inPk = juce::jmax (inPk, std::abs (d[i]));
        }
        if (inPk < 1.0e-4f)
            generateDemoBlock (buffer);
    }
    keyDetector.pushAudio (buffer);
    if (buffer.getNumSamples() > 0 && ! captureFrozen.load (std::memory_order_relaxed))
    {
        const auto* inL = buffer.getReadPointer (0);
        const auto* inR = buffer.getNumChannels() > 1 ? buffer.getReadPointer (1) : inL;
        dryRing.write (inL, inR, buffer.getNumSamples());
    }
    TrenchParams params;
    const float morphTarget = apvts.getRawParameterValue (ParamID::morph)->load();
    const float qTarget = apvts.getRawParameterValue (ParamID::q)->load();
    if (! controlSmoothersPrimed)
    {
        smoothedMorph = morphTarget;
        smoothedQ = qTarget;
        controlSmoothersPrimed = true;
    }
    const auto sampleRate = juce::jmax (1.0, getSampleRate());
    const auto blockSeconds = (double) buffer.getNumSamples() / sampleRate;
    constexpr double controlTauSeconds = 0.035;
    const auto controlAlpha = (float) (1.0 - std::exp (-blockSeconds / controlTauSeconds));
    smoothedMorph += (morphTarget - smoothedMorph) * controlAlpha;
    smoothedQ += (qTarget - smoothedQ) * controlAlpha;
    const int detMode = bakedReactMode.load (std::memory_order_relaxed);
    float inPeak = 0.0f;
    if (detMode >= 2)
    {
        const float fc = bakedReactCutoff.load (std::memory_order_relaxed);
        const float a = 1.0f - std::exp (-juce::MathConstants<float>::twoPi * fc / (float) sampleRate);
        for (int ch = 0; ch < juce::jmin (2, buffer.getNumChannels()); ++ch)
        {
            const auto* d = buffer.getReadPointer (ch);
            float s1 = bakedDetState1[ch], s2 = bakedDetState2[ch];
            float bandPeak = 0.0f, widePeak = 0.0f;
            for (int i = 0; i < buffer.getNumSamples(); ++i)
            {
                s1 += a * (d[i] - s1);
                const float x1 = detMode == 2 ? d[i] - s1 : s1;
                s2 += a * (x1 - s2);
                const float v = detMode == 2 ? x1 - s2 : s2;
                bandPeak = juce::jmax (bandPeak, std::abs (v));
                widePeak = juce::jmax (widePeak, std::abs (d[i]));
            }
            bakedDetState1[ch] = s1; bakedDetState2[ch] = s2;
            constexpr float silenceFloor = 1.0e-3f;
            constexpr float fullLevel = 0.0316f;
            if (widePeak > silenceFloor && std::isfinite (bandPeak) && std::isfinite (widePeak))
            {
                const float ratio = juce::jlimit (0.0f, 1.0f, bandPeak / widePeak);
                const float loud = juce::jlimit (0.0f, 1.0f, (widePeak - silenceFloor) / (fullLevel - silenceFloor));
                inPeak = juce::jmax (inPeak, ratio * loud);
            }
        }
    }
    else
    {
        for (int ch = 0; ch < juce::jmin (2, buffer.getNumChannels()); ++ch)
        {
            const auto* d = buffer.getReadPointer (ch);
            for (int i = 0; i < buffer.getNumSamples(); ++i)
                inPeak = juce::jmax (inPeak, std::abs (d[i]));
        }
    }
    inPeak = juce::jlimit (0.0f, 1.0f, inPeak);
    const float envAtk = (float) (1.0 - std::exp (-blockSeconds / 0.004));
    const float envRel = (float) (1.0 - std::exp (-blockSeconds / 0.140));
    motionInputEnv += (inPeak - motionInputEnv) * (inPeak > motionInputEnv ? envAtk : envRel);
    double bpm = 120.0, ppq = -1.0; bool playing = false;
    double qnPerBar = 4.0;
    if (auto* ph = getPlayHead())
        if (auto pos = ph->getPosition())
        {
            if (auto b = pos->getBpm()) bpm = *b;
            if (auto p = pos->getPpqPosition()) ppq = *p;
            playing = pos->getIsPlaying();
            if (auto ts = pos->getTimeSignature())
                qnPerBar = trench::quarterNotesPerBar (ts->numerator, ts->denominator);
        }
    // ENV/SYNC/RISER index order on the face does not match trench::ModTrigger's
    // enum order (Sync,Env,Riser) — translate explicitly rather than cast.
    static constexpr trench::ModTrigger kTriggerForParam[3] = {
        trench::ModTrigger::Env, trench::ModTrigger::Sync, trench::ModTrigger::Riser
    };
    const int triggerIdx = juce::jlimit (0, 2, (int) apvts.getRawParameterValue (ParamID::modTrigger)->load());
    if (modRestartRequest.exchange (false, std::memory_order_relaxed))
        morphMod.requestRestart();
    const auto modResult = morphMod.apply (
        apvts.getRawParameterValue (ParamID::modOn)->load() > 0.5f,
        kTriggerForParam[triggerIdx],
        (trench::ModShape) juce::jlimit (0, 5, (int) apvts.getRawParameterValue (ParamID::modShape)->load()),
        (int) apvts.getRawParameterValue (ParamID::modSync)->load() == 0,
        (int) apvts.getRawParameterValue (ParamID::modNote)->load(),
        (trench::ModFeel) juce::jlimit (0, 2, (int) apvts.getRawParameterValue (ParamID::modFeel)->load()),
        apvts.getRawParameterValue (ParamID::modRate)->load(),
        apvts.getRawParameterValue (ParamID::modDepth)->load(),
        0.0f,   // modulation is MORPH ONLY (Tyson 2026-07-25) - no Q depth exists
        motionInputEnv, bpm, ppq, playing, qnPerBar,
        smoothedMorph, smoothedQ, buffer.getNumSamples());
    modPhaseForUi.store (morphMod.uiPhase(), std::memory_order_relaxed);
    effectiveMorphForUi.store (modResult.morph, std::memory_order_relaxed);
    effectiveQForUi.store (modResult.q, std::memory_order_relaxed);
    morphModulatedForUi.store (std::abs (modResult.morph - smoothedMorph) > 0.0005f,
                               std::memory_order_relaxed);
    qModulatedForUi.store (std::abs (modResult.q - smoothedQ) > 0.0005f,
                           std::memory_order_relaxed);
    params.morph = mapMorphForLoadedBody (modResult.morph);
    params.q     = mapSecondaryForLoadedBody (modResult.q);
    params.slamDrive = apvts.getRawParameterValue (ParamID::slamDrive)->load();
    params.bite = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::clip)->load());
    // BITE law (Tyson 2026-07-25): nothing baked - the 20% base was too
    // strong. SLAM carries bite in quietly: quadratic, so low slam adds
    // nothing and full slam lands a tasteful ~22%.
    params.interstageDrive = juce::jlimit (0.0f, 1.0f,
        apvts.getRawParameterValue (ParamID::bite)->load()
        + 0.22f * params.slamDrive * params.slamDrive);
    auto* inputModeParam = apvts.getRawParameterValue (ParamID::inputMode);
    const bool slamIntoFilter = (inputModeParam != nullptr && inputModeParam->load() > 0.5f);
    if (slamIntoFilter)
        params.slamDrive *= kIntoFilterDriveScale;
    const int desiredInputMode = slamIntoFilter ? kMackieDeskSlam : kCleanInputMode;
    if (desiredInputMode != lastInputModeSent)
    {
        dspBridge.setInputMode (desiredInputMode);
        lastInputModeSent = desiredInputMode;
    }
    const float fiveDBase = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::fiveD)->load());
    float space = fiveDBase;
    params.fiveD = space;
    lastSpaceSent.store (space, std::memory_order_relaxed);
    dspBridge.setSpatialMode (space > 0.001f ? 0  : kSpatialOff);
    float pan = rigPan.load (std::memory_order_relaxed);
    if (space > 0.001f)
    {
        constexpr double kTwoPi = 2.0 * juce::MathConstants<double>::pi;
        double revPpq = -1.0, qnPerBar = 4.0;
        if (auto* ph = getPlayHead())
            if (auto pos = ph->getPosition())
            {
                if (pos->getIsPlaying())
                    if (auto p = pos->getPpqPosition()) revPpq = juce::jmax (0.0, *p);
                if (auto ts = pos->getTimeSignature())
                    qnPerBar = trench::quarterNotesPerBar (ts->numerator, ts->denominator);
            }
        if (revPpq >= 0.0)
        {
            const double beatsPerRev = 2.0 * qnPerBar;
            spatialOrbitPhase = std::fmod (kTwoPi * revPpq / beatsPerRev, kTwoPi);
        }
        else
        {
            const double sr = getSampleRate() > 0.0 ? getSampleRate() : 48000.0;
            constexpr double kOrbitHz = 0.35;
            spatialOrbitPhase += kTwoPi * kOrbitHz * (double) buffer.getNumSamples() / sr;
            if (spatialOrbitPhase >= kTwoPi) spatialOrbitPhase -= kTwoPi;
        }
        pan = (float) std::sin (spatialOrbitPhase);
    }
    if (! juce::approximatelyEqual (pan, lastRigPanSent))
    {
        dspBridge.setQSoundFallbackPan (pan);
        lastRigPanSent = pan;
    }
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
    const float mixTarget = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::amount)->load());
    params.amount = 1.0f;
    {
        // Fast synced modulation needs a tighter coefficient ramp than a manual
        // knob move, or it zippers; bar-scale notes (4/2/1 bar, index<=2) are
        // slow enough to use the same glide as a hand move.
        static constexpr float kTight = 0.164f, kGlide = 1.0f;
        const bool modRunning = apvts.getRawParameterValue (ParamID::modOn)->load() > 0.5f
                              && (int) apvts.getRawParameterValue (ParamID::modSync)->load() == 0;
        const int noteIdx = (int) apvts.getRawParameterValue (ParamID::modNote)->load();
        params.rampScale = (modRunning && noteIdx > 2) ? kTight : kGlide;
    }
    params.pitchRatio = 1.0f;
    params.keySnap = juce::jlimit (0, 24,
        (int) apvts.getRawParameterValue (ParamID::keySnap)->load());
    punchBlend.captureDry (buffer.getArrayOfReadPointers(), buffer.getNumChannels(), buffer.getNumSamples());
    fixedRateIsland.process (buffer, dspBridge, params);
    punchBlend.blend (buffer.getArrayOfWritePointers(), buffer.getNumChannels(), buffer.getNumSamples(), mixTarget);
    const float outDb = apvts.getRawParameterValue (ParamID::output)->load();
    outputGain.setTargetValue (juce::Decibels::decibelsToGain (outDb));
    outputGain.applyGain (buffer, buffer.getNumSamples());
    // The desk stage reports the TRUE limit amount: the fraction of samples
    // pushed past the pressure knee. That (not raw output peak) is the meter.
    float limitFrac = 0.0f;
    if (! slamIntoFilter)
    {
        if (buffer.getNumChannels() >= 2)
            limitFrac = trench::slamOutputPressureBlockStereo (buffer.getWritePointer (0),
                                                    buffer.getWritePointer (1),
                                                    buffer.getNumSamples(), params.slamDrive);
        else if (buffer.getNumChannels() == 1)
            limitFrac = trench::slamOutputPressureBlock (buffer.getWritePointer (0),
                                             buffer.getNumSamples(), params.slamDrive);
    }
    dspBridge.publishUiSnapshot();
    if (auto* ph = getPlayHead())
        if (auto pos = ph->getPosition())
            if (auto b = pos->getBpm())
                hostBpm.store (*b, std::memory_order_relaxed);
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
        const float prevClip = outClipForUi.load (std::memory_order_relaxed);
        outClipForUi.store (juce::jmax (limitFrac, prevClip * 0.90f), std::memory_order_relaxed);
        if (! captureFrozen.load (std::memory_order_relaxed))
            captureRing.write (postL, postR, buffer.getNumSamples());
    }
    {
        const juce::uint64 cur = processedFrames.load (std::memory_order_relaxed);
        const float mNow = morphParamForGesture != nullptr ? morphParamForGesture->getValue() : 0.0f;
        const float sNow = slamParamForGesture  != nullptr ? slamParamForGesture->getValue()  : 0.0f;
        if (! gestureTrackPrimed)
        {
            prevGestureMorph = mNow; prevGestureSlam = sNow; gestureTrackPrimed = true;
        }
        if (std::abs (mNow - prevGestureMorph) > 0.02f || std::abs (sNow - prevGestureSlam) > 0.02f)
        {
            const juce::uint64 lastMove = lastMoveFrame.load (std::memory_order_relaxed);
            const double idleGapFrames = 0.4 * sampleRate;
            if (! haveGesture.load (std::memory_order_relaxed)
                || (double) (cur - lastMove) > idleGapFrames)
                gestureAnchorFrame.store (cur, std::memory_order_relaxed);
            lastMoveFrame.store (cur, std::memory_order_relaxed);
            haveGesture.store (true, std::memory_order_relaxed);
        }
        prevGestureMorph = mNow; prevGestureSlam = sNow;
        processedFrames.store (cur + (juce::uint64) buffer.getNumSamples(), std::memory_order_relaxed);
    }
}
void PluginProcessor::generateDemoBlock (juce::AudioBuffer<float>& buffer)
{
    const double sr = juce::jmax (1.0, getSampleRate());
    const int n = buffer.getNumSamples();
    const int chs = juce::jmin (2, buffer.getNumChannels());
    if (chs <= 0) return;
    static const int seq[16] = { 0, 0, 12, 0,  7, 0, 0, 3,  5, 0, 7, 0,  0, 10, 3, 7 };
    const auto rngf = [this]
    {
        demoRng = demoRng * 1664525u + 1013904223u;
        return (float) ((double) (demoRng >> 8) / (double) (1u << 24)) * 2.0f - 1.0f;
    };
    for (int i = 0; i < n; ++i)
    {
        const double t = (double) (demoSample++) / sr;
        const double sixteenth = t * 8.0;
        const int    step = ((int) sixteenth) % 16;
        const double frac = sixteenth - std::floor (sixteenth);
        const double freq = 55.0 * std::pow (2.0, (double) seq[step] / 12.0);
        demoSawPhase += freq / sr;
        if (demoSawPhase >= 1.0) demoSawPhase -= 1.0;
        const float saw  = (float) (2.0 * demoSawPhase - 1.0);
        const float bass = saw * (float) std::exp (-frac * 6.0) * 0.5f;
        const float hat  = (step % 2 == 1) ? rngf() * (float) std::exp (-frac * 45.0) * 0.3f : 0.0f;
        const float s    = juce::jlimit (-1.0f, 1.0f, bass + hat);
        for (int ch = 0; ch < chs; ++ch)
            buffer.getWritePointer (ch)[i] = s;
    }
}
int PluginProcessor::copyScopeSamples (float* outL, float* outR, int count) const noexcept
{
    if (outL == nullptr || outR == nullptr || count <= 0)
        return 0;
    count = juce::jmin (count, kScopeLen);
    const int wp = scopeWritePos.load (std::memory_order_relaxed);
    for (int i = 0; i < count; ++i)
    {
        const int idx = (wp - count + i) & (kScopeLen - 1);
        outL[i] = scopeL[(size_t) idx].load (std::memory_order_relaxed);
        outR[i] = scopeR[(size_t) idx].load (std::memory_order_relaxed);
    }
    return count;
}
void PluginProcessor::parameterChanged (const juce::String& parameterID, float newValue)
{
    if (parameterID == ParamID::body)
    {
        const int raw = juce::roundToInt (newValue);
        // An out-of-range index must never resolve to a DIFFERENT preset. The
        // old modulo wrap silently loaded some other body when a saved project
        // named a slot this roster no longer has; land on NO FILTER instead.
        const int wanted = (raw >= 0 && raw < trench::bodyCount()) ? raw : trench::kNoFilterIndex;
        pendingBodyIndex.store (wanted, std::memory_order_relaxed);
        triggerAsyncUpdate();
    }
    else if (parameterID == ParamID::hdMode)
    {
        // HD picks the island's internal rate, which is only read in
        // prepareToPlay - so flipping it did nothing until the host happened to
        // re-prepare. Re-prepare the island ourselves, with audio suspended.
        const bool hd = newValue > 0.5f;
        if (hd == hdModeApplied)
            return;
        const double sr = getSampleRate();
        if (sr <= 0.0)
            return;                 // not prepared yet; prepareToPlay will read it
        juce::ScopedLock audioLock (getCallbackLock());
        fixedRateIsland.prepare (sr, getBlockSize(), dspBridge,
                                 hd ? TrenchRates::emuInternalRateHd : TrenchRates::emuInternalRate);
        setLatencySamples (fixedRateIsland.getLatencySamples());
        punchBlend.prepare (sr, fixedRateIsland.getLatencySamples(), getBlockSize());
        punchBlend.setLatency (fixedRateIsland.getLatencySamples());
        hdModeApplied = hd;
    }
}
void PluginProcessor::handleAsyncUpdate()
{
    const int want = pendingBodyIndex.load (std::memory_order_relaxed);
    if (want == loadedBodyIndex.load (std::memory_order_relaxed))
        return;
    lastLoadOk.store (false, std::memory_order_release);
    juce::MemoryBlock raw;
    juce::String json;
    bool ok;
    if (trench::bodyRawBytes (want, raw))
    {
        ok = dspBridge.loadCartridgeBytes (raw);
        currentBodyBytes = raw;
        rosterBodyBytes = currentBodyBytes;
    }
    else
    {
        json = trench::bodyCartridgeJson (want);
        ok = json.isNotEmpty() && dspBridge.loadCartridge (json);
        captureCurrentBodyBytes (json);
    }
    storeLoadedBodyBehavior (want, json);
    lastLoadOk.store (ok, std::memory_order_release);
    controlSmoothersPrimed = false;
    loadedBodyIndex.store (want, std::memory_order_relaxed);
    {
        const auto spec = trench::bodyBakedReactSpec (want);
        bakedReactMode.store (spec.mode, std::memory_order_relaxed);
        bakedReactCutoff.store (spec.cutoffHz, std::memory_order_relaxed);
    }
    if (trench::bodyIsAudition (want))
        auditionSlotMtime = trench::auditionSlotFile().getLastModificationTime();
    // MIX law: every body arrives at 100% mix
    if (ok)
        if (auto* amount = apvts.getParameter (ParamID::amount))
            amount->setValueNotifyingHost (1.0f);
    juce::Logger::writeToLog (juce::String ("body switch -> ")
                               + trench::bodyDisplayName (want)
                               + (ok ? " ok" : " FAIL"));
}
void PluginProcessor::captureCurrentBodyBytes (const juce::String& cartridgeJson)
{
    if (cartridgeJson.isEmpty() || ! TrenchDspBridge::bodyBytesFromJson (cartridgeJson, currentBodyBytes))
        currentBodyBytes.setSize (0);
    rosterBodyBytes = currentBodyBytes;
}
bool PluginProcessor::seedCurrentBody()
{
#ifndef TRENCH_PLAYER_EXTRAS
    return false;
#else
    if (currentBodyBytes.getSize() != 240)
        captureCurrentBodyBytes (trench::bodyCartridgeJson (loadedBodyIndex.load (std::memory_order_relaxed)));
    if (currentBodyBytes.getSize() != 240)
        return false;
    juce::MemoryBlock sibling;
    if (dspBridge.seedSiblingFromBytes (currentBodyBytes.getData(), currentBodyBytes.getSize(),
                                        ++seedCounter, 1.0, sibling))
    {
        currentBodyBytes = std::move (sibling);
        lastLoadOk.store (true, std::memory_order_release);
        juce::Logger::writeToLog ("SEED -> sibling auditioned");
        return true;
    }
    juce::Logger::writeToLog ("SEED -> no legal sibling within budget (try again)");
    return false;
#endif
}
void PluginProcessor::exportCurrentBody()
{
    if (currentBodyBytes.getSize() != 240)
        captureCurrentBodyBytes (trench::bodyCartridgeJson (loadedBodyIndex.load (std::memory_order_relaxed)));
    if (currentBodyBytes.getSize() != 240)
        return;
    auto dir = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                   .getChildFile ("TRENCH")
                   .getChildFile ("exports");
    dir.createDirectory();
    auto base = trench::bodyDisplayName (loadedBodyIndex.load (std::memory_order_relaxed))
                    .retainCharacters ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ")
                    .replaceCharacter (' ', '_');
    if (base.isEmpty())
        base = "body";
    juce::File f;
    for (int i = 1; i < 10000; ++i)
    {
        f = dir.getChildFile (base + "_" + juce::String (i).paddedLeft ('0', 3) + ".body240");
        if (! f.existsAsFile())
            break;
    }
    if (f.replaceWithData (currentBodyBytes.getData(), currentBodyBytes.getSize()))
        juce::Logger::writeToLog ("EXPORT body -> " + f.getFullPathName());
}
void PluginProcessor::forgeAuditionTyped (const std::vector<double>& cards)
{
    juce::MemoryBlock body;
    if (! TrenchDspBridge::compileTypedBody (cards.data(), (int) cards.size(), body)
        || body.getSize() != 240)
    {
        lastLoadOk.store (false, std::memory_order_release);
        juce::Logger::writeToLog ("FORGE compile FAILED");
        return;
    }
    if (installBodyBytes (body.getData(), body.getSize()))
    {
        rosterBodyBytes = currentBodyBytes;
        juce::Logger::writeToLog ("FORGE -> typed body compiled + auditioned");
    }
}
juce::File PluginProcessor::forgeSaveBody (const juce::String& name, bool overwrite)
{
    if (currentBodyBytes.getSize() != 240)
        return {};
    // canonical body home = repo bodies/candidates ("no documents", 2026-07-25)
    auto dir = juce::File ("C:/Users/hooki/df2-workstation/bodies/candidates");
    dir.createDirectory();
    auto base = name.retainCharacters ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ")
                    .trim().replaceCharacter (' ', '_');
    if (base.isEmpty())
        base = "forge";
    auto f = dir.getChildFile (base + ".body240");
    // designer saves own their name: overwrite in place so the loaded plugin
    // hot-follows the same file. Classic saves keep suffixing.
    for (int i = 1; ! overwrite && f.existsAsFile() && i < 10000; ++i)
        f = dir.getChildFile (base + "_" + juce::String (i).paddedLeft ('0', 2) + ".body240");
    if (f.replaceWithData (currentBodyBytes.getData(), currentBodyBytes.getSize()))
    {
        juce::Logger::writeToLog ("FORGE save -> " + f.getFullPathName());
        return f;
    }
    return {};
}
bool PluginProcessor::renderRecipe (const unsigned char* body, float morph, float q, float slam,
                                    bool qsound, double seconds, juce::AudioBuffer<float>& out)
{
    if (body == nullptr)
        return false;
    const double sr = juce::jmax (1.0, getSampleRate());
    const int frames = (int) std::ceil (seconds * sr);
    if (frames <= 0)
        return false;
    std::vector<float> dl ((size_t) frames, 0.0f), dr ((size_t) frames, 0.0f);
    const int got = dryRing.snapshotLast (seconds, dl.data(), dr.data(), frames);
    if (got <= 0)
        return false;
    void* pe = trench_engine_create();
    if (pe == nullptr)
        return false;
    trench_engine_prepare (pe, sr);
    if (trench_engine_load_body_bytes (pe, body, 240) != 0)
    {
        trench_engine_destroy (pe);
        return false;
    }
    const float s = juce::jlimit (0.0f, 1.0f, slam);
    trench_engine_set_input_mode (pe, 0 );
    trench_engine_set_agc_enabled (pe, 1);
    trench_engine_set_saturation_enabled (pe, 1);
    trench_engine_set_spatial_mode (pe, qsound ? 0  : 2 );
    trench_engine_set_parameters (pe, morph, q, 0.0f, qsound ? 1.0f : 0.0f, 1.0f);
    out.setSize (2, got);
    float* L = out.getWritePointer (0);
    float* R = out.getWritePointer (1);
    std::copy (dl.begin(), dl.begin() + got, L);
    std::copy (dr.begin(), dr.begin() + got, R);
    constexpr int B = 512;
    for (int off = 0; off < got; off += B)
    {
        const int blk = juce::jmin (B, got - off);
        trench_engine_process_block (pe, L + off, R + off, blk, (double) morph, (double) q);
    }
    trench_engine_destroy (pe);
    trench::slamOutputPressureBlockStereo (L, R, got, s);
    if (auto* o = apvts.getRawParameterValue (ParamID::output))
        out.applyGain (juce::Decibels::decibelsToGain (o->load()));
    return true;
}
std::vector<PluginProcessor::VariantPreview> PluginProcessor::buildTakeTray (int n)
{
#ifndef TRENCH_PLAYER_EXTRAS
    juce::ignoreUnused (n);
    return {};
#else
    std::vector<VariantPreview> out;
    n = juce::jlimit (1, 12, n);
    const auto readNorm = [this] (const char* id, float fb)
    {
        if (auto* v = apvts.getRawParameterValue (id)) return juce::jlimit (0.0f, 1.0f, v->load());
        return fb;
    };
    const float morph = readNorm (ParamID::morph, 0.5f);
    const float q     = readNorm (ParamID::q, 0.0f);
    const float slam  = readNorm (ParamID::slamDrive, 0.0f);
    const double seconds = smartTakeSeconds();
    const auto hash01 = [] (juce::uint64 x) -> float
    {
        x ^= x >> 33; x *= 0xff51afd7ed558ccdULL;
        x ^= x >> 33; x *= 0xc4ceb9fe1a85ec53ULL;
        x ^= x >> 33;
        return (float) ((double) (x >> 11) / (double) (1ULL << 53));
    };
    juce::MemoryBlock original = rosterBodyBytes;
    if (original.getSize() != 240)
        TrenchDspBridge::bodyBytesFromJson (
            trench::bodyCartridgeJson (loadedBodyIndex.load (std::memory_order_relaxed)), original);
    if (original.getSize() != 240)
        return out;
    const auto buildSlot = [&] (const unsigned char* body, const VariantPreview& recipe,
                                bool asHeard, VariantPreview& vp) -> bool
    {
        juce::AudioBuffer<float> wet;
        if (! renderRecipe (body, recipe.morph, recipe.q, recipe.slam, recipe.qsound, seconds, wet))
            return false;
        std::memcpy (vp.bytes.data(), body, 240);
        vp.morph = recipe.morph; vp.q = recipe.q; vp.slam = recipe.slam;
        vp.qsound = recipe.qsound; vp.axis = recipe.axis; vp.asHeard = asHeard;
        const int frames = wet.getNumSamples();
        const float* L = wet.getReadPointer (0);
        const float* R = wet.getNumChannels() > 1 ? wet.getReadPointer (1) : L;
        double sumAbs = 0.0, sumDiff = 0.0;
        float prev = 0.0f;
        for (int b = 0; b < kTakeWaveN; ++b)
        {
            const int a = (int) ((long long) b * frames / kTakeWaveN);
            const int e = juce::jmax (a + 1, (int) ((long long) (b + 1) * frames / kTakeWaveN));
            float mn = 0.0f, mx = 0.0f;
            for (int k = a; k < e && k < frames; ++k)
            {
                const float m = 0.5f * (L[k] + R[k]);
                mn = juce::jmin (mn, m); mx = juce::jmax (mx, m);
                sumAbs += std::abs (m); sumDiff += std::abs (m - prev); prev = m;
            }
            vp.wmin[b] = juce::jlimit (-1.0f, 1.0f, mn);
            vp.wmax[b] = juce::jlimit (-1.0f, 1.0f, mx);
        }
        vp.bright = sumAbs > 1.0e-6 ? juce::jlimit (0.0f, 1.0f, (float) (sumDiff / sumAbs)) : 0.0f;
        vp.valid = true;
        return true;
    };
    {
        VariantPreview recipe; recipe.morph = morph; recipe.q = q; recipe.slam = slam;
        recipe.axis = AxisFamily;
        VariantPreview vp;
        if (buildSlot (static_cast<const unsigned char*> (original.getData()), recipe, true, vp))
            out.push_back (vp);
    }
    std::vector<juce::MemoryBlock> families;
    for (const char* base : { "mason_tube", "sf_tube_47cm_to_17cm",
                              "sf_x_vowel_iy_to_tube_co_25cm", "vowelshift" })
    {
        int sz = 0;
        const char* d = BinaryData::getNamedResource ((juce::String (base) + "_json").toRawUTF8(), sz);
        if (d != nullptr && sz > 0)
        {
            juce::MemoryBlock mb;
            if (TrenchDspBridge::bodyBytesFromJson (juce::String::createStringFromData (d, sz), mb)
                && mb.getSize() == 240)
                families.push_back (std::move (mb));
        }
    }
    int familyCursor = 0;
    for (int i = 1; i < n; ++i)
    {
        const int axis = (i - 1) % 5;
        VariantPreview vp;
        if (axis == AxisFamily && ! families.empty())
        {
            const auto& fam = families[(size_t) (familyCursor++ % (int) families.size())];
            VariantPreview recipe;
            recipe.morph = morph; recipe.q = q; recipe.slam = slam; recipe.qsound = false;
            recipe.axis = AxisFamily;
            buildSlot (static_cast<const unsigned char*> (fam.getData()), recipe, false, vp);
        }
        else
        {
            const double amt = juce::jmap ((double) i, 1.0, (double) juce::jmax (2, n - 1), 0.4, 2.0);
            for (int attempt = 0; attempt < 6 && ! vp.valid; ++attempt)
            {
                const juce::uint64 seedVal = ++variantBankCursor;
                unsigned char sib[240];
                if (trench_seed_body (static_cast<const unsigned char*> (original.getData()), 240,
                                      (unsigned long long) seedVal, amt, 65u, 0.9999, sib) != 0)
                    continue;
                VariantPreview recipe;
                recipe.morph = morph; recipe.q = q; recipe.slam = slam; recipe.qsound = false;
                recipe.axis = axis;
                switch (axis)
                {
                    case AxisMorph:  recipe.morph = hash01 (seedVal * 2 + 1); break;
                    case AxisQ:      recipe.q     = juce::jlimit (0.0f, 1.0f, 0.45f + 0.5f * hash01 (seedVal * 2 + 2)); break;
                    case AxisQSound: recipe.qsound = true; break;
                    case AxisSlam:   recipe.slam  = juce::jlimit (0.0f, 1.0f, 0.5f + 0.5f * hash01 (seedVal * 2 + 3)); break;
                    default:         break;
                }
                buildSlot (sib, recipe, false, vp);
            }
        }
        if (vp.valid)
            out.push_back (vp);
    }
    return out;
#endif
}
bool PluginProcessor::installBodyBytes (const void* bytes, size_t len)
{
    if (bytes == nullptr || len != 240)
        return false;
    if (! dspBridge.loadCartridgeBytes (bytes, len))
        return false;
    currentBodyBytes = juce::MemoryBlock (bytes, len);
    lastLoadOk.store (true, std::memory_order_release);
    return true;
}
bool PluginProcessor::copyCurrentBodyBytes (void* out, size_t len)
{
    if (out == nullptr || len != 240)
        return false;
    if (currentBodyBytes.getSize() != 240)
        captureCurrentBodyBytes (trench::bodyCartridgeJson (loadedBodyIndex.load (std::memory_order_relaxed)));
    if (currentBodyBytes.getSize() != 240)
        return false;
    std::memcpy (out, currentBodyBytes.getData(), 240);
    return true;
}
bool PluginProcessor::probeCurrentBodyForUi (float morph, float q, float outCoeffs[30], float& outBoost)
{
    if (outCoeffs == nullptr)
        return false;
    if (currentBodyBytes.getSize() != 240)
        captureCurrentBodyBytes (trench::bodyCartridgeJson (loadedBodyIndex.load (std::memory_order_relaxed)));
    if (currentBodyBytes.getSize() != 240)
        return false;
    return TrenchDspBridge::probePackedBody (currentBodyBytes.getData(), currentBodyBytes.getSize(),
                                             morph, q, outCoeffs, outBoost);
}
juce::File PluginProcessor::writeTake (double seconds, bool oneShot, int beats)
{
    const double sr = juce::jmax (1.0, getSampleRate());
    const double bpm = hostBpm.load (std::memory_order_relaxed);
    const int maxFrames = (int) std::ceil (seconds * sr);
    if (maxFrames <= 0)
        return {};
    juce::AudioBuffer<float> take (2, maxFrames);
    const int frames = captureRing.snapshotLast (seconds,
                                                 take.getWritePointer (0),
                                                 take.getWritePointer (1),
                                                 maxFrames);
    if (frames <= 0)
        return {};
    take.setSize (2, frames, true, true, true);
    auto dir = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                   .getChildFile ("TRENCH")
                   .getChildFile ("takes");
    dir.createDirectory();
    auto base = trench::bodyDisplayName (loadedBodyIndex.load (std::memory_order_relaxed))
                    .retainCharacters ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ")
                    .replaceCharacter (' ', '_');
    if (base.isEmpty())
        base = "take";
    juce::File f;
    for (int i = 1; i < 10000; ++i)
    {
        f = dir.getChildFile (base + "_take_" + juce::String (i).paddedLeft ('0', 3) + ".wav");
        if (! f.existsAsFile())
            break;
    }
    trench::TakeTags tags;
    tags.description = "TRENCH take";
    tags.oneShot = oneShot;
    tags.bpm = bpm;
    tags.beats = beats;
    if (! trench::writeTakeWav (f, take, sr, tags))
        return {};
    lastTakeFile = f;
    juce::Logger::writeToLog ("CAPTURE take -> " + f.getFullPathName());
    return f;
}
juce::File PluginProcessor::captureTake (trench::CaptureRange range)
{
    const double bpm = hostBpm.load (std::memory_order_relaxed);
    const auto plan = trench::planCapture (range, bpm);
    return writeTake (plan.seconds, plan.oneShot, plan.beats);
}
double PluginProcessor::smartTakeSeconds() const
{
    const double sr = juce::jmax (1.0, getSampleRate());
    constexpr double fallback = 4.0, minSec = 0.6, maxSec = 8.0;
    constexpr double recentWindowSec = 8.0;
    constexpr double prerollSec = 0.15;
    const juce::uint64 cur      = processedFrames.load (std::memory_order_relaxed);
    const juce::uint64 lastMove = lastMoveFrame.load (std::memory_order_relaxed);
    const juce::uint64 anchor   = gestureAnchorFrame.load (std::memory_order_relaxed);
    if (! haveGesture.load (std::memory_order_relaxed)
        || cur <= lastMove
        || (double) (cur - lastMove) / sr > recentWindowSec
        || anchor > cur)
        return juce::jlimit (minSec, maxSec, fallback);
    const juce::uint64 prerollFrames = (juce::uint64) (prerollSec * sr);
    const juce::uint64 start = anchor > prerollFrames ? anchor - prerollFrames : 0;
    const double secs = (double) (cur - start) / sr;
    return juce::jlimit (minSec, maxSec, secs);
}
juce::File PluginProcessor::captureSmartTake()
{
    return writeTake (smartTakeSeconds(), true, 0);
}
int PluginProcessor::getTakePreview (float* out, int count)
{
    if (out == nullptr || count <= 0)
        return 0;
    for (int i = 0; i < count; ++i)
        out[i] = 0.0f;
    const double sr = juce::jmax (1.0, getSampleRate());
    const double seconds = smartTakeSeconds();
    const int frames = (int) std::ceil (seconds * sr);
    if (frames <= 0)
        return 0;
    std::vector<float> l ((size_t) frames, 0.0f), r ((size_t) frames, 0.0f);
    const int got = captureRing.snapshotLast (seconds, l.data(), r.data(), frames);
    if (got <= 0)
        return 0;
    for (int i = 0; i < count; ++i)
    {
        const int a = (int) ((long long) i * got / count);
        const int b = juce::jmax (a + 1, (int) ((long long) (i + 1) * got / count));
        float pk = 0.0f;
        for (int k = a; k < b && k < got; ++k)
            pk = juce::jmax (pk, 0.5f * (std::abs (l[(size_t) k]) + std::abs (r[(size_t) k])));
        out[i] = juce::jlimit (0.0f, 1.0f, pk);
    }
    return got;
}
void PluginProcessor::timerCallback()
{
    dspBridge.reclaim();
    trench::KeyDetector::Result keyResult;
    if (keyDetector.analyse (keyResult))
    {
        for (size_t index = 0; index < keyProbabilitySum.size(); ++index)
            keyProbabilitySum[index] += keyResult.probabilities[index];
        ++keyProbabilityWindows;
        if (keyProbabilityWindows >= 3)
        {
            std::array<float, 24> average {};
            for (size_t index = 0; index < average.size(); ++index)
                average[index] = keyProbabilitySum[index] / (float) keyProbabilityWindows;
            int best = 0, second = 1;
            if (average[(size_t) second] > average[(size_t) best])
                std::swap (best, second);
            for (int index = 2; index < (int) average.size(); ++index)
            {
                if (average[(size_t) index] > average[(size_t) best])
                {
                    second = best;
                    best = index;
                }
                else if (average[(size_t) index] > average[(size_t) second])
                {
                    second = index;
                }
            }
            const float confidence = average[(size_t) best];
            const float margin = confidence - average[(size_t) second];
            keyConfidenceForUi.store (confidence, std::memory_order_relaxed);
            if (confidence >= 0.25f && margin >= 0.05f)
            {
                detectedKeyForUi.store (best, std::memory_order_relaxed);
                detectedAltKeyForUi.store (second, std::memory_order_relaxed);
            }
            else
            {
                detectedKeyForUi.store (-1, std::memory_order_relaxed);
                detectedAltKeyForUi.store (-1, std::memory_order_relaxed);
            }
            keyProbabilitySum.fill (0.0f);
            keyProbabilityWindows = 0;
        }
    }
    // user bodies hot-reload in place: the Workstation saves, the plugin
    // follows - no TYPE menu round trip. Only disk-loaded .body240 bodies.
    {
        const auto base = trench::bodyBaseForIndex (loadedBodyIndex.load (std::memory_order_relaxed));
        if (juce::File::isAbsolutePath (base) && base.endsWithIgnoreCase (".body240"))
        {
            const juce::File f (base);
            const auto t = f.existsAsFile() ? f.getLastModificationTime() : juce::Time();
            if (base != watchedBodyPath)
            {
                watchedBodyPath = base;   // new selection: arm, don't reload
                watchedBodyMtime = t;
            }
            else if (t != watchedBodyMtime)
            {
                watchedBodyMtime = t;
                juce::MemoryBlock raw;
                if (f.loadFileAsData (raw) && raw.getSize() == 240
                    && dspBridge.loadCartridgeBytes (raw))
                {
                    currentBodyBytes = raw;
                    rosterBodyBytes = currentBodyBytes;
                    controlSmoothersPrimed = false;
                    lastLoadOk.store (true, std::memory_order_release);
                    juce::Logger::writeToLog ("body hot-reload <- " + f.getFullPathName());
                }
            }
        }
        else if (watchedBodyPath.isNotEmpty())
            watchedBodyPath.clear();
    }
#ifndef TRENCH_PLAYER_DIAGNOSTICS
    return;
#else
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
    lastLoadOk.store (false, std::memory_order_release);
    const int loadedIndex = loadedBodyIndex.load (std::memory_order_relaxed);
    const bool ok = dspBridge.loadCartridge (json);
    storeLoadedBodyBehavior (loadedIndex, json);
    lastLoadOk.store (ok, std::memory_order_release);
    captureCurrentBodyBytes (json);
    controlSmoothersPrimed = false;
#endif
}
bool PluginProcessor::hasEditor() const { return true; }
juce::AudioProcessorEditor* PluginProcessor::createEditor()
{
    return new PluginEditor (*this);
}
void PluginProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    auto state = apvts.copyState();
    // BODY travels by stable id, never by index alone: the roster appends the
    // user's bodies folder, so slot N names a different filter on another
    // machine or after any roster edit.
    state.setProperty ("bodyId",
                       trench::bodyBaseForIndex (
                           juce::roundToInt (apvts.getRawParameterValue (ParamID::body)->load())),
                       nullptr);
#ifdef TRENCH_PLAYER_EXTRAS
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
        const auto bodyId = tree.getProperty ("bodyId").toString();
#ifdef TRENCH_PLAYER_EXTRAS
        if (tree.hasProperty ("clean_audio_enabled"))
            trench::clean_audio::setEnabled (static_cast<bool> (tree.getProperty ("clean_audio_enabled")));
#endif
        apvts.replaceState (std::move (tree));
        if (bodyId.isNotEmpty())
        {
            int index = trench::bodyIndexForBase (bodyId);
            if (index < 0)
            {
                trench::rescanBodyRoster();     // the saved body may be a user file
                index = trench::bodyIndexForBase (bodyId);
            }
            // A body this machine does not have lands on NO FILTER - never on
            // whatever else happens to occupy the saved index.
            setParameterDenormalized (ParamID::body,
                                      (float) (index >= 0 ? index : trench::kNoFilterIndex));
        }
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
    setParameterDenormalized (ParamID::body, (float) trench::kNoFilterIndex);
    setParameterDenormalized (ParamID::inputMode, 0.0f);
    setParameterDenormalized (ParamID::output, 0.0f);
    setParameterDenormalized (ParamID::slamDrive, 0.0f);
    setParameterDenormalized (ParamID::fiveD, 0.0f);
    setParameterDenormalized (ParamID::modOn, 0.0f);
    setParameterDenormalized (ParamID::modDepth, 0.0f);
}
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new PluginProcessor();
}
