//! Packed compiler for the retained six-section Morph Designer grammar.
//!
//! Input values are the XML's 0..127 `freq`/`gain` endpoint fields. Output is
//! one direct five-word runtime stage. This module owns no catalog or preset
//! names; the workstation reads those from the external source directory.

use crate::stage_law::{words_from_roots, StageRoots};

const FW_BASE: i32 = 18;
const FW_SCALE: i32 = 220;

/// Compile one source section at one authored endpoint to its direct packed
/// runtime words. Type 0 is the exact identity stage.
pub fn compile_designer_stage(
    type_id: u8,
    freq: u8,
    gain: u8,
    global_shift: i32,
) -> Result<[u16; 5], &'static str> {
    if freq > 127 || gain > 127 {
        return Err("designer freq/gain must be in 0..127");
    }
    if type_id == 0 {
        return Ok(words_from_roots(&StageRoots::IDENTITY));
    }

    let fv = (FW_SCALE * i32::from(freq)) / 128 + FW_BASE;
    let radius = (fv * 124) / 256 + 118;
    let gain_offset = ((i32::from(gain) - 64).div_euclid(2) + global_shift).clamp(-32, 31);
    let byte_word = |value: i32| -> u16 { ((value.clamp(0, 255) as u16) << 8) as u16 };

    match type_id {
        1 => Ok([
            byte_word(fv),
            byte_word(radius + gain_offset),
            byte_word(fv),
            byte_word(radius - gain_offset),
            0xE000,
        ]),
        2 => Ok([
            0xEC00,
            0xFF00,
            byte_word(fv),
            byte_word(radius - gain_offset),
            (((fv + 0xF5) << 8) & 0xFFFF) as u16,
        ]),
        3 => {
            // The source recipe compresses emitted word 2 only. Radius and
            // the low-rate scale word retain the uncompressed frequency.
            let compressed = if fv > 0xDB && gain_offset < 0 {
                (((fv - 220) * (gain_offset + 32)) >> 5) + 220
            } else {
                fv
            };
            let scale_word = ((fv - 18) * -12 - 8192) & 0xFFFF;
            Ok([
                byte_word(FW_BASE),
                byte_word((FW_BASE * 124) / 256 + 150),
                byte_word(compressed),
                byte_word(radius - gain_offset),
                scale_word as u16,
            ])
        }
        _ => Err("designer type must be 0, 1, 2, or 3"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::minifloat::stage_words_to_biquad;

    #[test]
    fn type_zero_is_exact_runtime_identity() {
        let words = compile_designer_stage(0, 127, 127, 31).unwrap();
        assert_eq!(stage_words_to_biquad(words), [1.0, 0.0, 0.0, 0.0, 0.0]);
    }

    #[test]
    fn type_three_compresses_only_its_emitted_frequency_word() {
        let words = compile_designer_stage(3, 127, 0, 0).unwrap();
        let raw_fv = (FW_SCALE * 127) / 128 + FW_BASE;
        let offset = ((0 - 64_i32).div_euclid(2)).clamp(-32, 31);
        let compressed = (((raw_fv - 220) * (offset + 32)) >> 5) + 220;
        assert_eq!(words[2], (compressed as u16) << 8);
        assert_eq!(words[4], (((raw_fv - 18) * -12 - 8192) & 0xFFFF) as u16);
    }
}
