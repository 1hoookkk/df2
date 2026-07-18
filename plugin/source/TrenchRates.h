#pragma once

namespace TrenchRates
{
    static constexpr double emuInternalRate = 39062.5;
    // HD island option: exactly 2x the unit — same geometry, words re-derived
    // at load (trench-core stage_law::reencode_words_at). Never the default.
    static constexpr double emuInternalRateHd = 78125.0;
}
