//! REAL-MATERIAL A/B — the voicing decision on an actual break, not test tones.
//!
//! Renders DL_Classic Break through Talking Hedz with a slow morph sweep:
//!   stock     = the current awake chain (agc 4.0, slam 0.6)  — the leveler trio
//!   candidate = proposed voicing: slam 0.15 (teeth, not leveling),
//!               AGC floored at 8 dB max cut (transient shaper, not normalizer)
//! Both renders are loudness-matched afterwards so the A/B is fair.
//!
//! Run: cargo test -p trench-core --test probe_real_material -- --ignored --nocapture

use trench_core::{Cartridge, FilterEngine, InputMode};

const SR_EMU: f64 = 39_062.5;
const OUT_SR: u32 = 48_000;
const BLOCK: usize = 256;
const BREAK_WAV: &str = r"C:\Program Files\Image-Line\FL Studio 11\Data\Patches\Packs\Legacy\Loops\DL_Classic Break.wav";

fn read_wav_mono(path: &str) -> (Vec<f32>, u32) {
    let b = std::fs::read(path).expect("read wav");
    assert!(&b[0..4] == b"RIFF" && &b[8..12] == b"WAVE", "not a wav");
    let mut pos = 12usize;
    let mut sr = 44100u32;
    let mut channels = 1u16;
    let mut bits = 16u16;
    let mut data: Vec<f32> = Vec::new();
    while pos + 8 <= b.len() {
        let id = &b[pos..pos + 4];
        let size = u32::from_le_bytes([b[pos + 4], b[pos + 5], b[pos + 6], b[pos + 7]]) as usize;
        let body = pos + 8;
        if id == b"fmt " {
            channels = u16::from_le_bytes([b[body + 2], b[body + 3]]);
            sr = u32::from_le_bytes([b[body + 4], b[body + 5], b[body + 6], b[body + 7]]);
            bits = u16::from_le_bytes([b[body + 14], b[body + 15]]);
        } else if id == b"data" {
            let end = (body + size).min(b.len());
            match bits {
                16 => {
                    let mut i = body;
                    while i + 2 * channels as usize <= end {
                        let mut acc = 0f32;
                        for c in 0..channels as usize {
                            let v = i16::from_le_bytes([b[i + 2 * c], b[i + 2 * c + 1]]);
                            acc += v as f32 / 32768.0;
                        }
                        data.push(acc / channels as f32);
                        i += 2 * channels as usize;
                    }
                }
                24 => {
                    let mut i = body;
                    while i + 3 * channels as usize <= end {
                        let mut acc = 0f32;
                        for c in 0..channels as usize {
                            let o = i + 3 * c;
                            let v = i32::from_le_bytes([0, b[o], b[o + 1], b[o + 2]]) >> 8;
                            acc += v as f32 / 8_388_608.0;
                        }
                        data.push(acc / channels as f32);
                        i += 3 * channels as usize;
                    }
                }
                32 => {
                    let mut i = body;
                    while i + 4 * channels as usize <= end {
                        let mut acc = 0f32;
                        for c in 0..channels as usize {
                            let o = i + 4 * c;
                            acc += f32::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]]);
                        }
                        data.push(acc / channels as f32);
                        i += 4 * channels as usize;
                    }
                }
                _ => panic!("unsupported bit depth {bits}"),
            }
        }
        pos = body + size + (size & 1);
    }
    assert!(!data.is_empty(), "no data chunk");
    (data, sr)
}

fn resample_linear(x: &[f32], from: f64, to: f64) -> Vec<f32> {
    let ratio = from / to;
    let n = (x.len() as f64 / ratio) as usize;
    (0..n)
        .map(|i| {
            let p = i as f64 * ratio;
            let i0 = p.floor() as usize;
            let f = (p - i0 as f64) as f32;
            let a = x.get(i0).copied().unwrap_or(0.0);
            let b = x.get(i0 + 1).copied().unwrap_or(a);
            a + (b - a) * f
        })
        .collect()
}

fn rms(x: &[f32]) -> f32 {
    (x.iter().map(|s| s * s).sum::<f32>() / x.len().max(1) as f32).sqrt()
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
#[ignore = "renders the real-material voicing A/B to dev/tmp/sound_probe/real_material"]
fn probe_real_material() {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let out = root.join("dev/tmp/sound_probe/real_material");
    std::fs::create_dir_all(&out).expect("mkdir");

    // the break, mono, at the emu rate, looped to ~10 s, gain-staged to a
    // healthy mix level (-14 dBFS RMS)
    let (raw, wav_sr) = read_wav_mono(BREAK_WAV);
    let mut brk = resample_linear(&raw, wav_sr as f64, SR_EMU);
    let target_len = (SR_EMU * 10.0) as usize;
    while brk.len() < target_len {
        let take = (target_len - brk.len()).min(brk.len());
        let copy: Vec<f32> = brk[..take].to_vec();
        brk.extend(copy);
    }
    brk.truncate(target_len);
    let g = 10f32.powf(-14.0 / 20.0) / rms(&brk).max(1e-9);
    for s in brk.iter_mut() {
        *s *= g;
    }
    write_wav(&out.join("break_dry.wav"), &resample_linear(&brk, SR_EMU, OUT_SR as f64), OUT_SR);

    let dir = root.join("ref/p2k_variants/P2k_013_talking_hedz");
    let body_path = std::fs::read_dir(&dir)
        .expect("variants dir")
        .flatten()
        .map(|e| e.path())
        .find(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.starts_with("variant_0_") && n.ends_with(".bin"))
                .unwrap_or(false)
        })
        .expect("talking hedz body");
    let bytes = std::fs::read(&body_path).expect("read body");

    let variants: &[(&str, InputMode, f32, f32, f32)] = &[
        // name, input_mode, slam_drive, agc_max_cut_db, agc_drive
        // harness "awake chain" (what the earlier probes measured):
        ("stock", InputMode::MackieDeskSlam, 0.6, f32::INFINITY, 4.0),
        ("candidate", InputMode::MackieDeskSlam, 0.15, 8.0, 4.0),
        // the SHIPPING PLUGIN's actual config (PluginProcessor: clean input,
        // musicalAgcDrive = 1.0, slam param default 0.25 post-body):
        ("plugin_stock", InputMode::None, 0.25, f32::INFINITY, 1.0),
        ("plugin_candidate", InputMode::None, 0.25, 8.0, 1.0),
        // decomposition: which plugin stage does the ~13 dB of leveling?
        ("plugin_slam0", InputMode::None, 0.0, f32::INFINITY, 1.0),
        ("plugin_nosat", InputMode::None, 0.25, f32::INFINITY, -1.0), // -1 sentinel: saturation off
        ("plugin_slam0_nosat", InputMode::None, 0.0, f32::INFINITY, -1.0),
    ];

    for (name, mode, slam, max_cut, agc_drive) in variants {
        let cart = Cartridge::from_body_bytes("P2k_013_talking_hedz", &bytes, 1.0).expect("cart");
        let mut eng = FilterEngine::new();
        eng.prepare(SR_EMU);
        eng.load_cartridge(cart);
        eng.debug.agc_enabled = true;
        eng.debug.agc_max_cut_db = *max_cut;
        if *agc_drive < 0.0 {
            eng.debug.saturation_enabled = false;
            eng.set_agc_drive(1.0);
        } else {
            eng.set_agc_drive(*agc_drive);
        }
        eng.set_input_mode(*mode);
        eng.set_slam_drive(*slam);

        let mut wet: Vec<f32> = Vec::with_capacity(brk.len());
        let mut off = 0usize;
        while off < brk.len() {
            let len = BLOCK.min(brk.len() - off);
            let mut l = brk[off..off + len].to_vec();
            let mut r = l.clone();
            // slow morph sweep 0.15 -> 0.9 over the loop, q parked at 0.4
            let m = 0.15 + 0.75 * (off as f64 / brk.len() as f64);
            eng.process_block(&mut l, &mut r, m, 0.4);
            wet.extend_from_slice(&l);
            off += len;
        }

        // loudness-match to -14 dB RMS so the A/B is level-fair
        let mk = 10f32.powf(-14.0 / 20.0) / rms(&wet).max(1e-9);
        for s in wet.iter_mut() {
            *s *= mk;
        }
        let f = format!("break_{name}.wav");
        write_wav(&out.join(&f), &resample_linear(&wet, SR_EMU, OUT_SR as f64), OUT_SR);
        println!("{name}: makeup {:.1} dB, wrote {f}", 20.0 * mk.log10());
    }

    // Mini level-ladder per config: does the SHIPPING chain level dynamics?
    println!("\nladders (in dBFS -> chain gain dB):");
    for (name, mode, slam, max_cut, agc_drive) in variants {
        let mut gains = Vec::new();
        for (k, in_db) in [-24.0f32, -12.0, 0.0].iter().enumerate() {
            let amp = 10f32.powf(in_db / 20.0) * 0.7;
            let mut s = 0x9E3779B9u64 + k as u64;
            let mut b0 = 0f32;
            let n = (SR_EMU * 0.8) as usize;
            let noise: Vec<f32> = (0..n)
                .map(|_| {
                    s ^= s << 13;
                    s ^= s >> 7;
                    s ^= s << 17;
                    let w = ((s as f64 / u64::MAX as f64) as f32 - 0.5) * 2.0;
                    b0 = 0.99 * b0 + 0.05 * w;
                    (b0 * 6.0 + w * 0.25) * amp
                })
                .collect();
            let cart = Cartridge::from_body_bytes("P2k_013_talking_hedz", &bytes, 1.0).expect("cart");
            let mut eng = FilterEngine::new();
            eng.prepare(SR_EMU);
            eng.load_cartridge(cart);
            eng.debug.agc_enabled = true;
            eng.debug.agc_max_cut_db = *max_cut;
            eng.set_agc_drive(*agc_drive);
            eng.set_input_mode(*mode);
            eng.set_slam_drive(*slam);
            let mut wet: Vec<f32> = Vec::with_capacity(noise.len());
            let mut off = 0usize;
            while off < noise.len() {
                let len = BLOCK.min(noise.len() - off);
                let mut l = noise[off..off + len].to_vec();
                let mut r = l.clone();
                eng.process_block(&mut l, &mut r, 0.5, 0.5);
                wet.extend_from_slice(&l);
                off += len;
            }
            let g = 20.0 * (rms(&wet) / rms(&noise).max(1e-9)).log10();
            gains.push(g);
        }
        let span = (gains[0] - gains[2]).abs();
        println!(
            "  {name:>16}: {:+5.1} {:+5.1} {:+5.1}  | leveling span {:.1} dB (0 = ideal)",
            gains[0], gains[1], gains[2], span
        );
    }

    println!("open: {}", out.display());
}
