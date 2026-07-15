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
};

inline const MovePreset* movePresets (int& countOut) noexcept
{
    static const MovePreset table[] = {
        { "Still", 0, 0, 0, 0, 3, 0.0f, 0.5f, 0.0f, 0.0f, 0.0f, false },
        { "Morph Sweep", 0, 2, 0, 3, 3, 0.35f, 0.5f, 0.0f, 0.0f, 0.0f, true },
        { "Q Pulse", 0, 1, 2, 2, 3, 0.35f, 0.5f, 0.35f, 0.0f, 0.0f, true },
    };
    countOut = (int) (sizeof (table) / sizeof (table[0]));
    return table;
}

} // namespace trench
