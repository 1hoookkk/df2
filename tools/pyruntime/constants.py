"""Frozen constants — must match runtime/src/lib.rs and trench-core."""
import math

SR = 39062.5
"""Authoring-domain sample rate (Hz). Original hardware: 10 MHz / 256."""

NUM_BODY_STAGES = 12
"""Physical biquad stages in the cascade."""

PLUGIN_SR = 44100.0
"""Plugin runtime sample rate (Hz). Not used in authoring domain."""

TWO_PI = 2.0 * math.pi

FREQ_MIN = 20.0
FREQ_MAX = SR / 2.0 - 1.0  # 19530.25 Hz — just under Nyquist
NUM_RESPONSE_POINTS = 256

ACTOR_RANGES = {
    "Foundation": (20.0, 250.0),
    "Mass": (60.0, 600.0),
    "Throat": (250.0, 2500.0),
    "Bite": (1200.0, 5500.0),
    "Air": (2800.0, 14000.0),
    "Scar": (20.0, 18000.0),
}
