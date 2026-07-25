use std::io::Write;
use trench_core::desk_drive::mackity_saturate;
use trench_core::oversample::Oversampler4x;
fn synth_808(fs: f64, dur_s: f64) -> Vec<f64> {
    let n = (fs * dur_s) as usize;
    let mut out = Vec::with_capacity(n);
    let mut phase = 0.0f64;
    for i in 0..n {
        let t = i as f64 / fs;
        let f = 46.0 + 44.0 * (-t / 0.022).exp();
        phase += 2.0 * std::f64::consts::PI * f / fs;
        let body = phase.sin();
        let env = (-t / 0.40).exp();
        let click = if t < 0.006 {
            (1.0 - t / 0.006) * (2.0 * std::f64::consts::PI * 1800.0 * t).sin()
        } else {
            0.0
        };
        out.push((body * env + click * 0.5) * 0.9);
    }
    out
}
fn synth_sweep(fs: f64, dur_s: f64) -> Vec<f64> {
    let n = (fs * dur_s) as usize;
    let (f_lo, f_hi) = (1400.0f64, 9000.0f64);
    let mut phase = 0.0f64;
    (0..n)
        .map(|i| {
            let u = i as f64 / n as f64;
            let f = f_lo * (f_hi / f_lo).powf(u);
            phase += 2.0 * std::f64::consts::PI * f / fs;
            phase.sin() * 0.7
        })
        .collect()
}
fn synth_lead(fs: f64, f0: f64, dur_s: f64) -> Vec<f64> {
    let n = (fs * dur_s) as usize;
    let kmax = (0.45 * fs / f0) as usize;
    (0..n)
        .map(|i| {
            let t = i as f64 / fs;
            let env = (1.0 - (-t / 0.01).exp()) * (-t / 1.2).exp();
            let mut s = 0.0;
            for k in 1..=kmax {
                s += (2.0 * std::f64::consts::PI * f0 * k as f64 * t).sin() / k as f64;
            }
            s * 0.5 * env
        })
        .collect()
}
fn process(input: &[f64], drive: f64, oversample: bool) -> Vec<f64> {
    let mut os = Oversampler4x::new();
    input
        .iter()
        .map(|&x| {
            if oversample {
                let up = os.upsample(x);
                os.downsample(&[
                    mackity_saturate(up[0] * drive),
                    mackity_saturate(up[1] * drive),
                    mackity_saturate(up[2] * drive),
                    mackity_saturate(up[3] * drive),
                ])
            } else {
                mackity_saturate(x * drive)
            }
        })
        .collect()
}
fn rms(x: &[f64]) -> f64 {
    (x.iter().map(|v| v * v).sum::<f64>() / x.len() as f64).sqrt()
}
fn write_wav_f32(path: &str, data: &[f64], fs: u32) {
    let mut f = std::fs::File::create(path).expect("create wav");
    let n = data.len() as u32;
    let byte_rate = fs * 4;
    let data_bytes = n * 4;
    let mut h = Vec::new();
    h.extend_from_slice(b"RIFF");
    h.extend_from_slice(&(36 + data_bytes).to_le_bytes());
    h.extend_from_slice(b"WAVE");
    h.extend_from_slice(b"fmt ");
    h.extend_from_slice(&16u32.to_le_bytes());
    h.extend_from_slice(&3u16.to_le_bytes());
    h.extend_from_slice(&1u16.to_le_bytes());
    h.extend_from_slice(&fs.to_le_bytes());
    h.extend_from_slice(&byte_rate.to_le_bytes());
    h.extend_from_slice(&4u16.to_le_bytes());
    h.extend_from_slice(&32u16.to_le_bytes());
    h.extend_from_slice(b"data");
    h.extend_from_slice(&data_bytes.to_le_bytes());
    f.write_all(&h).unwrap();
    for &s in data {
        f.write_all(&(s as f32).to_le_bytes()).unwrap();
    }
}
fn main() {
    let fs = 48000.0;
    let drive = 10f64.powf(12.0 / 20.0);
    let target = 0.20f64;
    let scale = |x: &[f64]| {
        let g = target / rms(x).max(1e-9);
        let peak = x.iter().fold(0.0f64, |m, &v| m.max((v * g).abs()));
        let g = if peak > 0.98 { g * 0.98 / peak } else { g };
        x.iter().map(|&v| v * g).collect::<Vec<_>>()
    };
    let render = |name: &str, src: &[f64]| {
        let fizzy = scale(&process(src, drive, false));
        let pristine = scale(&process(src, drive, true));
        write_wav_f32(&format!("slam_{name}_fizzy.wav"), &fizzy, fs as u32);
        write_wav_f32(&format!("slam_{name}_pristine.wav"), &pristine, fs as u32);
        println!("wrote slam_{name}_fizzy.wav / slam_{name}_pristine.wav");
    };
    render("sweep", &synth_sweep(fs, 3.0));
    render("lead", &synth_lead(fs, 330.0, 1.8));
    render("808", &synth_808(fs, 1.6));
}
