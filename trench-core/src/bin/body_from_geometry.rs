use trench_core::cascade::NUM_STAGES;
use trench_core::minifloat::PackedCorners;
use trench_core::stage_law::{words_from_roots, StageRoots};
fn num(obj: &str, key: &str) -> f64 {
    let pat = format!("\"{key}\"");
    let rest = &obj[obj.find(&pat).unwrap_or_else(|| panic!("missing {key}")) + pat.len()..];
    let rest = rest.trim_start().strip_prefix(':').expect("bad json").trim_start();
    let end = rest
        .find(|c: char| !(c.is_ascii_digit() || c == '.' || c == '-' || c == 'e' || c == 'E' || c == '+'))
        .unwrap_or(rest.len());
    rest[..end].parse().unwrap_or_else(|_| panic!("bad number for {key}"))
}
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let (inp, outp) = match &args[..] {
        [_, i, o] => (i.clone(), o.clone()),
        _ => {
            eprintln!("usage: body-from-geometry <in.json> <out.body240>");
            std::process::exit(2);
        }
    };
    let text = std::fs::read_to_string(&inp).expect("read geometry json");
    let mut stages: Vec<StageRoots> = Vec::new();
    let mut rest = text.as_str();
    while let Some(key_at) = rest.find("\"pole_hz\"") {
        let start = rest[..key_at].rfind('{').expect("stage object open brace");
        let obj_end = rest[key_at..].find('}').expect("unterminated stage") + key_at;
        let obj = &rest[start..=obj_end];
        stages.push(StageRoots {
            pole_hz: num(obj, "pole_hz"),
            pole_r: num(obj, "pole_r"),
            zero_hz: num(obj, "zero_hz"),
            zero_r: num(obj, "zero_r"),
            scale: num(obj, "scale"),
        });
        rest = &rest[obj_end + 1..];
    }
    assert_eq!(stages.len(), 4 * NUM_STAGES, "need exactly 4 corners x 6 stages");
    let mut words = [[[0u16; 5]; NUM_STAGES]; 4];
    for (i, s) in stages.iter().enumerate() {
        assert!(s.pole_r < 1.0 && s.pole_r >= 0.0, "pole_r out of range: {s:?}");
        words[i / NUM_STAGES][i % NUM_STAGES] = words_from_roots(s);
    }
    let packed = PackedCorners { words };
    let mut max_r = 0.0f64;
    for mi in 0..25 {
        for qi in 0..25 {
            let rows = packed.interpolate_biquad(mi as f32 / 24.0, qi as f32 / 24.0);
            for row in rows.iter() {
                let (a1, a2) = (row[3] as f64, row[4] as f64);
                for v in row.iter() {
                    assert!(v.is_finite(), "non-finite coeff at grid ({mi},{qi})");
                }
                let disc = a1 * a1 - 4.0 * a2;
                let r = if disc >= 0.0 {
                    let s = disc.sqrt();
                    ((-a1 + s) / 2.0).abs().max(((-a1 - s) / 2.0).abs())
                } else {
                    a2.sqrt()
                };
                max_r = max_r.max(r);
            }
        }
    }
    assert!(max_r < 1.0, "UNSTABLE: max pole radius {max_r} on sampled grid");
    let mut bytes = Vec::with_capacity(240);
    for c in 0..4 {
        for s in 0..NUM_STAGES {
            for w in words[c][s] {
                bytes.extend_from_slice(&w.to_le_bytes());
            }
        }
    }
    std::fs::write(&outp, &bytes).expect("write body240");
    println!("wrote {outp} (sampled-grid max pole radius {max_r:.6})");
}
