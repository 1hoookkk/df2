use trench_core::cartridge::Cartridge;
use trench_core::engine::FilterEngine;
const SR: f64 = 39_062.5;
const BPM: f64 = 120.0;
const BARS: usize = 4;
const ORBIT_HZ: f64 = BPM / 60.0 / 2.0;
const BLOCK: usize = 128;
fn rng(state: &mut u32) -> f64 {
    *state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
    (*state >> 8) as f64 / (1u32 << 24) as f64 * 2.0 - 1.0
}
fn groove() -> Vec<f32> {
    let spb = 60.0 / BPM;
    let n = (SR * spb * 4.0 * BARS as f64) as usize;
    let mut out = vec![0.0f64; n];
    let mut state = 0x2545_f491u32;
    let beat_s = (SR * spb) as usize;
    for beat in 0..(4 * BARS) {
        let at = beat * beat_s;
        let kn = (SR * 0.35) as usize;
        let mut phase = 0.0f64;
        for i in 0..kn.min(n - at) {
            let t = i as f64 / SR;
            let f = 48.0 + 90.0 * (-t / 0.025).exp();
            phase += 2.0 * std::f64::consts::PI * f / SR;
            out[at + i] += phase.sin() * (-t / 0.22).exp() * 0.9;
        }
        if beat % 4 == 1 || beat % 4 == 3 {
            let sn = (SR * 0.18) as usize;
            for i in 0..sn.min(n - at) {
                let t = i as f64 / SR;
                let noise = rng(&mut state) * (-t / 0.045).exp();
                let body = (2.0 * std::f64::consts::PI * 190.0 * t).sin() * (-t / 0.06).exp();
                out[at + i] += 0.55 * noise + 0.3 * body;
            }
        }
        for h in 0..2 {
            let hat_at = at + h * beat_s / 2;
            let hn = (SR * 0.05) as usize;
            let mut prev = 0.0f64;
            for i in 0..hn.min(n.saturating_sub(hat_at)) {
                let t = i as f64 / SR;
                let w = rng(&mut state);
                let hp = w - prev;
                prev = w;
                out[hat_at + i] += 0.22 * hp * (-t / 0.012).exp();
            }
        }
    }
    out.iter().map(|&x| (x * 0.6) as f32).collect()
}
fn write_wav(path: &str, samples: &[f32]) {
    let n = samples.len() as u32;
    let mut bytes = Vec::with_capacity(44 + samples.len() * 2);
    bytes.extend_from_slice(b"RIFF");
    bytes.extend_from_slice(&(36 + n * 2).to_le_bytes());
    bytes.extend_from_slice(b"WAVEfmt ");
    bytes.extend_from_slice(&16u32.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&(SR as u32).to_le_bytes());
    bytes.extend_from_slice(&((SR as u32) * 2).to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&16u16.to_le_bytes());
    bytes.extend_from_slice(b"data");
    bytes.extend_from_slice(&(n * 2).to_le_bytes());
    for &s in samples {
        bytes.extend_from_slice(&((s.clamp(-1.0, 1.0) * 32767.0) as i16).to_le_bytes());
    }
    std::fs::write(path, bytes).expect("write wav");
}
fn pink(n: usize) -> Vec<f32> {
    let mut state = 0x2545_f491u32;
    let mut b = [0.0f64; 6];
    (0..n)
        .map(|_| {
            let w = rng(&mut state);
            b[0] = 0.99886 * b[0] + w * 0.0555179;
            b[1] = 0.99332 * b[1] + w * 0.0750759;
            b[2] = 0.96900 * b[2] + w * 0.1538520;
            b[3] = 0.86650 * b[3] + w * 0.3104856;
            b[4] = 0.55000 * b[4] + w * 0.5329522;
            let p = b[0] + b[1] + b[2] + b[3] + b[4] + b[5] + w * 0.5362;
            b[5] = w * 0.115926;
            (p * 0.11) as f32
        })
        .collect()
}
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let (body_path, outdir, sweep) = match &args[..] {
        [_, b, o] => (b.clone(), o.clone(), false),
        [_, b, o, m] if m == "--sweep" => (b.clone(), o.clone(), true),
        _ => {
            eprintln!("usage: rate-ab <body.body240> <outdir> [--sweep]");
            std::process::exit(2);
        }
    };
    let bytes = std::fs::read(&body_path).expect("read body");
    std::fs::create_dir_all(&outdir).expect("outdir");
    let input = if sweep { pink((SR * 8.0) as usize) } else { groove() };
    let n = input.len();
    for (label, scale) in [("80ms", 1.0f32), ("13ms", 0.164), ("0p8ms", 0.0)] {
        let mut engine = FilterEngine::new();
        engine.prepare(SR);
        let cart = Cartridge::from_body_bytes("rate_ab", &bytes, 1.0).expect("cartridge");
        engine.load_cartridge(cart);
        engine.debug.coeff_ramp_scale = scale;
        {
            let pre = (SR * 0.5) as usize;
            let start_morph = if sweep { 0.0 } else { 0.5 };
            let start_q = if sweep { 0.0 } else { 0.7 };
            let mut i = 0usize;
            while i < pre {
                let len = BLOCK.min(pre - i);
                let mut l: Vec<f32> = input[i % n..(i % n) + len.min(n - i % n)].to_vec();
                l.resize(len, 0.0);
                let mut r = l.clone();
                engine.process_block(&mut l, &mut r, start_morph, start_q);
                i += len;
            }
        }
        let mut out = Vec::with_capacity(n);
        let mut i = 0usize;
        while i < n {
            let len = BLOCK.min(n - i);
            let mut l: Vec<f32> = input[i..i + len].to_vec();
            let mut r = l.clone();
            let t = i as f64 / SR;
            let (morph, q) = if sweep {
                let ph = i as f64 / n as f64;
                (if ph < 0.5 { ph * 2.0 } else { 2.0 - ph * 2.0 }, 0.0)
            } else {
                (0.5 + 0.5 * (2.0 * std::f64::consts::PI * ORBIT_HZ * t).sin(), 0.7)
            };
            engine.process_block(&mut l, &mut r, morph, q);
            out.extend_from_slice(&l);
            i += len;
        }
        let peak = out.iter().fold(0.0f32, |m, &x| m.max(x.abs())).max(1e-9);
        let g = 0.708 / peak;
        for x in out.iter_mut() {
            *x *= g;
        }
        let path = format!("{outdir}/rate_{label}.wav");
        write_wav(&path, &out);
        println!("wrote {path} (scale {scale}, peak matched)");
    }
}
