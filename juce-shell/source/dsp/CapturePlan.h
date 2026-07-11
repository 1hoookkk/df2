#pragma once

namespace trench
{
// The four Capture ranges the user picks. Hit/Tail are fixed one-shots; the bar
// ranges are tempo-locked loops so a dropped take auto-warps in the DAW.
enum class CaptureRange { Hit, Tail, OneBar, FourBar };

// How long to freeze and how to tag it.
struct CapturePlan
{
    double seconds = 0.0;
    bool oneShot = true;
    int beats = 0; // loop length in beats (0 for one-shots)
};

// Map a range + host tempo (bpm; <=0 = unknown) to a window length and tags. Bar
// ranges lock to the host bar grid; with no tempo they fall back to a musical
// fixed length but stay flagged as loops.
inline CapturePlan planCapture (CaptureRange range, double bpm)
{
    const double secPerBeat = (bpm > 0.0) ? 60.0 / bpm : 0.5; // 0.5s/beat == 120 BPM fallback
    switch (range)
    {
        case CaptureRange::Hit:     return { 0.6, true,  0 };
        case CaptureRange::Tail:    return { 3.0, true,  0 };
        case CaptureRange::OneBar:  return { secPerBeat * 4.0,  false, 4 };
        case CaptureRange::FourBar: return { secPerBeat * 16.0, false, 16 };
    }
    return { 3.0, true, 0 };
}
} // namespace trench
