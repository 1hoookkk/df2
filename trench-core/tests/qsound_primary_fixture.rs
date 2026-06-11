use std::path::{Path, PathBuf};

use hound::{SampleFormat, WavReader, WavSpec, WavWriter};
use trench_core::cartridge::SpatialProfile;
use trench_core::qsound_spatial::QSoundSpatial;

const SAMPLE_RATE: u32 = 11_025;
const FRAMES: usize = 166_591;
const IMPULSE_SAMPLE: usize = 30_000;
const IMPULSE_AMPLITUDE: f32 = 0.5;
const FIXTURE: &str = "../ref/canonical/qsound/qcreator_qright90_impulse_11025.wav";
const PROFILE: &str = "../ref/canonical/qsound/profile_engine_recon_source.json";
const CANDIDATE: &str = "../dev/tmp/qsound/profile_qright90_render.wav";
const FALLBACK_CANDIDATE: &str = "../dev/tmp/qsound/fallback_qright90_render.wav";

#[derive(Debug)]
struct Stereo {
    l: Vec<f32>,
    r: Vec<f32>,
}

fn read_pcm16_stereo(path: &Path) -> Stereo {
    let mut reader = WavReader::open(path).expect("open fixture");
    let spec = reader.spec();
    assert_eq!(spec.channels, 2);
    assert_eq!(spec.sample_rate, SAMPLE_RATE);
    assert_eq!(spec.bits_per_sample, 16);
    assert_eq!(spec.sample_format, SampleFormat::Int);

    let samples: Vec<f32> = reader
        .samples::<i16>()
        .map(|sample| sample.expect("decode fixture sample") as f32 / 32768.0)
        .collect();
    let mut l = Vec::with_capacity(samples.len() / 2);
    let mut r = Vec::with_capacity(samples.len() / 2);
    for frame in samples.chunks_exact(2) {
        l.push(frame[0]);
        r.push(frame[1]);
    }
    Stereo { l, r }
}

fn write_float_stereo(path: &Path, stereo: &Stereo) {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).expect("create candidate output directory");
    }
    let spec = WavSpec {
        channels: 2,
        sample_rate: SAMPLE_RATE,
        bits_per_sample: 32,
        sample_format: SampleFormat::Float,
    };
    let mut writer = WavWriter::create(path, spec).expect("create candidate wav");
    for (&l, &r) in stereo.l.iter().zip(&stereo.r) {
        writer.write_sample(l).expect("write L");
        writer.write_sample(r).expect("write R");
    }
    writer.finalize().expect("finalize candidate wav");
}

fn argmax_abs(samples: &[f32]) -> usize {
    samples
        .iter()
        .enumerate()
        .max_by(|(_, a), (_, b)| a.abs().total_cmp(&b.abs()))
        .map(|(index, _)| index)
        .expect("non-empty buffer")
}

fn rms(samples: impl Iterator<Item = f32>, count: usize) -> f32 {
    (samples.map(|sample| sample * sample).sum::<f32>() / count as f32).sqrt()
}

fn residual_db(reference: &[f32], candidate: &[f32]) -> (f32, f32) {
    let count = reference.len().min(candidate.len());
    let reference_rms = rms(reference[..count].iter().copied(), count);
    let residual_rms = rms(
        reference[..count]
            .iter()
            .zip(&candidate[..count])
            .map(|(&a, &b)| a - b),
        count,
    );
    (
        20.0 * residual_rms.log10(),
        20.0 * (residual_rms / reference_rms).log10(),
    )
}

fn max_abs_residual(reference: &[f32], candidate: &[f32]) -> f32 {
    reference
        .iter()
        .zip(candidate)
        .map(|(&a, &b)| (a - b).abs())
        .fold(0.0, f32::max)
}

fn fixture_path(path: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join(path)
}

#[test]
fn measure_profile_against_qcreator_qright90_fixture() {
    let reference = read_pcm16_stereo(&fixture_path(FIXTURE));
    assert_eq!(reference.l.len(), FRAMES);
    assert_eq!(reference.r.len(), FRAMES);
    assert_eq!(argmax_abs(&reference.l), 30_001);
    assert_eq!(argmax_abs(&reference.r), 30_000);

    let profile_json =
        std::fs::read_to_string(fixture_path(PROFILE)).expect("read reconstruction profile");
    let profile: SpatialProfile =
        serde_json::from_str(&profile_json).expect("parse reconstruction profile");
    let mut stage = QSoundSpatial::new(SAMPLE_RATE as f32);
    stage.set_profile(&profile);
    stage.set_space(1.0);

    let mut candidate = Stereo {
        l: vec![0.0; FRAMES],
        r: vec![0.0; FRAMES],
    };
    candidate.l[IMPULSE_SAMPLE] = IMPULSE_AMPLITUDE;
    candidate.r[IMPULSE_SAMPLE] = IMPULSE_AMPLITUDE;
    stage.process_stereo(&mut candidate.l, &mut candidate.r);
    write_float_stereo(&fixture_path(CANDIDATE), &candidate);

    let (l_residual_dbfs, l_null_db) = residual_db(&reference.l, &candidate.l);
    let (r_residual_dbfs, r_null_db) = residual_db(&reference.r, &candidate.r);
    println!(
        "profile qright90: ref_argmax=({}, {}) candidate_argmax=({}, {})",
        argmax_abs(&reference.l),
        argmax_abs(&reference.r),
        argmax_abs(&candidate.l),
        argmax_abs(&candidate.r)
    );
    println!(
        "profile qright90: L residual={l_residual_dbfs:.3} dBFS null={l_null_db:.3} dB; R residual={r_residual_dbfs:.3} dBFS null={r_null_db:.3} dB"
    );

    assert!(l_residual_dbfs.is_finite());
    assert!(r_residual_dbfs.is_finite());
}

#[test]
fn fallback_nulls_qcreator_qright90_fixture_at_native_rate() {
    let reference = read_pcm16_stereo(&fixture_path(FIXTURE));
    let mut stage = QSoundSpatial::new(SAMPLE_RATE as f32);
    stage.set_space(1.0);
    stage.set_fallback_pan(1.0);

    let mut candidate = Stereo {
        l: vec![0.0; FRAMES],
        r: vec![0.0; FRAMES],
    };
    candidate.l[IMPULSE_SAMPLE] = IMPULSE_AMPLITUDE;
    candidate.r[IMPULSE_SAMPLE] = IMPULSE_AMPLITUDE;
    stage.process_stereo(&mut candidate.l, &mut candidate.r);
    write_float_stereo(&fixture_path(FALLBACK_CANDIDATE), &candidate);

    let l_max_residual = max_abs_residual(&reference.l, &candidate.l);
    let r_max_residual = max_abs_residual(&reference.r, &candidate.r);
    println!(
        "fallback qright90: ref_argmax=({}, {}) candidate_argmax=({}, {})",
        argmax_abs(&reference.l),
        argmax_abs(&reference.r),
        argmax_abs(&candidate.l),
        argmax_abs(&candidate.r)
    );
    println!("fallback qright90: max residual L={l_max_residual:.9} R={r_max_residual:.9}");

    assert_eq!(argmax_abs(&candidate.l), 30_001);
    assert_eq!(argmax_abs(&candidate.r), 30_000);
    assert!(l_max_residual <= f32::EPSILON);
    assert!(r_max_residual <= f32::EPSILON);
}

#[test]
fn fallback_left_extreme_is_the_constructed_mirror_of_qright90() {
    let reference = read_pcm16_stereo(&fixture_path(FIXTURE));
    let mut stage = QSoundSpatial::new(SAMPLE_RATE as f32);
    stage.set_space(1.0);
    stage.set_fallback_pan(-1.0);

    let mut candidate = Stereo {
        l: vec![0.0; FRAMES],
        r: vec![0.0; FRAMES],
    };
    candidate.l[IMPULSE_SAMPLE] = IMPULSE_AMPLITUDE;
    candidate.r[IMPULSE_SAMPLE] = IMPULSE_AMPLITUDE;
    stage.process_stereo(&mut candidate.l, &mut candidate.r);

    assert!(max_abs_residual(&reference.r, &candidate.l) <= f32::EPSILON);
    assert!(max_abs_residual(&reference.l, &candidate.r) <= f32::EPSILON);
}

#[test]
fn fallback_center_is_literal_dry_mono() {
    let mut stage = QSoundSpatial::new(SAMPLE_RATE as f32);
    stage.set_space(1.0);
    stage.set_fallback_pan(0.0);

    let mut l = vec![1.0, 0.0, -0.25, 0.75];
    let mut r = vec![0.0, 1.0, 0.25, -0.75];
    stage.process_stereo(&mut l, &mut r);

    assert_eq!(l, vec![0.5, 0.5, 0.0, 0.0]);
    assert_eq!(r, l);
}

#[test]
fn fallback_midpoint_interpolates_center_to_right_extreme() {
    fn render(pan: f32) -> Stereo {
        let mut stage = QSoundSpatial::new(SAMPLE_RATE as f32);
        stage.set_space(1.0);
        stage.set_fallback_pan(pan);
        let mut output = Stereo {
            l: vec![0.0; 128],
            r: vec![0.0; 128],
        };
        output.l[16] = 0.5;
        output.r[16] = 0.5;
        stage.process_stereo(&mut output.l, &mut output.r);
        output
    }

    let center = render(0.0);
    let midpoint = render(0.5);
    let right = render(1.0);
    for i in 0..center.l.len() {
        assert!((midpoint.l[i] - 0.5 * (center.l[i] + right.l[i])).abs() <= f32::EPSILON);
        assert!((midpoint.r[i] - 0.5 * (center.r[i] + right.r[i])).abs() <= f32::EPSILON);
    }
}

#[test]
fn fallback_resampling_is_finite_and_reset_clears_pending_tail() {
    let mut stage = QSoundSpatial::new(48_000.0);
    stage.set_space(1.0);

    let mut l = vec![1.0];
    let mut r = vec![1.0];
    stage.process_stereo(&mut l, &mut r);
    stage.reset();

    let mut l = vec![0.0; 256];
    let mut r = vec![0.0; 256];
    stage.process_stereo(&mut l, &mut r);
    assert!(l.iter().all(|&sample| sample == 0.0));
    assert!(r.iter().all(|&sample| sample == 0.0));

    l[0] = 1.0;
    r[0] = 1.0;
    stage.process_stereo(&mut l, &mut r);
    assert!(l.iter().all(|sample| sample.is_finite()));
    assert!(r.iter().all(|sample| sample.is_finite()));
    assert!(l.iter().any(|&sample| sample != 0.0));
    assert_eq!(r[0], 16_382.0 / 16_384.0);
}
