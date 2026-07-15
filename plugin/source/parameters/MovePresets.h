#pragma once

#include "TrenchParameters.h"

namespace trench
{

struct MovePreset
{
    const char* name;
    int body;
    int modulation;
    int shape;
    int time;
    int mode;
    float tension;
    float morph;
    float q;
    float slam;
    float outputDb;
    bool moveOn;
    float fiveD;   // QSound SPACE depth 0..1 (0 = no spatial stage)
};

inline const MovePreset* movePresets (int& countOut) noexcept
{
    static const MovePreset table[] = {
        { "Still",       0, 0, 0, 0, 3, 0.0f,  0.5f, 0.0f,  0.0f, 0.0f, false, 0.0f },
        { "Morph Sweep", 0, 2, 0, 3, 3, 0.35f, 0.5f, 0.0f,  0.0f, 0.0f, true,  0.0f },
        { "Q Pulse",     0, 1, 2, 2, 3, 0.35f, 0.5f, 0.35f, 0.0f, 0.0f, true,  0.0f },
        // Orbit — the QSound showcase: AutoHalf morph motion (tone) + head-orbit
        // (fiveD). slam=0 so the desk never smears the orbiting width.
        { "Orbit",       0, 3, 3, 4, 3, 0.5f,  0.5f, 0.30f, 0.0f, 0.0f, false, 0.6f },
    };
    countOut = (int) (sizeof (table) / sizeof (table[0]));
    return table;
}

} // namespace trench
