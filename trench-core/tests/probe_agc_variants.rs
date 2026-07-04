//! AGC VARIANT PROBE — does taming the AGC give the sound its dynamics back?
//!
//! Follow-up to `probe_sound_chain`, which proved the awake chain levels every
//! input (-24..0 dBFS pink) to ~-13 dB RMS out. This probe renders the same
//! level ladder + transient-hits battery through five AGC variants of the
//! P2k_013_talking_hedz body:
//!   stock          — awake chain as shipped (agc_drive 4, slam 0.6)
//!   adapt_x0_25    — AGC adaptation 4x slower  (debug.agc_rate_scale = 0.25)
//!   adapt_x0_05    — AGC adaptation 20x slower (debug.agc_rate_scale = 0.05)
//!   clamp_6db      — AGC cut floored at 6 dB   (debug.agc_max_cut_db = 6.0)
//!   bypass_makeup  — AGC bypassed + fixed makeup calibrated so the -12 dBFS
//!                    ladder rung matches stock's output level
//! Plus the coefficient-ramp A/B: 8 s morph ramp at coeff_ramp_scale 1 / 0.25 / 4.
//!
//! Prints per-variant gain tables and per-hit peak spread; writes WAVs + index
//! HTML to dev/tmp/sound_probe/agc_variants/.
//!
//! Run: cargo test -p trench-core --test probe_agc_variants -- --ignored --nocapture

use trench_core::{Cartridge, FilterEngine, InputMode};

const BODY: &str = "P2k_013_talking_hedz";
const SR_EMU: f64 = 39_062.5;
const OUT_SR: u32 = 48_000;
const BLOCK: usize = 256;

#[derive(Clone, Copy)]
struct Variant {
    tag: &'static str,
    rate_scale: f32,
    max_cut_db: f32,
    bypass: bool,
    makeup: f32,
}

fn load_body(root: &std::path::Path, fav: &str) -> Option<Vec<u8>> {
    let dir = root.join("ref/p2k_variants").join(fav);
    let path = std::fs::read_dir(&dir).ok().and_then(|rd| {
        rd.flatten().map(|e| e.path()).find(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.starts_with("variant_0_") && n.ends_with(".bin"))
                .unwrap_or(false)
        })
    })?;
    std::fs::read(&path).ok()
}

fn make_engine(bytes: &[u8], v: &Variant) -> FilterEngine {
    let cart = Cartridge::from_body_bytes(BODY, bytes, 1.0).expect("body load");
    let mut eng = FilterEngine::new();
    eng.prepare(SR_EMU);
    eng.load_cartridge(cart);
    // Awake chain, identical to probe_sound_chain's `awake` config…
    eng.debug.agc_enabled = true;
    eng.set_agc_drive(4.0);
    eng.set_input_mode(InputMode::MackieDeskSlam);
    eng.set_slam_drive(0.6);
    // …plus the variant's debug knobs.
    eng.debug.agc_rate_scale = v.rate_scale;
    eng.debug.agc_max_cut_db = v.max_cut_db;
    eng.debug.agc_bypass = v.bypass;
    eng.debug.agc_makeup_gain = v.makeup;
    eng
}

fn process(eng: &mut FilterEngine, dry: &[f32], morph_fn: impl Fn(usize) -> (f64, f64)) -> Vec<f32> {
    let mut wet = Vec::with_capacity(dry.len());
    let mut off = 0usize;
    while off < dry.len() {
        let len = BLOCK.min(dry.len() - off);
        let mut l = dry[off..off + len].to_vec();
        let mut r = l.clone();
        let (m, q) = morph_fn(off);
        eng.process_block(&mut l, &mut r, m, q);
        wet.extend_from_slice(&l);
        off += len;
    }
    wet
}

// deterministic pink-ish noise — identical generator to probe_sound_chain
fn pink(n: usize, amp: f32, seed: u64) -> Vec<f32> {
    let mut s = seed.max(1);
    let mut b0 = 0f32;
    let mut b1 = 0f32;
    let mut b2 = 0f32;
    (0..n)
        .map(|_| {
            s ^= s << 13;
            s ^= s >> 7;
            s ^= s << 17;
            let w = ((s as f64 / u64::MAX as f64) as f32 - 0.5) * 2.0;
            b0 = 0.997 * b0 + 0.029591 * w;
            b1 = 0.985 * b1 + 0.032534 * w;
            b2 = 0.950 * b2 + 0.048056 * w;
            (b0 + b1 + b2 + w * 0.05) * amp
        })
        .collect()
}

fn saw(n: usize, freq: f64, amp: f32, fade: usize) -> Vec<f32> {
    let mut phase = 0f64;
    (0..n)
        .map(|i| {
            phase = (phase + freq / SR_EMU).fract();
            let env = (i as f32 / fade as f32)
                .min(1.0)
                .min((n - 1 - i) as f32 / fade as f32)
                .max(0.0);
            ((phase * 2.0 - 1.0) as f32) * amp * env
        })
        .collect()
}

// 8 transient hits — identical pattern to probe_sound_chain's dry_hits
fn hits(total: usize, spacing: usize, hit_len: usize, amp: f32) -> Vec<f32> {
    let mut out = vec![0f32; total];
    let mut phase = 0f64;
    let mut k = 0usize;
    while k * spacing + hit_len < total {
        let start = k * spacing;
        for i in 0..hit_len {
            phase = (phase + 82.4 / SR_EMU).fract(); // E2 — punchy bass hit
            let env = (-4.0 * i as f32 / hit_len as f32).exp();
            out[start + i] = ((phase * 2.0 - 1.0) as f32) * amp * env;
        }
        k += 1;
    }
    out
}

fn rms_db(x: &[f32]) -> f32 {
    let ms = x.iter().map(|s| s * s).sum::<f32>() / x.len().max(1) as f32;
    10.0 * (ms.max(1e-12)).log10()
}

fn peak_db(x: &[f32]) -> f32 {
    let p = x.iter().fold(0f32, |m, s| m.max(s.abs()));
    20.0 * p.max(1e-9).log10()
}

fn resample_48k(wet: &[f32]) -> Vec<f32> {
    let ratio = SR_EMU / OUT_SR as f64;
    let out_n = (wet.len() as f64 / ratio) as usize;
    (0..out_n)
        .map(|i| {
            let p = i as f64 * ratio;
            let i0 = p.floor() as usize;
            let frac = (p - i0 as f64) as f32;
            let a = wet.get(i0).copied().unwrap_or(0.0);
            let b = wet.get(i0 + 1).copied().unwrap_or(a);
            a + (b - a) * frac
        })
        .collect()
}

fn write_wav(path: &std::path::Path, samples: &[f32], sr: u32) {
    let data_len = (samples.len() * 2) as u32;
    let mut b: Vec<u8> = Vec::with_capacity(44 + data_len as usize);
    b.extend_from_slice(b"RIFF");
    b.extend_from_slice(&(36 + data_len).to_le_bytes());
    b.extend_from_slice(b"WAVE");
    b.extend_from_slice(b"fmt ");
    b.extend_from_slice(&16u32.to_le_bytes());
    b.extend_from_slice(&1u16.to_le_bytes());
    b.extend_from_slice(&1u16.to_le_bytes());
    b.extend_from_slice(&sr.to_le_bytes());
    b.extend_from_slice(&(sr * 2).to_le_bytes());
    b.extend_from_slice(&2u16.to_le_bytes());
    b.extend_from_slice(&16u16.to_le_bytes());
    b.extend_from_slice(b"data");
    b.extend_from_slice(&data_len.to_le_bytes());
    for &s in samples {
        b.extend_from_slice(&((s.clamp(-1.0, 1.0) * 32767.0) as i16).to_le_bytes());
    }
    std::fs::write(path, b).expect("write wav");
}

#[test]
#[ignore = "renders the AGC-variant probe battery to dev/tmp/sound_probe/agc_variants"]
fn probe_agc_variants() {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let out_root = root.join("dev/tmp/sound_probe/agc_variants");
    std::fs::create_dir_all(&out_root).expect("mkdir");

    let bytes = load_body(&root, BODY).expect("body bin missing: ref/p2k_variants");

    let ladder_seg = (SR_EMU * 0.8) as usize;
    let ramp_n = (SR_EMU * 8.0) as usize;
    let hit_spacing = (SR_EMU * 0.32) as usize;
    let hit_len = (SR_EMU * 0.14) as usize;
    let hits_n = hit_spacing * 8 + hit_len;
    let dry_hits = hits(hits_n, hit_spacing, hit_len, 0.85);
    write_wav(&out_root.join("dry_hits.wav"), &resample_48k(&dry_hits), OUT_SR);

    // --- Calibrate bypass makeup: match stock's output on the -12 dBFS rung ---
    let cal_noise = pink(ladder_seg, 10f32.powf(-12.0 / 20.0) * 0.7, 0x9E3779B9 + 2);
    let stock_v = Variant { tag: "stock", rate_scale: 1.0, max_cut_db: f32::INFINITY, bypass: false, makeup: 1.0 };
    let mut eng = make_engine(&bytes, &stock_v);
    let stock_cal = rms_db(&process(&mut eng, &cal_noise, |_| (0.5, 0.5)));
    let bypass_unity = Variant { tag: "bypass_cal", rate_scale: 1.0, max_cut_db: f32::INFINITY, bypass: true, makeup: 1.0 };
    let mut eng = make_engine(&bytes, &bypass_unity);
    let bypass_cal = rms_db(&process(&mut eng, &cal_noise, |_| (0.5, 0.5)));
    let makeup = 10f32.powf((stock_cal - bypass_cal) / 20.0);
    println!(
        "bypass makeup calibration @ -12 dBFS rung: stock out {stock_cal:.1} dB, bypass(unity) out {bypass_cal:.1} dB -> makeup {:.2}x ({:+.1} dB)",
        makeup,
        20.0 * makeup.log10()
    );

    let variants = [
        stock_v,
        Variant { tag: "adapt_x0_25", rate_scale: 0.25, max_cut_db: f32::INFINITY, bypass: false, makeup: 1.0 },
        Variant { tag: "adapt_x0_05", rate_scale: 0.05, max_cut_db: f32::INFINITY, bypass: false, makeup: 1.0 },
        Variant { tag: "clamp_6db", rate_scale: 1.0, max_cut_db: 6.0, bypass: false, makeup: 1.0 },
        Variant { tag: "bypass_makeup", rate_scale: 1.0, max_cut_db: f32::INFINITY, bypass: true, makeup },
    ];

    let mut html = String::from(
        "<!doctype html><meta charset=utf-8><title>AGC VARIANTS — talking_hedz</title>\
         <style>body{background:#0a0c12;color:#cdd6e2;font:13px ui-monospace,monospace;padding:24px}\
         h1{font-size:15px;color:#e0608a;font-weight:400}h2{font-size:13px;color:#60c8e0;font-weight:400;margin:20px 0 4px}\
         .row{display:flex;align-items:center;gap:14px;padding:6px 0;border-bottom:1px solid #232838}\
         .n{width:380px}audio{height:30px}.k{color:#68748a}pre{color:#8fa3bd}</style>\
         <h1>AGC VARIANT PROBE — P2k_013_talking_hedz</h1>\
         <div class=k>ladder = -24/-18/-12/-6/0 dBFS pink · hits = 8 equal transient bass hits \
         (spread should be ~0 dB if dynamics survive)</div>\
         <h2>dry reference</h2>\
         <div class=row><span class=n>dry hits</span><audio controls preload=none src=dry_hits.wav></audio></div>",
    );

    for v in &variants {
        println!("\n=== variant {} ===", v.tag);
        html.push_str(&format!("<h2>{}</h2>", v.tag));

        // --- Level ladder (format identical to probe_sound_chain) ---
        let mut ladder_wet: Vec<f32> = Vec::new();
        let mut gain_lines = String::new();
        println!("L ladder (in dBFS -> out RMS dB, delta):");
        let mut gains: Vec<f32> = Vec::new();
        for (k, in_db) in [-24.0f32, -18.0, -12.0, -6.0, 0.0].iter().enumerate() {
            let amp = 10f32.powf(in_db / 20.0) * 0.7;
            let noise = pink(ladder_seg, amp, 0x9E3779B9 + k as u64);
            let in_rms = rms_db(&noise);
            let mut eng = make_engine(&bytes, v);
            let wet = process(&mut eng, &noise, |_| (0.5, 0.5));
            let out_rms = rms_db(&wet);
            let g = out_rms - in_rms;
            gains.push(g);
            let line = format!(
                "  {in_db:>6.1} | in {in_rms:>6.1} -> out {out_rms:>6.1} | gain {g:>5.1} dB"
            );
            println!("{line}");
            gain_lines.push_str(&line);
            gain_lines.push('\n');
            ladder_wet.extend_from_slice(&wet);
            ladder_wet.extend(std::iter::repeat(0f32).take(2000));
        }
        // dynamics retention = how much of the 24 dB input span survives to the output
        let out_span = *gains.last().unwrap() - *gains.first().unwrap() + 24.0;
        println!("  output span across 24 dB input span: {out_span:.1} dB (24.0 = fully preserved)");
        let f = format!("{}_L_ladder.wav", v.tag);
        write_wav(&out_root.join(&f), &resample_48k(&ladder_wet), OUT_SR);
        html.push_str(&format!(
            "<pre>{gain_lines}  output span across 24 dB input span: {out_span:.1} dB</pre>\
             <div class=row><span class=n>L ladder -24/-18/-12/-6/0 dBFS pink</span><audio controls preload=none src=\"{f}\"></audio></div>"
        ));

        // --- Hits battery, continuous stream, per-hit peak spread ---
        let mut eng = make_engine(&bytes, v);
        let wet = process(&mut eng, &dry_hits, |_| (0.6, 0.55));
        let mut peaks: Vec<f32> = Vec::new();
        for k in 0..8 {
            let s = k * hit_spacing;
            let e = (s + hit_spacing).min(wet.len());
            peaks.push(peak_db(&wet[s..e]));
        }
        let pmax = peaks.iter().cloned().fold(f32::MIN, f32::max);
        let pmin = peaks.iter().cloned().fold(f32::MAX, f32::min);
        let spread = pmax - pmin;
        let peaks_str = peaks.iter().map(|p| format!("{p:>6.1}")).collect::<Vec<_>>().join(" ");
        println!("C hits: per-hit peaks dB [{peaks_str}]  spread {spread:.1} dB  rms {:.1} dB", rms_db(&wet));
        let f = format!("{}_C_hits.wav", v.tag);
        write_wav(&out_root.join(&f), &resample_48k(&wet), OUT_SR);
        html.push_str(&format!(
            "<pre>per-hit peaks dB [{peaks_str}]  spread {spread:.1} dB</pre>\
             <div class=row><span class=n>C hits (continuous, 8 equal transients)</span><audio controls preload=none src=\"{f}\"></audio></div>"
        ));
    }

    // --- Cascade interpolation ramp A/B: stock vs 4x shorter vs 4x longer ---
    // Reachable via the debug knob `coeff_ramp_scale` (scales the ramp_samples
    // handed to Cascade::set_targets each control chunk).
    println!("\n=== coeff ramp A/B (8s morph ramp, stock AGC) ===");
    html.push_str("<h2>coeff ramp A/B — 8 s morph ramp (stock AGC chain)</h2>");
    let ramp_dry = saw(ramp_n, 55.0, 0.5, 2000);
    for (tag, scale) in [("ramp_x1", 1.0f32), ("ramp_x0_25", 0.25), ("ramp_x4", 4.0)] {
        let mut eng = make_engine(&bytes, &stock_v);
        eng.debug.coeff_ramp_scale = scale;
        let wet = process(&mut eng, &ramp_dry, |off| ((off as f64 / ramp_n as f64).min(1.0), 0.35));
        println!("  {tag}: rms {:.1} dB peak {:.1} dB", rms_db(&wet), peak_db(&wet));
        let f = format!("M_morphramp_{tag}.wav");
        write_wav(&out_root.join(&f), &resample_48k(&wet), OUT_SR);
        html.push_str(&format!(
            "<div class=row><span class=n>morph ramp, coeff_ramp_scale {scale}</span><audio controls preload=none src=\"{f}\"></audio></div>"
        ));
    }

    // --- Attribution: which stage levels? Bypass AGC, then also strip the desk
    // slam input stage, then also the output saturator. Gain table per config.
    println!("\n=== leveling attribution (AGC bypassed, unity makeup) ===");
    html.push_str("<h2>leveling attribution — AGC bypassed, strip stages one by one</h2><pre>");
    for (tag, slam_on, sat_on) in [
        ("no_agc__slam_on__sat_on", true, true),
        ("no_agc__slam_off__sat_on", false, true),
        ("no_agc__slam_off__sat_off", false, false),
    ] {
        let mut gains: Vec<f32> = Vec::new();
        for (k, in_db) in [-24.0f32, -18.0, -12.0, -6.0, 0.0].iter().enumerate() {
            let amp = 10f32.powf(in_db / 20.0) * 0.7;
            let noise = pink(ladder_seg, amp, 0x9E3779B9 + k as u64);
            let in_rms = rms_db(&noise);
            let mut eng = make_engine(&bytes, &bypass_unity);
            if !slam_on {
                eng.set_input_mode(InputMode::None);
                eng.set_slam_drive(0.0);
            }
            eng.debug.saturation_enabled = sat_on;
            let wet = process(&mut eng, &noise, |_| (0.5, 0.5));
            gains.push(rms_db(&wet) - in_rms);
        }
        let span = *gains.last().unwrap() - *gains.first().unwrap() + 24.0;
        let gains_str = gains.iter().map(|g| format!("{g:>6.1}")).collect::<Vec<_>>().join(" ");
        let line = format!("  {tag:<28} gains [{gains_str}]  span {span:>5.1} dB");
        println!("{line}");
        html.push_str(&line);
        html.push('\n');
    }
    html.push_str("</pre>");

    let page = out_root.join("index.html");
    std::fs::write(&page, html).expect("write html");
    println!("\nopen: {}", page.display());
}
