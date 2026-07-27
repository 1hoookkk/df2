#pragma once
#include <cmath>
namespace trench
{
inline float slamGainDb (float slamNorm) noexcept
{
    const float s = slamNorm < 0.0f ? 0.0f : (slamNorm > 1.0f ? 1.0f : slamNorm);
    if (s <= 0.75f)
        return 24.0f * s;
    return 18.0f + 48.0f * (s - 0.75f);
}
inline float slamGainLinear (float slamNorm) noexcept
{
    return std::pow (10.0f, slamGainDb (slamNorm) / 20.0f);
}
constexpr float kSlamHeadroomDb = 9.0f;
inline float internalClip (float x) noexcept
{
    return x > 1.0f ? 1.0f : (x < -1.0f ? -1.0f : x);
}
inline float slamPreProcess (float* buf, int n, float slamNorm) noexcept
{
    if (buf == nullptr || n <= 0)
        return 0.0f;
    const float g = slamGainLinear (slamNorm);
    int clipped = 0;
    for (int i = 0; i < n; ++i)
    {
        float y = buf[i] * g;
        if (y > 1.0f || y < -1.0f) { ++clipped; y = internalClip (y); }
        buf[i] = y;
    }
    return (float) clipped / (float) n;
}
inline float slamPostProcess (float* buf, int n, float outTrimDb) noexcept
{
    if (buf == nullptr || n <= 0)
        return 0.0f;
    const float g = std::pow (10.0f, outTrimDb / 20.0f);
    int clipped = 0;
    for (int i = 0; i < n; ++i)
    {
        float y = buf[i] * g;
        if (y > 1.0f || y < -1.0f) { ++clipped; y = internalClip (y); }
        buf[i] = y;
    }
    return (float) clipped / (float) n;
}
inline float slamOutputGainDb (float slamNorm) noexcept
{
    const float s = slamNorm < 0.0f ? 0.0f : (slamNorm > 1.0f ? 1.0f : slamNorm);
    return 12.0f * s;
}
constexpr float kSlamInputTrimDb = -6.0f;
inline float slamInputGainLinear() noexcept
{
    return std::pow (10.0f, kSlamInputTrimDb / 20.0f);
}
inline float slamOutputMakeupLinear() noexcept
{
    return 1.0f / slamInputGainLinear();
}
constexpr float kSlamPressureKnee = 0.72f;
constexpr float kFinalSafetyKnee = 0.9440609f;    // -0.5 dBFS
constexpr float kFinalSafetyCeiling = 0.9885531f; // -0.1 dBFS
extern "C" void trench_desk_saturate_stereo (float* left, float* right, int numSamples, float drive);
inline float slamRoundedLimit (float x) noexcept
{
    const float a = std::fabs (x);
    if (a <= kSlamPressureKnee)
        return x;
    return (x < 0.0f ? -1.0f : 1.0f)
        * (kSlamPressureKnee + (1.0f - kSlamPressureKnee)
                                  * std::tanh ((a - kSlamPressureKnee)
                                               / (1.0f - kSlamPressureKnee)));
}
inline float slamOutputPressureBlock (float* data, int n, float slamNorm) noexcept
{
    if (data == nullptr || n <= 0)
        return 0.0f;
    const float s = slamNorm < 0.0f ? 0.0f : (slamNorm > 1.0f ? 1.0f : slamNorm);
    const float inputGain = slamInputGainLinear();
    if (s <= 1.0e-4f)
        return 0.0f;
    const float drive = inputGain * std::pow (10.0f, slamOutputGainDb (s) / 20.0f);
    const float makeup = slamOutputMakeupLinear();
    int limited = 0;
    for (int i = 0; i < n; ++i)
        if (std::fabs (data[i] * drive) > kSlamPressureKnee)
            ++limited;
    trench_desk_saturate_stereo (data, nullptr, n, drive);
    for (int i = 0; i < n; ++i)
        data[i] *= makeup;
    return (float) limited / (float) n;
}
inline float slamOutputPressureBlockStereo (float* left, float* right, int n, float slamNorm) noexcept
{
    if (left == nullptr || right == nullptr || n <= 0)
        return 0.0f;
    if (left == right)
        return slamOutputPressureBlock (left, n, slamNorm);
    const float s = slamNorm < 0.0f ? 0.0f : (slamNorm > 1.0f ? 1.0f : slamNorm);
    const float inputGain = slamInputGainLinear();
    if (s <= 1.0e-4f)
        return 0.0f;
    const float drive = inputGain * std::pow (10.0f, slamOutputGainDb (s) / 20.0f);
    const float makeup = slamOutputMakeupLinear();
    int limited = 0;
    for (int i = 0; i < n; ++i)
        if (std::fabs (left[i] * drive) > kSlamPressureKnee
            || std::fabs (right[i] * drive) > kSlamPressureKnee)
            ++limited;
    trench_desk_saturate_stereo (left, right, n, drive);
    for (int i = 0; i < n; ++i)
    {
        left[i] *= makeup;
        right[i] *= makeup;
    }
    return (float) limited / (float) n;
}
inline float finalSafetyCeilingSample (float x) noexcept
{
    if (! std::isfinite (x))
        return 0.0f;
    const float a = std::fabs (x);
    if (a <= kFinalSafetyKnee)
        return x;
    const float span = kFinalSafetyCeiling - kFinalSafetyKnee;
    const float bounded = kFinalSafetyKnee
                        + span * std::tanh ((a - kFinalSafetyKnee) / span);
    return std::copysign (std::fmin (bounded, kFinalSafetyCeiling), x);
}
inline float finalSafetyCeilingBlockStereo (
    float* left, float* right, int n) noexcept
{
    if (left == nullptr || n <= 0)
        return 0.0f;
    int limited = 0;
    const bool stereo = right != nullptr && right != left;
    for (int i = 0; i < n; ++i)
    {
        const bool hit = std::fabs (left[i]) > kFinalSafetyKnee
                      || (stereo && std::fabs (right[i]) > kFinalSafetyKnee);
        if (hit)
            ++limited;
        left[i] = finalSafetyCeilingSample (left[i]);
        if (stereo)
            right[i] = finalSafetyCeilingSample (right[i]);
    }
    return (float) limited / (float) n;
}
inline float slamOutputDriveBlock (float* buf, int n, float slamNorm) noexcept
{
    return slamPostProcess (buf, n, slamGainDb (slamNorm));
}
inline float slamDriveBlock (float* buf, int n, float slamNorm,
                             float headroomDb = kSlamHeadroomDb) noexcept
{
    if (buf == nullptr || n <= 0)
        return 0.0f;
    const float s = slamNorm < 0.0f ? 0.0f : (slamNorm > 1.0f ? 1.0f : slamNorm);
    const float drive  = std::pow (10.0f, (slamGainDb (s) - headroomDb) / 20.0f);
    const float makeup = std::pow (10.0f, (headroomDb * (1.0f - s)) / 20.0f);
    int clipped = 0;
    for (int i = 0; i < n; ++i)
    {
        float y = buf[i] * drive;
        if (y > 1.0f || y < -1.0f) { ++clipped; y = internalClip (y); }
        buf[i] = y * makeup;
    }
    return (float) clipped / (float) n;
}
inline const char* slamStatusLabel (float slamNorm) noexcept
{
    if (slamNorm >= 0.97f) return "HOT";
    const int db = (int) std::lround (slamOutputGainDb (slamNorm));
    switch (db)
    {
        case 0:  return "+0";
        case 3:  return "+3";
        case 6:  return "+6";
        case 9:  return "+9";
        case 12: return "+12";
        default: break;
    }
    if (db < 3)  return "+0";
    if (db < 6)  return "+3";
    if (db < 9)  return "+6";
    if (db < 12) return "+9";
    return "+12";
}
}
