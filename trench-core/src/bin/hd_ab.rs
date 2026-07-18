//! hd_ab — level-matched island-rate A/B: the SAME body + groove + morph ride,
//! rendered through the engine at 39062.5 (legacy island) and 78125 (HD).
//!
//!   cargo run -p trench-core --release --bin hd-ab -- <body.body240> <outstem>
//!
//! Writes <outstem>_39k.wav and <outstem>_hd.wav at the ENGINE rate (f32 WAV,
//! rate in the header). Resample/level-match downstream before judging.

use trench_core::cartridge::Cartridge;
use trench_core::desk_drive::{DeskDrive, SUPPORTED_MODEL};
use trench_core::engine::{FilterEngine, InputMode, SpatialMode};

const BPM: f64 = 120.0;
const BARS: usize = 4;
const BLOCK: usize = 128;

fn rng(state: &mut u32) -> f64 {
    *state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
    (*state >> 8) as f64 / (1u32 << 24) as f64 * 2.0 - 1.0
}

/// The rate_ab drum groove (kick quarters, snare 2/4, 1/8 hats), at `sr`.
fn groove(sr: f64) -> Vec<f32> {
    let spb = 60.0 / BPM;
    let n = (sr * spb * 4.0 * BARS as f64) as usize;
    let mut out = vec![0.0f64; n];
    let mut state = 0x2545_f491u32;
    let beat_s = (sr * spb) as usize;
    for beat in 0..(4 * BARS) {
        let at = beat * beat_s;
        let kn = (sr * 0.35) as usize;
        let mut phase = 0.0f64;
        for i in 0..kn.min(n - at) {
            let t = i as f64 / sr;
            let f = 48.0 + 90.0 * (-t / 0.025).exp();
            phase += 2.0 * std::f64::consts::PI * f / sr;
            out[at + i] += phase.sin() * (-t / 0.22).exp() * 0.9;
        }
        if beat % 4 == 1 || beat % 4 == 3 {
            let sn = (sr * 0.18) as usize;
            for i in 0..sn.min(n - at) {
                let t = i as f64 / sr;
                let noise = rng(&mut state) * (-t / 0.045).exp();
                let body = (2.0 * std::f64::consts::PI * 190.0 * t).sin() * (-t / 0.06).exp();
                out[at + i] += 0.55 * noise + 0.3 * body;
            }
        }
        for eighth in 0..2 {
            let hat_at = at + eighth * beat_s / 2;
            let hn = (sr * 0.05) as usize;
            for i in 0..hn.min(n.saturating_sub(hat_at)) {
                let t = i as f64 / sr;
                out[hat_at + i] += rng(&mut state) * (-t / 0.012).exp() * 0.25;
            }
        }
    }
    out.iter().map(|v| (*v * 0.5) as f32).collect()
}

/// The reese riff: A1 A1 C2 D2 F1 G1 A1 E2, one note per second, three
/// band-limited saws detuned ±0.4% — the beating low-mid wall, playing a line.
const RIFF_HZ: [f64; 8] = [55.0, 55.0, 65.41, 73.42, 43.65, 49.0, 55.0, 82.41];
/// Pitch class of each riff note relative to C, folded to ±6 (what the
/// KeyTrackDetector would emit): A=-3, C=0, D=+2, F=+5, G=-5, E=+4.
const RIFF_PC: [i32; 8] = [-3, -3, 0, 2, 5, -5, -3, 4];

fn reese(sr: f64) -> Vec<f32> {
    let n = (sr * 8.0) as usize;
    let mut out = vec![0.0f64; n];
    for detune in [-0.004f64, 0.0, 0.004] {
        let mut phase = 0.0f64;
        for i in 0..n {
            let note = ((i as f64 / sr).floor() as usize).min(7);
            let f0 = RIFF_HZ[note] * (1.0 + detune);
            phase += std::f64::consts::TAU * f0 / sr;
            let top = (8_000.0 / f0).floor() as usize;
            let mut s = 0.0;
            let mut k = 1;
            while k <= top {
                s += (phase * k as f64).sin() / k as f64;
                k += 1;
            }
            out[i] += s / 3.0;
        }
    }
    let peak = out.iter().fold(0.0f64, |m, v| m.max(v.abs()));
    out.iter().map(|v| (v / peak * 0.5) as f32).collect()
}

fn render(body: &[u8], rate: f64, bite: f32) -> Vec<f32> {
    let mut eng = FilterEngine::new();
    eng.prepare(rate);
    eng.set_interstage_drive(bite);
    let cart = Cartridge::from_body_bytes_at("ab", body, 1.0, rate).expect("cartridge");
    eng.load_cartridge(cart);
    let is_reese = std::env::var("HD_AB_SOURCE").as_deref() == Ok("reese");
    let keytrack = std::env::var("HD_AB_KEYTRACK").as_deref() == Ok("1");
    let fx = std::env::var("HD_AB_FX").unwrap_or_default();
    // inslam: the engine's own pre-cascade Mackie desk (the Into-Filter route)
    if fx == "inslam" {
        eng.set_input_mode(InputMode::MackieDeskSlam);
        eng.set_slam_drive(0.10); // the shipped kIntoFilterDriveScale at full
    }
    // orbit: QSound engaged, SPACE ridden by a slow orbit below
    if fx == "orbit" {
        eng.set_spatial_mode(SpatialMode::QSound);
    }
    // outslam: the same measured desk AFTER the engine (where SLAM ships)
    let mut out_desk_l = DeskDrive::new();
    let mut out_desk_r = DeskDrive::new();
    if fx == "outslam" {
        out_desk_l.prepare(rate as f32);
        out_desk_r.prepare(rate as f32);
        out_desk_l.configure(SUPPORTED_MODEL);
        out_desk_r.configure(SUPPORTED_MODEL);
    }
    let src = if is_reese { reese(rate) } else { groove(rate) };
    let total = src.len();
    let mut out = Vec::with_capacity(total * 2);
    // Warm start: run the full loop once and discard — coefficient ramps land,
    // AGC and desk state settle — then capture. Renders must never cold-start.
    for pass in 0..2 {
        let capture = pass == 1;
        if capture {
            out.clear();
        }
    let mut off = 0usize;
    while off < total {
        let n = BLOCK.min(total - off);
        let mut l: Vec<f32> = src[off..off + n].to_vec();
        let mut r = l.clone();
        let t = off as f64 / rate;
        // reese: beat-ish morph orbit (the modulation); groove: slow ride
        let morph = if is_reese && std::env::var("HD_AB_MORPHSTEP").as_deref() == Ok("1") {
            // chords CHANGE, they don't smear: hold each pose for 2 beats
            if (t * 2.0).floor() as i64 % 2 == 0 { 0.0 } else { 1.0 }
        } else if is_reese {
            0.5 + 0.45 * (std::f64::consts::TAU * 2.0 * t).sin()
        } else {
            off as f64 / total as f64
        };
        if keytrack {
            // the engine half of KEY TRACK, fed the riff's known pitch classes
            // (exactly what the plugin's detector emits for these notes)
            let pc = RIFF_PC[(t.floor() as usize).min(7)];
            eng.set_pitch_ratio((2.0f64.powf(pc as f64 / 12.0)) as f32);
        }
        if fx == "orbit" {
            // ORBIT: SPACE swept 0..1 at 0.25 Hz — a slow head-wrap
            eng.set_space((0.5 + 0.5 * (std::f64::consts::TAU * 0.25 * t).sin()) as f32);
        }
        eng.process_block(&mut l, &mut r, morph, 0.7);
        if fx == "outslam" {
            let slam = std::env::var("HD_AB_SLAM")
                .ok()
                .and_then(|v| v.parse::<f32>().ok())
                .unwrap_or(0.5);
            for v in l.iter_mut() {
                *v = out_desk_l.process(*v, slam);
            }
            for v in r.iter_mut() {
                *v = out_desk_r.process(*v, slam);
            }
        }
        // interleave stereo (identical channels unless QSound is live)
        if capture {
            for i in 0..n {
                out.push(l[i]);
                out.push(r[i]);
            }
        }
        off += n;
    }
    }
    out
}

fn write_wav_f32(path: &str, rate: u32, data: &[f32]) {
    let bytes_len = (data.len() * 4) as u32;
    let mut w: Vec<u8> = Vec::with_capacity(44 + data.len() * 4);
    w.extend_from_slice(b"RIFF");
    w.extend_from_slice(&(36 + bytes_len).to_le_bytes());
    w.extend_from_slice(b"WAVEfmt ");
    w.extend_from_slice(&16u32.to_le_bytes());
    w.extend_from_slice(&3u16.to_le_bytes()); // IEEE float
    w.extend_from_slice(&2u16.to_le_bytes()); // stereo interleaved
    w.extend_from_slice(&rate.to_le_bytes());
    w.extend_from_slice(&(rate * 8).to_le_bytes());
    w.extend_from_slice(&8u16.to_le_bytes());
    w.extend_from_slice(&32u16.to_le_bytes());
    w.extend_from_slice(b"data");
    w.extend_from_slice(&bytes_len.to_le_bytes());
    for v in data {
        w.extend_from_slice(&v.to_le_bytes());
    }
    std::fs::write(path, w).expect("write wav");
}

/// Mission-F probe: the SAME packed lerp, called PER SAMPLE instead of per
/// 32-sample control block. BODY SOLO cascade + the output desk (the default
/// sound). mode: "lerp32" = 32-sample snap grid (the current engine's
/// granularity, no ramp), "lerp1" = per-sample, "fm" = per-sample with the
/// morph itself at audio rate (55 Hz anatomy FM around centre).
fn render_per_sample(body: &[u8], rate: f64, mode: &str) -> Vec<f32> {
    use trench_core::cascade::Cascade;
    let cart = Cartridge::from_body_bytes_at("ps", body, 1.0, rate).expect("cartridge");
    let mut casc = Cascade::new();
    let mut desk = DeskDrive::new();
    desk.prepare(rate as f32);
    desk.configure(SUPPORTED_MODEL);
    let src = reese(rate);
    let n = src.len();
    let mut out = Vec::with_capacity(n * 2);
    let q = 0.7f64;
    for i in 0..n {
        let t = i as f64 / rate;
        let morph = match mode {
            "fm" => 0.5 + 0.3 * (std::f64::consts::TAU * 55.0 * t).sin(),
            _ => 0.5 + 0.45 * (std::f64::consts::TAU * 2.0 * t).sin(),
        };
        if mode != "lerp32" || i % 32 == 0 {
            let rows = cart.interpolate(morph, q);
            casc.snap_targets(&rows);
        }
        let v = desk.process(casc.tick(src[i]), 0.5);
        out.push(v);
        out.push(v);
    }
    out
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let (body_path, stem, bite) = match &args[..] {
        [_, b, s] => (b.clone(), s.clone(), 0.0f32),
        [_, b, s, d] => (b.clone(), s.clone(), d.parse().expect("bite 0..1")),
        _ => {
            eprintln!("usage: hd-ab <body.body240> <outstem> [bite]");
            std::process::exit(2);
        }
    };
    let body = std::fs::read(&body_path).expect("read body");
    if let Ok(mode) = std::env::var("HD_AB_PERSAMPLE") {
        let x = render_per_sample(&body, 78_125.0, &mode);
        write_wav_f32(&format!("{stem}_{mode}.wav"), 78_125, &x);
        println!("wrote {stem}_{mode}.wav (per-sample probe, HD rate)");
        return;
    }
    let a = render(&body, 39_062.5, bite);
    let b = render(&body, 78_125.0, bite);
    let rms = |x: &[f32]| (x.iter().map(|v| (*v as f64).powi(2)).sum::<f64>() / x.len() as f64).sqrt();
    let (ra, rb) = (rms(&a), rms(&b));
    let g = (ra / rb.max(1e-12)) as f32;
    let b_matched: Vec<f32> = b.iter().map(|v| v * g).collect();
    println!(
        "39k rms {:.4}, hd rms {:.4} -> hd level-matched by {:+.2} dB",
        ra,
        rb,
        20.0 * (g as f64).log10()
    );
    write_wav_f32(&format!("{stem}_39k.wav"), 39_062, &a);
    write_wav_f32(&format!("{stem}_hd.wav"), 78_125, &b_matched);
    println!("wrote {stem}_39k.wav / {stem}_hd.wav (engine-rate f32 mono, HD level-matched)");
}
