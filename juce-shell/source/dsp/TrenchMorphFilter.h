#pragma once
#include <juce_audio_basics/juce_audio_basics.h>
#include <array>
#include <cmath>

namespace Trench {

    // =========================================================================
    // Filter State & Words
    // =========================================================================
    
    struct StageWords {
        uint16_t w[5] = { 0x1FFF, 0x0FFF, 0x1FFF, 0x0FFF, 0x0FFF }; // Identity
    };

    struct FilterCoeffs {
        float c0, c1, c2, c3, c4;
    };

    template <size_t NumStages>
    struct FilterFrame {
        std::array<StageWords, NumStages> stages;
    };

    // =========================================================================
    // The Decoder (FUN_1802c3600) — Precomputed LUT
    // =========================================================================

    namespace Decoder {
        static inline float decode_emu_uint16_raw(uint16_t raw_val) {
            uint32_t uVar1 = (uint32_t)raw_val + 1;
            if (uVar1 == 0x10000) return 1.0f;
            if (uVar1 == 1) return 0.0f;
            float fVar6;
            int exponent = ((int)((uVar1 >> 12) & 0xF)) - 15;
            if (exponent < -14) {
                fVar6 = (float)(uVar1 & 0xFFF) * 0.00024414063f; 
            } else {
                fVar6 = (float)((uVar1 & 0xFFF) | 0x1000) * 0.00012207031f; 
            }
            return std::exp2(fVar6); 
        }

        struct DecoderLUT {
            float data[65536];
            DecoderLUT() {
                for (int i = 0; i < 65536; ++i)
                    data[i] = decode_emu_uint16_raw(static_cast<uint16_t>(i));
            }
        };

        static inline const float* getLUT() {
            static DecoderLUT instance;
            return instance.data;
        }
    }

    // =========================================================================
    // The Rossum Proprietary Render Kernel
    // =========================================================================

    class RossumStage {
    public:
        void reset() { s0 = s1 = 0.0f; }

        inline float processSample(float input, const FilterCoeffs& c) {
            const float temp = input + s1 * c.c3 - s0 * c.c2;
            const float s0_new = s0 * 2.0f + temp - s1;
            const float output = (s0 * c.c0 + temp - s1 * c.c1) * c.c4;
            s1 = s0;
            s0 = s0_new;
            return output;
        }

    private:
        float s0 = 0.0f, s1 = 0.0f;
    };

    // =========================================================================
    // CORE ARCHITECTURE: Hardened Rossum Morph Engine
    // =========================================================================

    template <size_t NumStages>
    class RossumMorphFilter {
    public:
        RossumMorphFilter() : morphTarget(0.0f), morphState(0.0f), 
                            qTarget(0.0f), qState(0.0f), 
                            smoothingAlpha(0.995f), framesValid(false) {
            clearState();
        }

        void prepareToPlay(float sampleRate) {
            smoothingAlpha = std::exp(-1.0f / (0.01f * sampleRate));
            clearState();
        }

        void clearState() {
            for (auto& stage : cascadedStages) {
                stage.reset();
            }
        }

        void setFrames(const FilterFrame<NumStages>& m0q0, const FilterFrame<NumStages>& m0q1,
                       const FilterFrame<NumStages>& m1q0, const FilterFrame<NumStages>& m1q1) {
            corners[0] = m0q0;
            corners[1] = m0q1;
            corners[2] = m1q0;
            corners[3] = m1q1;
            framesValid = true;
        }

        void setTargetMorph(float m) { morphTarget = std::fmax(0.0f, std::fmin(1.0f, m)); }
        void setTargetQ(float q) { qTarget = std::fmax(0.0f, std::fmin(1.0f, q)); }

        void processAudioBlock(const float* inBuffer, float* outBuffer, int numSamples) {
            if (!framesValid) {
                for (int n = 0; n < numSamples; ++n) outBuffer[n] = inBuffer[n];
                return;
            }

            const float* lut = Decoder::getLUT();

            for (int n = 0; n < numSamples; ++n) {
                morphState = morphState * smoothingAlpha + morphTarget * (1.0f - smoothingAlpha);
                qState = qState * smoothingAlpha + qTarget * (1.0f - smoothingAlpha);

                float m = morphState;
                float q = qState;
                float sample = inBuffer[n];

                for (size_t s = 0; s < NumStages; ++s) {
                    FilterCoeffs c;
                    float raws[5];

                    for (int w = 0; w < 5; ++w) {
                        float w0 = (float)corners[0].stages[s].w[w];
                        float w1 = (float)corners[1].stages[s].w[w];
                        float w2 = (float)corners[2].stages[s].w[w];
                        float w3 = (float)corners[3].stages[s].w[w];

                        float im0 = w0 + q * (w1 - w0);
                        float im1 = w2 + q * (w3 - w2);
                        float interpW = im0 + m * (im1 - im0);
                        
                        raws[w] = lut[static_cast<uint16_t>(std::round(interpW))];
                    }

                    c.c0 = raws[0] * 4.0f + raws[1];
                    c.c1 = raws[1];
                    c.c2 = raws[2] * 4.0f + raws[3];
                    c.c3 = raws[3];
                    c.c4 = raws[4];

                    sample = cascadedStages[s].processSample(sample, c);
                }
                outBuffer[n] = sample;
            }
        }

    private:
        std::array<FilterFrame<NumStages>, 4> corners;
        std::array<RossumStage, NumStages> cascadedStages;
        
        float morphTarget, morphState;
        float qTarget, qState;
        float smoothingAlpha;
        bool framesValid;
    };

    using TrenchFilter6 = RossumMorphFilter<6>;

} // namespace Trench