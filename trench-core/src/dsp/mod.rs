/// Exact EmulatorX/X3 table-driven AGC decay/recovery character.
///
/// Verified from `FUN_1802c04e0`: `idx = (gain * abs(sample) as int) & 0xf`.
pub const AGC_TABLE: [f32; 16] = [
    1.0001, 1.0001, 0.996, 0.990, 0.920, 0.500, 0.200, 0.160, 0.120, 0.120, 0.120, 0.120, 0.120,
    0.120, 0.120, 0.120,
];
