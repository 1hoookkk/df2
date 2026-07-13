//! PROBE (chunk 1, in progress) — what the seven proven section forms actually
//! are, in the language of the stage law. Not the alphabet yet: evidence first.

#[cfg(test)]
mod probe {
    use crate::compiler::{biquad_to_words, section_biquad, AUTHORING_SR};
    use crate::minifloat::stage_words_to_biquad;
    use crate::stage_law::{geometry_from_words, RootPair};

    /// Each letter with the parameters that show what it is for. NOTCH takes a
    /// negative depth (its gain arg is `min(0)`); the rolloffs are plotted at
    /// unity so the target is the plain filter, not the filter plus a trim.
    const LETTERS: [(&str, i32, f64, f64, f64); 7] = [
        //  name          id    fc      q     gain/depth dB
        ("PEAK", 0, 1200.0, 4.0, 12.0),
        ("CUT / NOTCH", 2, 1200.0, 4.0, -24.0),
        ("LO-SHELF", 1, 1200.0, 4.0, 12.0),
        ("HI-SHELF", 6, 1200.0, 4.0, 12.0),
        ("LOWPASS", 3, 1200.0, 4.0, 0.0),
        ("HIGHPASS", 4, 1200.0, 4.0, 0.0),
        ("BANDPASS", 5, 1200.0, 4.0, 0.0),
    ];

    const NPTS: usize = 256;
    const F_LO: f64 = 20.0;
    const F_HI: f64 = 19_000.0;

    fn db(bq: [f64; 5], hz: f64) -> f64 {
        let [b0, b1, b2, a1, a2] = bq;
        let w = core::f64::consts::TAU * hz / AUTHORING_SR;
        let (c1, s1) = ((-w).cos(), (-w).sin());
        let (c2, s2) = ((-2.0 * w).cos(), (-2.0 * w).sin());
        let n = ((b0 + b1 * c1 + b2 * c2).powi(2) + (b1 * s1 + b2 * s2).powi(2)).sqrt();
        let d = ((1.0 + a1 * c1 + a2 * c2).powi(2) + (a1 * s1 + a2 * s2).powi(2)).sqrt();
        20.0 * (n / d.max(1e-300)).log10()
    }

    fn kind(p: &RootPair) -> String {
        match p {
            RootPair::Conjugate { hz, r } => format!("conjugate · {hz:.0} Hz · r {r:.4}"),
            RootPair::RealPair { root_a, root_b } => format!("REAL · {root_a:+.4} , {root_b:+.4}"),
            RootPair::Degenerate => "origin".to_string(),
        }
    }

    /// Every letter, target vs packed, as data. TARGET is the proven float
    /// section; PACKED is that section after the real five-word round trip —
    /// what the runtime actually plays. Writes JSON for plotting.
    #[test]
    fn plot_every_letter_against_its_target() {
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .join("out");
        std::fs::create_dir_all(&dir).unwrap();

        let freqs: Vec<f64> = (0..NPTS)
            .map(|i| F_LO * (F_HI / F_LO).powf(i as f64 / (NPTS - 1) as f64))
            .collect();

        let mut json = String::from("{\n  \"sr\": 39062.5,\n  \"freqs\": [");
        json.push_str(
            &freqs
                .iter()
                .map(|f| format!("{f:.2}"))
                .collect::<Vec<_>>()
                .join(","),
        );
        json.push_str("],\n  \"letters\": [\n");

        for (i, (name, id, fc, q, gain)) in LETTERS.iter().enumerate() {
            let target = section_biquad(*id, *fc, *q, *gain);
            let words = biquad_to_words(target);
            let packed = stage_words_to_biquad(words);
            let g = geometry_from_words(words);

            let t: Vec<f64> = freqs.iter().map(|&f| db(target, f)).collect();
            let p: Vec<f64> = freqs.iter().map(|&f| db(packed, f)).collect();
            let max_err = t
                .iter()
                .zip(&p)
                .map(|(a, b)| (a - b).abs())
                .fold(0.0f64, f64::max);

            let real_zero = matches!(g.zero, RootPair::RealPair { .. });
            let arr = |v: &[f64]| {
                v.iter()
                    .map(|x| format!("{x:.3}"))
                    .collect::<Vec<_>>()
                    .join(",")
            };
            json.push_str(&format!(
                "    {{\"name\":\"{name}\",\"fc\":{fc},\"q\":{q},\"gain\":{gain},\
                 \"pole\":\"{}\",\"zero\":\"{}\",\"realZero\":{real_zero},\
                 \"maxErrDb\":{max_err:.3},\"words\":[{}],\
                 \"target\":[{}],\"packed\":[{}]}}{}\n",
                kind(&g.pole),
                kind(&g.zero),
                words
                    .iter()
                    .map(|w| w.to_string())
                    .collect::<Vec<_>>()
                    .join(","),
                arr(&t),
                arr(&p),
                if i + 1 == LETTERS.len() { "" } else { "," }
            ));

            println!(
                "{name:<12} max |target - packed| = {max_err:5.2} dB   zero: {}",
                kind(&g.zero)
            );
        }
        json.push_str("  ]\n}\n");

        let path = dir.join("letters.json");
        std::fs::write(&path, json).unwrap();
        println!("\nwrote {}", path.display());
    }
}
