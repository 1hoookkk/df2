//! Render Tyson's named P2K favourites through the SHIPPED awake chain
//! (AGC at the authentic 4.0 teeth + Mackie desk-slam) at the four corners and
//! the middle, so the P2K quality bar is audible in df2. The ear judges — no
//! scoring. See memory: produce-presets-not-method-questions, agc-drive-is-the-character.
//!
//! Run: cargo test -p trench-core --test audition_p2k_favourites -- --ignored --nocapture

use trench_core::{Cartridge, FilterEngine, InputMode};

const FAVOURITES: &[&str] = &[
    "P2k_001_megasweepz",
    "P2k_002_early_rizer",
    "P2k_003_millennium",
    "P2k_004_meaty_gizmo",
    "P2k_005_klub_klassik",
    "P2k_006_bassbox_303",
    "P2k_009_tb_or_not_tb",
    "P2k_013_talking_hedz",
    "P2k_015_dj_alkaline",
    "P2k_018_razor_blades",
    "P2k_022_deep_bouche",
    "P2k_023_freak_shifta",
    "P2k_025_angelz_hairz",
    "P2k_027_acid_ravage",
    "P2k_029_lucifer_s_q",
    "P2k_031_ear_bender",
];

// The 5 listen positions: HOME · MORPH · TENSION · MORPH+TENSION · MIDDLE.
const POSITIONS: &[(f64, f64)] = &[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5)];

#[test]
#[ignore = "renders favourite WAVs to dev/tmp/audition_p2k"]
fn audition_p2k_favourites() {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let out = root.join("dev/tmp/audition_p2k");
    std::fs::create_dir_all(&out).expect("mkdir out");

    let sr_emu = 39_062.5f64;
    let out_sr = 48_000u32;
    let seg_secs = 1.1f64;
    let seg_n = (sr_emu * seg_secs) as usize;
    let block = 256usize;

    let mut rendered: Vec<(String, String)> = Vec::new();

    for fav in FAVOURITES {
        let dir = root.join("ref/p2k_variants").join(fav);
        let body = std::fs::read_dir(&dir).ok().and_then(|rd| {
            rd.flatten().map(|e| e.path()).find(|p| {
                p.file_name()
                    .and_then(|n| n.to_str())
                    .map(|n| n.starts_with("variant_0_") && n.ends_with(".bin"))
                    .unwrap_or(false)
            })
        });
        let Some(path) = body else {
            println!("SKIP {fav}: no variant_0 .bin");
            continue;
        };
        let bytes = std::fs::read(&path).expect("read body");
        let Ok(cart) = Cartridge::from_body_bytes(fav, &bytes, 1.0) else {
            println!("SKIP {fav}: body did not load");
            continue;
        };

        let mut eng = FilterEngine::new();
        eng.prepare(sr_emu);
        eng.load_cartridge(cart);
        // L11 voicing (LAWS.md, Tyson's real-material verdict 2026-07-04):
        // slam 0.15 + AGC cut cap 8 dB. The old awake chain (agc 4.0 +
        // slam 0.6) was a 24 dB brick-wall leveler — never again.
        eng.debug.agc_enabled = true;
        eng.debug.agc_max_cut_db = 8.0;
        eng.set_agc_drive(4.0);
        eng.set_input_mode(InputMode::MackieDeskSlam);
        eng.set_slam_drive(0.15);

        // Reese-ish 55 Hz sawtooth — rich harmonics excite formants AND carry bass.
        let mut phase = 0.0f64;
        let mut wet: Vec<f32> = Vec::with_capacity(seg_n * POSITIONS.len());
        for (pi, &(morph, q)) in POSITIONS.iter().enumerate() {
            let mut off = 0usize;
            while off < seg_n {
                let len = block.min(seg_n - off);
                let mut l = vec![0f32; len];
                for (i, s) in l.iter_mut().enumerate() {
                    phase = (phase + 55.0 / sr_emu).fract();
                    // short fade at each segment edge to avoid clicks
                    let pos = off + i;
                    let env = (pos as f32 / 600.0)
                        .min(1.0)
                        .min((seg_n - pos) as f32 / 600.0);
                    *s = ((phase * 2.0 - 1.0) as f32) * 0.5 * env;
                }
                let mut r = l.clone();
                eng.process_block(&mut l, &mut r, morph, q);
                wet.extend_from_slice(&l);
                off += len;
            }
            let _ = pi;
        }

        // Resample EMU -> 48 kHz.
        let ratio = sr_emu / out_sr as f64;
        let out_n = (wet.len() as f64 / ratio) as usize;
        let resampled: Vec<f32> = (0..out_n)
            .map(|i| {
                let p = i as f64 * ratio;
                let i0 = p.floor() as usize;
                let frac = (p - i0 as f64) as f32;
                let a = wet.get(i0).copied().unwrap_or(0.0);
                let b = wet.get(i0 + 1).copied().unwrap_or(a);
                a + (b - a) * frac
            })
            .collect();

        let fname = format!("{fav}.wav");
        write_wav(&out.join(&fname), &resampled, out_sr);
        let peak = resampled.iter().fold(0.0f32, |m, &s| m.max(s.abs()));
        println!("wrote {fname} (peak {peak:.3})");
        rendered.push((fav.to_string(), fname));
    }

    // Audition page.
    let mut html = String::from(
        "<!doctype html><meta charset=utf-8><title>P2K favourites — the ceiling</title>\
         <style>body{background:#0a0c12;color:#cdd6e2;font:13px ui-monospace,monospace;padding:24px}\
         h1{font-size:15px;color:#60c8e0;font-weight:400}\
         .row{display:flex;align-items:center;gap:14px;padding:7px 0;border-bottom:1px solid #232838}\
         .n{width:230px;color:#cdd6e2}audio{height:30px}\
         .key{color:#68748a;margin:8px 0 18px}</style>\
         <h1>P2K favourites — awake engine (AGC 4.0 + slam)</h1>\
         <div class=key>each clip: HOME · MORPH · TENSION · MORPH+TENSION · MIDDLE (1.1s each). reese 55Hz saw.</div>",
    );
    for (name, file) in &rendered {
        html.push_str(&format!(
            "<div class=row><span class=n>{name}</span>\
             <audio controls preload=none src=\"{file}\"></audio></div>"
        ));
    }
    let page = out.join("audition.html");
    std::fs::write(&page, html).expect("write html");
    println!("\nopen: {}", page.display());
    println!(
        "rendered {}/{} favourites",
        rendered.len(),
        FAVOURITES.len()
    );
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
