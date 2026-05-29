#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

extern "C"
{
    void* trench_engine_create();
    void trench_engine_destroy (void* engine);
    void trench_engine_prepare (void* engine, double sampleRate);
    int trench_engine_load_cartridge (void* engine, const char* json);
    int trench_engine_load_body_bytes (void* engine, const unsigned char* bytes, size_t len);
    void trench_engine_set_parameters (void* engine, float morph, float q, float slamDrive, float fiveD);
    void trench_engine_set_input_mode (void* engine, unsigned int mode);  // 0=None, 1=MackieDeskSlam, 2=Cvsd
    void trench_engine_set_spatial_mode (void* engine, int mode);         // 0=QSound, 1=Trench, 2=Off
    void trench_engine_process_block (void* engine, float* left, float* right, int numSamples, double morph, double q);
    void trench_engine_get_coeffs (void* engine, float* outCoeffs, float* outBoost);
}

struct TrenchParams
{
    float morph = 0.0f; // normalised 0..1
    float q = 0.0f;     // normalised 0..1
    float slamDrive = 0.0f;
    float fiveD = 0.0f;
};

class TrenchDspBridge
{
public:
    TrenchDspBridge()
    {
        engine = trench_engine_create();
    }

    ~TrenchDspBridge()
    {
        if (engine != nullptr)
            trench_engine_destroy (engine);
    }

    void prepare (double sampleRate, int /*maxBlockSize*/)
    {
        if (engine != nullptr)
            trench_engine_prepare (engine, sampleRate);
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

    void process (juce::AudioBuffer<float>& buffer, const TrenchParams& params)
    {
        if (engine == nullptr || buffer.getNumChannels() < 2)
            return;

        // APVTS Morph/Q are already normalised 0..1. Do not divide by 100.
        trench_engine_set_parameters (engine, params.morph, params.q, params.slamDrive, params.fiveD);
        trench_engine_process_block (engine,
                                     buffer.getWritePointer (0),
                                     buffer.getWritePointer (1),
                                     buffer.getNumSamples(),
                                     params.morph,
                                     params.q);
    }

    void getSmoothedCoeffsForUI (float* outCoeffs, float& outBoost)
    {
        if (engine == nullptr || outCoeffs == nullptr)
        {
            outBoost = 1.0f;
            return;
        }

        trench_engine_get_coeffs (engine, outCoeffs, &outBoost);
    }

    // Switches the engine's pre-cascade input character stage.
    // 0 = None (clean), 1 = Mackie desk slam, 2 = CVSD (EOS 6400 companding).
    void setInputMode (int mode)
    {
        if (engine != nullptr)
            trench_engine_set_input_mode (engine, static_cast<unsigned int> (juce::jlimit (0, 2, mode)));
    }

    // Post-cascade spatial stage. 0 = QSound (realistic ITD/ILD/shelves; falls
    // back to a symmetric widener when the body carries no spatial profile),
    // 1 = Trench M/S matrix, 2 = Off. Clean ground-truth audio keeps this Off.
    void setSpatialMode (int mode)
    {
        if (engine != nullptr)
            trench_engine_set_spatial_mode (engine, juce::jlimit (0, 2, mode));
    }

    void reset() {}

private:
    void* engine = nullptr;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchDspBridge)
};
