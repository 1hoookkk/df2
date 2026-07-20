//! candidates — the preset audition batch.
//!
//! Scans the freshest body-producing work on disk, certifies each candidate
//! through the retained sampled grid, renders one fixed-input audition WAV
//! per body at M0_Q0 (BODY SOLO, no normalization), and writes one folder:
//!
//!   out/candidates/bodies/<tag>__<name>__<sha12>.body240
//!   out/candidates/audio/<tag>__<name>__<sha12>.wav
//!   out/candidates/manifest.json
//!   out/candidates/MANIFEST.md
//!
//! With `--actors`, also runs the actor compiler over the measured-object IR
//! library (LPC pole scaffold, one extraction per source). Failures are
//! reported in the manifest, never repaired. Nothing here is promoted; the
//! operator listens, names keepers, and promotion happens explicitly after
//! that.

use serde::Serialize;
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use trench_core::cartridge::Cartridge;
use trench_core::engine::{FilterEngine, InputMode, SpatialMode};
use trench_core::stage_law::STAGE_SR;
use trench_workstation::app::AppState;
use trench_workstation::hash::sha256_hex;
use trench_workstation::model::SampledAudit;

#[derive(Serialize)]
struct CandidateRow {
    file: String,
    audio: String,
    body_sha256: String,
    tag: String,
    source: String,
    certified: bool,
    certify_pass: bool,
    max_pole_radius: f64,
    rendered_peak: f32,
    clipped_pcm: bool,
    note: String,
}

#[derive(Serialize)]
struct RejectedRow {
    source: String,
    reason: String,
}

#[derive(Serialize)]
struct Manifest {
    format: String,
    contract: String,
    sample_rate_hz: f64,
    audition_seconds: f32,
    audition_position: String,
    audition_mode: String,
    input_source: String,
    candidates: Vec<CandidateRow>,
    rejected: Vec<RejectedRow>,
}

const AUDITION_SECONDS: f32 = 5.0;
const MONITOR_GAIN: f32 = 1.0;

fn main() -> Result<(), String> {
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("workstation manifest must be inside the repository")
        .to_path_buf();
    let out_dir = repo_root.join("out").join("candidates");
    let bodies_dir = out_dir.join("bodies");
    let audio_dir = out_dir.join("audio");
    fs::create_dir_all(&bodies_dir).map_err(|error| error.to_string())?;
    fs::create_dir_all(&audio_dir).map_err(|error| error.to_string())?;

    // Fixed audition input: one deterministic source slice for every body.
    let input = fixed_input(&repo_root)?;
    let input_label = "wav-source-library (first cello match, first 5 s, mono, engine rate)";

    let mut rows: Vec<CandidateRow> = Vec::new();
    let mut rejected: Vec<RejectedRow> = Vec::new();
    let mut seen_body_hashes = HashSet::new();
    let include_actors = std::env::args().any(|argument| argument == "--actors");

    // 1. Existing packed bodies from the recent workstreams.
    for (tag, dir) in candidate_dirs(&repo_root) {
        let mut paths = Vec::new();
        collect_bodies(&dir, &mut paths);
        paths.sort();
        for path in paths {
            let bytes = match fs::read(&path) {
                Ok(bytes) if bytes.len() == 240 => bytes,
                Ok(bytes) => {
                    rejected.push(RejectedRow {
                        source: path.display().to_string(),
                        reason: format!("not a 240-byte body ({} bytes)", bytes.len()),
                    });
                    continue;
                }
                Err(error) => {
                    rejected.push(RejectedRow {
                        source: path.display().to_string(),
                        reason: format!("read failed: {error}"),
                    });
                    continue;
                }
            };
            let body_sha256 = sha256_hex(&bytes);
            if !seen_body_hashes.insert(body_sha256.clone()) {
                continue;
            }
            let stem = path
                .file_stem()
                .and_then(|value| value.to_str())
                .unwrap_or("unnamed")
                .replace('_', "-");
            let name = format!("{tag}__{stem}__{}", &body_sha256[..12]);
            emit_candidate(
                &name,
                tag.as_str(),
                &path.display().to_string(),
                &bytes,
                &input,
                &bodies_dir,
                &audio_dir,
                "packed body from the recent workstreams",
                &mut rows,
                &mut rejected,
            );
        }
    }

    // 2. The actor compiler is opt-in: the measured-object library is useful
    // source evidence, but it is too broad to mix into every preset audition.
    if include_actors {
        let mut state = AppState::new(&repo_root).map_err(|error| error.to_string())?;
        let mut ir_wavs = Vec::new();
        collect_wavs(
            &repo_root
                .join("wav-source-library")
                .join("measured_objects"),
            &mut ir_wavs,
        );
        ir_wavs.sort();
        for path in ir_wavs {
            let decoded = decode_wav_mono(&path);
            let result = decoded.and_then(|(samples, rate)| {
                state
                    .load_fixed_actor_audio(&samples, rate as f64, &path)
                    .map_err(|error| error.to_string())
            });
            match result {
                Ok(report) => {
                    let bytes = state
                        .session
                        .to_body_bytes()
                        .map_err(|error| error.to_string())?;
                    let body_sha256 = sha256_hex(&bytes);
                    if !seen_body_hashes.insert(body_sha256.clone()) {
                        continue;
                    }
                    let stem = path
                        .file_stem()
                        .and_then(|value| value.to_str())
                        .unwrap_or("unnamed")
                        .replace([' ', '_'], "-");
                    let name = format!("ACTOR__{stem}__{}", &body_sha256[..12]);
                    emit_candidate(
                        &name,
                        "ACTOR",
                        &path.display().to_string(),
                        &bytes,
                        &input,
                        &bodies_dir,
                        &audio_dir,
                        "LPC pole scaffold from measured audio; zeros closed (coincident with poles)",
                        &mut rows,
                        &mut rejected,
                    );
                    let _ = report;
                }
                Err(reason) => rejected.push(RejectedRow {
                    source: path.display().to_string(),
                    reason,
                }),
            }
        }
    }

    rows.sort_by(|left, right| left.file.cmp(&right.file));
    let manifest = Manifest {
        format: "trench-candidates-v1".to_owned(),
        contract: "sampled certification only; audible keep/kill remains the operator's decision"
            .to_owned(),
        sample_rate_hz: STAGE_SR,
        audition_seconds: AUDITION_SECONDS,
        audition_position: "M0_Q0 (authored corner anchor)".to_owned(),
        audition_mode: "BODY SOLO (raw six-stage cascade, no normalization)".to_owned(),
        input_source: input_label.to_owned(),
        candidates: rows,
        rejected,
    };
    let json = serde_json::to_string_pretty(&manifest).map_err(|error| error.to_string())?;
    fs::write(out_dir.join("manifest.json"), json).map_err(|error| error.to_string())?;
    let mut md = String::from("# Candidates — audition batch\n\n");
    md.push_str(&format!(
        "Input: {} · position M0_Q0 · BODY SOLO raw cascade · no normalization.\n\n",
        input_label
    ));
    md.push_str("| file | tag | cert | pole r max | peak | note |\n|---|---|---|---|---|---|\n");
    for row in &manifest.candidates {
        md.push_str(&format!(
            "| {} | {} | {} | {:.4} | {:.3} | {} |\n",
            row.file,
            row.tag,
            if row.certify_pass { "PASS" } else { "FAIL" },
            row.max_pole_radius,
            row.rendered_peak,
            row.note
        ));
    }
    md.push_str("\n## Rejected (never repaired, reported only)\n\n");
    for row in &manifest.rejected {
        md.push_str(&format!("- {} — {}\n", row.source, row.reason));
    }
    fs::write(out_dir.join("MANIFEST.md"), md).map_err(|error| error.to_string())?;
    println!(
        "candidates: {} certified, {} rejected -> {}",
        manifest.candidates.len(),
        manifest.rejected.len(),
        out_dir.display()
    );
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn emit_candidate(
    name: &str,
    tag: &str,
    source: &str,
    bytes: &[u8],
    input: &[f32],
    bodies_dir: &Path,
    audio_dir: &Path,
    note: &str,
    rows: &mut Vec<CandidateRow>,
    rejected: &mut Vec<RejectedRow>,
) {
    let audit = match SampledAudit::run(bytes) {
        Ok(audit) => audit,
        Err(error) => {
            rejected.push(RejectedRow {
                source: source.to_owned(),
                reason: format!("sampled audit could not run: {error}"),
            });
            return;
        }
    };
    if !audit.pass || !audit.certify_pass {
        rejected.push(RejectedRow {
            source: source.to_owned(),
            reason: "failed sampled packed-runtime certification".to_owned(),
        });
        return;
    }
    let (wav, peak, clipped) = match render_audition(bytes, input) {
        Ok(render) => render,
        Err(reason) => {
            rejected.push(RejectedRow {
                source: source.to_owned(),
                reason,
            });
            return;
        }
    };
    let file = format!("{name}.body240");
    let audio = format!("{name}.wav");
    if let Err(error) = fs::write(bodies_dir.join(&file), bytes) {
        rejected.push(RejectedRow {
            source: source.to_owned(),
            reason: format!("body write failed: {error}"),
        });
        return;
    }
    if let Err(error) = fs::write(audio_dir.join(&audio), wav) {
        rejected.push(RejectedRow {
            source: source.to_owned(),
            reason: format!("audio write failed: {error}"),
        });
        return;
    }
    rows.push(CandidateRow {
        file,
        audio,
        body_sha256: sha256_hex(bytes),
        tag: tag.to_owned(),
        source: source.to_owned(),
        certified: true,
        certify_pass: true,
        max_pole_radius: audit.maximum_pole_radius,
        rendered_peak: peak,
        clipped_pcm: clipped,
        note: note.to_owned(),
    });
}

/// Fixed 64-sample-block render of the raw cascade at M0_Q0, matching the
/// GUI monitor path. No per-body gain staging of any kind.
fn render_audition(body: &[u8], input: &[f32]) -> Result<(Vec<u8>, f32, bool), String> {
    let cartridge = Cartridge::from_body_bytes("candidates-audition", body, 1.0)
        .map_err(|error| error.to_string())?;
    let mut engine = FilterEngine::new();
    engine.prepare(STAGE_SR);
    engine.load_cartridge(cartridge);
    engine.set_input_mode(InputMode::None);
    engine.set_spatial_mode(SpatialMode::Off);
    engine.set_amount(1.0);
    engine.debug.spatial_enabled = false;
    engine.debug.agc_enabled = false;
    engine.debug.dc_block_enabled = false;
    engine.debug.saturation_enabled = false;
    let frames = (AUDITION_SECONDS * STAGE_SR as f32) as usize;
    let mut out = vec![0.0f32; frames];
    let mut cursor = 0usize;
    while cursor < frames {
        let end = (cursor + 64).min(frames);
        let take = end - cursor;
        let mut left: Vec<f32> = (0..take)
            .map(|index| input[(cursor + index) % input.len()])
            .collect();
        let mut right = left.clone();
        engine.process_block(&mut left, &mut right, 0.0, 0.0);
        out[cursor..end].copy_from_slice(&left[..take]);
        cursor = end;
    }
    if out.iter().any(|sample| !sample.is_finite()) {
        return Err("render produced nonfinite samples".to_owned());
    }
    let peak = out.iter().fold(0.0f32, |acc, sample| acc.max(sample.abs()));
    if peak <= 1.0e-6 {
        return Err("render is silent".to_owned());
    }
    let clipped = peak > 1.0;
    let mut wav = wav_pcm16_header(out.len());
    for sample in &out {
        let scaled = (sample * MONITOR_GAIN * 32767.0).clamp(-32768.0, 32767.0);
        wav.extend_from_slice(&(scaled as i16).to_le_bytes());
    }
    Ok((wav, peak, clipped))
}

fn wav_pcm16_header(frames: usize) -> Vec<u8> {
    let rate = STAGE_SR as u32;
    let data = (frames * 2) as u32;
    let mut wav = Vec::with_capacity(44);
    wav.extend_from_slice(b"RIFF");
    wav.extend_from_slice(&(36 + data).to_le_bytes());
    wav.extend_from_slice(b"WAVEfmt ");
    wav.extend_from_slice(&16u32.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes());
    wav.extend_from_slice(&rate.to_le_bytes());
    wav.extend_from_slice(&(rate * 2).to_le_bytes());
    wav.extend_from_slice(&2u16.to_le_bytes());
    wav.extend_from_slice(&16u16.to_le_bytes());
    wav.extend_from_slice(b"data");
    wav.extend_from_slice(&data.to_le_bytes());
    wav
}

fn candidate_dirs(repo_root: &Path) -> Vec<(String, PathBuf)> {
    let tmp = repo_root.join("dev").join("tmp");
    let mut dirs: Vec<(String, PathBuf)> = vec![
        ("MASTER".into(), tmp.join("master_body_trial_20260720")),
        ("SHIPV2".into(), tmp.join("ship_v2")),
        ("SHIPV2".into(), tmp.join("ship_v2_batch2")),
        ("SHIP".into(), tmp.join("ship_bodies")),
        ("CROSS4".into(), tmp.join("cross4_bodies")),
        ("VOW2".into(), tmp.join("vowel_from_tables_v2")),
        ("NAMES".into(), tmp.join("namesakes")),
        // The checked-in plugin body folder still contains the legacy 132-body
        // pool. It is not a candidate source; promotion is a separate,
        // explicit operator action after packed-runtime proof and listening.
    ];
    dirs.retain(|(_, dir)| dir.is_dir());
    dirs
}

fn collect_bodies(root: &Path, output: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    for entry in entries.filter_map(Result::ok) {
        let path = entry.path();
        if path.is_dir() {
            collect_bodies(&path, output);
        } else if path
            .extension()
            .and_then(|value| value.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("body240"))
        {
            output.push(path);
        }
    }
}

fn collect_wavs(root: &Path, output: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    for entry in entries.filter_map(Result::ok) {
        let path = entry.path();
        if path.is_dir() {
            collect_wavs(&path, output);
        } else if path
            .extension()
            .and_then(|value| value.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("wav"))
        {
            output.push(path);
        }
    }
}

fn fixed_input(repo_root: &Path) -> Result<Vec<f32>, String> {
    let mut wavs = Vec::new();
    collect_wavs(&repo_root.join("wav-source-library"), &mut wavs);
    wavs.sort();
    let path = wavs
        .iter()
        .find(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .unwrap_or_default()
                .to_lowercase()
                .contains("cello")
        })
        .or_else(|| wavs.first())
        .ok_or_else(|| "no wav source available for the fixed input".to_owned())?;
    let (mono, _) = decode_wav_mono(path)?;
    let frames = (AUDITION_SECONDS * STAGE_SR as f32) as usize;
    if mono.len() < frames {
        return Err("fixed input source is shorter than the audition window".to_owned());
    }
    Ok(mono[..frames].to_vec())
}

fn decode_wav_mono(path: &Path) -> Result<(Vec<f32>, u32), String> {
    use rodio::{Decoder, Source};
    use std::io::BufReader;
    let file = fs::File::open(path).map_err(|error| format!("WAV could not be opened: {error}"))?;
    let decoder = Decoder::new(BufReader::new(file))
        .map_err(|error| format!("WAV could not be decoded: {error}"))?;
    let rate = decoder.sample_rate();
    let channels = decoder.channels() as usize;
    let interleaved = decoder
        .convert_samples::<f32>()
        .take(12_000_000)
        .collect::<Vec<f32>>();
    if channels == 0 || interleaved.len() < channels * 2_048 {
        return Err("WAV is too short".to_owned());
    }
    let mono = interleaved
        .chunks(channels)
        .map(|frame| frame.iter().copied().sum::<f32>() / frame.len() as f32)
        .collect::<Vec<_>>();
    if mono.iter().any(|sample| !sample.is_finite()) {
        return Err("WAV contains nonfinite samples".to_owned());
    }
    Ok((mono, rate))
}
