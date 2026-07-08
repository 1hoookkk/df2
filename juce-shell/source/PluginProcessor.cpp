#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "TrenchBodyRoster.h"
#include "SmartMotion.h"
#include "parameters/MovePresets.h"
#include "BinaryData.h"

#include <cmath>

namespace
{
constexpr int kCleanInputMode = 0; // None
constexpr int kSpatialOff = 2;

// Motion Warp — reshape the 0..1 morph trajectory. Abuses the morph
// interpolation so the filter dwells on one frame then snaps, or quantises into
// discrete vowel states. Pure on the control value; the engine still clamps.
inline float applyMotionWarp (int warp, float p) noexcept
{
    p = juce::jlimit (0.0f, 1.0f, p);
    switch (warp)
    {
        case 1: return p * p;                                   // Square Up — hangs low, snaps high
        case 2: return 1.0f - (1.0f - p) * (1.0f - p);          // Square Down — hangs high, snaps low
        case 3: return std::round (p * 2.0f) / 2.0f;            // Step 3 — 0 / .5 / 1
        case 4: return std::round (p * 3.0f) / 3.0f;            // Step 4 — 0 / .33 / .66 / 1
        default: return p;                                      // Off — linear
    }
}
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
    if (trench::clean_audio::kEnabled())
        forceCleanAudioUiState();

    const int startIndex = juce::jlimit (0, juce::jmax (0, trench::bodyCount() - 1),
                                         (int) apvts.getRawParameterValue (ParamID::body)->load());
    pendingBodyIndex.store (startIndex, std::memory_order_relaxed);
    loadedBodyIndex.store (startIndex, std::memory_order_relaxed);
    const auto startJson = trench::bodyCartridgeJson (startIndex);
    storeLoadedBodyBehavior (startIndex, startJson);
    juce::MemoryBlock startRaw;
    if (trench::bodyRawBytes (startIndex, startRaw))   // baked raw .body240 (shipping bodies)
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
    apvts.addParameterListener (ParamID::body, this);
    apvts.addParameterListener (ParamID::motionOn, this);
    morphParamForGesture = apvts.getParameter (ParamID::morph);
    slamParamForGesture  = apvts.getParameter (ParamID::slamDrive);
    startTimer (400);

    // Load the Motion pattern blob from state if present (recall path).
    refreshPatternSnapshotFromState();

    // MOVE matrix: seed from factory, then overlay any persisted edits.
    initMoveMatrix();
    loadMoveMatrix();
}

PluginProcessor::~PluginProcessor()
{
    stopTimer();
    apvts.removeParameterListener (ParamID::motionOn, this);
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

int PluginProcessor::getNumPrograms()
{
    int n = 1; trench::movePresets (n); return n;
}

int PluginProcessor::getCurrentProgram() { return currentProgram; }

void PluginProcessor::setCurrentProgram (int index)
{
    int n = 0;
    const auto* presets = trench::movePresets (n);
    if (index < 0 || index >= n)
        return;
    currentProgram = index;
    const auto& p = presets[index];

    setParameterDenormalized (ParamID::body,        (float) p.body);
    setParameterDenormalized (ParamID::moveShape,   (float) p.shape);
    setParameterDenormalized (ParamID::moveTime,    (float) p.time);
    setParameterDenormalized (ParamID::moveMode,    (float) p.mode);
    setParameterDenormalized (ParamID::moveTension, p.tension);
    setParameterDenormalized (ParamID::morph,       p.morph);
    setParameterDenormalized (ParamID::q,           p.q);
    setParameterDenormalized (ParamID::slamDrive,   p.slam);
    setParameterDenormalized (ParamID::output,      p.outputDb);
    setParameterDenormalized (ParamID::moveOn,      p.moveOn ? 1.0f : 0.0f);
    applyModulationBehavior ((trench::TypeBehavior) p.modulation, p.body);
}

const juce::String PluginProcessor::getProgramName (int index)
{
    int n = 0;
    const auto* presets = trench::movePresets (n);
    if (index < 0 || index >= n)
        return {};
    return presets[index].name;
}

void PluginProcessor::changeProgramName (int index, const juce::String& newName)
{
    juce::ignoreUnused (index, newName);   // factory presets are read-only
}

// ── MOVE routing matrix store ─────────────────────────────────────────────────
void PluginProcessor::initMoveMatrix() noexcept
{
    for (int g = 0; g < trench::kNumGestures; ++g)
    {
        const auto fm = trench::factoryMatrix (g);
        for (int s = 0; s < trench::kNumSources; ++s)
            for (int t = 0; t < trench::kNumTargets; ++t)
                moveMatrix[g][s * trench::kNumTargets + t].store (fm.get (s, t), std::memory_order_relaxed);
    }
}

float PluginProcessor::moveMatrixCell (int gesture, int src, int tgt) const noexcept
{
    if (gesture < 0 || gesture >= trench::kNumGestures) return 0.0f;
    const int cell = (src & 3) * trench::kNumTargets + (tgt & 3);
    return moveMatrix[gesture][cell].load (std::memory_order_relaxed);
}

void PluginProcessor::setMoveMatrixCell (int gesture, int src, int tgt, float value) noexcept
{
    if (gesture < 0 || gesture >= trench::kNumGestures) return;
    const int cell = (src & 3) * trench::kNumTargets + (tgt & 3);
    moveMatrix[gesture][cell].store (juce::jlimit (0.0f, 1.0f, value), std::memory_order_relaxed);
    persistMoveMatrix();
}

void PluginProcessor::restoreMoveMatrix (int gesture) noexcept
{
    if (gesture < 0 || gesture >= trench::kNumGestures) return;
    const auto fm = trench::factoryMatrix (gesture);
    for (int s = 0; s < trench::kNumSources; ++s)
        for (int t = 0; t < trench::kNumTargets; ++t)
            moveMatrix[gesture][s * trench::kNumTargets + t].store (fm.get (s, t), std::memory_order_relaxed);
    persistMoveMatrix();
}

void PluginProcessor::persistMoveMatrix()
{
    // Serialise 7x16 floats as a comma list onto apvts.state (recalled with the project).
    juce::String blob;
    blob.preallocateBytes (7 * 16 * 6);
    for (int g = 0; g < trench::kNumGestures; ++g)
        for (int c = 0; c < trench::kNumSources * trench::kNumTargets; ++c)
            blob << juce::String (moveMatrix[g][c].load (std::memory_order_relaxed), 3) << ",";
    apvts.state.setProperty ("moveMatrix", blob, nullptr);
}

void PluginProcessor::loadMoveMatrix()
{
    const auto v = apvts.state.getProperty ("moveMatrix");
    if (! v.isString()) return;
    auto toks = juce::StringArray::fromTokens (v.toString(), ",", "");
    toks.removeEmptyStrings();
    const int expected = trench::kNumGestures * trench::kNumSources * trench::kNumTargets;
    if (toks.size() < expected) return;       // malformed/old state -> keep factory
    int i = 0;
    for (int g = 0; g < trench::kNumGestures; ++g)
        for (int c = 0; c < trench::kNumSources * trench::kNumTargets; ++c)
            moveMatrix[g][c].store (juce::jlimit (0.0f, 1.0f, toks[i++].getFloatValue()),
                                    std::memory_order_relaxed);
}

float PluginProcessor::mapMorphForLoadedBody (float morph) const noexcept
{
    return trench::applyMorphTaper (
        static_cast<trench::MorphTaper> (loadedMorphTaper.load (std::memory_order_relaxed)),
        morph);
}

float PluginProcessor::mapSecondaryForLoadedBody (float q) const noexcept
{
    // Secondary is the packed body axis. Input drive must not secretly ride the
    // lower wheel; it belongs to an explicit hidden/advanced control path.
    return juce::jlimit (0.0f, 1.0f, q);
}

trench::MotionPattern PluginProcessor::getMotionPattern() const
{
    const juce::SpinLock::ScopedLockType sl (patternLock);
    return patternSnapshot;
}

void PluginProcessor::setMotionPattern (const trench::MotionPattern& p)
{
    {
        const juce::SpinLock::ScopedLockType sl (patternLock);
        patternSnapshot = p;
    }
    // Mirror onto state so host recall + UI agree. String params are cheap to
    // write; this is only called on drag-end from the UI, never per-block.
    apvts.state.setProperty ("motionPattern", trench::encodeMotionPattern (p), nullptr);
}

void PluginProcessor::refreshPatternSnapshotFromState()
{
    const auto blob = apvts.state.getProperty ("motionPattern").toString();
    const auto p = trench::decodeMotionPattern (blob);
    const juce::SpinLock::ScopedLockType sl (patternLock);
    patternSnapshot = p;
}

PluginProcessor::ModulatedControls PluginProcessor::applyMotion (float morph, float q, float drive, float inputEnv, int numSamples) noexcept
{
    const bool on = apvts.getRawParameterValue (ParamID::motionOn)->load() > 0.5f;
    if (! on)
        return { morph, q, drive };

    if (motionResetRequested.exchange (false, std::memory_order_acq_rel))
    {
        motionEngine.resetPlaybackPosition();
        motionStepForUi.store (0, std::memory_order_relaxed);
    }

    // SMART MOTION: the Modulation button plays a curated, per-body motion identity
    // (the engine's default pattern is empty, which is why the button used to do
    // nothing). Recompute only when the body changes — audio-thread only, no lock.
    const int bodyIdx = loadedBodyIndex.load (std::memory_order_relaxed);
    const auto typeBehavior = getModulationBehaviorForUi();
    if (bodyIdx != cachedSmartIndex || (int) typeBehavior != cachedSmartBehavior)
    {
        cachedSmart      = trench::smartMotionFor (bodyIdx, typeBehavior);
        cachedSmartIndex = bodyIdx;
        cachedSmartBehavior = (int) typeBehavior;
    }

    const bool   bpmSync   = apvts.getRawParameterValue (ParamID::motionBpm)->load() > 0.5f;
    const float  rateHz    = apvts.getRawParameterValue (ParamID::motionRate)->load();
    const int    sync      = (int) apvts.getRawParameterValue (ParamID::motionSync)->load();
    // TIME: the live division selector (1/4..1/32), seeded from the tile's
    // curated default on arm (applyModulationBehavior) but user-adjustable
    // from there — the same "seed on arm, then live" pattern Depth uses.
    const int    divIdx    = (int) apvts.getRawParameterValue (ParamID::motionDiv)->load();
    const bool   smooth    = cachedSmart.smooth;       // glide vs stepped
    const int    direction = cachedSmart.direction;    // Fwd / Pendulum / ...
    const int    length    = cachedSmart.length;
    // DEPTH is the public depth lever (the renamed/repurposed AMOUNT fader):
    // it scales the curated Morph/Q sweep from still (0) to full (1), and
    // simultaneously scales the honest-dose filter blend (see processBlock).
    // amount=0 is a true null even while armed.
    const float  amount    = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::amount)->load());
    const float  mDepth    = cachedSmart.morphDepth * amount;
    const float  qDepth    = cachedSmart.qDepth     * amount;
    // Morph/Q only. Drive/SLAM stays an explicit control path outside Motion.
    constexpr bool accToDrv = false;
    constexpr float drvDepth = 0.0f;

    // The curated per-body pattern (values drive Morph, gates pulse Q).
    const trench::MotionPattern& pat = cachedSmart.pattern;

    if (typeBehavior == trench::TypeBehavior::Dynamic)
    {
        const float react = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::motionReact)->load());
        const float push = juce::jlimit (0.0f, 1.0f, inputEnv * juce::jmax (amount, react));
        motionStepForUi.store ((int) std::round (push * 15.0f), std::memory_order_relaxed);
        return {
            juce::jlimit (0.0f, 1.0f, morph + push * cachedSmart.morphDepth),
            juce::jlimit (0.0f, 1.0f, q     + push * cachedSmart.qDepth),
            drive
        };
    }

    // Read host tempo + transport state once per block.
    double bpm = 0.0;
    bool transportPlaying = false;
    if (auto* ph = getPlayHead())
    {
        if (auto pos = ph->getPosition())
        {
            if (auto b = pos->getBpm()) bpm = *b;
            transportPlaying = pos->getIsPlaying();
        }
    }

    if ((typeBehavior == trench::TypeBehavior::AutoQuarter
         || typeBehavior == trench::TypeBehavior::AutoHalf
         || typeBehavior == trench::TypeBehavior::Wobble)
        && ! transportPlaying)
    {
        motionStepForUi.store (0, std::memory_order_relaxed);
        return { morph, q, drive };
    }

    const auto r = motionEngine.apply (on, bpmSync, rateHz, divIdx, sync, smooth,
                                       direction, length, mDepth, qDepth,
                                       accToDrv, drvDepth,
                                       pat.values.data(), pat.triggers.data(),
                                       bpm, transportPlaying,
                                       morph, q, drive, numSamples);
    motionStepForUi.store (motionEngine.getCurrentStepForUi(), std::memory_order_relaxed);

    float outMorph = r.morph;
    float outQ     = r.q;

    // Block-rate "abuse" cluster. Guarded so an armed-but-idle Motion (amount 0,
    // react 0) still returns the engine's centre untouched — the null contract.
    const float react = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::motionReact)->load());
    if (amount > 0.0005f || react > 0.0005f)
    {
        // Morph<->Q cross-modulation: each axis's offset bleeds into the other,
        // forming a coupled loop inside the modulation path.
        const float cross = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::motionCross)->load());
        if (cross > 0.0005f)
        {
            const float mOff = outMorph - morph;
            const float qOff = outQ - q;
            outMorph = juce::jlimit (0.0f, 1.0f, outMorph + qOff * cross);
            outQ     = juce::jlimit (0.0f, 1.0f, outQ     + mOff * cross);
        }

        // Warp the morph trajectory (square-law / quantise).
        outMorph = applyMotionWarp ((int) apvts.getRawParameterValue (ParamID::motionWarp)->load(), outMorph);

        // Self-modulation: the input's own level pushes resonance.
        if (react > 0.0005f)
            outQ = juce::jlimit (0.0f, 1.0f, outQ + inputEnv * react);
    }

    return { outMorph, outQ, r.drive };
}

void PluginProcessor::storeLoadedBodyBehavior (int bodyIndex, const juce::String& cartridgeJson)
{
    const auto behavior = trench::bodyBehaviorFromCartridgeJson (bodyIndex, cartridgeJson);
    loadedSecondaryTarget.store (static_cast<int> (behavior.secondaryTarget), std::memory_order_relaxed);
    loadedMorphTaper.store (static_cast<int> (behavior.morphTaper), std::memory_order_relaxed);
}

trench::TypeBehavior PluginProcessor::getModulationBehaviorForUi() const noexcept
{
    const bool on = apvts.getRawParameterValue (ParamID::motionOn)->load() > 0.5f;
    if (! on)
        return trench::TypeBehavior::Static;

    const int tile = (int) apvts.getRawParameterValue (ParamID::motionTile)->load();
    switch (juce::jlimit (0, 3, tile))
    {
        case 0: return trench::TypeBehavior::AutoHalf;    // Riser
        case 1: return trench::TypeBehavior::AutoQuarter; // Breathe
        case 2: return trench::TypeBehavior::Dynamic;     // Adlib Chop
        default: return trench::TypeBehavior::Wobble;     // Wobble
    }
}

// Called when the MOTION selector picks a tile. Arms Motion with that tile
// for the given body. `behavior` is derived by the caller from the tile
// index via getModulationBehaviorForUi's mapping.
void PluginProcessor::applyModulationBehavior (trench::TypeBehavior behavior, int bodyIndex)
{
    setParameterDenormalized (ParamID::moveOn, 0.0f);
    setParameterDenormalized (ParamID::moveTension, 0.0f);
    setParameterDenormalized (ParamID::motionWarp, 0.0f);
    setParameterDenormalized (ParamID::motionCross, 0.0f);
    setParameterDenormalized (ParamID::motionBpm, 1.0f);
    setParameterDenormalized (ParamID::motionSync, 0.0f); // predictable play-start reset.

    if (behavior == trench::TypeBehavior::Static)
    {
        setParameterDenormalized (ParamID::motionOn, 0.0f);
        return;
    }

    setParameterDenormalized (ParamID::motionOn, 1.0f);
    // DEPTH (ParamID::amount) is a live, user-owned fader now — arming a
    // tile must not stomp it. React is still an internal constant (not
    // exposed as a control per the current design: MOTION/TIME/DEPTH only).
    setParameterDenormalized (ParamID::motionReact,
                              behavior == trench::TypeBehavior::Dynamic ? 0.85f : 0.0f);
    // TIME: seed the live division from this tile's curated default, then
    // it's user-adjustable from there (same seed-on-arm-then-live pattern).
    const auto seeded = trench::smartMotionFor (bodyIndex, behavior);
    setParameterDenormalized (ParamID::motionDiv, (float) seeded.divIdx);
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
    motionEngine.prepare (sampleRate);
    gestureEngine.prepare (sampleRate);
    outputGain.reset (sampleRate, 0.02); // 20 ms ramp
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

    if (! lastLoadOk.load (std::memory_order_acquire))
    {
        buffer.clear();
        return;
    }

    // DEMO MODE: only when explicitly armed (off by default) -> synthesize a groove so
    // the standalone can be shown off with nothing plugged in. Hosted plugin: never.
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

    // Dry (pre-filter) source for the Take-tray waveform previews.
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

    // Block-rate input envelope for Motion React: peak of the dry input (the
    // buffer still holds input here, pre-filter), fast attack / slow release.
    float inPeak = 0.0f;
    for (int ch = 0; ch < juce::jmin (2, buffer.getNumChannels()); ++ch)
    {
        const auto* d = buffer.getReadPointer (ch);
        for (int i = 0; i < buffer.getNumSamples(); ++i)
            inPeak = juce::jmax (inPeak, std::abs (d[i]));
    }
    inPeak = juce::jlimit (0.0f, 1.0f, inPeak);
    // TIME-based attack/release (was per-block fractions, so the follower's feel
    // changed with the host buffer size — jittery at FL's small blocks). 4 ms
    // attack rides transients; 140 ms release breathes musically at any buffer.
    const float envAtk = (float) (1.0 - std::exp (-blockSeconds / 0.004));
    const float envRel = (float) (1.0 - std::exp (-blockSeconds / 0.140));
    motionInputEnv += (inPeak - motionInputEnv) * (inPeak > motionInputEnv ? envAtk : envRel);

    // Motion offsets around the smoothed host center. Null contract: motionOn
    // false or all depths ~0 returns the inputs unchanged.
    auto mod = applyMotion (smoothedMorph,
                            smoothedQ,
                            apvts.getRawParameterValue (ParamID::slamDrive)->load(),
                            motionInputEnv,
                            buffer.getNumSamples());

    // MOVE (Page 2): visible surface is MOVE + TIME. In FREE, MOVE directly performs
    // the selected body gesture. In synced times, the hidden engine loops that gesture.
    // Processor-owned, so it runs with the editor closed and in an offline bounce.
    {
        const float moveAmount = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::moveTension)->load());
        const int   shapeIdx = juce::jlimit (0, trench::kNumGestures - 1,
                                             (int) apvts.getRawParameterValue (ParamID::moveShape)->load());
        const int   timeIdx  = juce::jlimit (0, trench::kNumGestureTimes - 1,
                                             (int) apvts.getRawParameterValue (ParamID::moveTime)->load());
        const bool  freeTime = trench::gestureTimeIsFree (timeIdx);
        const float slamBase = apvts.getRawParameterValue (ParamID::slamDrive)->load();

        // Transport + time signature: cycle length must honour BPM AND the meter, so a
        // "1 BAR" gesture is a real bar at 3/4 or 7/8, not a hardcoded 4 beats.
        double bpm = 120.0, ppq = -1.0; bool playing = false;
        double qnPerBar = 4.0;   // quarter-notes per bar
        if (auto* ph = getPlayHead())
            if (auto pos = ph->getPosition())
            {
                if (auto b = pos->getBpm()) bpm = *b;
                if (auto p = pos->getPpqPosition()) ppq = *p;
                playing = pos->getIsPlaying();
                if (auto ts = pos->getTimeSignature())
                    qnPerBar = trench::quarterNotesPerBar (ts->numerator, ts->denominator);
            }
        const double cycleBeats = trench::gestureCycleQuarterNotes (timeIdx, qnPerBar); // in quarter notes

        const bool moveActive = freeTime ? (moveAmount > 0.0005f) : true;
        if (moveActive && ! lastMoveOn)
            gestureEngine.reset();
        lastMoveOn = moveActive;
        lastMovePlaying = playing;

        if (moveActive)
        {
            trench::MoveMatrix mtx;
            for (int s = 0; s < trench::kNumSources; ++s)
                for (int t = 0; t < trench::kNumTargets; ++t)
                    mtx.w[s][t] = moveMatrix[shapeIdx][s * trench::kNumTargets + t].load (std::memory_order_relaxed);

            trench::MoveContext ctx;             // routeMaster stays 1.0 (matrix is heard in full; no route_* params in V1)
            ctx.driftAmt    = apvts.getRawParameterValue (ParamID::moveDrift)->load();
            ctx.swing       = apvts.getRawParameterValue (ParamID::moveSwing)->load();
            ctx.phaseOffset = apvts.getRawParameterValue (ParamID::movePhase)->load();

            const auto gest = freeTime
                ? trench::evaluateLanes ((trench::Gesture) shapeIdx, moveAmount, moveAmount,
                                         smoothedMorph, smoothedQ, slamBase, 0.0f, mtx, {}, ctx)
                : gestureEngine.advanceLanes (
                    (trench::Gesture) shapeIdx, moveAmount, cycleBeats,
                    smoothedMorph, smoothedQ, slamBase, 0.0f,
                    mtx, trench::MoveMode::Loop, bpm, ppq, playing,
                    buffer.getNumSamples(), qnPerBar, ctx);
            mod.morph = gest.morph; mod.q = gest.press; mod.drive = gest.slam; mod.guard = gest.guard;
            movePhaseForUi.store (freeTime ? moveAmount : gestureEngine.uiPhase(), std::memory_order_relaxed);
            moveArmedWaitingForUi.store (false, std::memory_order_relaxed);
        }
        else
        {
            movePhaseForUi.store (moveAmount, std::memory_order_relaxed);
            moveArmedWaitingForUi.store (false, std::memory_order_relaxed);
        }
    }
    moveGuardForUi.store (mod.guard, std::memory_order_relaxed);
    moveSlamForUi.store (mod.drive, std::memory_order_relaxed);

    effectiveMorphForUi.store (mod.morph, std::memory_order_relaxed);
    effectiveQForUi.store (mod.q, std::memory_order_relaxed);
    morphModulatedForUi.store (std::abs (mod.morph - smoothedMorph) > 0.0005f,
                               std::memory_order_relaxed);
    qModulatedForUi.store (std::abs (mod.q - smoothedQ) > 0.0005f,
                           std::memory_order_relaxed);

    params.morph = mapMorphForLoadedBody (mod.morph);
    params.q     = mapSecondaryForLoadedBody (mod.q);

    // SLAM is output-only, applied in the DSP bridge after the body. The engine's
    // own Rust input stage stays CLEAN (None), so SLAM cannot change filter excitation.
    params.slamDrive = mod.drive;
    params.bite = 0.0f;   // BITE RESERVED in V1 — lane is computed (mod.bite) but not applied to audio
    if (kCleanInputMode != lastInputModeSent)
    {
        dspBridge.setInputMode (kCleanInputMode);
        lastInputModeSent = kCleanInputMode;
    }

    // Continuous QSound depth (SPACE). 0 = hard bypass (spatial stage Off).
    // When Motion is armed and 5D's own base is nonzero, Space rides the
    // same morph/Q offset Motion is already producing on this block — the
    // offset magnitude (mod.morph - smoothedMorph, mod.q - smoothedQ) is a
    // direct measure of "how much motion is happening right now" that both
    // the Dynamic (envelope-follower) and Auto*/Wobble (tempo-synced) paths
    // already populate, so no new plumbing is needed to read it. This reads
    // the fiveD parameter but never writes it — the base value stays exactly
    // what the user/preset set; only the per-block effective value sent to
    // the DSP is offset.
    const float fiveDBase = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::fiveD)->load());
    float space = fiveDBase;
    if (fiveDBase > 0.001f && apvts.getRawParameterValue (ParamID::motionOn)->load() > 0.5f)
    {
        const float offset = std::abs (mod.morph - smoothedMorph) + std::abs (mod.q - smoothedQ);
        space = juce::jlimit (0.0f, 1.0f, fiveDBase + offset);
    }
    params.fiveD = space;
    lastSpaceSent.store (space, std::memory_order_relaxed);
    dspBridge.setSpatialMode (space > 0.001f ? 0 /*QSound*/ : kSpatialOff);

    // Voicing-rig pan pose (the dev rig writes it; the shipping UI never does).
    const float pan = rigPan.load (std::memory_order_relaxed);
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

    // AMOUNT — honest dose. A coefficient-domain blend toward identity inside
    // the engine (see trench-core FilterEngine::set_amount), not a post-filter
    // audio crossfade — so the on-screen curve (read from the same cascade
    // coefficients) moves with it. Ramped the same way morph/q already are,
    // via Cascade's own per-block coefficient ramp — no separate JUCE-side
    // smoothing needed.
    params.amount = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::amount)->load());

    if (! trench::bodyIsNoFilter (loadedBodyIndex.load (std::memory_order_relaxed)))
        fixedRateIsland.process (buffer, dspBridge, params);

    // GUARD — MOVE output safety/compensation. The gesture's GUARD lane ducks the wet
    // output (up to kGuardMaxDb) at the gesture's peak so a build/suck/pulse cannot throw
    // a huge level jump on a track or master. mod.guard is already lane-smoothed (no zipper).
    constexpr float kGuardMaxDb = 5.0f;
    const float guardGain = juce::Decibels::decibelsToGain (-kGuardMaxDb * juce::jlimit (0.0f, 1.0f, mod.guard));
    if (guardGain < 0.999f)
        buffer.applyGain (guardGain);

    const float outDb = apvts.getRawParameterValue (ParamID::output)->load();
    outputGain.setTargetValue (juce::Decibels::decibelsToGain (outDb));
    outputGain.applyGain (buffer, buffer.getNumSamples());

    // The ONLY place the engine's coefficients are read: publish them into the
    // lock-free UI snapshot from the audio thread. The editor reads the snapshot,
    // never the live engine, so the message/VBlank thread cannot race the audio
    // thread's exclusive access to the Rust engine.
    dspBridge.publishUiSnapshot();

    // Host tempo for bar-range captures (0 if the host exposes none).
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

        // Edison capture: record the FINAL wet output (the same post-everything tap as the
        // scope) into the rolling buffer for captureTake(). FROZEN while Page 2 is open so
        // auditioning a seeded variant never records over the captured source moment.
        if (! captureFrozen.load (std::memory_order_relaxed))
            captureRing.write (postL, postR, buffer.getNumSamples());
    }

    // Smart-take gesture tracking. Detect Morph/Slam movement (normalised 0..1) and
    // remember where the current gesture burst started + when it last moved, so the
    // Take page can size a window around "the moment I just heard". Lock-free.
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
            const double idleGapFrames = 0.4 * sampleRate; // a new burst after 0.4s still
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

    // A simple looping bass groove + hats — broadband enough that the filter sweep is
    // obvious by ear and the take waveforms have real shape. ~120 BPM, 16th notes.
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

//==============================================================================
void PluginProcessor::parameterChanged (const juce::String& parameterID, float newValue)
{
    if (parameterID == ParamID::body)
    {
        const int raw = juce::roundToInt (newValue);
        pendingBodyIndex.store (trench::bodyIsNoFilter (raw) ? trench::kNoFilterIndex
                                                             : trench::wrapBodyIndex (raw),
                                std::memory_order_relaxed);
        triggerAsyncUpdate();
    }
    else if (parameterID == ParamID::motionOn && newValue > 0.5f)
    {
        motionResetRequested.store (true, std::memory_order_release);
    }
}

void PluginProcessor::handleAsyncUpdate()
{
    const int want = pendingBodyIndex.load (std::memory_order_relaxed);
    if (want == loadedBodyIndex.load (std::memory_order_relaxed))
        return;

    lastLoadOk.store (false, std::memory_order_release);

    if (trench::bodyIsNoFilter (want))   // No Filter = true bypass: load nothing; processBlock passes through
    {
        currentBodyBytes.setSize (0);
        rosterBodyBytes.setSize (0);
        lastLoadOk.store (true, std::memory_order_release);
        controlSmoothersPrimed = false;
        loadedBodyIndex.store (want, std::memory_order_relaxed);
        juce::Logger::writeToLog ("body switch -> No Filter (bypass)");
        return;
    }

    juce::MemoryBlock raw;
    juce::String json;
    bool ok;
    if (trench::bodyRawBytes (want, raw))
    {
        // Raw .body240 library file: load the 240 bytes straight through the runtime
        // body loader (same path as a JSON cartridge), and use them as the anchor body.
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
    if (trench::bodyIsAudition (want))
        auditionSlotMtime = trench::auditionSlotFile().getLastModificationTime();

    juce::Logger::writeToLog (juce::String ("body switch -> ")
                               + trench::bodyDisplayName (want)
                               + (ok ? " ok" : " FAIL"));
}

void PluginProcessor::captureCurrentBodyBytes (const juce::String& cartridgeJson)
{
    if (cartridgeJson.isEmpty() || ! TrenchDspBridge::bodyBytesFromJson (cartridgeJson, currentBodyBytes))
        currentBodyBytes.setSize (0);

    // This is only ever called with a genuine roster/audition cartridge (body load),
    // never with a seeded sibling — so it doubles as the fixed anchor the Variant
    // bank re-seeds from. Seeding/installing a variant mutates currentBodyBytes only.
    rosterBodyBytes = currentBodyBytes;
}

void PluginProcessor::seedCurrentBody()
{
    // Seed from the body that is actually playing (may already be a sibling); fall
    // back to the roster base if we do not have live bytes yet.
    if (currentBodyBytes.getSize() != 240)
        captureCurrentBodyBytes (trench::bodyCartridgeJson (loadedBodyIndex.load (std::memory_order_relaxed)));
    if (currentBodyBytes.getSize() != 240)
        return;

    juce::MemoryBlock sibling;
    if (dspBridge.seedSiblingFromBytes (currentBodyBytes.getData(), currentBodyBytes.getSize(),
                                        ++seedCounter, 1.0, sibling))
    {
        currentBodyBytes = std::move (sibling);
        lastLoadOk.store (true, std::memory_order_release);
        juce::Logger::writeToLog ("SEED -> sibling auditioned");
    }
    else
    {
        juce::Logger::writeToLog ("SEED -> no legal sibling within budget (try again)");
    }
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
        rosterBodyBytes = currentBodyBytes;   // anchor seeds to the forged body too
        juce::Logger::writeToLog ("FORGE -> typed body compiled + auditioned");
    }
}

juce::File PluginProcessor::forgeSaveBody (const juce::String& name)
{
    if (currentBodyBytes.getSize() != 240)
        return {};
    auto dir = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                   .getChildFile ("TRENCH").getChildFile ("bodies");
    dir.createDirectory();
    auto base = name.retainCharacters ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ")
                    .trim().replaceCharacter (' ', '_');
    if (base.isEmpty())
        base = "forge";
    auto f = dir.getChildFile (base + ".body240");
    for (int i = 1; f.existsAsFile() && i < 10000; ++i)
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
        return false; // nothing fed in yet

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
    trench_engine_set_input_mode (pe, 0 /*None*/);
    trench_engine_set_agc_enabled (pe, 1);
    trench_engine_set_saturation_enabled (pe, 1);
    trench_engine_set_agc_drive (pe, 1.0f);                           // hardware-faithful identity pre-scale (matches live path)
    trench_engine_set_spatial_mode (pe, qsound ? 0 /*QSound*/ : 2 /*Off*/);
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

    // THE ORIGINAL: the body loaded via TYPE (the fixed roster reference). Every slot is
    // a version of THIS, so rerolling always explores the original, never the selection.
    juce::MemoryBlock original = rosterBodyBytes;
    if (original.getSize() != 240)
        TrenchDspBridge::bodyBytesFromJson (
            trench::bodyCartridgeJson (loadedBodyIndex.load (std::memory_order_relaxed)), original);
    if (original.getSize() != 240)
        return out;

    // Render `body` through the dry source at this recipe, fill the crude waveform.
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
        // Character: high-frequency content (mean |Δ| / mean |x|) -> bright vs dark.
        vp.bright = sumAbs > 1.0e-6 ? juce::jlimit (0.0f, 1.0f, (float) (sumDiff / sumAbs)) : 0.0f;
        vp.valid = true;
        return true;
    };

    // Slot 0 = AS HEARD: the original at the wheel position you just played.
    {
        VariantPreview recipe; recipe.morph = morph; recipe.q = q; recipe.slam = slam;
        recipe.axis = AxisFamily;
        VariantPreview vp;
        if (buildSlot (static_cast<const unsigned char*> (original.getData()), recipe, true, vp))
            out.push_back (vp);
    }

    // Real "filter family" bodies from the physical/vowel tables (baked cartridges).
    // The AxisFamily slots pull these so some variants carry genuine vowel/tube
    // character instead of just a seeded sibling of the original.
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

    // Slots 1..n-1 = recipe variants, each EMPHASISING one effect (cycling Morph / Q /
    // QSound / Slam / family) so the tray reads in colour. Family slots use a real table
    // body; the rest seed a sibling of the original and push one axis.
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
        return {}; // nothing recorded yet

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
    constexpr double recentWindowSec = 8.0; // gesture must have ended within this
    constexpr double prerollSec = 0.15;

    const juce::uint64 cur      = processedFrames.load (std::memory_order_relaxed);
    const juce::uint64 lastMove = lastMoveFrame.load (std::memory_order_relaxed);
    const juce::uint64 anchor   = gestureAnchorFrame.load (std::memory_order_relaxed);

    // No gesture, or the last move is stale -> a simple fallback window to "now".
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
    // Always (message thread): release the body the audio thread retired after a
    // swap, so a body switch's old cartridge memory is freed promptly.
    dspBridge.reclaim();

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

    // Load the recalled Motion pattern into the audio-thread snapshot.
    refreshPatternSnapshotFromState();
    // Restore any recalled MOVE matrix edits (keeps factory if absent).
    loadMoveMatrix();
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
    setParameterDenormalized (ParamID::body, (float) trench::kNoFilterIndex);   // clean = No Filter (bypass)
    setParameterDenormalized (ParamID::inputMode, 0.0f);
    setParameterDenormalized (ParamID::output, 0.0f);
    setParameterDenormalized (ParamID::slamDrive, 0.0f);   // clean; bodies are already at level (faithful AGC)
    setParameterDenormalized (ParamID::fiveD, 0.0f);
    // Motion defaults to off so a clean-audio restore cannot drag in motion.
    setParameterDenormalized (ParamID::motionOn, 0.0f);
    setParameterDenormalized (ParamID::motionMorphDepth, 0.0f);
    setParameterDenormalized (ParamID::motionQDepth, 0.0f);
    setParameterDenormalized (ParamID::motionAccentToDrive, 0.0f);
    setParameterDenormalized (ParamID::moveOn, 0.0f);
    setParameterDenormalized (ParamID::moveTension, 0.0f);
    setParameterDenormalized (ParamID::moveTime, 0.0f);
#ifdef TRENCH_PLAYER_EXTRAS
    setParameterDenormalized (ParamID::teleportMode, 0.0f);
    setParameterDenormalized (ParamID::teleportAmount, 0.0f);
#endif
}

//==============================================================================
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new PluginProcessor();
}
