#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

#include "BiteStage.h"

#include <atomic>
#include <cstdint>
#include <cstring>

extern "C"
{
    void* trench_engine_create();
    void trench_engine_destroy (void* engine);
    void trench_engine_prepare (void* engine, double sampleRate);
    int trench_engine_load_cartridge (void* engine, const char* json);
    int trench_engine_load_body_bytes (void* engine, const unsigned char* bytes, size_t len);
    void trench_engine_reclaim (void* engine);
    void trench_engine_set_parameters (void* engine, float morph, float q, float slamDrive, float fiveD, float amount);
    void trench_engine_set_input_mode (void* engine, unsigned int mode);  // 0=None, 1=MackieDeskSlam, 2=Cvsd
    void trench_engine_set_spatial_mode (void* engine, int mode);         // 0=QSound, 1=Trench, 2=Off
    void trench_engine_set_qsound_fallback_pan (void* engine, float pan); // -1=left, 0=mono centre, +1=right
    void trench_engine_set_agc_enabled (void* engine, int enabled);
    void trench_engine_set_saturation_enabled (void* engine, int enabled);
    void trench_engine_set_agc_drive (void* engine, float drive);
    void trench_engine_set_coeff_ramp_scale (void* engine, float scale); // morph RATE: 1.0=80ms glide .. 0=32-sample snap
    void trench_engine_set_pitch_ratio (void* engine, float ratio);      // KEY TRACKING: transpose conjugate resonances; 1.0=off (bit-exact)
    void trench_engine_set_key_snap (void* engine, int choice);          // MANUAL KEY SNAP: 0=off, 1..12 minor, 13..24 major
    void trench_engine_set_interstage_drive (void* engine, float drive); // BITE: inter-stage soft-clip inside the cascade; 0=linear (bit-exact)
    void trench_engine_process_block (void* engine, float* left, float* right, int numSamples, double morph, double q);
    void trench_engine_get_coeffs (void* engine, float* outCoeffs, float* outBoost);
    int trench_packed_probe (const unsigned char* bytes, size_t len, double morph, double q,
                             double* outBiquad, double* outMaxPoleRadius,
                             uint32_t* outUnstableMask, uint32_t* outNonfiniteMask);

    // SEED / EXPORT support — stateless packed-math, owned by core (see trench-core ffi.rs).
    int trench_pack_body_from_corner_words (const unsigned short* words, size_t n, unsigned char* outBody);
    int trench_certify_body (const unsigned char* bytes, size_t len, unsigned int res, double rMax,
                             int* outPass, double* outMaxRadius, double* outFailMorph, double* outFailQ);
    int trench_seed_body (const unsigned char* inBody, size_t len, unsigned long long seed, double amt,
                          unsigned int res, double rMax, unsigned char* outBody);
    int trench_cartridge_json_to_body (const char* json, unsigned char* outBody);
    // Forge: compile 6 typed cards (42 f64 = 6 x [type, fc_low, fc_high, q_lo, q_hi, gain_db, on]) -> 240 bytes.
    int trench_compile_body_typed (const double* cards, size_t nValues, unsigned char* outBody);
    // KEYFRAME RECORDER — per-wheel tempo-synced modulation value (one owner in
    // trench-core::keyframe). mode: 0=Pendulum 1=Rise 2=Saw 3=OneShot.
    float trench_keyframe_value (float a, float b, float legBars, double ppq,
                                 double beatsPerBar, unsigned mode);
    // MOTION TAKE prototype — one shared Morph/Q sampled path. `points` is an
    // interleaved array of normalized deltas; trench-core owns interpolation.
    int trench_motion_path_value (const float* points, size_t pointCount, double phase,
                                  int closed, float baseMorph, float baseQ, float amount,
                                  float* outMorph, float* outQ);
    // Time-preserving Motion Take path. `points` is
    // [normalized_time, morph_delta, q_delta] per point. gridSteps == 0 keeps
    // human timing; positive values snap only the internal event times.
    int trench_motion_path_value_timed (const float* points, size_t pointCount, double phase,
                                        int closed, size_t gridSteps, float baseMorph, float baseQ,
                                        float amount, float* outMorph, float* outQ);
}

struct TrenchParams
{
    float morph = 0.0f; // normalised 0..1
    float q = 0.0f;     // normalised 0..1
    float slamDrive = 0.0f; // final-output pressure, applied by PluginProcessor after output gain
    float fiveD = 0.0f;
    float amount = 1.0f; // 1 = full body, 0 = flat/identity — coefficient blend, not audio mix
    float bite = 0.0f;  // BITE/Damage 0..1 — post-cascade harmonic grit
    float rampScale = 0.164f; // morph RATE: approach-time scale (0=SNAP 0.8ms, 0.164=TIGHT 13ms, 1=GLIDE 80ms)
    float pitchRatio = 1.0f;  // KEY TRACKING transpose ratio (1.0 = off)
    int keySnap = 0;          // MANUAL KEY SNAP choice (0 = exact no-op)
    float interstageDrive = 0.0f; // BITE inter-stage drive (0 = linear cascade, bit-exact)
};

class TrenchDspBridge
{
public:
    TrenchDspBridge()
    {
        engine = trench_engine_create();

        // Seed the UI snapshot with a unity (passthrough) corner so the editor
        // shows a sane curve before the first audio block publishes real coeffs.
        for (int s = 0; s < 6; ++s)
            uiSnapshot.coeffs[s * 5] = 1.0f; // c0 = 1, rest already zero
        uiSnapshot.boost = 1.0f;
    }

    ~TrenchDspBridge()
    {
        if (engine != nullptr)
            trench_engine_destroy (engine);
    }

    void prepare (double sampleRate, int /*maxBlockSize*/)
    {
        if (engine != nullptr)
        {
            trench_engine_prepare (engine, sampleRate);
            trench_engine_set_agc_enabled (engine, 1);
            trench_engine_set_saturation_enabled (engine, 1);
        }
    }

    bool loadCartridge (const juce::String& json)
    {
        if (engine == nullptr)
            return false;

        return trench_engine_load_cartridge (engine, json.toRawUTF8()) == 0;
    }

    // Load a body directly from a raw 240-byte block (the canonical body
    // container). This is NOT a special DSP path: it routes through the same
    // Rust runtime body loader as a JSON roster body, so a live Forge audition
    // and a shipped roster body both end in the same PackedCorners runtime path.
    // Rejects anything that is not exactly 240 bytes.
    bool loadCartridgeBytes (const void* bytes, size_t len)
    {
        if (engine == nullptr || bytes == nullptr)
            return false;

        return trench_engine_load_body_bytes (engine,
                                              static_cast<const unsigned char*> (bytes),
                                              len) == 0;
    }

    bool loadCartridgeBytes (const juce::MemoryBlock& block)
    {
        return loadCartridgeBytes (block.getData(), block.getSize());
    }

    // SEED: spawn a legal, certified SIBLING of the body described by `cartridgeJson`
    // and stage it for the next block. `seed` makes it deterministic; `amt` scales the
    // family spread (1.0 = default). MESSAGE-THREAD ONLY — the perturb + surface-certify
    // run here off the audio thread; only the finished, certified 240 bytes cross to the
    // engine via the same staging mailbox a roster body uses. Returns false if no legal
    // sibling was found within the attempt budget (widen amt / try a new seed) or null engine.
    bool seedSiblingFromJson (const juce::String& cartridgeJson, uint64_t seed, double amt = 1.0)
    {
        if (engine == nullptr || cartridgeJson.isEmpty())
            return false;

        unsigned char src[240];
        if (trench_cartridge_json_to_body (cartridgeJson.toRawUTF8(), src) != 0)
            return false;

        unsigned char sib[240];
        if (trench_seed_body (src, sizeof (src), (unsigned long long) seed, amt, 65u, 0.9999, sib) != 0)
            return false;

        return trench_engine_load_body_bytes (engine, sib, sizeof (sib)) == 0;
    }

    // SEED from raw current-body bytes (what is actually playing — possibly already a
    // sibling) rather than from JSON. Spawns + certifies a sibling, stages it, and
    // copies it into `outSibling`. Message-thread only. False if no legal sibling.
    bool seedSiblingFromBytes (const void* srcBytes, size_t len, uint64_t seed, double amt,
                               juce::MemoryBlock& outSibling)
    {
        if (engine == nullptr || srcBytes == nullptr || len != 240)
            return false;

        unsigned char sib[240];
        if (trench_seed_body (static_cast<const unsigned char*> (srcBytes), len,
                              (unsigned long long) seed, amt, 65u, 0.9999, sib) != 0)
            return false;
        if (trench_engine_load_body_bytes (engine, sib, sizeof (sib)) != 0)
            return false;

        outSibling = juce::MemoryBlock (sib, sizeof (sib));
        return true;
    }

    // EXPORT-body: fill `out` with the canonical 240 bytes of the body described by
    // `cartridgeJson` (the currently loaded body). Lossless, native, no render. The
    // audio-render export is a separate forge handoff. Returns false on parse failure.
    static bool bodyBytesFromJson (const juce::String& cartridgeJson, juce::MemoryBlock& out)
    {
        out.setSize (240);
        return trench_cartridge_json_to_body (cartridgeJson.toRawUTF8(),
                                              static_cast<unsigned char*> (out.getData())) == 0;
    }

    // FORGE: compile 6 typed cards (42 f64) -> 240 bytes via the flat-ended typed compiler
    // (the correct musical path; NOT the raw pole/zero compile_body). Message thread.
    static bool compileTypedBody (const double* cards, int nValues, juce::MemoryBlock& out)
    {
        out.setSize (240);
        return trench_compile_body_typed (cards, (size_t) nValues,
                                          static_cast<unsigned char*> (out.getData())) == 0;
    }

    // UI-only packed-body response probe. Stateless: evaluates the same 240-byte body
    // and packed interpolation used by the runtime, without touching the live engine.
    static bool probePackedBody (const void* bytes, size_t len, float morph, float q,
                                 float outCoeffs[30], float& outBoost)
    {
        if (bytes == nullptr || outCoeffs == nullptr || len != 240)
            return false;

        double biquad[30] {};
        double maxPoleRadius = 0.0;
        uint32_t unstableMask = 0, nonfiniteMask = 0;
        const int rc = trench_packed_probe (static_cast<const unsigned char*> (bytes), len,
                                            (double) juce::jlimit (0.0f, 1.0f, morph),
                                            (double) juce::jlimit (0.0f, 1.0f, q),
                                            biquad, &maxPoleRadius, &unstableMask, &nonfiniteMask);
        juce::ignoreUnused (maxPoleRadius);
        if (rc != 0 || unstableMask != 0 || nonfiniteMask != 0)
            return false;

        for (int i = 0; i < 30; ++i)
            outCoeffs[i] = (float) biquad[i];
        outBoost = 1.0f;
        return true;
    }

    void process (juce::AudioBuffer<float>& buffer, const TrenchParams& params)
    {
        if (engine == nullptr || buffer.getNumChannels() < 2)
            return;

        // APVTS Morph/Q are already normalised 0..1. Do not divide by 100.
        // The AGC pre-scale is owned by trench-core (`engine::AGC_DRIVE`): it is
        // derived from the verified table's first tooth and the saturator knee,
        // not voiced here. Final-output SLAM is deliberately owned by
        // PluginProcessor after this fixed-rate island, ZAP, MOVE guard, and
        // output gain.
        const int n = buffer.getNumSamples();
        // The engine's own desk drive stays OFF (slam param 0). SLAM is applied
        // exactly once at the final host-rate output stage in PluginProcessor.
        // slamDrive now reaches the engine's pre-cascade desk; the engine IGNORES it
        // unless the input mode is MackieDeskSlam (the "Into Filter" slam route), so
        // the default Output route stays byte-unchanged.
        trench_engine_set_parameters (engine, params.morph, params.q, params.slamDrive, params.fiveD, params.amount);
        if (! juce::approximatelyEqual (params.rampScale, lastRampScaleSent))
        {
            trench_engine_set_coeff_ramp_scale (engine, params.rampScale);
            lastRampScaleSent = params.rampScale;
        }
        if (! juce::approximatelyEqual (params.pitchRatio, lastPitchRatioSent))
        {
            trench_engine_set_pitch_ratio (engine, params.pitchRatio);
            lastPitchRatioSent = params.pitchRatio;
        }
        if (params.keySnap != lastKeySnapSent)
        {
            trench_engine_set_key_snap (engine, params.keySnap);
            lastKeySnapSent = params.keySnap;
        }
        if (! juce::approximatelyEqual (params.interstageDrive, lastInterstageDriveSent))
        {
            trench_engine_set_interstage_drive (engine, params.interstageDrive);
            lastInterstageDriveSent = params.interstageDrive;
        }
        trench_engine_process_block (engine,
                                     buffer.getWritePointer (0),
                                     buffer.getWritePointer (1),
                                     n,
                                     params.morph,
                                     params.q);

        // CLIP — post-cascade drum-bus hard clip on the FILTERED signal (params.bite
        // carries ParamID::clip; the inter-stage BITE lives in the Rust engine).
        // Gain into a 1.0 ceiling; exact unity at clip=0.
        const float biteNorm = juce::jlimit (0.0f, 1.0f, params.bite);
        trench::biteDriveBlock (buffer.getWritePointer (0), n, biteNorm);
        trench::biteDriveBlock (buffer.getWritePointer (1), n, biteNorm);

    }

    // Message-thread reclaim: frees the body the audio thread retired after a
    // swap. Cheap; safe to call on a timer. The Rust side also reclaims on each
    // load, so this is only about releasing the previous body's memory promptly.
    void reclaim()
    {
        if (engine != nullptr)
            trench_engine_reclaim (engine);
    }

    // AUDIO-THREAD ONLY. Reads the live engine coefficients and publishes them
    // into the lock-free UI snapshot. Called once per processBlock so the editor
    // never has to touch the engine from the message/VBlank thread (which would
    // race the audio thread's exclusive &mut engine). No allocation.
    void publishUiSnapshot()
    {
        float c[30];
        float b = 1.0f;
        if (engine != nullptr)
            trench_engine_get_coeffs (engine, c, &b);
        else
            std::memset (c, 0, sizeof (c));

        // Seqlock write: bump to odd (write in progress), store fields, bump to
        // even (complete). A reader that sees an odd count or a changed count
        // retries.
        const uint32_t s = uiSnapshot.seq.load (std::memory_order_relaxed);
        uiSnapshot.seq.store (s + 1, std::memory_order_relaxed);
        std::atomic_thread_fence (std::memory_order_release);
        std::memcpy (uiSnapshot.coeffs, c, sizeof (c));
        uiSnapshot.boost = b;
        std::atomic_thread_fence (std::memory_order_release);
        uiSnapshot.seq.store (s + 2, std::memory_order_release);
    }

    // UI/MESSAGE-THREAD read of the published coefficient snapshot. Returns false
    // on a torn read (rare; caller keeps its previous frame) or null output.
    bool readUiSnapshot (float* outCoeffs, float& outBoost)
    {
        if (outCoeffs == nullptr)
            return false;

        for (int attempt = 0; attempt < 8; ++attempt)
        {
            const uint32_t s1 = uiSnapshot.seq.load (std::memory_order_acquire);
            if (s1 & 1u)
                continue; // a write is in progress

            float c[30];
            float b;
            std::atomic_thread_fence (std::memory_order_acquire);
            std::memcpy (c, uiSnapshot.coeffs, sizeof (c));
            b = uiSnapshot.boost;
            std::atomic_thread_fence (std::memory_order_acquire);

            if (uiSnapshot.seq.load (std::memory_order_acquire) == s1)
            {
                std::memcpy (outCoeffs, c, sizeof (c));
                outBoost = b;
                return true;
            }
        }
        return false;
    }

    // Switches the engine's pre-cascade input character stage.
    // 0 = None (clean), 1 = Mackie desk slam, 2 = CVSD (EOS 6400 companding).
    void setInputMode (int mode)
    {
        if (engine != nullptr)
            trench_engine_set_input_mode (engine, static_cast<unsigned int> (juce::jlimit (0, 2, mode)));
    }

    // Post-cascade spatial stage. 0 = QSound (profile ITD/ILD/shelves when
    // present; otherwise the local QCreator-anchored recreation), 1 = Trench
    // M/S matrix, 2 = Off. Clean ground-truth audio keeps this Off.
    void setSpatialMode (int mode)
    {
        if (engine != nullptr)
            trench_engine_set_spatial_mode (engine, juce::jlimit (0, 2, mode));
    }

    // Local no-profile QSound pose. The shipping path pins this to the
    // recovered exaggerated-right anchor; the setter remains available for
    // future authoring tools without adding another plug-in control.
    void setQSoundFallbackPan (float pan)
    {
        if (engine != nullptr)
            trench_engine_set_qsound_fallback_pan (engine, juce::jlimit (-1.0f, 1.0f, pan));
    }

    void setAgcEnabled (bool enabled)
    {
        if (engine != nullptr)
            trench_engine_set_agc_enabled (engine, enabled ? 1 : 0);
    }

    // Probe/debug only. The shipped pre-AGC scale is owned by trench-core
    // (`engine::AGC_DRIVE`); the product path never calls this.
    void setAgcDrive (float drive)
    {
        if (engine != nullptr)
            trench_engine_set_agc_drive (engine, juce::jmax (1.0f, drive));
    }

    void setSaturationEnabled (bool enabled)
    {
        if (engine != nullptr)
            trench_engine_set_saturation_enabled (engine, enabled ? 1 : 0);
    }

    void reset() {}

private:
    void* engine = nullptr;
    float lastRampScaleSent = -1.0f; // sentinel: first block always sends RATE
    float lastPitchRatioSent = -1.0f; // sentinel: first block always sends KEY TRACK ratio
    int lastKeySnapSent = -1;         // sentinel: first block always sends MANUAL KEY SNAP
    float lastInterstageDriveSent = -1.0f; // sentinel: first block always sends BITE drive

    // Lock-free seqlock snapshot: written by the audio thread (publishUiSnapshot),
    // read by the UI/VBlank thread (readUiSnapshot). Keeps the message thread off
    // the live Rust engine entirely.
    struct UiCoeffSnapshot
    {
        std::atomic<uint32_t> seq { 0 };
        float coeffs[30] {};
        float boost { 1.0f };
    };
    UiCoeffSnapshot uiSnapshot;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchDspBridge)
};
