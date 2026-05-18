//! Dump resampler output to a raw f32 file so a Python port can be
//! null-tested against the authoritative Rust implementation.
//!
//! Ignored by default — run explicitly:
//!   cargo test -p trench-core --test resampler_dump -- --ignored --nocapture
//!
//! Writes `target/resampler_dump_44k_to_native.f32` (host→native) and
//! `target/resampler_dump_native_to_44k.f32` (native→host) as little-
//! endian f32 arrays. The input signal is a 4096-sample 1 kHz sine at
//! 44100 Hz (same as the Rust roundtrip_preserves_sine test).
//!
//! `trench_core` does not currently expose a `resampler` module; the
//! diagnostic harness predates that module's removal/rewrite. The local
//! stub below keeps the file compiling so the workspace check passes
//! without `#[ignore]`-only tests being silently dropped from `cargo
//! check --tests`. When a real resampler lands in `trench_core`, delete
//! this stub and restore `use trench_core::resampler::{Resampler, NATIVE_SR};`.

use std::f32::consts::TAU;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;

mod local_resampler_stub {
    /// Authoring sample rate (silicon clock = 10 MHz / 256). Matches the
    /// rate used by every cartridge in `cartridges/` and by the Python
    /// reference pipeline in `authoring/compilers/parity_null.py`.
    pub const NATIVE_SR: f64 = 39_062.5;

    /// Stub kept so the `#[ignore]`d dump test still compiles. Producing
    /// (0, 0) on `process` causes `resample_all` to break out of its loop
    /// immediately, so the dump is empty rather than fabricated. Replace
    /// with a real `trench_core::resampler::Resampler` when one exists.
    pub struct Resampler;

    impl Resampler {
        pub fn new(_sr_in: f64, _sr_out: f64) -> Self {
            Self
        }

        pub fn process(&mut self, _input: &[f32], _output: &mut [f32]) -> (usize, usize) {
            (0, 0)
        }
    }
}

use local_resampler_stub::{Resampler, NATIVE_SR};

fn make_sine(sr: f64, freq: f64, n: usize) -> Vec<f32> {
    (0..n)
        .map(|i| (TAU as f64 * freq * i as f64 / sr).sin() as f32)
        .collect()
}

fn resample_all(r: &mut Resampler, input: &[f32]) -> Vec<f32> {
    let max_out =
        (input.len() as f64 / (44100.0 / NATIVE_SR).min(NATIVE_SR / 44100.0) + 2.0) as usize;
    // Actually: output count depends on direction. Use big buffer.
    let _ = max_out;
    let mut out = vec![0.0f32; input.len() * 2 + 64];
    let mut in_off = 0;
    let mut out_off = 0;
    while in_off < input.len() {
        let (consumed, produced) = r.process(&input[in_off..], &mut out[out_off..]);
        in_off += consumed;
        out_off += produced;
        if consumed == 0 && produced == 0 {
            break;
        }
    }
    out.truncate(out_off);
    out
}

fn target_dir() -> PathBuf {
    // Tests run from crate dir; step up to workspace target.
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("target")
}

fn write_f32(path: &PathBuf, buf: &[f32]) {
    let mut f = File::create(path).expect("create dump file");
    let mut bytes = Vec::with_capacity(buf.len() * 4);
    for &s in buf {
        bytes.extend_from_slice(&s.to_le_bytes());
    }
    f.write_all(&bytes).expect("write dump");
}

#[test]
#[ignore]
fn dump_resampler_outputs() {
    let n = 4096usize;

    // Host -> native.
    let inp = make_sine(44100.0, 1000.0, n);
    let mut down = Resampler::new(44100.0, NATIVE_SR);
    let native = resample_all(&mut down, &inp);

    // Native -> host.
    let inp2 = make_sine(NATIVE_SR, 1000.0, n);
    let mut up = Resampler::new(NATIVE_SR, 44100.0);
    let out = resample_all(&mut up, &inp2);

    let dir = target_dir();
    std::fs::create_dir_all(&dir).ok();
    let p1 = dir.join("resampler_dump_44k_to_native.f32");
    let p2 = dir.join("resampler_dump_native_to_44k.f32");
    write_f32(&p1, &native);
    write_f32(&p2, &out);
    eprintln!("wrote {} ({} samples)", p1.display(), native.len());
    eprintln!("wrote {} ({} samples)", p2.display(), out.len());
}
