#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

#include "parameters/TrenchParameters.h"
#include "TrenchBodyRoster.h"
#include "dsp/TrenchDspBridge.h"
#include "dsp/FixedRateTrenchIsland.h"
#include "dsp/TeleportEngine.h"
#include "dsp/MotionEngine.h"
#include "dsp/GestureEngine.h"
#include "SmartMotion.h"
#include "dsp/TrenchCleanBody.h"
#include "dsp/CaptureRing.h"
#include "dsp/CapturePlan.h"
#include "dsp/TakeWriter.h"

#include <array>
#include <atomic>
#include <vector>

class PluginProcessor final : public juce::AudioProcessor,
                              private juce::AudioProcessorValueTreeState::Listener,
                              private juce::AsyncUpdater,
                              private juce::Timer
{
public:
    PluginProcessor();
    ~PluginProcessor() override;

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override;

    const juce::String getName() const override;
    bool acceptsMidi() const override;
    bool producesMidi() const override;
    bool isMidiEffect() const override;
    double getTailLengthSeconds() const override;

    int getNumPrograms() override;
    int getCurrentProgram() override;
    void setCurrentProgram (int index) override;
    const juce::String getProgramName (int index) override;
    void changeProgramName (int index, const juce::String& newName) override;

    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;

    juce::AudioProcessorValueTreeState apvts;
    TrenchDspBridge dspBridge;

    const std::atomic<float>& getInputMeterLeftForUi() const noexcept  { return inputMeterL; }
    const std::atomic<float>& getInputMeterRightForUi() const noexcept { return inputMeterR; }

    // UI vectorscope feed: copies the most recent `count` post-filter stereo
    // samples (oldest -> newest) into the caller's buffers. Lock-free, may tear
    // a frame under contention — fine for a scope. Returns samples written.
    static constexpr int kScopeLen = 512;
    int copyScopeSamples (float* outL, float* outR, int count) const noexcept;

    // Motion pattern access (message-thread safe). The UI edits the pattern
    // via setMotionPattern; the audio thread snapshots it under patternLock.
    trench::MotionPattern getMotionPattern() const;
    void setMotionPattern (const trench::MotionPattern& p);
    int  getMotionStepForUi() const noexcept { return motionStepForUi.load (std::memory_order_relaxed); }

    // USER motion: alt-drag Morph to teach a custom gesture. Message-thread
    // only (called from WheelControl's alt-drag callbacks); the recorded
    // shape lands in the same patternSnapshot/setMotionPattern the audio
    // thread already reads. See MOVE chip's "USER" state.
    void beginUserMotionRecording();
    void addUserMotionSample (float morphValue);
    void endUserMotionRecording();

    // Status readout for the FX pane: which body is loaded and whether the last
    // load (body switch or authoring-slot hot-reload) parsed cleanly.
    int  getLoadedBodyIndex() const noexcept { return loadedBodyIndex.load (std::memory_order_relaxed); }
    bool getLastLoadOk()      const noexcept { return lastLoadOk.load (std::memory_order_relaxed); }
    bool isCleanGroundTruthAudio() const noexcept { return trench::clean_audio::kEnabled(); }
    float mapMorphForLoadedBody (float morph) const noexcept;
    float mapSecondaryForLoadedBody (float q) const noexcept;
    float getEffectiveMorphForUi() const noexcept { return effectiveMorphForUi.load (std::memory_order_relaxed); }
    float getEffectiveQForUi() const noexcept     { return effectiveQForUi.load (std::memory_order_relaxed); }
    bool isMorphModulatedForUi() const noexcept   { return morphModulatedForUi.load (std::memory_order_relaxed); }
    bool isQModulatedForUi() const noexcept       { return qModulatedForUi.load (std::memory_order_relaxed); }
    bool isMoveArmedWaiting() const noexcept      { return moveArmedWaitingForUi.load (std::memory_order_relaxed); }
    float getEffectiveSpaceForUi() const noexcept { return lastSpaceSent.load (std::memory_order_relaxed); }
    float getMoveGuardForUi() const noexcept      { return moveGuardForUi.load (std::memory_order_relaxed); }
    float getMoveSlamForUi() const noexcept       { return moveSlamForUi.load (std::memory_order_relaxed); }
    float getMovePhaseForUi() const noexcept      { return movePhaseForUi.load (std::memory_order_relaxed); }
    trench::TypeBehavior getModulationBehaviorForUi() const noexcept;

    // SEED / EXPORT (message thread; invoked from the TYPE-dropdown action items).
    // seedCurrentBody: spawn a legal, certified SIBLING of the body that is actually
    // playing (may already be a sibling) and audition it live. Returns false if
    // no certified sibling was staged. exportCurrentBody: write the current body's
    // 240 bytes to Documents/TRENCH/exports/.
    bool seedCurrentBody();
    void exportCurrentBody();

    // FORGE (message thread): compile 6 typed cards (42 f64 = 6 x [type, fc_low, fc_high,
    // q_lo, q_hi, gain_db, on]) via the typed compiler and audition the result live;
    // forgeSaveBody writes the current body as <name>.body240 into Documents/TRENCH/bodies/
    // (where the roster loader picks it up). Returns the saved file (invalid on failure).
    void forgeAuditionTyped (const std::vector<double>& cards);
    juce::File forgeSaveBody (const juce::String& name);

    // VARIANT BANK (message thread). Spawn `n` legal, certified SIBLINGS of the
    // currently-playing body and decode each one's response (at the current Morph/Q)
    // via a scratch engine, WITHOUT disturbing playback. The family spread runs from
    // tight (near the clean base) to wide (characterful) across the set, so the bank
    // is a range, not n copies. installBodyBytes installs a chosen variant live.
    // A Page-2 recipe variant: a body + Morph/Q/Slam/QSound recipe, with a COMPACT
    // WAVEFORM of that recipe previewed on the source you played (per-bucket min/max,
    // rendered through the REAL packed engine — a visualization, not a second source;
    // drag-out still exports the heard wet buffer). `axis` = the effect this variant
    // emphasises, used to colour the waveform.
    enum Axis { AxisFamily = 0, AxisMorph, AxisQ, AxisQSound, AxisSlam };
    static constexpr int kTakeWaveN = 56;
    struct VariantPreview
    {
        std::array<unsigned char, 240> bytes {};
        float morph = 0.0f, q = 0.0f, slam = 0.0f;
        bool  qsound = false;
        int   axis = AxisFamily;
        float wmin[kTakeWaveN] {};
        float wmax[kTakeWaveN] {};
        float bright = 0.0f;      // 0=dark .. 1=bright (HF content of the take)
        bool  valid = false;
        bool  asHeard = false;    // slot 0: the body/point you were just playing
    };
    // The Page-2 "mystery box": slot 0 = AS HEARD (the original at the point you played),
    // slots 1..n-1 = seeded recipe variants of THAT sound, each emphasising one effect
    // (Morph / Q / QSound / Slam / family), previewed as a waveform. Anchored to the
    // fixed roster (original) so rerolling never walks hotter. Click a slot -> install +
    // adopt its recipe live; drag -> captureSmartTake (the heard wet buffer).
    std::vector<VariantPreview> buildTakeTray (int n);
    bool installBodyBytes (const void* bytes, size_t len);
    bool copyCurrentBodyBytes (void* out, size_t len);
    bool probeCurrentBodyForUi (float morph, float q, float outCoeffs[30], float& outBoost);

    // Workstation-only listening switch. The processor remains the sole audio
    // authority; BODY SOLO changes which already-owned stages are enabled.
    void setWorkstationBodySolo (bool enabled) noexcept
    {
        workstationBodySolo.store (enabled, std::memory_order_release);
    }
    bool isWorkstationBodySolo() const noexcept
    {
        return workstationBodySolo.load (std::memory_order_acquire);
    }
    static constexpr const char* processorBuildIdentifier() noexcept
    {
        return "trench-plugin-processor-v1";
    }

    // CAPTURE (message thread): freeze the last `range` of the FINAL wet output
    // from the rolling buffer, write it as a BWAV/ACID take WAV under
    // Documents/TRENCH/takes/, and return the file (invalid File on failure).
    juce::File captureTake (trench::CaptureRange range);
    juce::File getLastTakeFile() const { return lastTakeFile; }

    // PAGE 2 capture freeze: while the Versions page is open, stop recording the rolling
    // wet/dry buffers so auditioning a seeded variant never records over the captured source
    // moment. The editor sets this on setPage; the audio thread reads it lock-free.
    void setCaptureFrozen (bool f) noexcept { captureFrozen.store (f, std::memory_order_relaxed); }

    // SMART TAKE (message thread): the Page-2 "keep what I just heard" gesture. No
    // range picker — TRENCH silently keeps a rolling wet buffer and, on demand,
    // freezes a window sized around the user's most recent Morph/Slam gesture (with a
    // little pre-roll + tail), falling back to a few seconds when there is no clear
    // gesture, clamped so it never dumps a whole session. Writes the WAV and returns
    // it (invalid File on failure) for performExternalDragDropOfFiles.
    juce::File captureSmartTake();

    // Downsampled |wet| envelope of the current smart-take window, for the Take page
    // preview. Fills `out` with `count` 0..1 peaks; returns frames sampled (0 = empty).
    int getTakePreview (float* out, int count);

    // MOVE routing matrix (ROUTE view editing). Per gesture, 4 sources x 4 targets;
    // cell index = src*4 + tgt. Lock-free atomics; the audio thread reads the current
    // gesture's row each block. Edits persist into apvts.state for host recall.
    float moveMatrixCell (int gesture, int src, int tgt) const noexcept;
    void  setMoveMatrixCell (int gesture, int src, int tgt, float value) noexcept;
    void  restoreMoveMatrix (int gesture) noexcept;   // reset a gesture's row to factory

private:
    struct ModulatedControls
    {
        float morph = 0.0f;
        float q = 0.0f;
        float drive = 0.0f;
        float guard = 0.0f;   // MOVE GUARD lane — output safety/compensation (0 outside MOVE)
    };

    // juce::AudioProcessorValueTreeState::Listener — body switching. May be
    // called on the audio thread (automation), so we only stash the request and
    // defer the JSON parse/load to handleAsyncUpdate() on the message thread.
    void parameterChanged (const juce::String& parameterID, float newValue) override;
    void handleAsyncUpdate() override;
    void timerCallback() override;
    void forceCleanAudioUiState();
    void setParameterDenormalized (const char* parameterID, float value);
    void storeLoadedBodyBehavior (int bodyIndex, const juce::String& cartridgeJson);
    void applyModulationBehavior (trench::TypeBehavior behavior, int bodyIndex);

    // Reads the Motion params + pattern snapshot and returns the modulated
    // {morph, q, drive} around the host center. Null contract: when motionOn
    // is false or all depths are ~0, returns the inputs unchanged.
    ModulatedControls applyMotion (float morph, float q, float drive, float inputEnv, int numSamples) noexcept;

    trench::FixedRateTrenchIsland fixedRateIsland;
    trench::TeleportEngine        teleportEngine;
    trench::MotionEngine          motionEngine;
    trench::GestureEngine         gestureEngine;   // MOVE (Page 2) — Body Gesture phrases

    int currentProgram = 0;   // selected factory MOVE preset (host program API)

    // MOVE matrix store: 7 gestures x 16 cells (src*4+tgt). Atomic so the audio thread
    // reads the live row while the editor edits. Mirrored into apvts.state on edit.
    std::atomic<float> moveMatrix[trench::kNumGestures][trench::kNumSources * trench::kNumTargets];
    void initMoveMatrix() noexcept;     // seed all rows from factoryMatrix()
    void persistMoveMatrix();           // serialise the store into apvts.state
    void loadMoveMatrix();              // restore the store from apvts.state (if present)
    bool lastMoveOn = false;            // moveOn rising edge -> re-arm one-shots
    bool lastMovePlaying = false;       // transport start -> re-arm ONE/ARM

    std::atomic<int>  pendingBodyIndex { trench::kNoFilterIndex };   // open on No Filter (bypass)
    std::atomic<int>  loadedBodyIndex { trench::kNoFilterIndex };
    std::atomic<int>  loadedSecondaryTarget { 0 };
    std::atomic<int>  loadedMorphTaper { 0 };
    std::atomic<bool> lastLoadOk { true };
    juce::Time        auditionSlotMtime;

    juce::LinearSmoothedValue<float> outputGain { 1.0f };

    float smoothedMorph = 0.0f;
    float smoothedQ = 0.0f;
    float motionInputEnv = 0.0f; // block-rate input envelope for Motion React
    bool controlSmoothersPrimed = false;
    std::atomic<float> inputMeterL { 0.0f };
    std::atomic<float> inputMeterR { 0.0f };
    std::atomic<bool>  moveArmedWaitingForUi { false };  // ARM waiting for next bar -> "FIRES NEXT BAR"
    std::atomic<float> moveGuardForUi { 0.0f };          // GUARD lane level for the status bar
    std::atomic<float> moveSlamForUi { 0.0f };           // SLAM lane level for the status bar
    std::atomic<float> movePhaseForUi { 0.0f };
    std::atomic<float> effectiveMorphForUi { 0.0f };
    std::atomic<float> effectiveQForUi { 0.0f };
    std::atomic<bool> morphModulatedForUi { false };
    std::atomic<bool> qModulatedForUi { false };

    // Motion pattern: UI writes via setMotionPattern (message thread) under
    // patternLock; audio thread snapshots it. The blob is mirrored on
    // apvts.state "motionPattern" for host recall.
    mutable juce::SpinLock patternLock;
    trench::MotionPattern patternSnapshot;
    std::atomic<bool> motionResetRequested { false };
    std::atomic<int> motionStepForUi { 0 };
    void refreshPatternSnapshotFromState();

    // USER motion recording scratch state (message thread only -- mouse
    // events, never touched by the audio thread).
    std::vector<std::pair<double, float>> userRecordingBuffer; // (elapsed ms, morph delta)
    double userRecordingStartMs = -1.0;
    float  userRecordingStartMorph = 0.0f;

    // Smart Motion: the per-body curated motion the Modulation button plays. Cached
    // on the audio thread, recomputed only when the loaded body changes (no lock).
    trench::SmartMotion cachedSmart;
    int cachedSmartIndex = -1;
    int cachedSmartBehavior = -1;

    std::array<std::atomic<float>, kScopeLen> scopeL {};
    std::array<std::atomic<float>, kScopeLen> scopeR {};
    std::atomic<int> scopeWritePos { 0 };

    int lastInputModeSent = -1;

public:
    // Voicing-rig QSound pan pose (-1..+1). Written by the diagnostics-only rig
    // panel on the message thread, applied on the audio thread in processBlock.
    std::atomic<float> rigPan { 0.0f };

private:
    float lastRigPanSent = -999.0f;   // force the first send
    std::atomic<float> lastSpaceSent { 0.0f };
    double spatialOrbitPhase = 0.0;   // 5D: free-running azimuth orbit (radians)

    // DEMO MODE (standalone only): when no audio is routed in, synthesize a looping
    // groove as the input so the plugin can be auditioned with nothing plugged in —
    // for showing it off. Never runs in the hosted plugin (the real product never
    // generates audio). Silence-triggered, so routing real audio overrides it.
    std::atomic<bool> demoMode { false };   // off by default; no synth loop unless armed
    juce::uint64  demoSample = 0;
    double        demoSawPhase = 0.0;
    juce::uint32  demoRng = 0x9e3779b9u;
    void generateDemoBlock (juce::AudioBuffer<float>& buffer);

    // The 240 bytes of the body currently installed (roster, audition, or a seeded
    // sibling). Message-thread only. SEED/EXPORT operate on this so they act on what
    // is actually playing, not merely the roster base.
    juce::MemoryBlock currentBodyBytes;
    // The fixed reference the Variant bank seeds from: the 240 bytes of the loaded
    // ROSTER body, captured at body-load time and NOT mutated by seeding or by
    // installing a chosen variant. Anchoring the bank here stops iterative
    // variant-select from walking the filter hotter every batch (each batch would
    // otherwise re-seed off the last selection and drift the poles to the rMax rim).
    juce::MemoryBlock rosterBodyBytes;
    uint64_t seedCounter = 0;
    uint64_t variantBankCursor = 0;
    void captureCurrentBodyBytes (const juce::String& cartridgeJson);

    // Edison-style wet-output capture. The audio thread writes the final output
    // into captureRing at the end of processBlock; captureTake() freezes a
    // trailing window on the message thread. hostBpm tracks the host tempo for
    // bar-range captures.
    static constexpr double kCaptureMaxSeconds = 24.0; // 4 bars down to ~40 BPM
    trench::CaptureRing captureRing;
    // Pre-filter (dry) source ring. The Take tray previews each recipe through THIS via
    // the real engine to draw the waveform thumbnail (visual only — drag-out still uses
    // the heard wet buffer, never this).
    trench::CaptureRing dryRing;
    std::atomic<bool> captureFrozen { false };   // true while Page 2 is open (set by the editor)
    bool renderRecipe (const unsigned char* body, float morph, float q, float slam,
                       bool qsound, double seconds, juce::AudioBuffer<float>& out);
    std::atomic<double> hostBpm { 0.0 };
    juce::File lastTakeFile;

    // Smart-take gesture tracking. The audio thread advances processedFrames every
    // block and, when Morph/Slam move past a threshold, records the burst's anchor +
    // last-move frame. smartTakeSeconds() reads these to size the take window.
    juce::File writeTake (double seconds, bool oneShot, int beats);
    double smartTakeSeconds() const;
    juce::RangedAudioParameter* morphParamForGesture = nullptr;
    juce::RangedAudioParameter* slamParamForGesture = nullptr;
    std::atomic<juce::uint64> processedFrames { 0 };
    std::atomic<juce::uint64> lastMoveFrame { 0 };
    std::atomic<juce::uint64> gestureAnchorFrame { 0 };
    std::atomic<bool> haveGesture { false };
    float prevGestureMorph = 0.0f;
    float prevGestureSlam = 0.0f;
    bool gestureTrackPrimed = false;

    std::atomic<bool> workstationBodySolo { false };
    bool lastWorkstationBodySolo = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginProcessor)
};
