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
constexpr float kSlamPressureKnee = 0.72f;
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
    if (s <= 1.0e-4f)
        return 0.0f;
    const float drive = std::pow (10.0f, slamOutputGainDb (s) / 20.0f);
    int limited = 0;
    for (int i = 0; i < n; ++i)
        if (std::fabs (data[i] * drive) > kSlamPressureKnee)
            ++limited;
    trench_desk_saturate_stereo (data, nullptr, n, drive);
    return (float) limited / (float) n;
}
inline float slamOutputPressureBlockStereo (float* left, float* right, int n, float slamNorm) noexcept
{
    if (left == nullptr || right == nullptr || n <= 0)
        return 0.0f;
    if (left == right)
        return slamOutputPressureBlock (left, n, slamNorm);
    const float s = slamNorm < 0.0f ? 0.0f : (slamNorm > 1.0f ? 1.0f : slamNorm);
    if (s <= 1.0e-4f)
        return 0.0f;
    const float drive = std::pow (10.0f, slamOutputGainDb (s) / 20.0f);
    int limited = 0;
    for (int i = 0; i < n; ++i)
        if (std::fabs (left[i] * drive) > kSlamPressureKnee
            || std::fabs (right[i] * drive) > kSlamPressureKnee)
            ++limited;
    trench_desk_saturate_stereo (left, right, n, drive);
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
