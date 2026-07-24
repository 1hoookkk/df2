#pragma once
namespace trench
{
enum class CaptureRange { Hit, Tail, OneBar, FourBar };
struct CapturePlan
{
    double seconds = 0.0;
    bool oneShot = true;
    int beats = 0;
};
inline CapturePlan planCapture (CaptureRange range, double bpm)
{
    const double secPerBeat = (bpm > 0.0) ? 60.0 / bpm : 0.5;
    switch (range)
    {
        case CaptureRange::Hit:     return { 0.6, true,  0 };
        case CaptureRange::Tail:    return { 3.0, true,  0 };
        case CaptureRange::OneBar:  return { secPerBeat * 4.0,  false, 4 };
        case CaptureRange::FourBar: return { secPerBeat * 16.0, false, 16 };
    }
    return { 3.0, true, 0 };
}
}
