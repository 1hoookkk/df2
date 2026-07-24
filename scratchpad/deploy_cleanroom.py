import shutil
from pathlib import Path

ROOT = Path(r"C:\Users\hooki\df2-workstation")
CLEAN = Path(r"C:\Users\hooki\df2\dev\tmp\x3_fixed_cleanroom")
BODIES = ROOT / "plugin" / "presets" / "bodies"
ROSTER = ROOT / "plugin" / "presets" / "PresetRoster.inc"

ITEMS = [
    ("6-Pole Lowpass", "x3_shape_6_pole_lowpass"),
    ("Contrary Bandpass", "x3_shape_contrary_bandpass"),
    ("4-Pole Lowpass", "x3_shape_4_pole_lowpass"),
    ("2-Pole Lowpass", "x3_shape_2_pole_lowpass"),
    ("4-Pole Highpass", "x3_shape_4_pole_highpass"),
    ("2-Pole Highpass", "x3_shape_2_pole_highpass"),
    ("4-Pole Bandpass", "x3_shape_4_pole_bandpass"),
    ("2-Pole Bandpass", "x3_shape_2_pole_bandpass"),
    ("Bat Phaser", "x3_shape_bat_phaser"),
    ("Flanger Lite", "x3_shape_flanger_lite"),
    ("Phaser 1", "x3_shape_phaser_1"),
    ("Phaser 2", "x3_shape_phaser_2"),
    ("Vocal Ah-Ay-Ee", "x3_shape_vocal_ah_ay_ee"),
    ("Vocal Oo-Ah", "x3_shape_vocal_oo_ah"),
]

lines = [
    "// Cleanroom E-mu Workhorse Roster",
    "// NO FILTER is injected separately as slot 0; do not list it here.",
]

for label, stem in ITEMS:
    src = CLEAN / stem / f"{stem}.body240"
    dst = BODIES / f"{stem}.body240"
    if src.exists():
        shutil.copy(src, dst)
        lines.append(f'TRENCH_PRESET("{label}", "{stem}", "WORKHORSE")')

ROSTER.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Deployed {len(lines)-2} cleanroom bodies to {BODIES} and updated {ROSTER}.")
