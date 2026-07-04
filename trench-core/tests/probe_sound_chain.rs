//! COMPLEX PROBE — "why isn't the sound THERE?" — chain isolation, not filter math.
//!
//! Four sub-probes per demo body, everything through the REAL engine:
//!   B  filter_only vs full_chain   (what the AGC+desk stage adds/removes)
//!   L  level ladder into the full chain (the AGC engagement curve — pink
//!      noise at -24/-18/-12/-6/0 dBFS; prints an in/out gain table)
//!   M  slow morph ramp (interpolation/zipper behaviour on a sustained saw)
//!   C  context: 8 transient hits processed as a continuous stream vs a
//!      FRESH engine per hit (the per-voice question)
//! Plus the DRY battery for reference. WAVs + index page to dev/tmp/sound_probe.
//!
//! Run: cargo test -p trench-core --test probe_sound_chain -- --ignored --nocapture

use trench_core::{Cartridge, FilterEngine, InputMode};

const BODIES: &[&str] = &[
    "P2k_013_talking_hedz",
    "P2k_004_meaty_gizmo",
    "P2k_029_lucifer_s_q",
];

const SR_EMU: f64 = 39_062.5;
const OUT_SR: u32 = 48_000;
const BLOCK: usize = 256;

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

fn make_engine(bytes: &[u8], name: &str, awake: bool) -> FilterEngine {
    let cart = Cartridge::from_body_bytes(name, bytes, 1.0).expect("body load");
    let mut eng = FilterEngine::new();
    eng.prepare(SR_EMU);
    eng.load_cartridge(cart);
    if awake {
        eng.debug.agc_enabled = true;
        eng.set_agc_drive(4.0);
        eng.set_input_mode(InputMode::MackieDeskSlam);
        eng.set_slam_drive(0.6);
    } else {
        eng.debug.agc_enabled = false;
        eng.set_input_mode(InputMode::None);
        eng.set_slam_drive(0.0);
    }
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

// deterministic pink-ish noise (xorshift white through a one-pole lowpass stack)
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

// 8 transient hits: saw bursts with a fast exponential decay, spaced apart
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
#[ignore = "renders the chain-isolation probe battery to dev/tmp/sound_probe"]
fn probe_sound_chain() {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let out_root = root.join("dev/tmp/sound_probe");
    std::fs::create_dir_all(&out_root).expect("mkdir");

    let seg = (SR_EMU * 1.2) as usize;
    let ladder_seg = (SR_EMU * 0.8) as usize;
    let ramp_n = (SR_EMU * 8.0) as usize;
    let hit_spacing = (SR_EMU * 0.32) as usize;
    let hit_len = (SR_EMU * 0.14) as usize;
    let hits_n = hit_spacing * 8 + hit_len;

    // DRY battery, written once
    let dry_saw = saw(seg, 55.0, 0.5, 600);
    let dry_hits = hits(hits_n, hit_spacing, hit_len, 0.85);
    write_wav(&out_root.join("dry_saw.wav"), &resample_48k(&dry_saw), OUT_SR);
    write_wav(&out_root.join("dry_hits.wav"), &resample_48k(&dry_hits), OUT_SR);

    let mut html = String::from(
        "<!doctype html><meta charset=utf-8><title>SOUND PROBE — chain isolation</title>\
         <style>body{background:#0a0c12;color:#cdd6e2;font:13px ui-monospace,monospace;padding:24px}\
         h1{font-size:15px;color:#e0608a;font-weight:400}h2{font-size:13px;color:#60c8e0;font-weight:400;margin:20px 0 4px}\
         .row{display:flex;align-items:center;gap:14px;padding:6px 0;border-bottom:1px solid #232838}\
         .n{width:340px}audio{height:30px}.k{color:#68748a}</style>\
         <h1>SOUND PROBE — is it the filter, the chain, or the context?</h1>\
         <div class=k>B: filter_only vs full_chain &nbsp;·&nbsp; L: level ladder (AGC engagement) \
         &nbsp;·&nbsp; M: morph ramp &nbsp;·&nbsp; C: continuous vs per-hit fresh engine</div>\
         <h2>dry reference</h2>\
         <div class=row><span class=n>dry saw</span><audio controls preload=none src=dry_saw.wav></audio></div>\
         <div class=row><span class=n>dry hits</span><audio controls preload=none src=dry_hits.wav></audio></div>",
    );

    for fav in BODIES {
        let Some(bytes) = load_body(&root, fav) else {
            println!("SKIP {fav}: no body bin");
            continue;
        };
        println!("\n=== {fav} ===");
        html.push_str(&format!("<h2>{fav}</h2>"));

        // --- B: filter_only vs full_chain, saw at MIDDLE then 85/30 ---
        for (tag, awake) in [("filter_only", false), ("full_chain", true)] {
            let mut eng = make_engine(&bytes, fav, awake);
            let mut wet = process(&mut eng, &dry_saw, |_| (0.5, 0.5));
            let mut eng2 = make_engine(&bytes, fav, awake);
            wet.extend(process(&mut eng2, &dry_saw, |_| (0.85, 0.3)));
            let f = format!("{fav}_B_{tag}.wav");
            write_wav(&out_root.join(&f), &resample_48k(&wet), OUT_SR);
            println!("B {tag}: rms {:.1} dB", rms_db(&wet));
            html.push_str(&format!(
                "<div class=row><span class=n>B {tag} (mid, then 85/30)</span><audio controls preload=none src=\"{f}\"></audio></div>"
            ));
        }

        // --- L: level ladder, pink noise, full chain, MIDDLE ---
        let mut ladder_wet: Vec<f32> = Vec::new();
        println!("L ladder (in dBFS -> out RMS dB, delta):");
        for (k, in_db) in [-24.0f32, -18.0, -12.0, -6.0, 0.0].iter().enumerate() {
            let amp = 10f32.powf(in_db / 20.0) * 0.7;
            let noise = pink(ladder_seg, amp, 0x9E3779B9 + k as u64);
            let in_rms = rms_db(&noise);
            let mut eng = make_engine(&bytes, fav, true);
            let wet = process(&mut eng, &noise, |_| (0.5, 0.5));
            let out_rms = rms_db(&wet);
            println!("  {in_db:>6.1} | in {in_rms:>6.1} -> out {out_rms:>6.1} | gain {:>5.1} dB", out_rms - in_rms);
            ladder_wet.extend_from_slice(&wet);
            ladder_wet.extend(std::iter::repeat(0f32).take(2000));
        }
        let f = format!("{fav}_L_ladder.wav");
        write_wav(&out_root.join(&f), &resample_48k(&ladder_wet), OUT_SR);
        html.push_str(&format!(
            "<div class=row><span class=n>L ladder -24/-18/-12/-6/0 dBFS pink</span><audio controls preload=none src=\"{f}\"></audio></div>"
        ));

        // --- M: 8s morph ramp on the saw, full chain ---
        let ramp_dry = saw(ramp_n, 55.0, 0.5, 2000);
        let mut eng = make_engine(&bytes, fav, true);
        let wet = process(&mut eng, &ramp_dry, |off| ((off as f64 / ramp_n as f64).min(1.0), 0.35));
        let f = format!("{fav}_M_morphramp.wav");
        write_wav(&out_root.join(&f), &resample_48k(&wet), OUT_SR);
        html.push_str(&format!(
            "<div class=row><span class=n>M morph ramp 0→1 over 8s (q 35)</span><audio controls preload=none src=\"{f}\"></audio></div>"
        ));

        // --- C: continuous stream vs fresh engine per hit ---
        let mut eng = make_engine(&bytes, fav, true);
        let cont = process(&mut eng, &dry_hits, |_| (0.6, 0.55));
        let f1 = format!("{fav}_C_continuous.wav");
        write_wav(&out_root.join(&f1), &resample_48k(&cont), OUT_SR);

        let mut fresh: Vec<f32> = Vec::with_capacity(dry_hits.len());
        let mut pos = 0usize;
        while pos < dry_hits.len() {
            let end = (pos + hit_spacing).min(dry_hits.len());
            let mut e = make_engine(&bytes, fav, true); // fresh voice per hit
            fresh.extend(process(&mut e, &dry_hits[pos..end], |_| (0.6, 0.55)));
            pos = end;
        }
        let f2 = format!("{fav}_C_perhit.wav");
        write_wav(&out_root.join(&f2), &resample_48k(&fresh), OUT_SR);
        println!("C: continuous rms {:.1} dB | per-hit rms {:.1} dB", rms_db(&cont), rms_db(&fresh));
        html.push_str(&format!(
            "<div class=row><span class=n>C continuous stream</span><audio controls preload=none src=\"{f1}\"></audio></div>\
             <div class=row><span class=n>C fresh engine per hit (the per-voice question)</span><audio controls preload=none src=\"{f2}\"></audio></div>"
        ));
    }

    let page = out_root.join("probe.html");
    std::fs::write(&page, html).expect("write html");
    println!("\nopen: {}", page.display());
}
