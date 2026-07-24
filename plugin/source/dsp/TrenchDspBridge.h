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
    void trench_engine_set_input_mode (void* engine, unsigned int mode);
    void trench_engine_set_spatial_mode (void* engine, int mode);
    void trench_engine_set_qsound_fallback_pan (void* engine, float pan);
    void trench_engine_set_agc_enabled (void* engine, int enabled);
    void trench_engine_set_saturation_enabled (void* engine, int enabled);
    void trench_engine_set_agc_drive (void* engine, float drive);
    void trench_engine_set_coeff_ramp_scale (void* engine, float scale);
    void trench_engine_set_pitch_ratio (void* engine, float ratio);
    void trench_engine_set_key_snap (void* engine, int choice);
    void trench_engine_set_interstage_drive (void* engine, float drive);
    void trench_engine_process_block (void* engine, float* left, float* right, int numSamples, double morph, double q);
    void trench_engine_get_coeffs (void* engine, float* outCoeffs, float* outBoost);
    int trench_packed_probe (const unsigned char* bytes, size_t len, double morph, double q,
                             double* outBiquad, double* outMaxPoleRadius,
                             uint32_t* outUnstableMask, uint32_t* outNonfiniteMask);
    int trench_pack_body_from_corner_words (const unsigned short* words, size_t n, unsigned char* outBody);
    int trench_stage_roots_from_words (const unsigned short* words, double* outRoots);
    int trench_stage_words_from_roots (const double* roots, unsigned short* outWords);
    int trench_certify_body (const unsigned char* bytes, size_t len, unsigned int res, double rMax,
                             int* outPass, double* outMaxRadius, double* outFailMorph, double* outFailQ);
    int trench_seed_body (const unsigned char* inBody, size_t len, unsigned long long seed, double amt,
                          unsigned int res, double rMax, unsigned char* outBody);
    int trench_cartridge_json_to_body (const char* json, unsigned char* outBody);
    int trench_compile_body_typed (const double* cards, size_t nValues, unsigned char* outBody);
    float trench_keyframe_value (float a, float b, float legBars, double ppq,
                                 double beatsPerBar, unsigned mode);
    int trench_motion_path_value (const float* points, size_t pointCount, double phase,
                                  int closed, float baseMorph, float baseQ, float amount,
                                  float* outMorph, float* outQ);
    int trench_motion_path_value_timed (const float* points, size_t pointCount, double phase,
                                        int closed, size_t gridSteps, float baseMorph, float baseQ,
                                        float amount, float* outMorph, float* outQ);
}
struct TrenchParams
{
    float morph = 0.0f;
    float q = 0.0f;
    float slamDrive = 0.0f;
    float fiveD = 0.0f;
    float amount = 1.0f;
    float bite = 0.0f;
    float rampScale = 0.164f;
    float pitchRatio = 1.0f;
    int keySnap = 0;
    float interstageDrive = 0.0f;
};
class TrenchDspBridge
{
public:
    TrenchDspBridge()
    {
        engine = trench_engine_create();
        for (int s = 0; s < 6; ++s)
            uiSnapshot.coeffs[s * 5] = 1.0f;
        uiSnapshot.boost = 1.0f;
    }
    ~TrenchDspBridge()
    {
        if (engine != nullptr)
            trench_engine_destroy (engine);
    }
    void prepare (double sampleRate, int )
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
    static bool bodyBytesFromJson (const juce::String& cartridgeJson, juce::MemoryBlock& out)
    {
        out.setSize (240);
        return trench_cartridge_json_to_body (cartridgeJson.toRawUTF8(),
                                              static_cast<unsigned char*> (out.getData())) == 0;
    }
    static bool compileTypedBody (const double* cards, int nValues, juce::MemoryBlock& out)
    {
        out.setSize (240);
        return trench_compile_body_typed (cards, (size_t) nValues,
                                          static_cast<unsigned char*> (out.getData())) == 0;
    }
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
        const int n = buffer.getNumSamples();
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
        const float biteNorm = juce::jlimit (0.0f, 1.0f, params.bite);
        trench::biteDriveBlock (buffer.getWritePointer (0), n, biteNorm);
        trench::biteDriveBlock (buffer.getWritePointer (1), n, biteNorm);
    }
    void reclaim()
    {
        if (engine != nullptr)
            trench_engine_reclaim (engine);
    }
    void publishUiSnapshot()
    {
        float c[30];
        float b = 1.0f;
        if (engine != nullptr)
            trench_engine_get_coeffs (engine, c, &b);
        else
            std::memset (c, 0, sizeof (c));
        const uint32_t s = uiSnapshot.seq.load (std::memory_order_relaxed);
        uiSnapshot.seq.store (s + 1, std::memory_order_relaxed);
        std::atomic_thread_fence (std::memory_order_release);
        std::memcpy (uiSnapshot.coeffs, c, sizeof (c));
        uiSnapshot.boost = b;
        std::atomic_thread_fence (std::memory_order_release);
        uiSnapshot.seq.store (s + 2, std::memory_order_release);
    }
    bool readUiSnapshot (float* outCoeffs, float& outBoost)
    {
        if (outCoeffs == nullptr)
            return false;
        for (int attempt = 0; attempt < 8; ++attempt)
        {
            const uint32_t s1 = uiSnapshot.seq.load (std::memory_order_acquire);
            if (s1 & 1u)
                continue;
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
    void setInputMode (int mode)
    {
        if (engine != nullptr)
            trench_engine_set_input_mode (engine, static_cast<unsigned int> (juce::jlimit (0, 2, mode)));
    }
    void setSpatialMode (int mode)
    {
        if (engine != nullptr)
            trench_engine_set_spatial_mode (engine, juce::jlimit (0, 2, mode));
    }
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
    float lastRampScaleSent = -1.0f;
    float lastPitchRatioSent = -1.0f;
    int lastKeySnapSent = -1;
    float lastInterstageDriveSent = -1.0f;
    struct UiCoeffSnapshot
    {
        std::atomic<uint32_t> seq { 0 };
        float coeffs[30] {};
        float boost { 1.0f };
    };
    UiCoeffSnapshot uiSnapshot;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchDspBridge)
};
