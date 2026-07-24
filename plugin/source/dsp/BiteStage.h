#pragma once
#include <cmath>
#include "SlamStage.h"
namespace trench
{
inline float biteClamp (float x) noexcept { return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); }
inline void biteDriveBlock (float* buf, int n, float clipNorm) noexcept
{
    if (buf == nullptr || n <= 0)
        return;
    const float s = biteClamp (clipNorm);
    if (s <= 1.0e-4f)
        return;
    const float drive = 1.0f + 4.0f * s;
    for (int i = 0; i < n; ++i)
    {
        const float y = internalClip (buf[i] * drive);
        buf[i] = buf[i] + (y - buf[i]) * s;
    }
}
}
