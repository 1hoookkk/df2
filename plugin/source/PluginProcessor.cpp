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
    // HD is a SOUND choice (Tyson): 78125 clean vs 39062.5 vintage island rate.
    const bool hd = apvts.getRawParameterValue (ParamID::hdMode)->load() > 0.5f;
    hdModeApplied = hd;
    fixedRateIsland.prepare (sampleRate, samplesPerBlock, dspBridge,
                             hd ? TrenchRates::emuInternalRateHd : TrenchRates::emuInternalRate);
    setLatencySamples (fixedRateIsland.getLatencySamples());
    dspBridge.setInputMode (kCleanInputMode);
    dspBridge.setSpatialMode (kSpatialOff);
    dspBridge.setQSoundFallbackPan (1.0f);
    morphMod.prepare (sampleRate);
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
        params.poleDistortion = 0.0f;
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
        juce::jlimit (0, trench::kNumBaseShapes + trench::kNumFuncGenPatterns - 1,
                      (int) apvts.getRawParameterValue (ParamID::modShape)->load()),
        true,   // host-locked only: FREE mode buried 2026-07-27
        (int) apvts.getRawParameterValue (ParamID::modNote)->load(),
        (trench::ModFeel) juce::jlimit (0, 2, (int) apvts.getRawParameterValue (ParamID::modFeel)->load()),
        0.0f,
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
    // CHEW law (2026-07-26): RESONANCE carries the chew, not SLAM.
    // E-MU precedent: BassOMatic 12 REZ drives the filter into distortion at max Q,
    // and the Mackie desk slam happened OUTSIDE the machine, after deliberately
    // clean outputs - so SLAM driving internal character was backwards twice over.
    //
    // Interstage clipping fires when the signal inside the cascade runs hot, and
    // what makes it hot is resonance - a high-Q section builds a peak that slams
    // the next stage. That is how real analog filters snarl. SLAM sits AFTER the
    // cascade and has no causal relationship to what happens inside it, so
    // driving bite from SLAM welded internal character to output level: no grit
    // at low output, no clean at high output.
    //
    // Quadratic: low Q adds nothing, full Q lands 55%. The old 0.22 ceiling was
    // ear-tuned for the INTERSTAGE SATURATOR; under pole-radius distortion the
    // offline sweep puts 0.22 at the bottom of the range (+21% RMS) and the useful
    // span running to ~0.6 (+87%) before it saturates.
    // full Q lands the same tasteful ~22%. Q here is the MODULATED value, so a
    // resonance sweep is a character gesture, not just a shape change.
    // CHEW now drives the AUTHENTIC E-MU mechanism: dynamic pole radius per section
    // (US 10,514,883), not the interstage saturator. E-MU deliberately used a 67-bit
    // accumulator so spikes pass BETWEEN sections unclipped - the nonlinearity lives
    // in the pole math, which is why the resonance blooms and wanders instead of
    // merely getting dirty. The old saturator path stays wired at 0 for A/B.
    const float qForChew = juce::jlimit (0.0f, 1.0f, modResult.q);
    // CHEW is Q's law, never a separate decision: the only dial is Q.
    const float chewAmount = juce::jlimit (0.0f, 1.0f, 0.55f * qForChew * qForChew);
    // CHEW is the FILTER destabilising itself, so it needs poles and is correctly
    // silent at No Filter. It is NOT a general distortion: E-MU kept the internal
    // path pristine (20-bit resampling exists to avoid internal grit) and generated
    // character outside the machine. SLAM is that outside - it owns all grit that
    // is not the filter's own, and works with or without a body loaded.
    params.poleDistortion  = chewAmount;
    params.fiveD = 0.0f;   // fiveD/QSound buried 2026-07-27: no home, no product function
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
        const bool modRunning = apvts.getRawParameterValue (ParamID::modOn)->load() > 0.5f;
        const int noteIdx = (int) apvts.getRawParameterValue (ParamID::modNote)->load();
        params.rampScale = (modRunning && noteIdx > 2) ? kTight : kGlide;
    }
    params.pitchRatio = 1.0f;
    params.keySnap = juce::jlimit (0, 24,
        (int) apvts.getRawParameterValue (ParamID::keySnap)->load());
    punchBlend.captureDry (buffer.getArrayOfReadPointers(), buffer.getNumChannels(), buffer.getNumSamples());
    fixedRateIsland.process (buffer, dspBridge, params);
    // SLAM is part of the WET voice: it runs before the MIX blend so MIX 0
    // returns the untouched signal no matter how hard the desk is driven.
    // The desk stage reports the TRUE limit amount: the fraction of samples
    // pushed past the pressure knee. That (not raw output peak) is the meter.
    float limitFrac = 0.0f;
    if (buffer.getNumChannels() >= 2)
        limitFrac = trench::slamOutputPressureBlockStereo (buffer.getWritePointer (0),
                                                buffer.getWritePointer (1),
                                                buffer.getNumSamples(), params.slamDrive);
    else if (buffer.getNumChannels() == 1)
        limitFrac = trench::slamOutputPressureBlock (buffer.getWritePointer (0),
                                         buffer.getNumSamples(), params.slamDrive);
    punchBlend.blend (buffer.getArrayOfWritePointers(), buffer.getNumChannels(), buffer.getNumSamples(), mixTarget);
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
        // prepareToPlay - re-prepare ourselves, with audio suspended.
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
    // Settings survive a body switch (Tyson 2026-07-27): MORPH, Q, MIX, SLAM
    // and modulation all stay where the hands left them - switching filters
    // changes the FILTER, nothing else.
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
    setParameterDenormalized (ParamID::slamDrive, 0.0f);
    setParameterDenormalized (ParamID::modOn, 0.0f);
    setParameterDenormalized (ParamID::modDepth, 0.0f);
}
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new PluginProcessor();
}
