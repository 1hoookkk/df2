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
    self, condition_fit_window, corner_to_resonances, display_name, fit_window_mode, fsm_fit,
    load_wav_with_meta, magnitude_response, realize_resonances, source_envelope, FitMode, ResoKind,
    Resonance, AUTHORING_RATE,
};
use crate::generators::{self, Architecture};

/// Corner letters for naming hand-drawn corners.
const SLOT_LETTERS: [&str; 4] = ["A", "B", "C", "D"];

/// The four corner slots, in body order: M0_Q0, M100_Q0, M0_Q100, M100_Q100.
/// A/B are the Morph endpoints (Q0 row); C/D are the Q endpoints (Q100 row).
pub const CARD_LABELS: [&str; 4] = ["A · MORPH 0", "B · MORPH 100", "C · Q", "D · Q"];

/// Export labels matching the runtime keyframe order.
const CORNER_LABELS: [&str; 4] = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];

/// Default per-corner boost stamped into newly-exported bodies.
///
/// Not a blind gain multiplier — this is the AGC engagement default. The E-mu
/// character (chip-saturate, & 0xF wrap chaos gating) lives at AGC table
/// indices 4-7 (mults 0.92 / 0.50 / 0.20 / 0.16), which engages when filter
/// peaks reach ~+22..+28 dB (`STATE.md` `Now` 2026-05-28). Below ~+15 dB the
/// AGC is asleep and the body sounds clinical/dry. A boost of 4.0 puts a
/// nominal-loudness corner into that engagement zone by default.
///
/// **Override-friendly:** the cartridge loader treats `boost` as per-keyframe
/// metadata and falls back to 1.0 when absent
/// (`trench-core/src/cartridge.rs::default_boost`). A future Forge UI may
/// publish bodies with `boost: 1.0` (Output knob is the user's control) or
/// other per-corner values; existing cartridges in
/// `juce-shell/assets/cartridges/` retain their explicit `boost: 4.0` so
/// roster loudness does not shift without intent.
fn default_boost_for_engagement() -> f64 {
    4.0
}

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

/// The PRESET dropdown list. Three sources, in priority order so the most
/// useful starting points are at the top:
///   1. GENERATED bodies (`bodies/generated/*.bin`, written by the Target
///      Browser) — your own original work.
///   2. P2K REFERENCE VARIANTS (`ref/p2k_variants/P2k_NNN_*/variant_*.bin`) —
///      the 50 canonical E-mu filter types × 4 variants each = 200 reference
///      bodies. Load one to "start from a body" and tweak by ear in DRAW.
///   3. RAW reference skins in `ref/presets/` — guardrails / null-test set.
/// All three load whole through the same 240-byte path; `from_rom_bytes` →
/// `corner_to_resonances` populates DRAW with actors at the loaded body's
/// pole positions.
pub fn available_presets() -> Vec<SourceEntry> {
    let mut gen = Vec::new();
    if let Some(dir) = generated_presets_dir() {
        scan_bins(&dir, &mut gen);
    }
    gen.sort_by(|a, b| a.label.cmp(&b.label));

    let mut p2k = Vec::new();
    if let Some(dir) = p2k_variants_dir() {
        scan_p2k_variants(&dir, &mut p2k);
    }
    // Sort P2K bodies by their numeric index (P2k_003 before P2k_010) then
    // variant number — so types stay together and read in spec order.
    p2k.sort_by(|a, b| a.category.cmp(&b.category).then(a.label.cmp(&b.label)));

    let mut refs = Vec::new();
    if let Some(dir) = presets_dir() {
        scan_bins(&dir, &mut refs);
    }
    refs.sort_by(|a, b| a.label.cmp(&b.label));

    gen.extend(p2k);
    gen.extend(refs);
    gen
}

fn scan_bins(dir: &Path, out: &mut Vec<SourceEntry>) {
    if let Ok(entries) = std::fs::read_dir(dir) {
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

fn presets_dir() -> Option<PathBuf> {
    let p = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("ref")
        .join("presets");
    p.is_dir().then_some(p)
}

/// Original bodies generated by `tools/target_browser.py`, dropped here so they
/// appear in the Factory's PRESET list and load whole with one click.
fn generated_presets_dir() -> Option<PathBuf> {
    let p = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("bodies")
        .join("generated");
    p.is_dir().then_some(p)
}

/// The 50 canonical P2K filter types × 4 variants each. Each subdirectory is
/// `P2k_NNN_<slug>/` containing `variant_K_dat_MMM.bin` files (240 bytes raw).
/// Load any of these in PRESET → enter DRAW → DRAW auto-populates actors at
/// the body's existing pole positions. Killing the cold-start problem.
fn p2k_variants_dir() -> Option<PathBuf> {
    let p = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("ref")
        .join("p2k_variants");
    p.is_dir().then_some(p)
}

/// Scan `ref/p2k_variants/P2k_NNN_<slug>/variant_K_*.bin` and produce one
/// `SourceEntry` per variant with a producer-facing label:
///   "Millennium · 0", "Bassbox 303 · 2", "Talking Hedz · 1"
/// The `category` field gets the numeric type id (`P2k_003`) so dropdowns
/// can sort by spec order while showing names. The raw 240-byte path goes
/// straight into `from_rom_bytes` like every other bin source.
fn scan_p2k_variants(root: &Path, out: &mut Vec<SourceEntry>) {
    let Ok(types) = std::fs::read_dir(root) else {
        return;
    };
    for type_entry in types.flatten() {
        let type_path = type_entry.path();
        if !type_path.is_dir() {
            continue;
        }
        let Some(dir_name) = type_path.file_name().and_then(|s| s.to_str()) else {
            continue;
        };
        // Directory names look like `P2k_003_millennium` or
        // `P2k_038_band_pass1_2_bpf`. Strip the `P2k_NNN_` prefix to get the
        // human slug; if the strip fails, fall back to the whole name.
        let (id_prefix, slug) = match split_p2k_dirname(dir_name) {
            Some(parts) => parts,
            None => continue,
        };
        let pretty = prettify_slug(&slug);

        let Ok(files) = std::fs::read_dir(&type_path) else {
            continue;
        };
        for file in files.flatten() {
            let path = file.path();
            if !path
                .extension()
                .map(|x| x.eq_ignore_ascii_case("bin"))
                .unwrap_or(false)
            {
                continue;
            }
            // Filename: `variant_K_dat_NNN.bin` — extract K.
            let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("");
            let variant_n = variant_number(stem);
            let label = match variant_n {
                Some(n) => format!("{pretty} · {n}"),
                None => format!("{pretty} · {stem}"),
            };
            out.push(SourceEntry {
                label,
                path,
                category: id_prefix.clone(),
            });
        }
    }
}

/// Split `P2k_NNN_<slug>` into (`P2k_NNN`, `slug`). Returns None if the prefix
/// doesn't parse — caller can skip the directory.
fn split_p2k_dirname(name: &str) -> Option<(String, String)> {
    // Expect "P2k_NNN_..." — three segments minimum, joined by underscores.
    let mut parts = name.splitn(3, '_');
    let p2k = parts.next()?;
    let num = parts.next()?;
    let rest = parts.next()?;
    if !p2k.eq_ignore_ascii_case("P2k") || num.parse::<u32>().is_err() {
        return None;
    }
    Some((format!("{p2k}_{num}"), rest.to_owned()))
}

/// "millennium" → "Millennium". "tb_or_not_tb" → "Tb Or Not Tb".
/// "band_pass1_2_bpf" → "Band Pass1 2 Bpf". Imperfect but readable; we never
/// hand-curate the slug list and the variant number distinguishes siblings.
fn prettify_slug(slug: &str) -> String {
    slug.split('_')
        .map(|w| {
            let mut c = w.chars();
            match c.next() {
                None => String::new(),
                Some(first) => first.to_ascii_uppercase().to_string() + c.as_str(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// Extract K from `variant_K_dat_NNN`. Returns None if the pattern doesn't fit.
fn variant_number(stem: &str) -> Option<u32> {
    stem.strip_prefix("variant_")?
        .split('_')
        .next()?
        .parse()
        .ok()
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

/// The 8-corner CUBE the GEN architectures generate. Two 4-corner planes — a
/// floor (z=0, corners 0..3) and a ceiling (z=1, corners 4..7) — that the
/// runtime collapses to ONE playable 4-corner body by Z-crossfading their packed
/// words at the active Z. That collapsed slice IS the publishable body: SHAPE
/// composes the cube from audited corners, and `body()`/`packed_authority()`
/// ship the exact crossfade bank PLAYER auditions (option A — Z is baked per
/// body; a compiled-v2 two-plane export keeping Z live is the next step,
/// `NOW.md` DO NEXT).
pub struct CubeState {
    pub arch: Architecture,
    /// Z (Transform) position, 0..1.
    pub z: f32,
    /// The eight generated cube corners (index i: x=i&1, y=(i>>1)&1, z=(i>>2)&1).
    pub corners: [CornerData; 8],
    floor: PackedCorners,
    ceiling: PackedCorners,
}

impl CubeState {
    /// Re-pack the two plane bodies from the 8 corners (after a corner is edited).
    fn rebuild_planes(&mut self) {
        self.floor = PackedCorners::from_corner_data(&[
            self.corners[0],
            self.corners[1],
            self.corners[2],
            self.corners[3],
        ]);
        self.ceiling = PackedCorners::from_corner_data(&[
            self.corners[4],
            self.corners[5],
            self.corners[6],
            self.corners[7],
        ]);
    }
}

/// Reduce a dense magnitude response to `n` log-spaced `[freq_hz, db]` control
/// points — an editable FSM curve seed from an existing corner's shape.
fn downsample_curve(dense: &[[f64; 2]], n: usize) -> Vec<[f64; 2]> {
    if dense.len() <= n || n == 0 {
        return dense.to_vec();
    }
    (0..n)
        .map(|i| {
            let idx = i * (dense.len() - 1) / (n - 1);
            dense[idx]
        })
        .collect()
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
    /// DRAW: the hand-placed actors per corner. When a corner's list is non-empty
    /// it is realized into `corners[i]` through `realize_resonances` — the same
    /// kind of object a fit produces. From-scratch authoring, no source needed.
    design: [Vec<Resonance>; 4],
    /// In DRAW mode the field places/drags actors instead of roaming the puck.
    design_mode: bool,
    /// The corner DRAW edits (0..3 = A/B/C/D). Selecting it snaps the puck there.
    active: usize,
    /// FSM: the per-corner TARGET magnitude curve (`[freq_hz, db]` control
    /// points). The new DRAW — you draw this curve, `refit` fits 6 biquads to it
    /// via `dsp::fsm_fit`, and the result lands in `corners[i]`. Freehand = wild
    /// corners; data/formula generators seed it for real corners.
    fsm_curve: [Vec<[f64; 2]>; 4],
    /// The active GEN cube, when an architecture is selected. The cube is the
    /// main authoring object; cleared on any load / reset.
    cube: Option<CubeState>,
    /// Which CUBE corner (0..7) the FSM editor is reshaping in place, if any.
    /// Set by `edit_cube_corner`; `refit` writes the fit back into the cube.
    cube_fsm: Option<usize>,
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
            design: core::array::from_fn(|_| Vec::new()),
            design_mode: false,
            active: 0,
            fsm_curve: core::array::from_fn(|_| Vec::new()),
            cube: None,
            cube_fsm: None,
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

    // ── DRAW (from-scratch corner authoring) ──────────────────────────────────
    pub fn design_mode(&self) -> bool {
        self.design_mode
    }

    pub fn active(&self) -> usize {
        self.active
    }

    /// Toggle DRAW. Entering pulls the active corner's existing shape (a loaded
    /// ROM seed or a fit) into editable actors — the SKETCH→SCULPT bridge — and
    /// snaps the puck to it so the scope shows exactly the corner you're shaping.
    pub fn toggle_design(&mut self) {
        self.design_mode = !self.design_mode;
        if self.design_mode {
            self.ensure_design_from_fit(self.active);
            self.ensure_fsm_from_fit(self.active);
            self.snap_to_active();
        }
    }

    /// Select which corner DRAW edits, snapping the puck to its grid position and
    /// (in DRAW) pulling its current shape into actors if it hasn't been touched.
    pub fn set_active(&mut self, i: usize) {
        self.active = i.min(3);
        if self.design_mode {
            self.ensure_design_from_fit(self.active);
            self.ensure_fsm_from_fit(self.active);
        }
        self.snap_to_active();
    }

    /// SKETCH→SCULPT: if corner `i` has a shape (loaded ROM / fit) but no actors
    /// yet, decode its poles into draggable actors so you can sculpt the seed.
    /// Leaves a corner already being drawn untouched.
    fn ensure_design_from_fit(&mut self, i: usize) {
        let i = i.min(3);
        if !self.design[i].is_empty() {
            return;
        }
        if let Some(c) = self.corners[i].as_ref() {
            let res = corner_to_resonances(&c.fit, AUTHORING_RATE);
            if !res.is_empty() {
                self.design[i] = res;
                self.rebuild(i);
            }
        }
    }

    fn snap_to_active(&mut self) {
        let (m, q) = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)][self.active.min(3)];
        self.morph = m;
        self.q = q;
    }

    /// The placed actors of corner `i` (for drawing the draggable handles).
    pub fn resonances(&self, i: usize) -> &[Resonance] {
        &self.design[i.min(3)]
    }

    /// Add an actor to the active corner and rebuild it. Returns its index.
    pub fn add_resonance(&mut self, freq_hz: f64, radius: f64, kind: ResoKind) -> usize {
        let i = self.active.min(3);
        if self.design[i].len() >= dsp::POLE_ZERO_COUNT {
            return self.design[i].len().saturating_sub(1); // six actors max (six stages)
        }
        self.design[i].push(Resonance {
            freq_hz,
            radius,
            kind,
            cavity_semis: if matches!(kind, ResoKind::Cavity) {
                3.0
            } else {
                0.0
            },
        });
        self.rebuild(i);
        self.design[i].len() - 1
    }

    /// Move actor `idx` of the active corner (frequency + sharpness) and rebuild.
    pub fn move_resonance(&mut self, idx: usize, freq_hz: f64, radius: f64) {
        let i = self.active.min(3);
        if let Some(r) = self.design[i].get_mut(idx) {
            r.freq_hz = freq_hz;
            r.radius = radius;
            self.rebuild(i);
        }
    }

    /// Remove actor `idx` from the active corner and rebuild.
    pub fn remove_resonance(&mut self, idx: usize) {
        let i = self.active.min(3);
        if idx < self.design[i].len() {
            self.design[i].remove(idx);
            self.rebuild(i);
        }
    }

    /// Index of the actor nearest `freq_hz` (log distance) in the active corner.
    pub fn nearest_resonance(&self, freq_hz: f64) -> Option<usize> {
        let i = self.active.min(3);
        self.design[i]
            .iter()
            .enumerate()
            .min_by(|(_, a), (_, b)| {
                let da = (a.freq_hz / freq_hz.max(1.0)).ln().abs();
                let db = (b.freq_hz / freq_hz.max(1.0)).ln().abs();
                da.partial_cmp(&db).unwrap_or(core::cmp::Ordering::Equal)
            })
            .map(|(idx, _)| idx)
    }

    /// Realize the active corner's actor list into a corner (or clear if empty).
    /// A drawn corner is the same kind of object a fit produces, so `body()`,
    /// `preview()`, and every save/export path work on it unchanged.
    fn rebuild(&mut self, i: usize) {
        if self.design[i].is_empty() {
            self.corners[i] = None;
        } else {
            let fit = realize_resonances(&self.design[i], AUTHORING_RATE);
            let fit_db = magnitude_response(&fit, AUTHORING_RATE);
            self.corners[i] = Some(Corner {
                name: format!("DRAW {}", SLOT_LETTERS[i]),
                fit,
                src_db: fit_db.clone(),
                fit_db,
                duration_s: 0.0,
                sample_rate: AUTHORING_RATE as u32,
                channels: 1,
                bits: 32,
                samples: Vec::new(),
                src_sr: 0.0,
            });
        }
        self.reference_body = None; // a drawn corner supersedes a loaded frame
        self.reference_packed = None;
        self.cube = None;
        self.body_rev += 1;
    }

    // ── FSM: the curve editor (the new DRAW) ──────────────────────────────────

    /// The active corner's target curve control points (for drawing the polyline).
    pub fn fsm_points(&self, i: usize) -> &[[f64; 2]] {
        &self.fsm_curve[i.min(3)]
    }

    /// Seed corner `i`'s FSM curve from its current fitted response if empty —
    /// the editor-open bridge so you start from the shape that's there, not blank.
    fn ensure_fsm_from_fit(&mut self, i: usize) {
        let i = i.min(3);
        if !self.fsm_curve[i].is_empty() {
            return;
        }
        if let Some(c) = self.corners[i].as_ref() {
            self.fsm_curve[i] = downsample_curve(&c.fit_db, 18);
        }
    }

    /// Replace the active corner's curve wholesale (from a SEED generator) and refit.
    pub fn seed_curve(&mut self, points: Vec<[f64; 2]>) {
        let i = self.active.min(3);
        self.fsm_curve[i] = points;
        self.refit(i);
    }

    /// Add a control point to the active corner's curve and refit.
    pub fn add_curve_point(&mut self, freq_hz: f64, db: f64) {
        let i = self.active.min(3);
        self.fsm_curve[i].push([freq_hz.max(20.0), db]);
        self.refit(i);
    }

    /// Move control point `idx` of the active corner and refit.
    pub fn move_curve_point(&mut self, idx: usize, freq_hz: f64, db: f64) {
        let i = self.active.min(3);
        if let Some(p) = self.fsm_curve[i].get_mut(idx) {
            *p = [freq_hz.max(20.0), db];
            self.refit(i);
        }
    }

    /// Remove control point `idx` from the active corner's curve and refit.
    pub fn remove_curve_point(&mut self, idx: usize) {
        let i = self.active.min(3);
        if idx < self.fsm_curve[i].len() {
            self.fsm_curve[i].remove(idx);
            self.refit(i);
        }
    }

    /// Index of the control point nearest `freq_hz` (log distance) in the active
    /// corner — for the drag/delete hit-test.
    pub fn nearest_curve_point(&self, freq_hz: f64) -> Option<usize> {
        let i = self.active.min(3);
        self.fsm_curve[i]
            .iter()
            .enumerate()
            .min_by(|(_, a), (_, b)| {
                let da = (a[0] / freq_hz.max(1.0)).ln().abs();
                let db = (b[0] / freq_hz.max(1.0)).ln().abs();
                da.partial_cmp(&db).unwrap_or(core::cmp::Ordering::Equal)
            })
            .map(|(idx, _)| idx)
    }

    /// Fit the active corner's target curve into a corner via `dsp::fsm_fit` and
    /// store the result. The constellation the UI overlays comes from decoding
    /// this corner. Clears it (back to passthrough/None) when fewer than 2 points.
    fn refit(&mut self, i: usize) {
        let i = i.min(3);
        let curve = self.fsm_curve[i].clone();
        let fit = fsm_fit(&curve, AUTHORING_RATE);

        // Editing a CUBE corner in place: write the fit back into the cube and
        // rebuild that corner's plane. The cube stays the object.
        if let Some(ci) = self.cube_fsm {
            if let (Some(fit), Some(cube)) = (fit, self.cube.as_mut()) {
                cube.corners[ci] = fit;
                cube.rebuild_planes();
                self.body_rev += 1;
            }
            return;
        }

        match fit {
            Some(fit) => {
                let fit_db = magnitude_response(&fit, AUTHORING_RATE);
                self.corners[i] = Some(Corner {
                    name: format!("FSM {}", SLOT_LETTERS[i]),
                    fit,
                    src_db: self.fsm_curve[i].clone(), // the drawn target = the ghost
                    fit_db,
                    duration_s: 0.0,
                    sample_rate: AUTHORING_RATE as u32,
                    channels: 1,
                    bits: 32,
                    samples: Vec::new(),
                    src_sr: 0.0,
                });
            }
            None => {
                self.corners[i] = None;
            }
        }
        self.reference_body = None;
        self.reference_packed = None;
        self.cube = None; // an authored corner supersedes a GEN cube
        self.body_rev += 1;
    }

    /// Click a CUBE corner (0..7) to reshape its filter: load that corner into
    /// the FSM editor (curve seeded from its response), snap the puck/Z to that
    /// vertex so the scope shows it, and route refits back into the cube.
    pub fn edit_cube_corner(&mut self, ci: usize) {
        let Some(cube) = self.cube.as_ref() else {
            return;
        };
        let ci = ci.min(7);
        let corner = cube.corners[ci];
        self.cube_fsm = Some(ci);
        self.active = 0;
        self.design_mode = true;
        self.fsm_curve[0] = downsample_curve(&magnitude_response(&corner, AUTHORING_RATE), 18);
        // Snap the navigator to this vertex so preview() shows exactly this corner.
        self.morph = (ci & 1) as f32;
        self.q = ((ci >> 1) & 1) as f32;
        if let Some(c) = self.cube.as_mut() {
            c.z = ((ci >> 2) & 1) as f32;
        }
        self.body_rev += 1;
    }

    /// Assign a bank architecture's sound to ONE cube corner (the spectrum-picker
    /// action): write that architecture's corner at this vertex's coords into the
    /// cube and re-pack the plane. Tyson composes the cube from bank corners.
    pub fn assign_cube_corner(&mut self, ci: usize, arch: Architecture) {
        let ci = ci.min(7);
        let (x, y, z) = (
            (ci & 1) as f64,
            ((ci >> 1) & 1) as f64,
            ((ci >> 2) & 1) as f64,
        );
        let corner = generators::eval_at(arch, x, y, z);
        if let Some(cube) = self.cube.as_mut() {
            cube.corners[ci] = corner;
            cube.rebuild_planes();
            self.body_rev += 1;
        }
    }

    /// Assign one audited library posture to a cube vertex.
    pub fn assign_cube_corner_data(&mut self, ci: usize, corner: CornerData) {
        if let Some(cube) = self.cube.as_mut() {
            cube.corners[ci.min(7)] = corner;
            cube.rebuild_planes();
            self.body_rev += 1;
        }
    }

    /// The cube corner currently being FSM-edited (0..7), if any.
    pub fn cube_fsm(&self) -> Option<usize> {
        self.cube_fsm
    }

    /// Leave cube-corner editing, back to navigating the cube.
    pub fn exit_cube_edit(&mut self) {
        self.cube_fsm = None;
        self.design_mode = false;
        self.fsm_curve[0].clear();
        self.body_rev += 1;
    }

    // ── GEN: the 8-corner cube navigator ──────────────────────────────────────

    /// Select a generator architecture: build its 8 cube corners and the two
    /// packed plane bodies (floor z=0, ceiling z=1). Resets the puck + Z to HOME.
    pub fn set_architecture(&mut self, arch: Architecture) {
        let corners = generators::generate(arch);
        let floor =
            PackedCorners::from_corner_data(&[corners[0], corners[1], corners[2], corners[3]]);
        let ceiling =
            PackedCorners::from_corner_data(&[corners[4], corners[5], corners[6], corners[7]]);
        self.cube = Some(CubeState {
            arch,
            z: 0.0,
            corners,
            floor,
            ceiling,
        });
        self.morph = 0.0;
        self.q = 0.0;
        self.design_mode = false;
        self.cube_fsm = None;
        self.body_rev += 1;
    }

    /// Leave cube mode (back to the loaded/FSM body, if any).
    pub fn clear_cube(&mut self) {
        self.cube_fsm = None;
        self.design_mode = false;
        if self.cube.take().is_some() {
            self.body_rev += 1;
        }
    }

    pub fn cube(&self) -> Option<&CubeState> {
        self.cube.as_ref()
    }

    /// `(arch label, (x_axis, y_axis, z_axis))` when a cube is active — for the UI.
    pub fn cube_axes(&self) -> Option<(&'static str, (&'static str, &'static str, &'static str))> {
        self.cube.as_ref().map(|c| (c.arch.label(), c.arch.axes()))
    }

    pub fn z(&self) -> f32 {
        self.cube.as_ref().map(|c| c.z).unwrap_or(0.0)
    }

    /// Move the Z (Transform) axis. Cheap; does not rebuild (preview re-derives).
    pub fn set_z(&mut self, z: f32) {
        if let Some(c) = self.cube.as_mut() {
            c.z = z.clamp(0.0, 1.0);
        }
    }

    /// Trilinear corner weights at the current (morph, q, z) — for the cube
    /// display blend lines and the nearest-vertex bake. Index i: x=i&1, y=(i>>1)&1,
    /// z=(i>>2)&1. Sums to 1.
    pub fn cube_weights(&self) -> Option<[f32; 8]> {
        let c = self.cube.as_ref()?;
        let (x, y, z) = (self.morph, self.q, c.z);
        let mut w = [0.0f32; 8];
        for (i, wi) in w.iter_mut().enumerate() {
            let fx = if i & 1 == 1 { x } else { 1.0 - x };
            let fy = if (i >> 1) & 1 == 1 { y } else { 1.0 - y };
            let fz = if (i >> 2) & 1 == 1 { z } else { 1.0 - z };
            *wi = fx * fy * fz;
        }
        Some(w)
    }

    /// The current GEN cube collapsed to ONE publishable 4-corner packed bank:
    /// the floor and ceiling plane bodies Z-crossfaded at the active Z (the
    /// owner's `lerp_u16`). This is the exact bank `cube_preview` auditions and
    /// `packed_authority` ships, so what plays at the four vertices is
    /// byte-for-byte what publishes. `None` when no cube is active.
    fn cube_bank(&self) -> Option<PackedCorners> {
        let c = self.cube.as_ref()?;
        Some(PackedCorners::z_crossfade(&c.floor, &c.ceiling, c.z))
    }

    /// The cube's coefficients at the current (morph, q, z): the Z-crossfaded
    /// 4-corner bank, morph/Q bilinear. Kernel domain, matching `preview()`.
    fn cube_preview(&self) -> Option<CornerData> {
        let bank = self.cube_bank()?;
        Some(bank.interpolate(self.morph.clamp(0.0, 1.0), self.q.clamp(0.0, 1.0)))
    }

    /// Drop the nearest cube vertex into slot `slot` and open FSM to refine it:
    /// the bake bridge from the GEN navigator to the publishable corner pipeline.
    /// Returns the cube corner index that was copied.
    pub fn cube_corner_to_fsm(&mut self, slot: usize) -> Option<usize> {
        let weights = self.cube_weights()?;
        let ci = weights
            .iter()
            .enumerate()
            .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(core::cmp::Ordering::Equal))
            .map(|(i, _)| i)?;
        let corner = self.cube.as_ref()?.corners[ci];
        let slot = slot.min(3);
        self.clear_cube();
        let fit_db = magnitude_response(&corner, AUTHORING_RATE);
        self.fsm_curve[slot] = downsample_curve(&fit_db, 18);
        self.corners[slot] = Some(Corner {
            name: format!("FSM {} ⟵ cube {ci}", SLOT_LETTERS[slot]),
            fit: corner,
            src_db: self.fsm_curve[slot].clone(),
            fit_db,
            duration_s: 0.0,
            sample_rate: AUTHORING_RATE as u32,
            channels: 1,
            bits: 32,
            samples: Vec::new(),
            src_sr: 0.0,
        });
        self.active = slot;
        self.design_mode = true;
        self.reference_body = None;
        self.reference_packed = None;
        self.body_rev += 1;
        Some(ci)
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
        self.cube = None;
        self.fsm_curve[i.min(3)].clear();
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
        self.cube = None;
        self.fsm_curve = core::array::from_fn(|_| Vec::new());
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
        // Direct unpack — one corner = one stored set of 5×6 packed words decoded
        // through `stage_words_to_kernel`. No interpolation primitive in the path.
        let corners = [
            packed.corner_kernel(0),
            packed.corner_kernel(1),
            packed.corner_kernel(2),
            packed.corner_kernel(3),
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
        self.cube = None;
        self.fsm_curve = core::array::from_fn(|_| Vec::new());
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
        self.cube = None;
        self.fsm_curve[i.min(3)].clear(); // re-seed FSM from the new fit on next edit
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
        if let Some(bank) = self.cube_bank() {
            // A composed GEN field publishes as its Z-crossfaded 4-corner slice —
            // the exact bank PLAYER auditions at the four vertices.
            return Some([
                bank.corner_kernel(0),
                bank.corner_kernel(1),
                bank.corner_kernel(2),
                bank.corner_kernel(3),
            ]);
        }
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
        if self.cube.is_some() {
            return self.cube_preview(); // GEN cube takes priority while navigating
        }
        if let Some(p) = &self.reference_packed {
            return Some(p.interpolate(self.morph.clamp(0.0, 1.0), self.q.clamp(0.0, 1.0)));
        }
        Some(dsp::body_preview(&self.body()?, self.morph, self.q))
    }

    /// The body's authoritative packed words — verbatim when a 240-byte body was
    /// loaded, otherwise derived-packed-canonical from the assembled four corners.
    /// This is the SINGLE coefficient surface every save/export goes through.
    fn packed_authority(&self) -> Option<PackedCorners> {
        if let Some(bank) = self.cube_bank() {
            return Some(bank); // byte-authoritative: ship the exact crossfade words
        }
        if let Some(p) = &self.reference_packed {
            return Some(p.clone());
        }
        Some(PackedCorners::from_corner_data(&self.body()?))
    }

    /// Test-only: install a verbatim 240-byte body straight into the
    /// `reference_packed` slot so the publish gate can be exercised without
    /// touching the filesystem. Mirrors `load_reference_rom` minus the I/O
    /// and the per-corner decode (decode is covered by FG-1 tests).
    #[cfg(test)]
    fn set_reference_for_test(&mut self, packed: PackedCorners) {
        let corners = [
            packed.corner_kernel(0),
            packed.corner_kernel(1),
            packed.corner_kernel(2),
            packed.corner_kernel(3),
        ];
        self.reference_body = Some(corners);
        self.reference_packed = Some(packed);
        self.body_rev += 1;
    }

    /// Publishability gate. Returns `None` when the body is honest to ship;
    /// `Some(reason)` when publishing would emit a body whose corners came
    /// from the `shift_corner`/`sharpen_corner` fallback in `body()`.
    ///
    /// Publishable when:
    /// 1. a verbatim 240-byte ROM/body was loaded (`reference_packed.is_some()`), or
    /// 2. all four corner slots are explicitly populated (real fit / design /
    ///    drawn / captured corner placed in each).
    ///
    /// The synthesised-corner fallback in `body()` is fine for in-Forge
    /// preview — drag a starter into HOME and see what the Morph axis sounds
    /// like before fitting the other slots — but it is never an honest
    /// publish. `save()` calls this; the underlying `export_json` /
    /// `export_body240` stay un-gated for preview and tests.
    pub fn publishability_error(&self) -> Option<String> {
        if self.cube.is_some() {
            return None; // a composed GEN field ships as its Z-crossfaded slice
        }
        if self.reference_packed.is_some() {
            return None;
        }
        let missing: Vec<&str> = CORNER_LABELS
            .iter()
            .enumerate()
            .filter_map(|(i, label)| {
                if self.corners[i].is_none() {
                    Some(*label)
                } else {
                    None
                }
            })
            .collect();
        if missing.is_empty() {
            None
        } else {
            Some(format!(
                "publish requires all 4 corners loaded (missing: {}). The synthesised-corner fallback is for in-Forge preview only — not a shippable body.",
                missing.join(", ")
            ))
        }
    }

    // ── reset / export / save ───────────────────────────────────────────────
    pub fn reset(&mut self) {
        self.corners = core::array::from_fn(|_| None);
        self.reference_body = None;
        self.reference_packed = None;
        self.design = core::array::from_fn(|_| Vec::new());
        self.fsm_curve = core::array::from_fn(|_| Vec::new());
        self.cube = None;
        self.cube_fsm = None;
        self.active = 0;
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
                    "boost": default_boost_for_engagement(),
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

    /// Worst-case pole radius across the bilinear-interp morph surface and
    /// the (morph, q) cell where it occurs. Returns `None` when no body is
    /// assembled yet. See `dsp::morph_surface_max_pole_radius` for the why
    /// (ARMAdillo behaviour: the middle can leave the unit circle even when
    /// the four corners are stable).
    pub fn morph_surface_stability(&self) -> Option<(f64, (f64, f64))> {
        let body = self.body()?;
        Some(dsp::morph_surface_max_pole_radius(&body, 5))
    }

    /// Human-readable stability warning, present only when the morph surface
    /// scan exceeded the safety radius. The UI surfaces this as a banner so
    /// the user knows the middle is destabilised even though the corners
    /// look fine on the response curve.
    pub fn stability_warning(&self) -> Option<String> {
        let (r, (m, q)) = self.morph_surface_stability()?;
        if r > dsp::STABILITY_RADIUS_LIMIT {
            Some(format!(
                "morph cell (m={:.2}, Q={:.2}) reaches r={:.4} — the middle is destabilised; widen the corner spread or pull the high-Q corner back",
                m, q, r
            ))
        } else {
            None
        }
    }

    /// Export and write to the canonical authoring slot. Writes BOTH the
    /// compiled-v1 JSON (with authoritative `packedWords`) and a raw
    /// `authoring_slot.body240` next to it. Returns the JSON path written.
    /// Logs (stderr) a stability warning if the morph surface destabilises,
    /// but does NOT block the write — the user may want to audition the edge.
    pub fn save(&self) -> Result<PathBuf, String> {
        if let Some(reason) = self.publishability_error() {
            return Err(reason);
        }
        let json = self.export_json().ok_or("drop a sound first")?;
        let bytes = self.export_body240().ok_or("drop a sound first")?;
        if let Some(msg) = self.stability_warning() {
            eprintln!("forge save: STABILITY WARNING — {msg}");
        }
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
        let raw = Cartridge::from_body_bytes("tone", &bytes, default_boost_for_engagement())
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

    // DRAW: a from-scratch corner (no source, no fit) realizes into a real corner,
    // stays finite + stable across the puck sweep, and exports through the same
    // canonical packed path as everything else.
    #[test]
    fn drawn_corner_realizes_and_exports() {
        let mut core = ForgeCore::default();
        core.toggle_design();
        assert!(core.design_mode());
        core.set_active(0);
        core.add_resonance(90.0, 0.94, ResoKind::Peak);
        core.add_resonance(300.0, 0.96, ResoKind::Peak);
        let edge = core.add_resonance(16_000.0, 0.99, ResoKind::Edge);
        assert_eq!(core.resonances(0).len(), 3);
        assert_eq!(core.nearest_resonance(15_000.0), Some(edge));

        let c = core.corner(0).expect("drawn corner present");
        assert!(
            c.fit.iter().flatten().all(|v| v.is_finite()),
            "drawn corner must be finite"
        );

        assert!(
            core.can_save(),
            "a body must assemble from one drawn corner"
        );
        for &(m, q) in &[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5)] {
            core.set_puck(m, q);
            let body = core.body().expect("body at every puck position");
            assert!(
                body.iter().flatten().flatten().all(|v| v.is_finite()),
                "non-finite drawn body at morph={m} q={q}"
            );
        }

        let json = core.export_json().expect("export json");
        assert!(
            json.contains("packedWords") && json.contains("M0_Q0"),
            "drawn body must export through the canonical packed path"
        );

        core.move_resonance(0, 120.0, 0.90);
        core.remove_resonance(0);
        assert_eq!(core.resonances(0).len(), 2, "remove drops an actor");
    }

    // SKETCH→SCULPT: a corner realized from actors decodes back into actors at the
    // same pole frequencies, so a loaded seed can be pulled into DRAW and nudged.
    #[test]
    fn corner_pulls_back_into_actors() {
        let res = vec![
            Resonance {
                freq_hz: 250.0,
                radius: 0.95,
                kind: ResoKind::Peak,
                cavity_semis: 0.0,
            },
            Resonance {
                freq_hz: 1_400.0,
                radius: 0.93,
                kind: ResoKind::Peak,
                cavity_semis: 0.0,
            },
        ];
        let corner = realize_resonances(&res, AUTHORING_RATE);
        let back = corner_to_resonances(&corner, AUTHORING_RATE);
        assert!(back.len() >= 2, "both poles recovered as actors");
        let f_lo = back.iter().map(|r| r.freq_hz).fold(f64::INFINITY, f64::min);
        assert!(
            (f_lo - 250.0).abs() / 250.0 < 0.08,
            "low pole frequency recovered (got {f_lo})"
        );
    }

    // The bridge end to end: a loaded corner (here a synthetic tone) becomes
    // editable DRAW actors the moment you enter DRAW on it.
    #[test]
    fn entering_draw_pulls_a_loaded_corner_into_actors() {
        let sr = 16_000.0;
        let tau = std::f64::consts::TAU;
        let tone: Vec<f64> = (0..8_000)
            .map(|i| {
                let t = i as f64 / sr;
                (tau * 700.0 * t).sin() + 0.4 * (tau * 1_800.0 * t).sin()
            })
            .collect();
        let mut core = ForgeCore::default();
        core.load_samples(0, &tone, sr, "seed".to_owned());
        assert!(core.corner(0).is_some());
        assert!(core.resonances(0).is_empty(), "no actors before DRAW");
        core.toggle_design(); // active = 0 → pulls its poles into editable actors
        assert!(
            !core.resonances(0).is_empty(),
            "a loaded seed becomes sculptable actors on entering DRAW"
        );
    }

    // CHEAP PROOF: construct a "metallic vowel" body directly through the resonance
    // API (Klatt formants + Bark notches as actors) — no fitter, no UI — and export
    // a shippable cartridge. M0/M100 = Ah/Oo soft anchors; Q0->Q100 heats the
    // formants and tears in fractures. Run, then load bodies/proofs/ in the DAW.
    #[test]
    fn cheap_proof_metallic_vowel() {
        let mut core = ForgeCore::default();
        core.toggle_design();

        core.set_active(0); // M0_Q0: "Ah" vocal anchor, soft
        core.add_resonance(730.0, 0.85, ResoKind::Peak);
        core.add_resonance(1090.0, 0.80, ResoKind::Peak);
        core.add_resonance(2440.0, 0.75, ResoKind::Peak);

        core.set_active(1); // M100_Q0: "Oo" vocal anchor, soft
        core.add_resonance(300.0, 0.85, ResoKind::Peak);
        core.add_resonance(870.0, 0.80, ResoKind::Peak);
        core.add_resonance(2240.0, 0.75, ResoKind::Peak);

        core.set_active(2); // M0_Q100: "Ah" heated + fracture
        core.add_resonance(730.0, 0.98, ResoKind::Peak);
        core.add_resonance(1090.0, 0.96, ResoKind::Peak);
        core.add_resonance(2440.0, 0.94, ResoKind::Peak);
        core.add_resonance(3150.0, 0.99, ResoKind::Notch);
        core.add_resonance(4400.0, 0.99, ResoKind::Notch);
        core.add_resonance(8000.0, 0.99, ResoKind::Edge);

        core.set_active(3); // M100_Q100: "Oo" heated + fracture
        core.add_resonance(300.0, 0.98, ResoKind::Peak);
        core.add_resonance(870.0, 0.96, ResoKind::Peak);
        core.add_resonance(2240.0, 0.94, ResoKind::Peak);
        core.add_resonance(3700.0, 0.99, ResoKind::Notch);
        core.add_resonance(5300.0, 0.99, ResoKind::Notch);
        core.add_resonance(9500.0, 0.99, ResoKind::Edge);

        // Body assembles, stays finite across the puck sweep.
        assert!(core.can_save());
        for &(m, q) in &[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5)] {
            core.set_puck(m, q);
            let body = core.body().expect("body at every puck position");
            assert!(body.iter().flatten().flatten().all(|v| v.is_finite()));
        }

        let json = core.export_json().expect("exports cleanly");
        assert!(json.contains("packedWords"));
        let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("bodies")
            .join("proofs");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("metallic_vowel_target.json"), json).unwrap();
    }

    // FG-2: bodies built through the shift_corner/sharpen_corner fabrication
    // fallback in `body()` must not publish. The fallback is fine for in-Forge
    // preview (drag HOME in, hear the Morph axis before fitting the rest) but
    // the publish gate requires every corner explicit.
    #[test]
    fn publish_gate_rejects_fabricated_corners() {
        let mut core = ForgeCore::default();
        core.toggle_design();

        // Empty Forge: every slot missing → publish refused, all 4 labels named.
        assert!(core.publishability_error().is_some());
        assert!(core.save().is_err());
        let msg = core.publishability_error().unwrap();
        for label in ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"] {
            assert!(msg.contains(label), "expected {label} in error: {msg}");
        }

        // One corner loaded: still refused; the three missing labels named.
        core.set_active(0);
        core.add_resonance(800.0, 0.85, ResoKind::Peak);
        let msg = core
            .publishability_error()
            .expect("only HOME loaded — still 3 missing");
        assert!(!msg.contains("M0_Q0"), "M0_Q0 was loaded: {msg}");
        for label in ["M100_Q0", "M0_Q100", "M100_Q100"] {
            assert!(msg.contains(label), "expected {label} in error: {msg}");
        }
        assert!(core.save().is_err());

        // All four corners explicitly drawn: gate clears.
        for slot in 1..4 {
            core.set_active(slot);
            core.add_resonance(800.0 + 200.0 * slot as f64, 0.85, ResoKind::Peak);
        }
        assert!(
            core.publishability_error().is_none(),
            "all 4 corners explicit — gate should clear"
        );
        // (We don't actually call .save() here because it writes to ~/Documents.)
    }

    #[test]
    fn publish_gate_accepts_verbatim_rom_body() {
        // A 240-byte ROM/body load takes the reference_packed path and is
        // shippable verbatim — no fabrication, no per-corner explicit setup
        // through the resonance UI required.
        use trench_core::minifloat::{PackedCorners, BODY_BYTES};
        let dummy_bytes = [0u8; BODY_BYTES]; // legal length; words may be all zero
        let packed = PackedCorners::from_body_bytes(&dummy_bytes).unwrap();
        let mut core = ForgeCore::default();
        // Simulate what load_reference_rom does for state: set the verbatim
        // body and packed, leave self.corners empty.
        core.set_reference_for_test(packed);
        assert!(
            core.publishability_error().is_none(),
            "verbatim 240-byte ROM must publish without any corners[] set"
        );
    }

    #[test]
    fn cube_navigates_and_previews_finite() {
        for arch in Architecture::ALL {
            let mut core = ForgeCore::default();
            core.set_architecture(arch);
            assert!(core.cube().is_some(), "{} cube not set", arch.label());
            assert!(core.cube_axes().is_some());
            for &z in &[0.0f32, 0.5, 1.0] {
                core.set_z(z);
                for &(m, q) in &[(0.0f32, 0.0f32), (1.0, 1.0), (0.5, 0.5)] {
                    core.set_puck(m, q);
                    let prev = core.preview().expect("cube preview");
                    assert!(
                        prev.iter().all(|s| s.iter().all(|v| v.is_finite())),
                        "{} preview non-finite at m{m} q{q} z{z}",
                        arch.label()
                    );
                }
            }
            // Trilinear weights sum to ~1.
            core.set_puck(0.3, 0.6);
            core.set_z(0.4);
            let w = core.cube_weights().unwrap();
            let sum: f32 = w.iter().sum();
            assert!((sum - 1.0).abs() < 1e-4, "weights sum {sum}");
        }
    }

    #[test]
    fn cube_corner_to_fsm_bakes_into_slot() {
        let mut core = ForgeCore::default();
        core.set_architecture(Architecture::Tube);
        core.set_puck(0.0, 0.0); // nearest vertex 0 (M0_Q0, z=0)
        core.set_z(0.0);
        let ci = core
            .cube_corner_to_fsm(0)
            .expect("bake nearest cube corner");
        assert_eq!(ci, 0);
        assert!(core.cube().is_none(), "cube cleared after bake");
        assert!(core.design_mode(), "FSM editor opened");
        assert!(core.corner(0).is_some(), "slot 0 populated");
        assert!(
            !core.fsm_points(0).is_empty(),
            "FSM curve seeded from the corner"
        );
    }

    // Option A (end-to-end): a composed GEN field is directly publishable as its
    // Z-crossfaded 4-corner slice — no explicit corners[] needed. The published
    // bytes ARE the exact crossfade bank, and what ships at the four vertices is
    // byte-for-byte what PLAYER auditions there.
    #[test]
    fn gen_cube_publishes_byte_authoritative_slice() {
        use trench_core::minifloat::{PackedCorners, BODY_BYTES};

        let mut core = ForgeCore::default();
        core.set_architecture(Architecture::Tube);
        core.set_z(0.5); // a real crossfade, not a pure plane

        // The composed field publishes without populating corners[].
        assert!(
            core.publishability_error().is_none(),
            "a composed GEN field must publish as its Z slice"
        );
        assert!(core.can_save());

        // The shipped bytes are the exact Z-crossfade of the two plane bodies.
        let expected = {
            let c = core.cube.as_ref().expect("cube active");
            PackedCorners::z_crossfade(&c.floor, &c.ceiling, c.z).to_rom_bytes()
        };
        let bytes = core.export_body240().expect("body240");
        assert_eq!(bytes.len(), BODY_BYTES);
        assert_eq!(
            bytes.as_slice(),
            expected.as_slice(),
            "published bytes must be the exact Z-crossfade slice"
        );

        // What ships at the four vertices == what PLAYER auditions there.
        let body = core.body().expect("cube body");
        for (ci, corner) in body.iter().enumerate() {
            let (m, q) = [(0.0f32, 0.0f32), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)][ci];
            core.set_puck(m, q);
            let played = core.preview().expect("vertex preview");
            for (a, b) in corner.iter().flatten().zip(played.iter().flatten()) {
                assert!((a - b).abs() < 1e-9, "vertex {ci}: ship != play ({a} vs {b})");
            }
        }

        // Loads back through the canonical loader as a PACKED body.
        let json = core.export_json().expect("export json");
        assert!(json.contains("packedWords"));
        let cart = Cartridge::from_json(&json).expect("loader parses cube export");
        assert!(cart.packed.is_some(), "cube export must be a packed body");
    }

    #[test]
    fn fsm_seed_curve_fits_and_supersedes_cube() {
        let mut core = ForgeCore::default();
        core.set_architecture(Architecture::Comb);
        core.toggle_design(); // open editor on slot 0
        let curve = dsp::klatt_vowel_curve("a", AUTHORING_RATE);
        core.seed_curve(curve);
        assert!(
            core.cube().is_none(),
            "authored FSM corner supersedes the cube"
        );
        assert!(core.corner(0).is_some(), "FSM fit landed in slot 0");
        let prev = core.preview().expect("preview after seed");
        assert!(prev.iter().all(|s| s.iter().all(|v| v.is_finite())));
    }
}
