//! forge_core — the source → body workflow.
//!
//! main.rs asks; forge_core answers. There is no egui in this file. It owns the
//! four corner slots, the puck (Morph × Q), the Q ruleset amount, and every
//! decision about how loaded sound becomes a response surface, then a packed
//! 4-corner body: fitting, actor alignment, Q100 auto-derivation, validity,
//! cartridge JSON, and the save path.
//!
//! The UI never builds the 240-byte body, never derives Q100, never serializes
//! the cartridge, and never decides whether a body is valid. It calls a method.
//! Stage rows are bookkeeping; the response audit is the authoring truth.

use std::path::{Path, PathBuf};

use trench_core::cartridge::{Cartridge, CornerData};
use trench_core::minifloat::PackedCorners;

use crate::dsp::{
    self, condition_fit_window, display_name, fit_window_mode, load_wav_with_meta,
    magnitude_response, source_envelope, FitMode, AUTHORING_RATE,
};

/// The four corner slots, in body order: M0_Q0, M100_Q0, M0_Q100, M100_Q100.
/// A/B are the Morph endpoints (Q0 row); C/D are the Q endpoints (Q100 row).
pub const CARD_LABELS: [&str; 4] = ["A · MORPH 0", "B · MORPH 100", "C · Q", "D · Q"];

/// Export labels matching the runtime keyframe order.
const CORNER_LABELS: [&str; 4] = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
const EXPORT_BOOST: f64 = 4.0;

/// A pickable source file for the corner dropdowns.
pub struct SourceEntry {
    pub label: String,
    pub path: PathBuf,
    /// Top-level folder under the pack — the dropdown groups by this.
    pub category: String,
}

/// Every `.wav` in the whole source pack (the phonetic bank, the loose pool, and
/// the percussion/texture sources), scanned and sorted — the full list each corner
/// dropdown offers. Any corner can load any source. Empty if the pack isn't here.
pub fn available_sources() -> Vec<SourceEntry> {
    let mut out = Vec::new();
    // Scan the pack root (the parent of the bank dir = corners_audio_only), which
    // holds the bank, the loose phonetic pool, and other_sources (kb6/nmr/plasma).
    if let Some(base) = legisign_bank_dir().and_then(|p| p.parent().map(Path::to_path_buf)) {
        collect_wavs(&base, &base, &mut out);
        collect_corners(&base, &base, &mut out); // DESIGN + PHYSICS corners, same wells
    }
    out.sort_by(|a, b| a.category.cmp(&b.category).then(a.label.cmp(&b.label)));
    out
}

/// Every verbatim `.bin` preset in `ref/presets/`, for the PRESET dropdown.
pub fn available_presets() -> Vec<SourceEntry> {
    let mut out = Vec::new();
    if let Some(dir) = presets_dir() {
        if let Ok(entries) = std::fs::read_dir(&dir) {
            for e in entries.flatten() {
                let p = e.path();
                if p.extension()
                    .map(|x| x.eq_ignore_ascii_case("bin"))
                    .unwrap_or(false)
                {
                    let label = p
                        .file_stem()
                        .and_then(|s| s.to_str())
                        .unwrap_or("?")
                        .to_owned();
                    out.push(SourceEntry {
                        label,
                        path: p,
                        category: String::new(),
                    });
                }
            }
        }
    }
    out.sort_by(|a, b| a.label.cmp(&b.label));
    out
}

fn presets_dir() -> Option<PathBuf> {
    let p = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("ref")
        .join("presets");
    p.is_dir().then_some(p)
}

fn collect_wavs(dir: &Path, base: &Path, out: &mut Vec<SourceEntry>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_wavs(&path, base, out);
        } else if path
            .extension()
            .map(|e| e.eq_ignore_ascii_case("wav"))
            .unwrap_or(false)
        {
            let label = path
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("?")
                .to_owned();
            let category = category_of(dir, base);
            out.push(SourceEntry {
                label,
                path,
                category,
            });
        }
    }
}

/// FULL relative folder path of `dir` under `base`, "/"-joined — the menu tree
/// path (each component becomes a nested submenu). Empty for files in the root.
fn category_of(dir: &Path, base: &Path) -> String {
    dir.strip_prefix(base)
        .map(|rel| {
            rel.components()
                .map(|c| c.as_os_str().to_string_lossy().into_owned())
                .collect::<Vec<_>>()
                .join("/")
        })
        .unwrap_or_default()
}

/// Scan precomputed corner files (`*.corner.json`) — the DESIGN (weapons) and
/// PHYSICS (vowel/tube/bell) faucets. They load straight into a well, no fit.
fn collect_corners(dir: &Path, base: &Path, out: &mut Vec<SourceEntry>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_corners(&path, base, out);
        } else if path
            .file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.ends_with(".corner.json"))
            .unwrap_or(false)
        {
            let label = path
                .file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.trim_end_matches(".corner.json").to_owned())
                .unwrap_or_else(|| "?".to_owned());
            let category = category_of(dir, base);
            out.push(SourceEntry {
                label,
                path,
                category,
            });
        }
    }
}

/// One loaded corner: the fitted filter plus cached display curves and file facts.
/// The UI reads these to draw a card; it does not produce them.
pub struct Corner {
    pub name: String,
    pub fit: CornerData,
    /// Smoothed source spectral envelope — the green ghost.
    pub src_db: Vec<[f64; 2]>,
    /// The fitted filter's own magnitude response.
    pub fit_db: Vec<[f64; 2]>,
    pub duration_s: f64,
    pub sample_rate: u32,
    pub channels: u16,
    pub bits: u16,
    /// The raw mono samples this corner was fit from (empty for precomputed
    /// `.corner.json` / ROM loads that carry no source). Kept so switching the
    /// fit mode can RE-FIT the same sound by ear instead of forcing a reload.
    samples: Vec<f64>,
    /// Sample rate of `samples`.
    src_sr: f64,
}

/// Owns the source → body workflow. Construct with `Default`.
pub struct ForgeCore {
    corners: [Option<Corner>; 4],
    morph: f32,
    q: f32,
    /// Q ruleset amount: how much hidden Q100 corners sharpen off their Q0 source.
    q_sharp: f32,
    /// Bumps whenever the assembled body changes (load / reset / Q amount).
    /// The UI uses it to invalidate render caches; the puck does not bump it.
    body_rev: u64,
    /// A reference frame loaded verbatim (e.g. Millennium) — when set, `body()`
    /// returns it as-is (no fit, no actor realignment), so a known frame shows on
    /// the surface exactly as authored. Cleared when a source is loaded or reset.
    reference_body: Option<[CornerData; 4]>,
    /// The verbatim packed words behind `reference_body`, when a 240-byte body was
    /// loaded. Kept so preview/export use the EXACT ROM words (no decode→repack
    /// round trip) — the byte-authoritative path. `None` for fitted/derived bodies.
    reference_packed: Option<PackedCorners>,
    /// Which fitter proposes a corner from a dropped sound. The fit is a starting
    /// point; this picks how it's derived. Default = the original peak picker.
    fit_mode: FitMode,
}

impl Default for ForgeCore {
    fn default() -> Self {
        Self {
            corners: core::array::from_fn(|_| None),
            morph: 0.0, // open clean at HOME (M0/Q0), not halfway into a hot Q100
            q: 0.0,
            q_sharp: 0.3, // gentler Q-sharpen so the Q axis sweeps instead of slamming
            body_rev: 0,
            reference_body: None,
            reference_packed: None,
            fit_mode: FitMode::default(),
        }
    }
}

impl ForgeCore {
    // ── reads ───────────────────────────────────────────────────────────────
    pub fn corner(&self, i: usize) -> Option<&Corner> {
        self.corners.get(i).and_then(|c| c.as_ref())
    }

    pub fn morph(&self) -> f32 {
        self.morph
    }

    pub fn q(&self) -> f32 {
        self.q
    }

    pub fn q_amount(&self) -> f32 {
        self.q_sharp
    }

    /// Bumps whenever the body changes; the puck (morph/q) does not move it.
    pub fn body_rev(&self) -> u64 {
        self.body_rev
    }

    pub fn count(&self) -> usize {
        self.corners.iter().flatten().count()
    }

    /// First empty slot, or 0 if all are full.
    pub fn next_empty(&self) -> usize {
        self.corners.iter().position(|c| c.is_none()).unwrap_or(0)
    }

    /// PLAY is allowed once at least one corner is loaded.
    pub fn can_play(&self) -> bool {
        self.count() > 0
    }

    /// SAVE is allowed when a body can be assembled (an anchor exists).
    pub fn can_save(&self) -> bool {
        self.body().is_some()
    }

    // ── puck + Q ruleset ──────────────────────────────────────────────────────
    /// Move the Morph × Q puck. Cheap; does not rebuild the body.
    pub fn set_puck(&mut self, morph: f32, q: f32) {
        self.morph = morph.clamp(0.0, 1.0);
        self.q = q.clamp(0.0, 1.0);
    }

    /// Set the Q ruleset amount. Returns true if it changed (the body moved).
    pub fn set_q_amount(&mut self, value: f32) -> bool {
        let v = value.clamp(0.0, 1.0);
        if (v - self.q_sharp).abs() < f32::EPSILON {
            return false;
        }
        self.q_sharp = v;
        self.body_rev += 1;
        true
    }

    /// Which fitter the next dropped sound is proposed by.
    pub fn fit_mode(&self) -> FitMode {
        self.fit_mode
    }

    /// Switch the fit mode and immediately RE-FIT every corner that still carries
    /// its source samples (so you can A/B the proposals by ear without reloading).
    /// Precomputed `.corner.json` / verbatim ROM corners have no source and are
    /// left untouched. Returns true if anything changed.
    pub fn set_fit_mode(&mut self, mode: FitMode) -> bool {
        if mode == self.fit_mode {
            return false;
        }
        self.fit_mode = mode;
        let mut refit_any = false;
        for slot in self.corners.iter_mut() {
            if let Some(c) = slot.as_mut() {
                if c.samples.len() >= 64 {
                    refit(c, mode);
                    refit_any = true;
                }
            }
        }
        self.body_rev += 1;
        refit_any
    }

    // ── loading ─────────────────────────────────────────────────────────────
    /// Load a WAV into slot `i`, fit it, and cache its display curves.
    pub fn load_source(&mut self, i: usize, path: &Path) -> Result<(), String> {
        let (samples, meta) = load_wav_with_meta(path)?;
        let fit_meta = FileFacts {
            name: display_name(path),
            duration_s: meta.duration_s,
            sample_rate: meta.sample_rate,
            channels: meta.channels,
            bits: meta.bits,
        };
        self.install(i, &samples, meta.sample_rate as f64, fit_meta);
        Ok(())
    }

    /// Load a precomputed corner (a DESIGN weapon or a PHYSICS body) straight into
    /// slot `i` — no WAV, no fit. The three faucets all land in the same well: a
    /// `.corner.json` is a compiled-v1 frame; we take its first corner verbatim.
    pub fn load_corner(&mut self, i: usize, path: &Path) -> Result<(), String> {
        let json = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
        let cart = Cartridge::from_json(&json)?;
        let corner = cart.corners[0];
        let fit_db = magnitude_response(&corner, AUTHORING_RATE);
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.trim_end_matches(".corner.json").to_owned())
            .unwrap_or_else(|| "corner".to_owned());
        self.corners[i] = Some(Corner {
            name,
            fit: corner,
            src_db: fit_db.clone(), // no source envelope — the corner IS the shape
            fit_db,
            duration_s: 0.0,
            sample_rate: AUTHORING_RATE as u32,
            channels: 1,
            bits: 32,
            samples: Vec::new(), // precomputed corner — nothing to re-fit
            src_sr: 0.0,
        });
        self.reference_body = None;
        self.reference_packed = None;
        self.body_rev += 1;
        Ok(())
    }

    /// Load the curated Legisign / Ladefoged four-corner source bank.
    ///
    /// This is the app's built-in phonetic starter body:
    /// A=/i/ bright front, B=/u/ dark back, C=/a/ open, D=/sh/ consonant-rich.
    pub fn load_legisign_phonetic_bank(&mut self) -> Result<(), String> {
        const PRIMES: [(&str, &str); 4] = [
            (
                "corner_1_bright_front_vowel__prime_i.wav",
                "C1 /i/ bright front",
            ),
            ("corner_2_dark_back_vowel__prime_u.wav", "C2 /u/ dark back"),
            ("corner_3_open_vowel__prime_a.wav", "C3 /a/ open"),
            (
                "corner_4_consonant_rich_spectral_mode__prime_sh.wav",
                "C4 /sh/ consonant",
            ),
        ];

        let base = legisign_prime_dir().ok_or("Legisign phonetic bank not found")?;
        let mut loaded: [Option<Corner>; 4] = core::array::from_fn(|_| None);
        for (i, (file, label)) in PRIMES.iter().enumerate() {
            let path = base.join(file);
            let (samples, meta) =
                load_wav_with_meta(&path).map_err(|e| format!("{}: {e}", path.display()))?;
            let facts = FileFacts {
                name: (*label).to_owned(),
                duration_s: meta.duration_s,
                sample_rate: meta.sample_rate,
                channels: meta.channels,
                bits: meta.bits,
            };
            loaded[i] = Some(Self::fit_corner(
                &samples,
                meta.sample_rate as f64,
                facts,
                self.fit_mode,
            ));
        }

        self.corners = loaded;
        self.reference_body = None;
        self.reference_packed = None;
        self.morph = 0.0;
        self.q = 0.0;
        self.body_rev += 1;
        Ok(())
    }

    /// Load a verbatim 240-byte ROM corner block directly into the four corners —
    /// bit-accurate, the gold path (no JSON, no fit, no realignment). Layout: 4
    /// corners A/B/C/D = M0_Q0/M100_Q0/M0_Q100/M100_Q100, 30 little-endian u16 each
    /// (6 stages × 5). `body()` then returns it verbatim, so the surface is exactly
    /// what the hardware plays. Cleared when a source is loaded or reset.
    pub fn load_reference_rom(&mut self, path: &Path, name: &str) -> Result<(), String> {
        let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
        let packed = trench_core::minifloat::PackedCorners::from_rom_bytes(&bytes)
            .map_err(|e| e.to_string())?;
        // Decode each corner verbatim by interpolating at its own grid position.
        let corners = [
            packed.interpolate(0.0, 0.0),
            packed.interpolate(1.0, 0.0),
            packed.interpolate(0.0, 1.0),
            packed.interpolate(1.0, 1.0),
        ];
        const LABELS: [&str; 4] = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
        for (ci, &corner) in corners.iter().enumerate() {
            let fit_db = magnitude_response(&corner, AUTHORING_RATE);
            self.corners[ci] = Some(Corner {
                name: format!("{name} {}", LABELS[ci]),
                fit: corner,
                src_db: Vec::new(),
                fit_db,
                duration_s: 0.0,
                sample_rate: AUTHORING_RATE as u32,
                channels: 1,
                bits: 16,
                samples: Vec::new(), // verbatim ROM corner — nothing to re-fit
                src_sr: 0.0,
            });
        }
        self.reference_body = Some(corners);
        // Keep the EXACT ROM words alive so preview/export stay byte-authoritative
        // (decode→repack would lose verbatim parity). This is the gold path.
        self.reference_packed = Some(packed);
        self.morph = 0.0;
        self.q = 0.0;
        self.body_rev += 1;
        Ok(())
    }

    /// Load already-captured mono samples into slot `i` (the capture path).
    pub fn load_samples(&mut self, i: usize, samples: &[f64], sample_rate: f64, name: String) {
        if samples.len() < 64 {
            return;
        }
        let facts = FileFacts {
            name,
            duration_s: samples.len() as f64 / sample_rate,
            sample_rate: sample_rate as u32,
            channels: 1,
            bits: 32,
        };
        self.install(i, samples, sample_rate, facts);
    }

    /// Window → fit → cache curves → store. The single fit path for both loaders.
    fn install(&mut self, i: usize, samples: &[f64], sr: f64, facts: FileFacts) {
        let corner = Self::fit_corner(samples, sr, facts, self.fit_mode);
        self.corners[i] = Some(corner);
        self.reference_body = None; // a loaded source supersedes a reference frame
        self.reference_packed = None;
        self.body_rev += 1;
    }

    fn fit_corner(samples: &[f64], sr: f64, facts: FileFacts, mode: FitMode) -> Corner {
        let (fit, fit_db, src_db) = fit_from_samples(samples, sr, mode);
        Corner {
            name: facts.name,
            fit,
            src_db,
            fit_db,
            duration_s: facts.duration_s,
            sample_rate: facts.sample_rate,
            channels: facts.channels,
            bits: facts.bits,
            samples: samples.to_vec(),
            src_sr: sr,
        }
    }

    // ── body assembly ─────────────────────────────────────────────────────────
    /// Assemble the 4-corner body around **HOME (M0_Q0)** as the identity anchor.
    /// HOME defines the six actors; every other corner inherits that actor identity
    /// (via `align_to_anchor`) before it is allowed to drift:
    ///
    /// - **HOME** (M0_Q0): the captured home pose — the coordinate origin.
    /// - **MORPH** (M100_Q0): the same body, swept. A kin variation of HOME (poles
    ///   shifted up a fifth) until its own source is captured — so the Morph axis
    ///   always has somewhere to glide.
    /// - **TENSION** (M0_Q100): HOME with more Q — `sharpen_corner` tightens the
    ///   pole radii and sharpens the zeros (the "tension seed") until its own
    ///   source is captured.
    /// - **MORPH+TENSION** (M100_Q100): the tension seed of MORPH, likewise.
    ///
    /// Returns None when HOME (and every other slot) is empty. NOTE: a captured
    /// Q100 corner is currently an independent fit re-indexed onto HOME's actors;
    /// the joint refit (warm-started from the tension seed, drift allowed while
    /// actor-locked) is the next step and is not yet wired.
    pub fn body(&self) -> Option<[CornerData; 4]> {
        if let Some(b) = self.reference_body {
            return Some(b); // a reference frame loaded verbatim — its own morph
        }
        let anchor_src = self.corners[0]
            .as_ref()
            .or_else(|| self.corners.iter().flatten().next())?;
        let anchor = dsp::canonical_anchor(&anchor_src.fit, AUTHORING_RATE);
        let inherit = |i: usize| {
            self.corners[i]
                .as_ref()
                .map(|c| dsp::align_to_anchor(&anchor, &c.fit, AUTHORING_RATE))
        };
        let amt = self.q_sharp as f64;
        let home = inherit(0).unwrap_or(anchor);
        // kin variation: HOME swept up a fifth, so the Morph axis glides even from
        // a single load (instead of an exact, motionless HOME duplicate).
        let morph = inherit(1).unwrap_or_else(|| dsp::shift_corner(&home, 1.5, AUTHORING_RATE));
        let tension = inherit(2).unwrap_or_else(|| dsp::sharpen_corner(&home, amt, AUTHORING_RATE));
        let morph_tension =
            inherit(3).unwrap_or_else(|| dsp::sharpen_corner(&morph, amt, AUTHORING_RATE));
        Some([home, morph, tension, morph_tension])
    }

    /// The coefficients at the current puck position, through the proven packed
    /// interpolation. None when nothing is loaded. A verbatim ROM body interpolates
    /// its EXACT words (no decode→repack); a fitted body packs then interpolates.
    pub fn preview(&self) -> Option<CornerData> {
        if let Some(p) = &self.reference_packed {
            return Some(p.interpolate(self.morph.clamp(0.0, 1.0), self.q.clamp(0.0, 1.0)));
        }
        Some(dsp::body_preview(&self.body()?, self.morph, self.q))
    }

    /// The body's authoritative packed words — verbatim when a 240-byte body was
    /// loaded, otherwise derived-packed-canonical from the assembled four corners.
    /// This is the SINGLE coefficient surface every save/export goes through.
    fn packed_authority(&self) -> Option<PackedCorners> {
        if let Some(p) = &self.reference_packed {
            return Some(p.clone());
        }
        Some(PackedCorners::from_corner_data(&self.body()?))
    }

    // ── reset / export / save ───────────────────────────────────────────────
    pub fn reset(&mut self) {
        self.corners = core::array::from_fn(|_| None);
        self.reference_body = None;
        self.reference_packed = None;
        self.morph = 0.0;
        self.q = 0.0;
        self.body_rev += 1;
    }

    /// Serialize the assembled body as a compiled-v1 cartridge. None when invalid.
    ///
    /// **`packedWords` is the authority** (the canonical 240-byte path the player
    /// and every tool now interpolate in). `stages` is emitted only as decoded
    /// readback/fallback — `Cartridge::from_json` ignores it whenever packed words
    /// are present, so it can never become coefficient truth. The body is six
    /// stages (`NUM_STAGES`), not the old 12-pad.
    pub fn export_json(&self) -> Option<String> {
        let body = self.body()?;
        let packed = self.packed_authority()?;
        let name = self
            .corners
            .iter()
            .filter_map(|c| c.as_ref().map(|c| c.name.as_str()))
            .collect::<Vec<_>>()
            .join(" · ");
        let keyframes: Vec<_> = CORNER_LABELS
            .iter()
            .enumerate()
            .zip(&body)
            .map(|((ci, label), corner)| {
                let packed_words: Vec<Vec<u16>> =
                    packed.words[ci].iter().map(|w| w.to_vec()).collect();
                let stages: Vec<_> = corner
                    .iter()
                    .map(|s| serde_json::json!({"c0":s[0],"c1":s[1],"c2":s[2],"c3":s[3],"c4":s[4]}))
                    .collect();
                serde_json::json!({
                    "label": label,
                    "boost": EXPORT_BOOST,
                    "packedWords": packed_words, // authority
                    "stages": stages,            // readback / legacy fallback only
                })
            })
            .collect();
        Some(
            serde_json::json!({
                "format": "compiled-v1",
                "name": name,
                "sampleRate": AUTHORING_RATE,
                "stages": 6,
                "authoringModel": "response-surface-v1",
                "responseAudit": trench_core::response::audit_kernel_surface(&body, AUTHORING_RATE, 256),
                "keyframes": keyframes,
            })
            .to_string(),
        )
    }

    /// The authoritative 240-byte body block (`.body240`): 4 corners × 6 stages ×
    /// 5 u16 little-endian, the exact on-disk container the canonical loader takes.
    pub fn export_body240(&self) -> Option<[u8; trench_core::minifloat::BODY_BYTES]> {
        Some(self.packed_authority()?.to_rom_bytes())
    }

    /// Export and write to the canonical authoring slot. Writes BOTH the
    /// compiled-v1 JSON (with authoritative `packedWords`) and a raw
    /// `authoring_slot.body240` next to it. Returns the JSON path written.
    pub fn save(&self) -> Result<PathBuf, String> {
        let json = self.export_json().ok_or("drop a sound first")?;
        let bytes = self.export_body240().ok_or("drop a sound first")?;
        let home = std::env::var("USERPROFILE")
            .or_else(|_| std::env::var("HOME"))
            .unwrap_or_default();
        let dir = PathBuf::from(home).join("Documents").join("TRENCH");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("authoring_slot.json");
        std::fs::write(&path, json).map_err(|e| format!("save failed: {e}"))?;
        std::fs::write(dir.join("authoring_slot.body240"), bytes)
            .map_err(|e| format!("save .body240 failed: {e}"))?;
        Ok(path)
    }
}

/// Window → fit (by mode) → display curves. The single fit computation, shared by
/// the initial load and a fit-mode re-fit. Fits the SUSTAINED body, not the bright
/// transient attack (attack-fitting tilts the corner bright and drops the low body
/// — audit 2026-05-24).
fn fit_from_samples(
    samples: &[f64],
    sr: f64,
    mode: FitMode,
) -> (CornerData, Vec<[f64; 2]>, Vec<[f64; 2]>) {
    let (start, end) = dsp::sustain_window(samples, sr);
    let win = condition_fit_window(&samples[start..end], false);
    let fit = fit_window_mode(&win, sr, mode);
    let fit_db = magnitude_response(&fit, AUTHORING_RATE);
    let src_db = source_envelope(&win, sr);
    (fit, fit_db, src_db)
}

/// Re-run the fit on a corner's stored source samples under a new mode, updating
/// its filter and cached display curves in place.
fn refit(corner: &mut Corner, mode: FitMode) {
    let (fit, fit_db, src_db) = fit_from_samples(&corner.samples, corner.src_sr, mode);
    corner.fit = fit;
    corner.fit_db = fit_db;
    corner.src_db = src_db;
}

/// The Legisign bank root (parent of `00_selected_primes`), holding the per-corner
/// folders the dropdown alternates live in.
fn legisign_bank_dir() -> Option<PathBuf> {
    legisign_prime_dir().and_then(|p| p.parent().map(Path::to_path_buf))
}

fn legisign_prime_dir() -> Option<PathBuf> {
    let forge_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    [
        forge_dir
            .join("..")
            .join("dev")
            .join("tmp")
            .join("arma_source_pack")
            .join("corners_audio_only")
            .join("phonetic_4corner_legisign")
            .join("00_selected_primes"),
        forge_dir
            .join("..")
            .join("dev")
            .join("tmp")
            .join("phonetic_curation_legisign")
            .join("corner_bank")
            .join("00_selected_primes"),
    ]
    .into_iter()
    .find(|p| p.is_dir())
}

/// File facts gathered before the fit, threaded into the stored `Corner`.
struct FileFacts {
    name: String,
    duration_s: f64,
    sample_rate: u32,
    channels: u16,
    bits: u16,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legisign_phonetic_bank_loads_four_prime_corners() {
        let mut core = ForgeCore::default();
        core.load_legisign_phonetic_bank()
            .expect("load Legisign phonetic bank");

        assert_eq!(core.count(), 4);
        assert_eq!(
            core.corner(0).map(|c| c.name.as_str()),
            Some("C1 /i/ bright front")
        );
        assert_eq!(
            core.corner(1).map(|c| c.name.as_str()),
            Some("C2 /u/ dark back")
        );
        assert_eq!(core.corner(2).map(|c| c.name.as_str()), Some("C3 /a/ open"));
        assert_eq!(
            core.corner(3).map(|c| c.name.as_str()),
            Some("C4 /sh/ consonant")
        );
        assert!(core.preview().is_some());
        assert!(core
            .export_json()
            .is_some_and(|json| json.contains("C1 /i/ bright front")));
    }

    // End-to-end: a deliberately "crazy" cross-category body — a vowel, a cymbal,
    // a space-plasma whistler, and an NMR resonance in the four corners — must fit
    // (through the now-live ARMA path), assemble into a finite body, survive a puck
    // sweep, and export valid cartridge JSON. This is the whole pipeline the user
    // cares about: any source → 6-pole+zero corner → morph body → save.
    #[test]
    fn crazy_cross_category_body_assembles_and_exports() {
        let base = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("dev/tmp/arma_source_pack/corners_audio_only");
        let picks = [
            "phonetic_4corner_legisign/00_selected_primes/corner_1_bright_front_vowel__prime_i.wav",
            "other_sources/kb6/extracted/EMU_Proteus3/Cymbal1.wav",
            "other_sources/plasma/whistler.wav",
            "other_sources/nmr/nmrtalk/inositol/fid.wav",
        ];
        let mut core = ForgeCore::default();
        for (i, rel) in picks.iter().enumerate() {
            let p = base.join(rel);
            if !p.exists() {
                eprintln!("skip (missing source): {rel}");
                return; // pack not present in this checkout — don't fail the suite
            }
            core.load_source(i, &p)
                .unwrap_or_else(|e| panic!("load {rel}: {e}"));
        }
        assert_eq!(core.count(), 4, "all four crazy corners loaded");

        // Every fitted coefficient must be finite (packable, stable).
        for i in 0..4 {
            let c = core.corner(i).expect("corner present");
            assert!(
                c.fit.iter().flatten().all(|v| v.is_finite()),
                "corner {i} has non-finite coeffs"
            );
        }

        // Body assembles and stays finite across a full puck sweep.
        assert!(core.can_save(), "body must assemble from 4 corners");
        for &(m, q) in &[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5)] {
            core.set_puck(m, q);
            let body = core.body().expect("body at every puck position");
            assert!(
                body.iter().flatten().flatten().all(|v| v.is_finite()),
                "non-finite body at morph={m} q={q}"
            );
        }

        // Exports valid cartridge JSON.
        let json = core.export_json().expect("export json");
        assert!(
            json.contains("M0_Q0") && json.len() > 100,
            "cartridge JSON looks empty"
        );
    }

    // Acceptance: a Forge export is byte-authoritative. The JSON must carry
    // `packedWords`, the canonical loader must treat it as a PACKED body (not the
    // stage fallback), and the `.body240` raw bytes must yield the identical packed
    // bank. Pack-independent: a synthetic tone seeds one corner.
    #[test]
    fn export_goes_through_canonical_packed_path() {
        use trench_core::cartridge::Cartridge;
        use trench_core::minifloat::BODY_BYTES;

        let sr = 16_000.0;
        let tau = std::f64::consts::TAU;
        let tone: Vec<f64> = (0..8_000)
            .map(|i| {
                let t = i as f64 / sr;
                (tau * 700.0 * t).sin() + 0.4 * (tau * 2_200.0 * t).sin()
            })
            .collect();
        let mut core = ForgeCore::default();
        core.load_samples(0, &tone, sr, "tone".to_owned());
        assert!(
            core.can_save(),
            "a body must assemble from one seeded corner"
        );

        let json = core.export_json().expect("export json");
        assert!(
            json.contains("packedWords"),
            "export must carry the packedWords authority"
        );

        let cart = Cartridge::from_json(&json).expect("canonical loader parses the export");
        assert!(
            cart.packed.is_some(),
            "the loader must treat a Forge export as a PACKED body (coefficient authority)"
        );

        let bytes = core.export_body240().expect("body240");
        assert_eq!(
            bytes.len(),
            BODY_BYTES,
            ".body240 must be exactly 240 bytes"
        );
        let raw = Cartridge::from_body_bytes("tone", &bytes, EXPORT_BOOST)
            .expect("loads from raw .body240");
        assert_eq!(
            cart.packed.unwrap().words,
            raw.packed.unwrap().words,
            "JSON packedWords and the .body240 file must produce an identical packed bank"
        );
    }

    // A verbatim 240-byte body, once loaded, must export the SAME 240 bytes — no
    // decode→repack drift on the gold path. Synthesizes a packed body in-memory.
    #[test]
    fn loaded_240_byte_body_exports_verbatim() {
        use trench_core::minifloat::{PackedCorners, BODY_BYTES};

        // A distinct-per-corner packed body (derived from four different corners).
        let corners: [CornerData; 4] = [
            [[0.95, 0.10, 1.30, 0.20, 0.50]; 6],
            [[1.10, 0.05, 1.60, 0.15, 0.60]; 6],
            [[0.85, 0.20, 1.10, 0.30, 0.40]; 6],
            [[1.20, 0.02, 1.80, 0.08, 0.70]; 6],
        ];
        let src_bytes = PackedCorners::from_corner_data(&corners).to_rom_bytes();
        let dir = std::env::temp_dir();
        let path = dir.join("trench_forge_verbatim_test.body240");
        std::fs::write(&path, src_bytes).expect("write temp body240");

        let mut core = ForgeCore::default();
        core.load_reference_rom(&path, "VERBATIM")
            .expect("load 240-byte body");

        let out = core.export_body240().expect("export body240");
        assert_eq!(out.len(), BODY_BYTES);
        assert_eq!(
            out.as_slice(),
            src_bytes.as_slice(),
            "a loaded 240-byte body must export verbatim (no decode→repack drift)"
        );
        let _ = std::fs::remove_file(&path);
    }
}
