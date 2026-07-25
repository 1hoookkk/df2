//! Native Designer corner/body assembly over the RE-verified firmware word
//! recipe (`heritage::compile_designer_stage`). The oracle is the DIRECT
//! firmware words; nothing here re-derives coefficient math.
use crate::heritage::compile_designer_stage;
use crate::stage_law::{words_from_roots, StageRoots};

pub const NUM_SECTIONS: usize = 6;
pub const WORDS_PER_CORNER: usize = NUM_SECTIONS * 5;
pub const BODY_BYTES: usize = 4 * WORDS_PER_CORNER * 2;

pub const TYPE_BYPASS: i32 = 0;
pub const TYPE_FREE: i32 = 4;

/// One morph endpoint of one section. `freq`/`gain` drive firmware types
/// 1..3; the f64 fields drive TYPE FREE via `words_from_roots`.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct DesignerRow {
    pub freq: i32,
    pub gain: i32,
    pub pole_hz: f64,
    pub pole_r: f64,
    pub zero_hz: f64,
    pub zero_r: f64,
    pub scale: f64,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct DesignerSection {
    pub type_id: i32,
    pub low: DesignerRow,
    pub high: DesignerRow,
}

/// XML header law: shift = -32 + int((frequency + gain) * 63), Python int()
/// truncation semantics.
pub fn heritage_shift(frequency: f64, gain: f64) -> i32 {
    -32 + ((frequency + gain) * 63.0).trunc() as i32
}

/// Python 3 round(): half to even.
fn py_round(x: f64) -> i32 {
    let f = x.floor();
    let d = x - f;
    if d > 0.5 {
        f as i32 + 1
    } else if d < 0.5 {
        f as i32
    } else if (f as i64) % 2 == 0 {
        f as i32
    } else {
        f as i32 + 1
    }
}

fn lerp(a: f64, b: f64, t: f64) -> f64 {
    a + t * (b - a)
}

pub fn compile_section(
    sec: &DesignerSection,
    morph: f64,
    shift: i32,
) -> Result<[u16; 5], &'static str> {
    match sec.type_id {
        TYPE_BYPASS => Ok(words_from_roots(&StageRoots::IDENTITY)),
        1..=3 => {
            let freq = py_round(lerp(sec.low.freq as f64, sec.high.freq as f64, morph));
            let gain = py_round(lerp(sec.low.gain as f64, sec.high.gain as f64, morph));
            if !(0..=127).contains(&freq) || !(0..=127).contains(&gain) {
                return Err("designer freq/gain must be in 0..127");
            }
            compile_designer_stage(sec.type_id as u8, freq as u8, gain as u8, shift)
        }
        TYPE_FREE => {
            let roots = StageRoots {
                pole_hz: lerp(sec.low.pole_hz, sec.high.pole_hz, morph),
                pole_r: lerp(sec.low.pole_r, sec.high.pole_r, morph),
                zero_hz: lerp(sec.low.zero_hz, sec.high.zero_hz, morph),
                zero_r: lerp(sec.low.zero_r, sec.high.zero_r, morph),
                scale: lerp(sec.low.scale, sec.high.scale, morph),
            };
            if [roots.pole_hz, roots.pole_r, roots.zero_hz, roots.zero_r, roots.scale]
                .iter()
                .any(|v| !v.is_finite())
            {
                return Err("designer FREE roots must be finite");
            }
            Ok(words_from_roots(&roots))
        }
        _ => Err("designer type must be 0..4"),
    }
}

/// Compile one corner (30 words). Missing sections pad as identity.
pub fn compile_corner(
    sections: &[DesignerSection],
    morph: f64,
    shift: i32,
) -> Result<[u16; WORDS_PER_CORNER], &'static str> {
    if sections.len() > NUM_SECTIONS {
        return Err("designer takes at most 6 sections");
    }
    let identity = words_from_roots(&StageRoots::IDENTITY);
    let mut out = [0u16; WORDS_PER_CORNER];
    for i in 0..NUM_SECTIONS {
        let words = match sections.get(i) {
            Some(sec) => compile_section(sec, morph, shift)?,
            None => identity,
        };
        out[i * 5..i * 5 + 5].copy_from_slice(&words);
    }
    Ok(out)
}

/// Assemble a .body240: corners (M0,Q0), (M100,Q0), (M0,Q100), (M100,Q100),
/// LE u16. `q0` and `q100` are the two Q-page section sets; heritage bodies
/// pass the same set twice (Q collapsed).
pub fn body_bytes(
    q0: &[DesignerSection],
    q100: &[DesignerSection],
    shift: i32,
) -> Result<[u8; BODY_BYTES], &'static str> {
    let corners = [
        compile_corner(q0, 0.0, shift)?,
        compile_corner(q0, 1.0, shift)?,
        compile_corner(q100, 0.0, shift)?,
        compile_corner(q100, 1.0, shift)?,
    ];
    let mut out = [0u8; BODY_BYTES];
    for (ci, corner) in corners.iter().enumerate() {
        for (wi, w) in corner.iter().enumerate() {
            let at = (ci * WORDS_PER_CORNER + wi) * 2;
            out[at..at + 2].copy_from_slice(&w.to_le_bytes());
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn py_round_is_half_to_even() {
        assert_eq!(py_round(0.5), 0);
        assert_eq!(py_round(1.5), 2);
        assert_eq!(py_round(2.5), 2);
        assert_eq!(py_round(-0.5), 0);
        assert_eq!(py_round(-1.5), -2);
        assert_eq!(py_round(1.4999), 1);
        assert_eq!(py_round(1.5001), 2);
    }

    #[test]
    fn heritage_shift_truncates_like_python_int() {
        assert_eq!(heritage_shift(0.0, 0.0), -32);
        assert_eq!(heritage_shift(0.0, 0.5), -32 + 31);
        assert_eq!(heritage_shift(1.0, 1.0), -32 + 126);
        assert_eq!(heritage_shift(0.9999, 0.0), -32 + 62);
    }

    #[test]
    fn empty_sections_give_identity_body() {
        let body = body_bytes(&[], &[], 0).unwrap();
        let identity = words_from_roots(&StageRoots::IDENTITY);
        for stage in 0..24 {
            for (wi, w) in identity.iter().enumerate() {
                let at = (stage * 5 + wi) * 2;
                assert_eq!(u16::from_le_bytes([body[at], body[at + 1]]), *w);
            }
        }
    }

    #[test]
    fn free_section_matches_words_from_roots() {
        let roots = StageRoots {
            pole_hz: 440.0,
            pole_r: 0.95,
            zero_hz: 880.0,
            zero_r: 0.7,
            scale: 1.0,
        };
        let sec = DesignerSection {
            type_id: TYPE_FREE,
            low: DesignerRow {
                pole_hz: roots.pole_hz,
                pole_r: roots.pole_r,
                zero_hz: roots.zero_hz,
                zero_r: roots.zero_r,
                scale: roots.scale,
                ..Default::default()
            },
            high: DesignerRow::default(),
        };
        assert_eq!(compile_section(&sec, 0.0, 0).unwrap(), words_from_roots(&roots));
    }
}
