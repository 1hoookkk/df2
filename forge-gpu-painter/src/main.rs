// TRENCH FORGE — Z-plane filter designer (GPU, eframe/wgpu, fully custom painted).
//
// Six second-order IIR sections; each section is a conjugate pole pair and a
// conjugate zero pair, stored per corner (M0Q0, M100Q0, M0Q100, M100Q100).
// Bytes are packed through trench_core::compiler::pack_body — the same forward
// compiler the shipped engine uses — and every curve on screen is computed from
// the packed words through the engine's own interpolation (lerp on u16 words,
// morph first, then Q). The plot is the engine or it is nothing.
//
// All chrome is custom painted: chips, menus, sliders, value fields, band
// cards, maps. egui supplies only the window, input and the painter.
// UI register is textbook DSP: Hz, pole radius r, zero radius r_z, gain dB,
// morph, Q. Type-family seeds cover the classic taxonomy (LPF / HPF / BPF /
// EQ / notch comb / resonant peaks / vowel formants / tube / metal).

use eframe::egui::{
    self, Align2, Color32, Event, FontId, Key, Pos2, Rect, Sense, Stroke, TextureHandle,
    TextureOptions, Vec2,
};
use serde::Serialize;
use std::f32::consts::TAU as TAU32;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

const F_MIN: f32 = 30.0;
const F_MAX: f32 = 16_000.0;
const DB_MIN: f32 = -36.0;
const DB_MAX: f32 = 48.0;
const FREQ_BINS: usize = 480;
const HEAT_W: usize = 320;
const HEAT_H: usize = 130;
const AUDIT_N: usize = 17;
const AUDIT_BINS: usize = 96;
const STAGES: usize = 6;
const CORNERS: usize = 4;
const SR: f32 = 39_062.5;

const RP_MIN: f32 = 0.5;
const RP_MAX: f32 = 0.9992;
const RZ_MAX: f32 = 0.9995;
const GAIN_DB_MIN: f32 = -26.0;
const GAIN_DB_MAX: f32 = 12.0;

// ── palette ───────────────────────────────────────────────────────────────────

const BG: Color32 = Color32::from_rgb(13, 14, 17);
const PANEL: Color32 = Color32::from_rgb(20, 21, 26);
const PANEL_HI: Color32 = Color32::from_rgb(28, 29, 36);
const EDGE: Color32 = Color32::from_rgb(43, 44, 53);
const TEXT: Color32 = Color32::from_rgb(214, 211, 205);
const TEXT_DIM: Color32 = Color32::from_rgb(133, 130, 124);
const TRUTH: Color32 = Color32::from_rgb(242, 239, 232);
const ICE: Color32 = Color32::from_rgb(143, 227, 240);
const EMBER: Color32 = Color32::from_rgb(199, 116, 31);
const FAULT: Color32 = Color32::from_rgb(229, 72, 60);
const GHOST_LO: Color32 = Color32::from_rgb(95, 182, 219);
const GHOST_HI: Color32 = Color32::from_rgb(224, 154, 95);

fn section_color(index: usize) -> Color32 {
    match index {
        0 => Color32::from_rgb(255, 196, 77),
        1 => Color32::from_rgb(188, 153, 255),
        2 => Color32::from_rgb(89, 205, 255),
        3 => Color32::from_rgb(127, 225, 180),
        4 => Color32::from_rgb(255, 117, 117),
        _ => Color32::from_rgb(244, 236, 157),
    }
}

fn with_alpha(c: Color32, a: u8) -> Color32 {
    Color32::from_rgba_unmultiplied(c.r(), c.g(), c.b(), a)
}

// ── enums ─────────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, PartialEq, Eq)]
enum CornerKey {
    M0Q0,
    M100Q0,
    M0Q100,
    M100Q100,
}

impl CornerKey {
    const ALL: [Self; 4] = [Self::M0Q0, Self::M100Q0, Self::M0Q100, Self::M100Q100];

    fn idx(self) -> usize {
        match self {
            Self::M0Q0 => 0,
            Self::M100Q0 => 1,
            Self::M0Q100 => 2,
            Self::M100Q100 => 3,
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::M0Q0 => "M0 Q0",
            Self::M100Q0 => "M100 Q0",
            Self::M0Q100 => "M0 Q100",
            Self::M100Q100 => "M100 Q100",
        }
    }

    fn morph_q(self) -> (f32, f32) {
        match self {
            Self::M0Q0 => (0.0, 0.0),
            Self::M100Q0 => (1.0, 0.0),
            Self::M0Q100 => (0.0, 1.0),
            Self::M100Q100 => (1.0, 1.0),
        }
    }

    fn scope_corners(self, scope: EditScope) -> Vec<usize> {
        match scope {
            EditScope::Corner => vec![self.idx()],
            EditScope::Frame => match self {
                Self::M0Q0 | Self::M0Q100 => vec![0, 2],
                Self::M100Q0 | Self::M100Q100 => vec![1, 3],
            },
            EditScope::All => vec![0, 1, 2, 3],
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum EditScope {
    Corner,
    Frame,
    All,
}

impl EditScope {
    fn label(self) -> &'static str {
        match self {
            Self::Corner => "this corner",
            Self::Frame => "this frame",
            Self::All => "all corners",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Quantize {
    Measured,
    Tet,
    Off,
}

impl Quantize {
    fn label(self) -> &'static str {
        match self {
            Self::Measured => "measured resonances",
            Self::Tet => "12-TET in key",
            Self::Off => "off",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum HandleKind {
    Pole,
    Zero,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Menu {
    Seed,
    Corners,
    Quantize,
    Scope,
    View,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum ValueField {
    PoleHz,
    PoleR,
    ZeroHz,
    ZeroR,
    GainDb,
}

// ── model ─────────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Serialize)]
struct CornerStage {
    pole_hz: f32,
    pole_r: f32,
    zero_hz: f32,
    zero_r: f32,
    gain_db: f32,
}

#[derive(Clone, Serialize)]
struct Section {
    on: bool,
    locked: bool,
    corners: [CornerStage; CORNERS],
}

#[derive(Serialize)]
struct SaveSidecar<'a> {
    note: &'a str,
    sections: &'a [Section],
}

#[derive(Clone, Copy)]
enum Drag {
    Handle {
        stage: usize,
        kind: HandleKind,
        gain: bool,
        start_pos: Pos2,
        start: [CornerStage; CORNERS],
    },
    Morph,
    Q,
    Value {
        field: ValueField,
        start_y: f32,
        start: [CornerStage; CORNERS],
    },
    SurfaceMap,
    SweepMap,
}

struct Tables {
    resonances: Vec<f32>,
    vowels: Vec<(String, f32, f32, f32, f32, f32, f32)>,
    metal_ratios: Vec<f32>,
}

/// One executed menu action (id strings keep the hit-test table flat).
#[derive(Clone, Copy, PartialEq, Eq)]
enum MenuAction {
    SeedDefault,
    SeedLowpass,
    SeedHighpass,
    SeedBandpass,
    SeedNotchComb,
    SeedParametric,
    SeedPeaks,
    SeedVowel(usize),
    SeedTube(usize),
    SeedMetal(usize),
    CopyCornerAll,
    DeriveQ,
    QuantSet(Quantize),
    KeySet(usize),
    ScopeSet(EditScope),
    ToggleSections,
    ToggleRail,
}

const VOWEL_PAIRS: [(&str, &str, &str); 4] = [
    ("aa", "iy", "vowel  ah > ee"),
    ("uw", "iy", "vowel  oo > ee"),
    ("aa", "uw", "vowel  ah > oo"),
    ("ae", "uh", "vowel  a > u"),
];
const TUBE_F0: [f32; 3] = [55.0, 110.0, 220.0];
const METAL_F0: [f32; 3] = [110.0, 220.0, 440.0];
const NOTES: [&str; 12] = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

// ── app state ─────────────────────────────────────────────────────────────────

struct App {
    sections: Vec<Section>,
    selected_stage: usize,
    selected_corner: CornerKey,
    scope: EditScope,
    quantize: Quantize,
    key_root: usize,
    morph: f32,
    q: f32,
    sweep: bool,
    sweep_t0: Instant,
    body: [u8; 240],
    response: Vec<f32>,
    ghost_low: Vec<f32>,
    ghost_high: Vec<f32>,
    stage_db: [[f32; FREQ_BINS]; STAGES],
    heat_texture: Option<TextureHandle>,
    heat_dirty: bool,
    show_sections: bool,
    show_rail: bool,
    audit_levels: [f32; AUDIT_N * AUDIT_N],
    audit_maxr: f32,
    audit_unstable: usize,
    audit_dirty: bool,
    audit_texture: Option<TextureHandle>,
    drag: Option<Drag>,
    open_menu: Option<Menu>,
    menu_opened_at: Option<Instant>,
    name_active: bool,
    body_name: String,
    undo: Vec<Vec<Section>>,
    redo: Vec<Vec<Section>>,
    tables: Tables,
    status: String,
    last_edit: Instant,
}

fn main() -> eframe::Result {
    if std::env::args().any(|arg| arg == "--bake-once") {
        let mut app = App::default_state();
        app.bake();
        println!("{}", app.status);
        return Ok(());
    }
    let options = eframe::NativeOptions {
        renderer: eframe::Renderer::Wgpu,
        viewport: egui::ViewportBuilder::default()
            .with_title("TRENCH FORGE — Z-plane filter designer")
            .with_inner_size([1420.0, 880.0])
            .with_min_inner_size([1020.0, 620.0]),
        ..Default::default()
    };
    eframe::run_native("TRENCH FORGE", options, Box::new(|cc| Ok(Box::new(App::new(cc)))))
}

// ── tables (measured values only) ─────────────────────────────────────────────

fn repo_root() -> PathBuf {
    let mut dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    for _ in 0..4 {
        if dir.join("tables").join("vowel_formants.json").exists() {
            return dir;
        }
        if !dir.pop() {
            break;
        }
    }
    PathBuf::from(".")
}

fn load_tables() -> Tables {
    let mut t = Tables { resonances: Vec::new(), vowels: Vec::new(), metal_ratios: Vec::new() };
    let dir = repo_root().join("tables");
    if let Ok(text) = fs::read_to_string(dir.join("vowel_formants.json")) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) {
            if let Some(vowels) = v["vowels"].as_array() {
                for vw in vowels {
                    let g = |k: &str| vw[k].as_f64().unwrap_or(0.0) as f32;
                    let key = vw["key"].as_str().unwrap_or("?").to_string();
                    let (f1, f2, f3) = (g("f1"), g("f2"), g("f3"));
                    if f1 > 0.0 {
                        for f in [f1, f2, f3] {
                            if (F_MIN..=F_MAX).contains(&f) {
                                t.resonances.push(f);
                            }
                        }
                        t.vowels.push((key, f1, f2, f3, g("bw1").max(40.0), g("bw2").max(60.0), g("bw3").max(100.0)));
                    }
                }
            }
        }
    }
    if let Ok(text) = fs::read_to_string(dir.join("metallic_modes.json")) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) {
            fn find_ratios(v: &serde_json::Value, out: &mut Vec<f32>) {
                if !out.is_empty() {
                    return;
                }
                match v {
                    serde_json::Value::Object(m) => {
                        if let Some(r) = m.get("ratios").and_then(|r| r.as_array()) {
                            for x in r {
                                if let Some(f) = x.as_f64() {
                                    out.push(f as f32);
                                }
                            }
                            return;
                        }
                        for x in m.values() {
                            find_ratios(x, out);
                        }
                    }
                    serde_json::Value::Array(a) => {
                        for x in a {
                            find_ratios(x, out);
                        }
                    }
                    _ => {}
                }
            }
            find_ratios(&v, &mut t.metal_ratios);
        }
    }
    t.resonances.sort_by(|a, b| a.partial_cmp(b).unwrap());
    t.resonances.dedup_by(|a, b| (*a - *b).abs() < 0.5);
    t
}

// ── default template ─────────────────────────────────────────────────────────

fn default_sections() -> Vec<Section> {
    fn sec(pf0: f32, pf1: f32, pr0: f32, pr1: f32, zf: f32, zr: f32, g0: f32, g1: f32) -> Section {
        Section {
            on: true,
            locked: false,
            corners: [
                CornerStage { pole_hz: pf0, pole_r: pr0, zero_hz: zf, zero_r: zr, gain_db: g0 },
                CornerStage { pole_hz: pf1, pole_r: pr0, zero_hz: zf, zero_r: zr, gain_db: g1 },
                CornerStage { pole_hz: pf0, pole_r: pr1, zero_hz: zf, zero_r: zr, gain_db: g0 },
                CornerStage { pole_hz: pf1, pole_r: pr1, zero_hz: zf, zero_r: zr, gain_db: g1 },
            ],
        }
    }
    vec![
        sec(134.0, 134.0, 0.985, 0.996, 4130.0, 0.85, 0.0, 0.0),
        sec(780.0, 2840.0, 0.960, 0.995, 4130.0, 0.90, 0.0, 3.0),
        sec(1090.0, 3790.0, 0.960, 0.995, 8250.0, 0.90, 0.0, 0.0),
        sec(5450.0, 1420.0, 0.900, 0.990, 16000.0, 0.95, 0.0, 0.0),
        sec(3790.0, 5450.0, 0.970, 0.997, 4440.0, 0.95, 0.0, 0.0),
        sec(9000.0, 9000.0, 0.600, 0.700, 16000.0, 0.98, 0.0, -3.0),
    ]
}

fn topology(s: &Section, corner: usize) -> &'static str {
    if !s.on {
        return "bypass";
    }
    let c = s.corners[corner];
    let sep = (c.zero_hz / c.pole_hz).log2().abs();
    if c.zero_r < 0.15 {
        return "resonator (near all-pole)";
    }
    if sep < 0.12 && (c.zero_r - c.pole_r).abs() < 0.05 {
        return "near-allpass";
    }
    let res = c.pole_r >= 0.93;
    let anti = c.zero_r >= 0.9;
    match (res, anti) {
        (true, true) => "pole-zero resonator",
        (true, false) => "resonant SOS",
        (false, true) => "notch / antiresonance",
        (false, false) => "shelving / tilt SOS",
    }
}

// ── app impl: state + DSP plumbing ───────────────────────────────────────────

impl App {
    fn new(cc: &eframe::CreationContext<'_>) -> Self {
        cc.egui_ctx.set_pixels_per_point(1.0);
        Self::default_state()
    }

    fn default_state() -> Self {
        let mut app = Self {
            sections: default_sections(),
            selected_stage: 1,
            selected_corner: CornerKey::M0Q0,
            scope: EditScope::Corner,
            quantize: Quantize::Measured,
            key_root: 9,
            morph: 0.0,
            q: 0.0,
            sweep: false,
            sweep_t0: Instant::now(),
            body: [0; 240],
            response: vec![0.0; FREQ_BINS],
            ghost_low: vec![0.0; FREQ_BINS],
            ghost_high: vec![0.0; FREQ_BINS],
            stage_db: [[0.0; FREQ_BINS]; STAGES],
            heat_texture: None,
            heat_dirty: true,
            show_sections: true,
            show_rail: true,
            audit_levels: [f32::NAN; AUDIT_N * AUDIT_N],
            audit_maxr: 0.0,
            audit_unstable: 0,
            audit_dirty: true,
            audit_texture: None,
            drag: None,
            open_menu: None,
            menu_opened_at: None,
            name_active: false,
            body_name: String::new(),
            undo: Vec::new(),
            redo: Vec::new(),
            tables: load_tables(),
            status: "ready — bytes packed by trench_core::compiler::pack_body (== shipped engine)".into(),
            last_edit: Instant::now(),
        };
        app.rebuild_body();
        app
    }

    fn push_undo(&mut self) {
        self.undo.push(self.sections.clone());
        if self.undo.len() > 120 {
            self.undo.remove(0);
        }
        self.redo.clear();
    }

    fn do_undo(&mut self) {
        if let Some(prev) = self.undo.pop() {
            self.redo.push(self.sections.clone());
            self.sections = prev;
            self.rebuild_body();
            self.status = "undo".into();
        }
    }

    fn do_redo(&mut self) {
        if let Some(next) = self.redo.pop() {
            self.undo.push(self.sections.clone());
            self.sections = next;
            self.rebuild_body();
            self.status = "redo".into();
        }
    }

    fn params168(&self) -> Vec<f64> {
        let mut out = Vec::with_capacity(168);
        for key in CornerKey::ALL {
            for section in &self.sections {
                let c = section.corners[key.idx()];
                out.push(if section.on { 1.0 } else { 0.0 });
                out.push(c.pole_hz as f64);
                out.push(c.pole_r as f64);
                out.push(db_to_lin(c.gain_db) as f64);
                out.push(if c.zero_r > 0.0001 { 1.0 } else { 0.0 });
                out.push(c.zero_hz as f64);
                out.push(c.zero_r as f64);
            }
        }
        out
    }

    fn rebuild_body(&mut self) {
        let params = self.params168();
        self.body = trench_core::compiler::pack_body(&params);
        self.recompute_response();
        self.heat_dirty = true;
        self.audit_dirty = true;
        self.last_edit = Instant::now();
    }

    fn words(&self) -> [[[u16; 5]; STAGES]; CORNERS] {
        let mut words = [[[0u16; 5]; STAGES]; CORNERS];
        let mut i = 0;
        for corner in &mut words {
            for stage in corner {
                for word in stage {
                    *word = u16::from_le_bytes([self.body[i], self.body[i + 1]]);
                    i += 2;
                }
            }
        }
        words
    }

    fn recompute_response(&mut self) {
        let words = self.words();
        let live = live_biquads(&words, self.morph, self.q);
        let lo = live_biquads(&words, 0.0, self.q);
        let hi = live_biquads(&words, 1.0, self.q);
        for i in 0..FREQ_BINS {
            let f = freq_at(i, FREQ_BINS);
            self.response[i] = cascade_db(&live, f);
            self.ghost_low[i] = cascade_db(&lo, f);
            self.ghost_high[i] = cascade_db(&hi, f);
            for s in 0..STAGES {
                self.stage_db[s][i] = biquad_db(live[s], f);
            }
        }
    }

    fn stage_db_at(&self, stage: usize, freq: f32) -> f32 {
        let t = (freq / F_MIN).log2() / (F_MAX / F_MIN).log2();
        let i = (t.clamp(0.0, 1.0) * (FREQ_BINS - 1) as f32).round() as usize;
        self.stage_db[stage][i]
    }

    fn recompute_heat(&mut self, ctx: &egui::Context) {
        let words = self.words();
        let mut pixels = Vec::with_capacity(HEAT_W * HEAT_H);
        for y in 0..HEAT_H {
            let morph = 1.0 - y as f32 / (HEAT_H - 1) as f32;
            let stages = live_biquads(&words, morph, self.q);
            for x in 0..HEAT_W {
                pixels.push(heat_color(cascade_db(&stages, freq_at(x, HEAT_W))));
            }
        }
        let image = egui::ColorImage { size: [HEAT_W, HEAT_H], pixels };
        match &mut self.heat_texture {
            Some(tex) => tex.set(image, TextureOptions::LINEAR),
            None => self.heat_texture = Some(ctx.load_texture("morph_sweep", image, TextureOptions::LINEAR)),
        }
        self.heat_dirty = false;
    }

    fn recompute_audit(&mut self, ctx: &egui::Context) {
        let words = self.words();
        let mut maxr = 0.0f32;
        let mut unstable = 0;
        for j in 0..AUDIT_N {
            let q = j as f32 / (AUDIT_N - 1) as f32;
            for i in 0..AUDIT_N {
                let m = i as f32 / (AUDIT_N - 1) as f32;
                let stages = live_biquads(&words, m, q);
                let mut mx = f32::NEG_INFINITY;
                for b in 0..AUDIT_BINS {
                    mx = mx.max(cascade_db(&stages, freq_at(b, AUDIT_BINS)));
                }
                self.audit_levels[j * AUDIT_N + i] = mx;
                let r = stages_max_pole_radius(&stages);
                if !(r < 1.0) {
                    unstable += 1;
                }
                maxr = maxr.max(r);
            }
        }
        self.audit_maxr = maxr;
        self.audit_unstable = unstable;
        let mut pixels = Vec::with_capacity(AUDIT_N * AUDIT_N);
        for j in (0..AUDIT_N).rev() {
            for i in 0..AUDIT_N {
                let k = j * AUDIT_N + i;
                let stable = self.audit_levels[k].is_finite();
                pixels.push(if stable { heat_color(self.audit_levels[k]) } else { FAULT });
            }
        }
        let image = egui::ColorImage { size: [AUDIT_N, AUDIT_N], pixels };
        match &mut self.audit_texture {
            Some(tex) => tex.set(image, TextureOptions::NEAREST),
            None => self.audit_texture = Some(ctx.load_texture("surface_map", image, TextureOptions::NEAREST)),
        }
        self.audit_dirty = false;
    }

    fn audit_at(&self, m: f32, q: f32) -> f32 {
        let i = (m * (AUDIT_N - 1) as f32).round() as usize;
        let j = (q * (AUDIT_N - 1) as f32).round() as usize;
        self.audit_levels[j * AUDIT_N + i]
    }

    fn select_corner(&mut self, corner: CornerKey) {
        self.selected_corner = corner;
        let (m, q) = corner.morph_q();
        let q_changed = (self.q - q).abs() > f32::EPSILON;
        self.morph = m;
        self.q = q;
        self.recompute_response();
        if q_changed {
            self.heat_dirty = true;
        }
    }

    fn grid(&self) -> Option<Vec<f32>> {
        match self.quantize {
            Quantize::Off => None,
            Quantize::Measured => (!self.tables.resonances.is_empty()).then(|| self.tables.resonances.clone()),
            Quantize::Tet => {
                const MINOR: [i32; 7] = [0, 2, 3, 5, 7, 8, 10];
                let mut out = Vec::new();
                for midi in 12..=120i32 {
                    let deg = (midi - self.key_root as i32).rem_euclid(12);
                    if !MINOR.contains(&deg) {
                        continue;
                    }
                    let f = 440.0 * 2f32.powf((midi as f32 - 69.0) / 12.0);
                    if (F_MIN..=F_MAX).contains(&f) {
                        out.push(f);
                    }
                }
                Some(out)
            }
        }
    }

    fn snap(&self, freq: f32, fine: bool) -> f32 {
        if fine {
            return freq;
        }
        let Some(grid) = self.grid() else { return freq };
        let mut best = freq;
        let mut bd = f32::INFINITY;
        for g in grid {
            let d = (g / freq).log2().abs();
            if d < bd {
                bd = d;
                best = g;
            }
        }
        if bd < 0.035 { best } else { freq }
    }

    // ── seeds: type-family templates + table-driven material ────────────────

    fn set_all(&mut self, rows: &[(bool, f32, f32, f32, f32, f32, f32, f32, f32)]) {
        // (on, pf_low, pf_high, pr_q0, pr_q1, zf_low, zf_high, zr, gain_db)
        for (s, row) in rows.iter().enumerate().take(STAGES) {
            let (on, pf0, pf1, pr0, pr1, zf0, zf1, zr, g) = *row;
            let sec = &mut self.sections[s];
            sec.on = on;
            sec.locked = false;
            for (ci, key) in CornerKey::ALL.iter().enumerate() {
                let (m, q) = key.morph_q();
                let c = &mut sec.corners[ci];
                c.pole_hz = (if m > 0.5 { pf1 } else { pf0 }).clamp(F_MIN, F_MAX);
                c.pole_r = (if q > 0.5 { pr1 } else { pr0 }).clamp(RP_MIN, RP_MAX);
                c.zero_hz = (if m > 0.5 { zf1 } else { zf0 }).clamp(F_MIN, F_MAX);
                c.zero_r = zr.clamp(0.0, RZ_MAX);
                c.gain_db = g;
            }
        }
        self.rebuild_body();
    }

    fn seed_default(&mut self) {
        self.push_undo();
        self.sections = default_sections();
        self.rebuild_body();
        self.status = "seed: default template".into();
    }

    /// Resonant low-pass sweep: stacked poles at the cutoff travelling up the
    /// band under morph, zeros parked high. Q sharpens the corner.
    fn seed_lowpass(&mut self) {
        self.push_undo();
        self.set_all(&[
            (true, 110.0, 3520.0, 0.97, 0.996, 14000.0, 14000.0, 0.85, 0.0),
            (true, 110.0, 3520.0, 0.93, 0.99, 14000.0, 14000.0, 0.85, 0.0),
            (true, 110.0, 3520.0, 0.88, 0.95, 14000.0, 14000.0, 0.85, 0.0),
            (true, 55.0, 55.0, 0.94, 0.96, 14000.0, 14000.0, 0.8, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.8, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.8, 0.0),
        ]);
        self.status = "seed: resonant low-pass sweep (110 Hz → 3.5 kHz, zeros parked high)".into();
    }

    /// High-pass: deep zeros pinned at the bottom of the band, poles at the
    /// moving cutoff giving the corner its resonance.
    fn seed_highpass(&mut self) {
        self.push_undo();
        self.set_all(&[
            (true, 110.0, 1760.0, 0.95, 0.993, 30.0, 30.0, 0.995, 0.0),
            (true, 110.0, 1760.0, 0.9, 0.97, 42.0, 42.0, 0.99, 0.0),
            (true, 110.0, 1760.0, 0.85, 0.92, 60.0, 60.0, 0.99, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 30.0, 30.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 30.0, 30.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 30.0, 30.0, 0.9, 0.0),
        ]);
        self.status = "seed: high-pass (zeros pinned low, resonant moving corner)".into();
    }

    /// Band-pass: one strong resonator riding the morph, zeros guarding both
    /// edges of the band.
    fn seed_bandpass(&mut self) {
        self.push_undo();
        self.set_all(&[
            (true, 220.0, 3520.0, 0.985, 0.996, 30.0, 30.0, 0.99, 0.0),
            (true, 220.0, 3520.0, 0.97, 0.99, 14000.0, 14000.0, 0.95, 0.0),
            (true, 220.0, 3520.0, 0.9, 0.95, 30.0, 30.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
        ]);
        self.status = "seed: band-pass (resonator sweep, zeros at both band edges)".into();
    }

    /// Notch comb: deep zero series at odd harmonics, near-allpass poles —
    /// the classic phaser construction. Morph shifts the whole comb.
    fn seed_notch_comb(&mut self) {
        self.push_undo();
        let f0_lo = 220.0;
        let f0_hi = 880.0;
        let mut rows = Vec::new();
        for k in 0..STAGES {
            let n = (2 * k + 1) as f32;
            rows.push((
                true,
                f0_lo * n * 0.97,
                f0_hi * n * 0.97,
                0.88f32,
                0.93f32,
                f0_lo * n,
                f0_hi * n,
                0.99f32,
                0.0f32,
            ));
        }
        self.set_all(&rows);
        self.status = "seed: notch comb / phase-shifter (zeros at odd multiples, near-allpass poles)".into();
    }

    /// Parametric boost: two strong peaking sections over a held low shelf —
    /// the EQ family. Morph slides the boost up the band.
    fn seed_parametric(&mut self) {
        self.push_undo();
        self.set_all(&[
            (true, 88.0, 88.0, 0.985, 0.992, 350.0, 350.0, 0.7, 3.0),
            (true, 220.0, 1760.0, 0.985, 0.996, 700.0, 3520.0, 0.9, 4.0),
            (true, 440.0, 3520.0, 0.98, 0.995, 1400.0, 7040.0, 0.9, 2.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
        ]);
        self.status = "seed: parametric boost over a held low shelf (EQ family)".into();
    }

    /// Resonant peaks: all six sections hot, spread across the band — the
    /// aggressive high-Q family. Q drives every radius to the rim.
    fn seed_peaks(&mut self) {
        self.push_undo();
        self.set_all(&[
            (true, 110.0, 165.0, 0.985, 0.997, 30.0, 30.0, 0.9, 0.0),
            (true, 330.0, 495.0, 0.985, 0.997, 14000.0, 14000.0, 0.9, 0.0),
            (true, 700.0, 1050.0, 0.985, 0.997, 14000.0, 14000.0, 0.9, 0.0),
            (true, 1400.0, 2100.0, 0.985, 0.997, 14000.0, 14000.0, 0.9, 0.0),
            (true, 2800.0, 4200.0, 0.985, 0.997, 14000.0, 14000.0, 0.9, 0.0),
            (true, 5600.0, 8400.0, 0.985, 0.997, 14000.0, 14000.0, 0.9, 0.0),
        ]);
        self.status = "seed: six resonant peaks, radius to the rim under Q".into();
    }

    fn seed_vowel_pair(&mut self, pair: usize) {
        let (low_key, high_key, label) = VOWEL_PAIRS[pair];
        let find = |k: &str| self.tables.vowels.iter().find(|v| v.0 == k).cloned();
        let (Some(lo), Some(hi)) = (find(low_key), find(high_key)) else {
            self.status = "vowel table not loaded (tables/vowel_formants.json)".into();
            return;
        };
        self.push_undo();
        let r_of = |bw: f32| (-std::f32::consts::PI * bw / SR).exp().clamp(RP_MIN, RP_MAX);
        let mut rows: Vec<(bool, f32, f32, f32, f32, f32, f32, f32, f32)> = vec![
            (true, 134.0, 134.0, 0.985, 0.996, 4130.0, 4130.0, 0.85, 0.0), // low anchor held
        ];
        for (f_lo, f_hi, bw_lo, bw_hi) in [
            (lo.1, hi.1, lo.4, hi.4),
            (lo.2, hi.2, lo.5, hi.5),
            (lo.3, hi.3, lo.6, hi.6),
        ] {
            let r0 = r_of(bw_lo.max(bw_hi));
            let r1 = (1.0 - (1.0 - r0) * 0.35).clamp(RP_MIN, RP_MAX);
            rows.push((true, f_lo, f_hi, r0, r1, f_lo * 4.0, f_hi * 4.0, 0.9, 0.0));
        }
        rows.push((false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0));
        rows.push((false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0));
        self.set_all(&rows);
        self.sections[0].locked = true; // the anchor boots locked
        self.status = format!("seed: {label} (Peterson-Barney formants, r from bandwidth; S1 anchor locked)");
    }

    fn seed_tube(&mut self, which: usize) {
        self.push_undo();
        let f0 = TUBE_F0[which % TUBE_F0.len()];
        let mut rows = Vec::new();
        for s in 0..STAGES {
            let n = (s + 1) as f32;
            let f = f0 * n;
            rows.push((true, f, f * 1.5, 0.99f32, 0.997f32, f * 3.0, f * 4.5, 0.9f32, 0.0f32));
        }
        self.set_all(&rows);
        self.status = format!("seed: tube partials 1,2,3… × {f0:.0} Hz (morph stretches the tube)");
    }

    fn seed_metal(&mut self, which: usize) {
        if self.tables.metal_ratios.len() < 2 {
            self.status = "metallic_modes table not loaded".into();
            return;
        }
        self.push_undo();
        let f0 = METAL_F0[which % METAL_F0.len()];
        let ratios = self.tables.metal_ratios.clone();
        let mut rows = Vec::new();
        for s in 0..STAGES {
            let ratio = ratios.get(s).copied().unwrap_or(*ratios.last().unwrap());
            let f = f0 * ratio;
            rows.push((true, f, f * 1.26, 0.985f32, 0.997f32, f * 3.0, f * 3.78, 0.9f32, 0.0f32));
        }
        self.set_all(&rows);
        self.status = format!("seed: inharmonic modal series × {f0:.0} Hz (metallic_modes ratios)");
    }

    // ── LPC fit (drop a WAV on the window) ───────────────────────────────────

    fn fit_wav(&mut self, path: &Path, into_high_frame: bool) {
        let Ok(bytes) = fs::read(path) else {
            self.status = format!("could not read {}", path.display());
            return;
        };
        let Some((samples, sr)) = parse_wav(&bytes) else {
            self.status = "not a readable WAV (PCM 16/24/32 or float32)".into();
            return;
        };
        let take = samples.len().min((sr * 4.0) as usize);
        let (mut poles, valleys) = trench_core::lpc::extract_poles_and_valleys(&samples[..take], sr);
        if poles.is_empty() {
            self.status = "LPC fit found no resonant poles in that file".into();
            return;
        }
        self.push_undo();
        poles.sort_by(|a, b| a.freq_hz.partial_cmp(&b.freq_hz).unwrap());
        let corner_ids: [usize; 2] = if into_high_frame { [1, 3] } else { [0, 2] };
        for s in 0..STAGES {
            if self.sections[s].locked {
                continue;
            }
            if let Some(p) = poles.get(s) {
                let f = (p.freq_hz as f32).clamp(F_MIN, F_MAX);
                let r = (p.radius as f32).clamp(RP_MIN, RP_MAX);
                let zf = valleys
                    .get(s)
                    .map(|v| (*v as f32).clamp(F_MIN, F_MAX))
                    .unwrap_or((f * 3.0).clamp(F_MIN, F_MAX));
                self.sections[s].on = true;
                for ci in corner_ids {
                    let q_hi = ci >= 2;
                    let rr = if q_hi { (1.0 - (1.0 - r) * 0.35).clamp(RP_MIN, RP_MAX) } else { r };
                    let c = &mut self.sections[s].corners[ci];
                    c.pole_hz = f;
                    c.pole_r = rr;
                    c.zero_hz = zf;
                    c.zero_r = 0.9;
                }
            }
        }
        self.rebuild_body();
        self.status = format!(
            "LPC fit: {} poles + {} valleys from {} → {} frame (locked sections held)",
            poles.len().min(STAGES),
            valleys.len().min(STAGES),
            path.file_name().map(|f| f.to_string_lossy().to_string()).unwrap_or_default(),
            if into_high_frame { "high (M100)" } else { "low (M0)" },
        );
    }

    // ── corner tools / bake / audition ───────────────────────────────────────

    fn copy_corner_to_all(&mut self) {
        self.push_undo();
        let src = self.selected_corner.idx();
        for s in &mut self.sections {
            if s.locked {
                continue;
            }
            let c = s.corners[src];
            for ci in 0..CORNERS {
                s.corners[ci] = c;
            }
        }
        self.rebuild_body();
        self.status = format!("copied {} to all corners (locked sections held)", self.selected_corner.label());
    }

    fn derive_q_corners(&mut self) {
        self.push_undo();
        for s in &mut self.sections {
            if s.locked {
                continue;
            }
            for (lo, hi) in [(0usize, 2usize), (1, 3)] {
                let mut c = s.corners[lo];
                c.pole_r = (1.0 - (1.0 - c.pole_r) * 0.35).clamp(RP_MIN, RP_MAX);
                s.corners[hi] = c;
            }
        }
        self.rebuild_body();
        self.status = "Q100 corners derived: pole radius toward the rim, zeros held".into();
    }

    fn bake(&mut self) {
        let slug = if self.body_name.trim().is_empty() {
            "forge_design".to_string()
        } else {
            self.body_name.trim().to_lowercase().replace(|c: char| !c.is_alphanumeric(), "_")
        };
        let out = repo_root().join("dev/tmp/forge_gpu_painter");
        let body_path = out.join(format!("{slug}.body240"));
        let json_path = out.join(format!("{slug}.source.json"));
        let _ = fs::create_dir_all(&out);
        if let Err(err) = fs::write(&body_path, self.body) {
            self.status = format!("bake failed: {err}");
            return;
        }
        let sidecar = SaveSidecar {
            note: "TRENCH FORGE source. Body bytes packed through trench_core::compiler::pack_body.",
            sections: &self.sections,
        };
        let _ = serde_json::to_vec_pretty(&sidecar).map(|json| fs::write(&json_path, json));
        self.status = format!("baked {} (240 bytes)", body_path.display());
    }

    fn publish_audition_slot(&mut self) {
        let words = self.words();
        let labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
        let keyframes: Vec<serde_json::Value> = (0..CORNERS)
            .map(|ci| {
                serde_json::json!({
                    "label": labels[ci],
                    "boost": 1.0,
                    "stages": [],
                    "packedWords": words[ci].iter().map(|row| row.to_vec()).collect::<Vec<_>>(),
                })
            })
            .collect();
        let cart = serde_json::json!({
            "format": "compiled-v1",
            "name": if self.body_name.trim().is_empty() { "forge audition" } else { self.body_name.trim() },
            "sampleRate": SR,
            "keyframes": keyframes,
        });
        let docs = std::env::var("USERPROFILE")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."))
            .join("Documents")
            .join("TRENCH");
        let _ = fs::create_dir_all(&docs);
        let path = docs.join("authoring_slot.json");
        match serde_json::to_vec_pretty(&cart).map(|j| fs::write(&path, j)) {
            Ok(Ok(())) => {
                self.status = "audition slot published — select Forge Audition in the plugin".into()
            }
            _ => self.status = "audition publish failed".into(),
        }
    }

    fn run_action(&mut self, action: MenuAction) {
        match action {
            MenuAction::SeedDefault => self.seed_default(),
            MenuAction::SeedLowpass => self.seed_lowpass(),
            MenuAction::SeedHighpass => self.seed_highpass(),
            MenuAction::SeedBandpass => self.seed_bandpass(),
            MenuAction::SeedNotchComb => self.seed_notch_comb(),
            MenuAction::SeedParametric => self.seed_parametric(),
            MenuAction::SeedPeaks => self.seed_peaks(),
            MenuAction::SeedVowel(i) => self.seed_vowel_pair(i),
            MenuAction::SeedTube(i) => self.seed_tube(i),
            MenuAction::SeedMetal(i) => self.seed_metal(i),
            MenuAction::CopyCornerAll => self.copy_corner_to_all(),
            MenuAction::DeriveQ => self.derive_q_corners(),
            MenuAction::QuantSet(q) => self.quantize = q,
            MenuAction::KeySet(k) => self.key_root = k,
            MenuAction::ScopeSet(s) => self.scope = s,
            MenuAction::ToggleSections => self.show_sections = !self.show_sections,
            MenuAction::ToggleRail => self.show_rail = !self.show_rail,
        }
    }

    // ── input ─────────────────────────────────────────────────────────────────

    fn key_input(&mut self, ctx: &egui::Context) {
        // name field captures typing
        if self.name_active {
            let events = ctx.input(|i| i.events.clone());
            for ev in events {
                match ev {
                    Event::Text(s) => {
                        if self.body_name.len() < 48 {
                            self.body_name.push_str(&s);
                        }
                    }
                    Event::Key { key: Key::Backspace, pressed: true, .. } => {
                        self.body_name.pop();
                    }
                    Event::Key { key: Key::Enter | Key::Escape, pressed: true, .. } => {
                        self.name_active = false;
                    }
                    _ => {}
                }
            }
            return;
        }
        ctx.input(|i| {
            if i.modifiers.ctrl && i.key_pressed(Key::Z) {
                if i.modifiers.shift {
                    self.do_redo();
                } else {
                    self.do_undo();
                }
            }
            if i.modifiers.ctrl && i.key_pressed(Key::Y) {
                self.do_redo();
            }
            if i.key_pressed(Key::Num1) {
                self.select_corner(CornerKey::M0Q0);
            }
            if i.key_pressed(Key::Num2) {
                self.select_corner(CornerKey::M100Q0);
            }
            if i.key_pressed(Key::Num3) {
                self.select_corner(CornerKey::M0Q100);
            }
            if i.key_pressed(Key::Num4) {
                self.select_corner(CornerKey::M100Q100);
            }
            if i.key_pressed(Key::Space) {
                self.sweep = !self.sweep;
                self.sweep_t0 = Instant::now();
            }
            if i.key_pressed(Key::L) {
                let s = self.selected_stage;
                self.sections[s].locked = !self.sections[s].locked;
                self.status = format!(
                    "S{} {}",
                    s + 1,
                    if self.sections[s].locked { "locked — edits and fits hold it" } else { "unlocked" }
                );
            }
            if i.key_pressed(Key::E) {
                let s = self.selected_stage;
                self.push_undo();
                self.sections[s].on = !self.sections[s].on;
                self.rebuild_body();
            }
            if i.key_pressed(Key::ArrowRight) {
                self.selected_stage = (self.selected_stage + 1) % STAGES;
            }
            if i.key_pressed(Key::ArrowLeft) {
                self.selected_stage = (self.selected_stage + STAGES - 1) % STAGES;
            }
        });
        let dropped = ctx.input(|i| i.raw.dropped_files.clone());
        if !dropped.is_empty() {
            let shift = ctx.input(|i| i.modifiers.shift);
            if let Some(path) = dropped[0].path.clone() {
                self.fit_wav(&path, shift);
            }
        }
    }
}

// ── layout ────────────────────────────────────────────────────────────────────

struct Layout {
    bar1: Rect,
    bar2: Rect,
    plot: Rect,
    rail: Option<Rect>,
    strip: Rect,
    values: Rect,
    statusbar: Rect,
}

fn layout(rect: Rect, show_rail: bool) -> Layout {
    let bar1_h = 38.0;
    let bar2_h = 28.0;
    let strip_h = 64.0;
    let values_h = 30.0;
    let status_h = 22.0;
    let rail_w = if show_rail { 248.0 } else { 0.0 };
    let bar1 = Rect::from_min_max(rect.min, Pos2::new(rect.right(), rect.top() + bar1_h));
    let bar2 = Rect::from_min_max(bar1.left_bottom(), Pos2::new(rect.right(), bar1.bottom() + bar2_h));
    let statusbar = Rect::from_min_max(Pos2::new(rect.left(), rect.bottom() - status_h), rect.max);
    let values = Rect::from_min_max(
        Pos2::new(rect.left(), statusbar.top() - values_h),
        Pos2::new(rect.right(), statusbar.top()),
    );
    let strip = Rect::from_min_max(
        Pos2::new(rect.left(), values.top() - strip_h),
        Pos2::new(rect.right(), values.top()),
    );
    let work = Rect::from_min_max(
        Pos2::new(rect.left() + 8.0, bar2.bottom() + 6.0),
        Pos2::new(rect.right() - 8.0, strip.top() - 6.0),
    );
    let (plot, rail) = if show_rail {
        (
            Rect::from_min_max(work.min, Pos2::new(work.right() - rail_w - 6.0, work.bottom())),
            Some(Rect::from_min_max(Pos2::new(work.right() - rail_w, work.top()), work.max)),
        )
    } else {
        (work, None)
    };
    Layout { bar1, bar2, plot, rail, strip, values, statusbar }
}

// ── custom widget hit lists ───────────────────────────────────────────────────

struct Hit<T> {
    rect: Rect,
    value: T,
}

struct Frame {
    corner_chips: Vec<Hit<CornerKey>>,
    menu_chips: Vec<Hit<Menu>>,
    menu_items: Vec<Hit<MenuAction>>,
    menu_rect: Option<Rect>,
    morph_rect: Rect,
    q_rect: Rect,
    sweep_rect: Rect,
    name_rect: Rect,
    bake_rect: Rect,
    audition_rect: Rect,
    handles: Vec<(Pos2, usize, HandleKind)>,
    cards: Vec<Hit<usize>>,
    locks: Vec<Hit<usize>>,
    value_fields: Vec<Hit<ValueField>>,
    on_rect: Rect,
    lock_rect: Rect,
    surface_rect: Option<Rect>,
    sweepmap_rect: Option<Rect>,
}

impl Default for Frame {
    fn default() -> Self {
        let z = Rect::NOTHING;
        Self {
            corner_chips: Vec::new(),
            menu_chips: Vec::new(),
            menu_items: Vec::new(),
            menu_rect: None,
            morph_rect: z,
            q_rect: z,
            sweep_rect: z,
            name_rect: z,
            bake_rect: z,
            audition_rect: z,
            handles: Vec::new(),
            cards: Vec::new(),
            locks: Vec::new(),
            value_fields: Vec::new(),
            on_rect: z,
            lock_rect: z,
            surface_rect: None,
            sweepmap_rect: None,
        }
    }
}

// ── update loop ───────────────────────────────────────────────────────────────

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.key_input(ctx);

        if self.sweep {
            let t = self.sweep_t0.elapsed().as_secs_f32();
            let phase = (t / 4.0).fract();
            self.morph = if phase < 0.5 { phase * 2.0 } else { 2.0 - phase * 2.0 };
            self.recompute_response();
            ctx.request_repaint_after(Duration::from_millis(16));
        }
        let pointer_down = ctx.input(|i| i.pointer.primary_down());
        let idle = !pointer_down && self.last_edit.elapsed() > Duration::from_millis(140);
        if self.heat_dirty && (self.heat_texture.is_none() || idle) {
            self.recompute_heat(ctx);
        }
        if self.audit_dirty && (self.audit_texture.is_none() || idle) {
            self.recompute_audit(ctx);
        }
        if self.heat_dirty || self.audit_dirty {
            ctx.request_repaint_after(Duration::from_millis(90));
        }

        egui::CentralPanel::default()
            .frame(egui::Frame::none().fill(BG))
            .show(ctx, |ui| {
                let rect = ui.max_rect();
                let resp = ui.allocate_rect(rect, Sense::click_and_drag());
                let p = ui.painter().clone();
                let lay = layout(rect, self.show_rail);

                let mut frame = Frame::default();
                self.draw_bar1(&p, lay.bar1, &mut frame);
                self.draw_bar2(&p, lay.bar2, &mut frame);
                self.draw_plot(&p, lay.plot, &mut frame);
                if let Some(rail) = lay.rail {
                    self.draw_rail(&p, rail, &mut frame);
                }
                self.draw_strip(&p, lay.strip, &mut frame);
                self.draw_values(&p, lay.values, &mut frame);
                self.draw_status(&p, lay.statusbar);
                // menu popup last (over everything)
                if self.open_menu.is_some() {
                    self.draw_menu(&p, &mut frame);
                }

                self.interact(ctx, &resp, lay, frame);
            });
    }
}

impl App {
    // ── bar 1: title · corners · morph/q · sweep · name · bake/audition · lamp ─

    fn draw_bar1(&self, p: &egui::Painter, bar: Rect, frame: &mut Frame) {
        p.rect_filled(bar, 0.0, PANEL);
        p.line_segment([bar.left_bottom(), bar.right_bottom()], Stroke::new(1.0, EDGE));
        let cy = bar.center().y;
        let mut x = bar.left() + 14.0;
        p.text(Pos2::new(x, cy), Align2::LEFT_CENTER, "TRENCH FORGE", FontId::monospace(14.0), TRUTH);
        x += 130.0;

        for corner in CornerKey::ALL {
            let w = if corner.label().len() > 6 { 76.0 } else { 60.0 };
            let r = Rect::from_min_size(Pos2::new(x, cy - 11.0), Vec2::new(w, 22.0));
            let active = corner == self.selected_corner;
            chip(p, r, corner.label(), active, ICE);
            frame.corner_chips.push(Hit { rect: r, value: corner });
            x += w + 6.0;
        }
        x += 10.0;

        let morph_r = Rect::from_min_size(Pos2::new(x, cy - 11.0), Vec2::new(170.0, 22.0));
        slider_chip(p, morph_r, "MORPH", self.morph, section_color(0));
        frame.morph_rect = morph_r;
        x += 180.0;
        let q_r = Rect::from_min_size(Pos2::new(x, cy - 11.0), Vec2::new(140.0, 22.0));
        slider_chip(p, q_r, "Q", self.q, ICE);
        frame.q_rect = q_r;
        x += 150.0;
        let sweep_r = Rect::from_min_size(Pos2::new(x, cy - 11.0), Vec2::new(64.0, 22.0));
        chip(p, sweep_r, "SWEEP", self.sweep, GHOST_HI);
        frame.sweep_rect = sweep_r;

        // right side, packed right-to-left
        let mut rx = bar.right() - 14.0;
        // lamp + audit text
        let (lcol, ltext) = if self.audit_dirty {
            (EMBER, "audit…".to_string())
        } else if self.audit_unstable > 0 {
            (FAULT, format!("{} unstable · max |p| {:.4}", self.audit_unstable, self.audit_maxr))
        } else {
            (TRUTH, format!("17×17 stable · max |p| {:.4}", self.audit_maxr))
        };
        let galley_w = ltext.len() as f32 * 6.4;
        p.text(Pos2::new(rx, cy), Align2::RIGHT_CENTER, &ltext, FontId::monospace(10.5), lcol);
        rx -= galley_w + 12.0;
        p.circle_filled(Pos2::new(rx, cy), 5.0, lcol);
        rx -= 18.0;

        let aud_r = Rect::from_min_size(Pos2::new(rx - 86.0, cy - 11.0), Vec2::new(86.0, 22.0));
        chip(p, aud_r, "AUDITION", false, Color32::from_rgb(127, 225, 180));
        frame.audition_rect = aud_r;
        rx -= 94.0;
        let bake_r = Rect::from_min_size(Pos2::new(rx - 60.0, cy - 11.0), Vec2::new(60.0, 22.0));
        chip(p, bake_r, "BAKE", false, section_color(0));
        frame.bake_rect = bake_r;
        rx -= 68.0;
        let name_r = Rect::from_min_size(Pos2::new(rx - 150.0, cy - 11.0), Vec2::new(150.0, 22.0));
        p.rect_filled(name_r, 4.0, Color32::from_rgb(12, 12, 15));
        p.rect_stroke(name_r, 4.0, Stroke::new(1.0, if self.name_active { ICE } else { EDGE }));
        let shown = if self.body_name.is_empty() && !self.name_active {
            "body name".to_string()
        } else {
            format!("{}{}", self.body_name, if self.name_active { "_" } else { "" })
        };
        p.text(
            name_r.left_center() + Vec2::new(7.0, 0.0),
            Align2::LEFT_CENTER,
            shown,
            FontId::monospace(11.0),
            if self.body_name.is_empty() && !self.name_active { TEXT_DIM } else { TEXT },
        );
        frame.name_rect = name_r;
    }

    // ── bar 2: menus + quick readouts ─────────────────────────────────────────

    fn draw_bar2(&self, p: &egui::Painter, bar: Rect, frame: &mut Frame) {
        p.rect_filled(bar, 0.0, Color32::from_rgb(17, 18, 22));
        p.line_segment([bar.left_bottom(), bar.right_bottom()], Stroke::new(1.0, EDGE));
        let cy = bar.center().y;
        let mut x = bar.left() + 14.0;
        let menus: [(Menu, String); 5] = [
            (Menu::Seed, "SEED ▾".into()),
            (Menu::Corners, "CORNERS ▾".into()),
            (Menu::Quantize, format!("QUANTIZE: {} ▾", self.quantize.label())),
            (Menu::Scope, format!("EDIT: {} ▾", self.scope.label())),
            (Menu::View, "VIEW ▾".into()),
        ];
        for (menu, label) in menus {
            let w = label.len() as f32 * 6.6 + 18.0;
            let r = Rect::from_min_size(Pos2::new(x, cy - 10.0), Vec2::new(w, 20.0));
            chip(p, r, &label, self.open_menu == Some(menu), TEXT);
            frame.menu_chips.push(Hit { rect: r, value: menu });
            x += w + 8.0;
        }
        if self.quantize == Quantize::Tet {
            let label = format!("KEY: {} minor", NOTES[self.key_root]);
            p.text(Pos2::new(x + 4.0, cy), Align2::LEFT_CENTER, label, FontId::monospace(10.5), TEXT_DIM);
        }
        // right: morph/q numerics
        p.text(
            Pos2::new(bar.right() - 14.0, cy),
            Align2::RIGHT_CENTER,
            format!("morph {:.2}   Q {:.2}", self.morph, self.q),
            FontId::monospace(10.5),
            TEXT_DIM,
        );
    }

    // ── menu popup ────────────────────────────────────────────────────────────

    fn menu_entries(&self, menu: Menu) -> Vec<(String, Option<MenuAction>)> {
        match menu {
            Menu::Seed => {
                let mut v: Vec<(String, Option<MenuAction>)> = vec![
                    ("— template —".into(), None),
                    ("default template".into(), Some(MenuAction::SeedDefault)),
                    ("— type families —".into(), None),
                    ("low-pass sweep (resonant)".into(), Some(MenuAction::SeedLowpass)),
                    ("high-pass (zeros pinned low)".into(), Some(MenuAction::SeedHighpass)),
                    ("band-pass (guarded resonator)".into(), Some(MenuAction::SeedBandpass)),
                    ("notch comb / phase-shifter".into(), Some(MenuAction::SeedNotchComb)),
                    ("parametric boost (EQ)".into(), Some(MenuAction::SeedParametric)),
                    ("six resonant peaks".into(), Some(MenuAction::SeedPeaks)),
                    ("— vowel formants (measured) —".into(), None),
                ];
                for (i, (_, _, label)) in VOWEL_PAIRS.iter().enumerate() {
                    v.push(((*label).into(), Some(MenuAction::SeedVowel(i))));
                }
                v.push(("— physical series —".into(), None));
                for (i, f0) in TUBE_F0.iter().enumerate() {
                    v.push((format!("tube partials × {f0:.0} Hz"), Some(MenuAction::SeedTube(i))));
                }
                for (i, f0) in METAL_F0.iter().enumerate() {
                    v.push((format!("struck metal × {f0:.0} Hz"), Some(MenuAction::SeedMetal(i))));
                }
                v.push(("— fit —".into(), None));
                v.push(("LPC fit: drop a WAV on the window".into(), None));
                v.push(("(plain = low frame · Shift = high frame)".into(), None));
                v
            }
            Menu::Corners => vec![
                ("copy this corner → all corners".into(), Some(MenuAction::CopyCornerAll)),
                ("derive Q100 from Q0 (radius → rim)".into(), Some(MenuAction::DeriveQ)),
            ],
            Menu::Quantize => {
                let mut v: Vec<(String, Option<MenuAction>)> = [Quantize::Measured, Quantize::Tet, Quantize::Off]
                    .iter()
                    .map(|q| {
                        (
                            format!("{}{}", if *q == self.quantize { "● " } else { "  " }, q.label()),
                            Some(MenuAction::QuantSet(*q)),
                        )
                    })
                    .collect();
                if self.quantize == Quantize::Tet {
                    v.push(("— key —".into(), None));
                    for (i, n) in NOTES.iter().enumerate() {
                        v.push((
                            format!("{}{} minor", if i == self.key_root { "● " } else { "  " }, n),
                            Some(MenuAction::KeySet(i)),
                        ));
                    }
                }
                v
            }
            Menu::Scope => [EditScope::Corner, EditScope::Frame, EditScope::All]
                .iter()
                .map(|s| {
                    (
                        format!("{}{}", if *s == self.scope { "● " } else { "  " }, s.label()),
                        Some(MenuAction::ScopeSet(*s)),
                    )
                })
                .collect(),
            Menu::View => vec![
                (
                    format!("{}per-section curves", if self.show_sections { "● " } else { "  " }),
                    Some(MenuAction::ToggleSections),
                ),
                (
                    format!("{}analysis rail (maps + audit)", if self.show_rail { "● " } else { "  " }),
                    Some(MenuAction::ToggleRail),
                ),
            ],
        }
    }

    fn draw_menu(&self, p: &egui::Painter, frame: &mut Frame) {
        let Some(menu) = self.open_menu else { return };
        let Some(chip) = frame.menu_chips.iter().find(|h| h.value == menu) else { return };
        let entries = self.menu_entries(menu);
        let row_h = 20.0;
        let w = entries.iter().map(|(s, _)| s.len()).max().unwrap_or(10) as f32 * 6.6 + 26.0;
        let h = entries.len() as f32 * row_h + 10.0;
        let origin = Pos2::new(chip.rect.left(), chip.rect.bottom() + 4.0);
        let rect = Rect::from_min_size(origin, Vec2::new(w.max(180.0), h));
        p.rect_filled(rect.expand(2.0), 6.0, Color32::from_rgba_unmultiplied(0, 0, 0, 110));
        p.rect_filled(rect, 6.0, PANEL_HI);
        p.rect_stroke(rect, 6.0, Stroke::new(1.0, EDGE));
        let mut y = rect.top() + 5.0;
        for (label, action) in entries {
            let row = Rect::from_min_size(Pos2::new(rect.left(), y), Vec2::new(rect.width(), row_h));
            if let Some(a) = action {
                frame.menu_items.push(Hit { rect: row, value: a });
                p.text(
                    Pos2::new(rect.left() + 12.0, row.center().y),
                    Align2::LEFT_CENTER,
                    label,
                    FontId::monospace(11.0),
                    TEXT,
                );
            } else {
                p.text(
                    Pos2::new(rect.left() + 12.0, row.center().y),
                    Align2::LEFT_CENTER,
                    label,
                    FontId::monospace(9.5),
                    TEXT_DIM,
                );
            }
            y += row_h;
        }
        frame.menu_rect = Some(rect);
    }

    // ── the plot (Pro-Q style) ────────────────────────────────────────────────

    fn draw_plot(&self, p: &egui::Painter, rect: Rect, frame: &mut Frame) {
        p.rect_filled(rect, 6.0, Color32::from_rgb(16, 17, 21));
        p.rect_stroke(rect, 6.0, Stroke::new(1.0, EDGE));
        draw_grid(p, rect);

        if self.show_sections {
            for (i, section) in self.sections.iter().enumerate() {
                if !section.on {
                    continue;
                }
                let selected = i == self.selected_stage;
                let color = section_color(i);
                let alpha = if selected { 150 } else { 46 };
                let pts: Vec<Pos2> = (0..FREQ_BINS)
                    .map(|bin| {
                        Pos2::new(
                            rect.left() + bin as f32 / (FREQ_BINS - 1) as f32 * rect.width(),
                            y_for_db(rect, self.stage_db[i][bin]),
                        )
                    })
                    .collect();
                p.add(egui::Shape::line(
                    pts,
                    Stroke::new(if selected { 1.5 } else { 1.0 }, with_alpha(color, alpha)),
                ));
            }
        }

        // frame ghosts
        for (arr, color) in [(&self.ghost_low, GHOST_LO), (&self.ghost_high, GHOST_HI)] {
            let pts: Vec<Pos2> = (0..FREQ_BINS)
                .map(|i| {
                    Pos2::new(
                        rect.left() + i as f32 / (FREQ_BINS - 1) as f32 * rect.width(),
                        y_for_db(rect, arr[i]),
                    )
                })
                .collect();
            p.add(egui::Shape::dashed_line(&pts, Stroke::new(1.0, with_alpha(color, 80)), 5.0, 4.0));
        }

        // combined response: subtle gradient fill + one bright line
        let n = self.response.len();
        let mut mesh = egui::epaint::Mesh::default();
        let base = y_for_db(rect, DB_MIN);
        for i in 0..n {
            let x = rect.left() + i as f32 / (n - 1) as f32 * rect.width();
            let y = y_for_db(rect, self.response[i]);
            mesh.colored_vertex(Pos2::new(x, y), with_alpha(TRUTH, 24));
            mesh.colored_vertex(Pos2::new(x, base), with_alpha(TRUTH, 0));
        }
        for i in 0..(n - 1) as u32 {
            let a = i * 2;
            mesh.add_triangle(a, a + 1, a + 2);
            mesh.add_triangle(a + 1, a + 3, a + 2);
        }
        p.add(egui::Shape::mesh(mesh));
        let pts: Vec<Pos2> = (0..n)
            .map(|i| {
                Pos2::new(
                    rect.left() + i as f32 / (n - 1) as f32 * rect.width(),
                    y_for_db(rect, self.response[i]),
                )
            })
            .collect();
        p.add(egui::Shape::line(pts, Stroke::new(2.0, TRUTH)));

        // handles
        let corner = self.selected_corner.idx();
        for (i, section) in self.sections.iter().enumerate() {
            if !section.on {
                continue;
            }
            let selected = i == self.selected_stage;
            let color = section_color(i);
            let dimmed = if section.locked { with_alpha(color, 110) } else { color };
            let c = section.corners[corner];

            let pole = Pos2::new(
                x_for_freq(rect, c.pole_hz),
                y_for_db(rect, self.stage_db_at(i, c.pole_hz)),
            );
            frame.handles.push((pole, i, HandleKind::Pole));
            let r = if selected { 7.0 } else { 5.0 };
            p.circle_filled(pole, r, dimmed);
            if selected {
                p.circle_stroke(pole, r + 2.5, Stroke::new(1.4, TRUTH));
            }
            if section.locked {
                draw_padlock(p, pole + Vec2::new(9.0, -9.0), dimmed);
            }

            let zero = Pos2::new(
                x_for_freq(rect, c.zero_hz),
                y_for_db(rect, self.stage_db_at(i, c.zero_hz)),
            );
            frame.handles.push((zero, i, HandleKind::Zero));
            let rz = if selected { 6.0 } else { 4.5 };
            p.circle_stroke(zero, rz, Stroke::new(if selected { 2.0 } else { 1.4 }, dimmed));
            if selected {
                p.circle_stroke(zero, rz + 2.5, Stroke::new(1.0, with_alpha(TRUTH, 160)));
            }

            if selected {
                let label = format!(
                    "{} · r {:.4}   ◯ {} · r {:.3}   {:+.1} dB{}",
                    format_freq(c.pole_hz),
                    c.pole_r,
                    format_freq(c.zero_hz),
                    c.zero_r,
                    c.gain_db,
                    if section.locked { "   LOCKED" } else { "" },
                );
                p.text(
                    Pos2::new(
                        pole.x.clamp(rect.left() + 8.0, rect.right() - 300.0),
                        (pole.y - 22.0).max(rect.top() + 6.0),
                    ),
                    Align2::LEFT_BOTTOM,
                    label,
                    FontId::monospace(11.5),
                    TEXT,
                );
            }
        }
    }

    // ── analysis rail ────────────────────────────────────────────────────────

    fn draw_rail(&self, p: &egui::Painter, rail: Rect, frame: &mut Frame) {
        p.rect_filled(rail, 6.0, PANEL);
        p.rect_stroke(rail, 6.0, Stroke::new(1.0, EDGE));
        let pad = 10.0;
        let mut y = rail.top() + pad;
        p.text(
            Pos2::new(rail.left() + pad, y),
            Align2::LEFT_TOP,
            "SURFACE — max |H| dB (morph × Q)",
            FontId::monospace(9.0),
            TEXT_DIM,
        );
        y += 16.0;
        let map_size = rail.width() - pad * 2.0;
        let map = Rect::from_min_size(Pos2::new(rail.left() + pad, y), Vec2::splat(map_size));
        if let Some(tex) = &self.audit_texture {
            p.image(tex.id(), map, Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0)), Color32::WHITE);
        }
        p.rect_stroke(map, 2.0, Stroke::new(1.0, EDGE));
        for (pm, pq) in [(0.5, 0.5), (0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)] {
            let pos = Pos2::new(map.left() + pm * map.width(), map.bottom() - pq * map.height());
            p.circle_stroke(pos, 3.0, Stroke::new(1.0, with_alpha(TRUTH, 180)));
        }
        let ph = Pos2::new(map.left() + self.morph * map.width(), map.bottom() - self.q * map.height());
        p.circle_stroke(ph, 5.0, Stroke::new(1.6, ICE));
        frame.surface_rect = Some(map);
        y += map_size + 8.0;

        if !self.audit_dirty {
            let pin = |m: f32, q: f32| {
                let v = self.audit_at(m, q);
                if v.is_finite() { format!("{v:.1}") } else { "unstable".into() }
            };
            p.text(
                Pos2::new(rail.left() + pad, y),
                Align2::LEFT_TOP,
                format!("center m50 q50   {} dB", pin(0.5, 0.5)),
                FontId::monospace(10.0),
                TEXT,
            );
            y += 14.0;
            p.text(
                Pos2::new(rail.left() + pad, y),
                Align2::LEFT_TOP,
                format!("quarters  {} / {} / {} / {}", pin(0.25, 0.25), pin(0.75, 0.25), pin(0.25, 0.75), pin(0.75, 0.75)),
                FontId::monospace(10.0),
                TEXT_DIM,
            );
            y += 20.0;
        }

        p.text(
            Pos2::new(rail.left() + pad, y),
            Align2::LEFT_TOP,
            format!("MORPH SWEEP — |H(f, morph)| at Q {:.2}", self.q),
            FontId::monospace(9.0),
            TEXT_DIM,
        );
        y += 16.0;
        let sweep_h = (rail.width() - pad * 2.0) * HEAT_H as f32 / HEAT_W as f32;
        let smap = Rect::from_min_size(Pos2::new(rail.left() + pad, y), Vec2::new(rail.width() - pad * 2.0, sweep_h));
        if let Some(tex) = &self.heat_texture {
            p.image(tex.id(), smap, Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0)), Color32::WHITE);
        }
        p.rect_stroke(smap, 2.0, Stroke::new(1.0, EDGE));
        let ly = smap.bottom() - self.morph * smap.height();
        p.line_segment([Pos2::new(smap.left(), ly), Pos2::new(smap.right(), ly)], Stroke::new(1.2, ICE));
        frame.sweepmap_rect = Some(smap);
        y += sweep_h + 6.0;
        p.text(
            Pos2::new(rail.left() + pad, y),
            Align2::LEFT_TOP,
            "morph 0 at bottom · heat −12…+44 dB absolute",
            FontId::monospace(8.5),
            TEXT_DIM,
        );
    }

    // ── band strip + value row ───────────────────────────────────────────────

    fn draw_strip(&self, p: &egui::Painter, strip: Rect, frame: &mut Frame) {
        p.rect_filled(strip, 0.0, Color32::from_rgb(17, 18, 22));
        p.line_segment([strip.left_top(), strip.right_top()], Stroke::new(1.0, EDGE));
        let pad = 8.0;
        let gap = 6.0;
        let w = (strip.width() - pad * 2.0 - gap * (STAGES as f32 - 1.0)) / STAGES as f32;
        let corner = self.selected_corner.idx();
        for (i, section) in self.sections.iter().enumerate() {
            let x = strip.left() + pad + i as f32 * (w + gap);
            let cell = Rect::from_min_size(Pos2::new(x, strip.top() + 6.0), Vec2::new(w, strip.height() - 12.0));
            let selected = i == self.selected_stage;
            let color = section_color(i);
            p.rect_filled(cell, 5.0, if selected { PANEL_HI } else { Color32::from_rgb(23, 24, 29) });
            p.rect_stroke(cell, 5.0, Stroke::new(if selected { 1.4 } else { 1.0 }, if selected { color } else { EDGE }));
            p.rect_filled(
                Rect::from_min_max(cell.left_top() + Vec2::new(2.0, 2.0), Pos2::new(cell.right() - 2.0, cell.top() + 5.0)),
                3.0,
                if section.on { color } else { with_alpha(color, 60) },
            );
            let c = section.corners[corner];
            let title = if section.on {
                format!("S{}  {}", i + 1, format_freq(c.pole_hz))
            } else {
                format!("S{}  off", i + 1)
            };
            p.text(
                cell.left_top() + Vec2::new(8.0, 10.0),
                Align2::LEFT_TOP,
                title,
                FontId::monospace(11.5),
                if section.on { TEXT } else { TEXT_DIM },
            );
            p.text(
                cell.left_top() + Vec2::new(8.0, 27.0),
                Align2::LEFT_TOP,
                topology(section, corner),
                FontId::monospace(9.0),
                TEXT_DIM,
            );
            // lock badge (click target)
            let lock_r = Rect::from_min_size(cell.right_top() + Vec2::new(-24.0, 8.0), Vec2::new(18.0, 18.0));
            if section.locked {
                draw_padlock(p, lock_r.center(), color);
            } else {
                p.circle_stroke(lock_r.center(), 4.0, Stroke::new(1.0, with_alpha(TEXT_DIM, 110)));
            }
            frame.locks.push(Hit { rect: lock_r, value: i });
            frame.cards.push(Hit { rect: cell, value: i });
        }
    }

    fn draw_values(&self, p: &egui::Painter, row: Rect, frame: &mut Frame) {
        p.rect_filled(row, 0.0, Color32::from_rgb(15, 16, 20));
        let corner = self.selected_corner.idx();
        let s = &self.sections[self.selected_stage];
        let c = s.corners[corner];
        let cy = row.center().y;
        let mut x = row.left() + 14.0;
        let color = section_color(self.selected_stage);

        p.text(
            Pos2::new(x, cy),
            Align2::LEFT_CENTER,
            format!("S{}", self.selected_stage + 1),
            FontId::monospace(12.0),
            color,
        );
        x += 36.0;

        // on / lock toggles
        let on_r = Rect::from_min_size(Pos2::new(x, cy - 9.0), Vec2::new(40.0, 18.0));
        chip(p, on_r, if s.on { "ON" } else { "OFF" }, s.on, color);
        frame.on_rect = on_r;
        x += 48.0;
        let lock_r = Rect::from_min_size(Pos2::new(x, cy - 9.0), Vec2::new(52.0, 18.0));
        chip(p, lock_r, if s.locked { "LOCKED" } else { "LOCK" }, s.locked, EMBER);
        frame.lock_rect = lock_r;
        x += 64.0;

        let mut field = |label: &str, value: String, field_id: ValueField, x: &mut f32| {
            p.text(Pos2::new(*x, cy), Align2::LEFT_CENTER, label, FontId::monospace(9.5), TEXT_DIM);
            *x += label.len() as f32 * 6.0 + 6.0;
            let w = value.len() as f32 * 7.0 + 14.0;
            let r = Rect::from_min_size(Pos2::new(*x, cy - 9.0), Vec2::new(w, 18.0));
            p.rect_filled(r, 3.0, Color32::from_rgb(11, 11, 14));
            p.rect_stroke(r, 3.0, Stroke::new(1.0, EDGE));
            p.text(r.center(), Align2::CENTER_CENTER, value, FontId::monospace(11.0), TEXT);
            frame.value_fields.push(Hit { rect: r, value: field_id });
            *x += w + 12.0;
        };
        field("pole", format!("{:.0} Hz", c.pole_hz), ValueField::PoleHz, &mut x);
        field("r", format!("{:.4}", c.pole_r), ValueField::PoleR, &mut x);
        field("zero", format!("{:.0} Hz", c.zero_hz), ValueField::ZeroHz, &mut x);
        field("r", format!("{:.4}", c.zero_r), ValueField::ZeroR, &mut x);
        field("gain", format!("{:+.1} dB", c.gain_db), ValueField::GainDb, &mut x);

        p.text(
            Pos2::new(row.right() - 14.0, cy),
            Align2::RIGHT_CENTER,
            "drag values ↕ · wheel = pole r · Shift fine · Alt+drag = gain · L lock · E on/off",
            FontId::monospace(9.0),
            TEXT_DIM,
        );
    }

    fn draw_status(&self, p: &egui::Painter, bar: Rect) {
        p.rect_filled(bar, 0.0, PANEL);
        p.line_segment([bar.left_top(), bar.right_top()], Stroke::new(1.0, EDGE));
        p.text(
            Pos2::new(bar.left() + 14.0, bar.center().y),
            Align2::LEFT_CENTER,
            &self.status,
            FontId::monospace(10.5),
            TEXT_DIM,
        );
        p.text(
            Pos2::new(bar.right() - 14.0, bar.center().y),
            Align2::RIGHT_CENTER,
            "1-4 corners · Space sweep · Ctrl+Z undo · Ctrl+Shift+Z redo · drop WAV = LPC fit",
            FontId::monospace(10.0),
            TEXT_DIM,
        );
    }

    // ── interaction ───────────────────────────────────────────────────────────

    fn interact(&mut self, ctx: &egui::Context, resp: &egui::Response, lay: Layout, frame: Frame) {
        let pointer = resp.interact_pointer_pos();
        let hover = ctx.input(|i| i.pointer.hover_pos());
        let (shift, alt) = ctx.input(|i| (i.modifiers.shift, i.modifiers.alt));

        // clicks
        if resp.clicked() {
            if let Some(pos) = pointer {
                // open menu popup eats clicks first
                if let Some(menu_rect) = frame.menu_rect {
                    if menu_rect.contains(pos) {
                        for item in &frame.menu_items {
                            if item.rect.contains(pos) {
                                self.run_action(item.value);
                                break;
                            }
                        }
                        self.open_menu = None;
                        return;
                    }
                    self.open_menu = None;
                }
                for h in &frame.menu_chips {
                    if h.rect.contains(pos) {
                        self.open_menu = if self.open_menu == Some(h.value) { None } else { Some(h.value) };
                        self.menu_opened_at = Some(Instant::now());
                        return;
                    }
                }
                self.name_active = frame.name_rect.contains(pos);
                for h in &frame.corner_chips {
                    if h.rect.contains(pos) {
                        self.select_corner(h.value);
                        return;
                    }
                }
                if frame.sweep_rect.contains(pos) {
                    self.sweep = !self.sweep;
                    self.sweep_t0 = Instant::now();
                    return;
                }
                if frame.bake_rect.contains(pos) {
                    self.bake();
                    return;
                }
                if frame.audition_rect.contains(pos) {
                    self.publish_audition_slot();
                    return;
                }
                if frame.on_rect.contains(pos) {
                    self.push_undo();
                    let s = self.selected_stage;
                    self.sections[s].on = !self.sections[s].on;
                    self.rebuild_body();
                    return;
                }
                if frame.lock_rect.contains(pos) {
                    let s = self.selected_stage;
                    self.sections[s].locked = !self.sections[s].locked;
                    return;
                }
                for h in &frame.locks {
                    if h.rect.contains(pos) {
                        self.sections[h.value].locked = !self.sections[h.value].locked;
                        self.status = format!(
                            "S{} {}",
                            h.value + 1,
                            if self.sections[h.value].locked { "locked" } else { "unlocked" }
                        );
                        return;
                    }
                }
                for h in &frame.cards {
                    if h.rect.contains(pos) {
                        self.selected_stage = h.value;
                        return;
                    }
                }
                if lay.plot.contains(pos) {
                    if let Some((stage, _)) = nearest_handle(pos, &frame.handles) {
                        self.selected_stage = stage;
                    }
                }
            }
        }

        // double click: card on/off
        if resp.double_clicked() {
            if let Some(pos) = pointer {
                for h in &frame.cards {
                    if h.rect.contains(pos) {
                        self.push_undo();
                        self.sections[h.value].on = !self.sections[h.value].on;
                        self.rebuild_body();
                        return;
                    }
                }
            }
        }

        // drags
        if resp.drag_started() {
            if let Some(pos) = pointer {
                if frame.menu_rect.map_or(false, |r| r.contains(pos)) {
                    // no drags inside menus
                } else if frame.morph_rect.contains(pos) {
                    self.sweep = false;
                    self.drag = Some(Drag::Morph);
                } else if frame.q_rect.contains(pos) {
                    self.drag = Some(Drag::Q);
                } else if frame.surface_rect.map_or(false, |r| r.contains(pos)) {
                    self.sweep = false;
                    self.drag = Some(Drag::SurfaceMap);
                } else if frame.sweepmap_rect.map_or(false, |r| r.contains(pos)) {
                    self.sweep = false;
                    self.drag = Some(Drag::SweepMap);
                } else {
                    let mut grabbed = false;
                    for h in &frame.value_fields {
                        if h.rect.contains(pos) {
                            let s = self.selected_stage;
                            if self.sections[s].locked {
                                self.status = format!("S{} is locked — unlock to edit", s + 1);
                            } else {
                                self.push_undo();
                                self.drag = Some(Drag::Value {
                                    field: h.value,
                                    start_y: pos.y,
                                    start: self.sections[s].corners,
                                });
                            }
                            grabbed = true;
                            break;
                        }
                    }
                    if !grabbed && lay.plot.contains(pos) {
                        if let Some((stage, kind)) = nearest_handle(pos, &frame.handles) {
                            self.selected_stage = stage;
                            if self.sections[stage].locked {
                                self.status = format!("S{} is locked — unlock to drag (L)", stage + 1);
                            } else {
                                self.push_undo();
                                self.drag = Some(Drag::Handle {
                                    stage,
                                    kind,
                                    gain: alt,
                                    start_pos: pos,
                                    start: self.sections[stage].corners,
                                });
                            }
                        }
                    }
                }
            }
        }
        if resp.dragged() {
            if let (Some(pos), Some(drag)) = (pointer, self.drag) {
                match drag {
                    Drag::Morph => {
                        self.morph = ((pos.x - frame.morph_rect.left()) / frame.morph_rect.width()).clamp(0.0, 1.0);
                        self.recompute_response();
                    }
                    Drag::Q => {
                        self.q = ((pos.x - frame.q_rect.left()) / frame.q_rect.width()).clamp(0.0, 1.0);
                        self.recompute_response();
                        self.heat_dirty = true;
                    }
                    Drag::SurfaceMap => {
                        if let Some(map) = frame.surface_rect {
                            self.morph = ((pos.x - map.left()) / map.width()).clamp(0.0, 1.0);
                            let new_q = (1.0 - (pos.y - map.top()) / map.height()).clamp(0.0, 1.0);
                            if (new_q - self.q).abs() > 0.002 {
                                self.q = new_q;
                                self.heat_dirty = true;
                            }
                            self.recompute_response();
                        }
                    }
                    Drag::SweepMap => {
                        if let Some(map) = frame.sweepmap_rect {
                            self.morph = (1.0 - (pos.y - map.top()) / map.height()).clamp(0.0, 1.0);
                            self.recompute_response();
                        }
                    }
                    Drag::Value { field, start_y, start } => {
                        self.apply_value_drag(field, start_y - pos.y, start, shift);
                    }
                    Drag::Handle { stage, kind, gain, start_pos, start } => {
                        self.apply_handle_drag(stage, kind, gain, start_pos, pos, start, shift);
                    }
                }
            }
        }
        if resp.drag_stopped() {
            self.drag = None;
        }

        // wheel over plot: selected section pole radius
        if let Some(pos) = hover {
            if lay.plot.contains(pos) && self.open_menu.is_none() {
                let scroll = ctx.input(|i| {
                    let raw = i.raw_scroll_delta.y;
                    if raw.abs() > 0.0 { raw } else { i.smooth_scroll_delta.y }
                });
                if scroll.abs() >= 0.5 {
                    let stage = self.selected_stage;
                    if self.sections[stage].locked {
                        self.status = format!("S{} is locked", stage + 1);
                    } else {
                        let steps = (scroll / 120.0).clamp(-6.0, 6.0);
                        let step = if shift { 0.0008 } else { 0.0035 };
                        self.push_undo();
                        for ci in self.selected_corner.scope_corners(self.scope) {
                            let c = &mut self.sections[stage].corners[ci];
                            c.pole_r = (c.pole_r + steps * step).clamp(RP_MIN, RP_MAX);
                        }
                        self.rebuild_body();
                    }
                }
            }
        }
    }

    fn apply_handle_drag(
        &mut self,
        stage: usize,
        kind: HandleKind,
        gain: bool,
        start_pos: Pos2,
        pos: Pos2,
        start: [CornerStage; CORNERS],
        shift: bool,
    ) {
        let dx = pos.x - start_pos.x;
        let dy = pos.y - start_pos.y;
        let fine = if shift { 0.25 } else { 1.0 };
        let freq_ratio = 2.0_f32.powf(dx * fine / 240.0);
        for ci in self.selected_corner.scope_corners(self.scope) {
            let s = start[ci];
            let snapped_pole = self.snap((s.pole_hz * freq_ratio).clamp(F_MIN, F_MAX), shift);
            let snapped_zero = self.snap((s.zero_hz * freq_ratio).clamp(F_MIN, F_MAX), shift);
            let c = &mut self.sections[stage].corners[ci];
            match kind {
                HandleKind::Pole => {
                    c.pole_hz = snapped_pole;
                    if gain {
                        c.gain_db = (s.gain_db - dy * fine / 8.0).clamp(GAIN_DB_MIN, GAIN_DB_MAX);
                    } else {
                        c.pole_r = (1.0 - (1.0 - s.pole_r) * 2.0_f32.powf(dy * fine / 90.0)).clamp(RP_MIN, RP_MAX);
                    }
                }
                HandleKind::Zero => {
                    c.zero_hz = snapped_zero;
                    if gain {
                        c.gain_db = (s.gain_db - dy * fine / 8.0).clamp(GAIN_DB_MIN, GAIN_DB_MAX);
                    } else {
                        c.zero_r = (1.0 - (1.0 - s.zero_r) * 2.0_f32.powf(-dy * fine / 90.0)).clamp(0.0, RZ_MAX);
                    }
                }
            }
        }
        self.rebuild_body();
    }

    fn apply_value_drag(&mut self, field: ValueField, dy: f32, start: [CornerStage; CORNERS], shift: bool) {
        let fine = if shift { 0.2 } else { 1.0 };
        let stage = self.selected_stage;
        for ci in self.selected_corner.scope_corners(self.scope) {
            let s = start[ci];
            let c = &mut self.sections[stage].corners[ci];
            match field {
                ValueField::PoleHz => {
                    c.pole_hz = (s.pole_hz * 2.0_f32.powf(dy * fine / 96.0)).clamp(F_MIN, F_MAX)
                }
                ValueField::PoleR => {
                    c.pole_r = (1.0 - (1.0 - s.pole_r) * 2.0_f32.powf(-dy * fine / 60.0)).clamp(RP_MIN, RP_MAX)
                }
                ValueField::ZeroHz => {
                    c.zero_hz = (s.zero_hz * 2.0_f32.powf(dy * fine / 96.0)).clamp(F_MIN, F_MAX)
                }
                ValueField::ZeroR => {
                    c.zero_r = (1.0 - (1.0 - s.zero_r) * 2.0_f32.powf(-dy * fine / 60.0)).clamp(0.0, RZ_MAX)
                }
                ValueField::GainDb => {
                    c.gain_db = (s.gain_db + dy * fine / 6.0).clamp(GAIN_DB_MIN, GAIN_DB_MAX)
                }
            }
        }
        self.rebuild_body();
    }
}

// ── painted primitives ───────────────────────────────────────────────────────

fn chip(p: &egui::Painter, rect: Rect, text: &str, active: bool, color: Color32) {
    let fill = if active { with_alpha(color, 42) } else { Color32::from_rgb(24, 24, 30) };
    let stroke = if active { Stroke::new(1.3, color) } else { Stroke::new(1.0, EDGE) };
    p.rect_filled(rect, 5.0, fill);
    p.rect_stroke(rect, 5.0, stroke);
    p.text(
        rect.center(),
        Align2::CENTER_CENTER,
        text,
        FontId::monospace(10.5),
        if active { color } else { Color32::from_rgb(168, 162, 154) },
    );
}

fn slider_chip(p: &egui::Painter, rect: Rect, label: &str, value: f32, color: Color32) {
    p.rect_filled(rect, 5.0, Color32::from_rgb(24, 24, 30));
    p.rect_stroke(rect, 5.0, Stroke::new(1.0, EDGE));
    let fill = Rect::from_min_max(rect.left_top(), Pos2::new(rect.left() + rect.width() * value, rect.bottom()));
    p.rect_filled(fill.shrink(2.0), 4.0, with_alpha(color, 42));
    p.circle_filled(Pos2::new(rect.left() + rect.width() * value, rect.center().y), 4.5, color);
    p.text(
        rect.left_center() + Vec2::new(7.0, 0.0),
        Align2::LEFT_CENTER,
        label,
        FontId::monospace(10.0),
        Color32::from_rgb(168, 162, 154),
    );
    p.text(
        rect.right_center() + Vec2::new(-7.0, 0.0),
        Align2::RIGHT_CENTER,
        format!("{value:.2}"),
        FontId::monospace(10.0),
        color,
    );
}

fn draw_padlock(p: &egui::Painter, center: Pos2, color: Color32) {
    let body = Rect::from_center_size(center + Vec2::new(0.0, 1.5), Vec2::new(7.0, 5.5));
    p.rect_filled(body, 1.0, color);
    // shackle: small arc approximated by a circle stroke clipped above the body
    p.circle_stroke(center + Vec2::new(0.0, -2.5), 2.6, Stroke::new(1.2, color));
}

fn draw_grid(p: &egui::Painter, rect: Rect) {
    let major = Color32::from_rgba_unmultiplied(110, 105, 118, 46);
    let minor = Color32::from_rgba_unmultiplied(110, 105, 118, 20);
    for f in [50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0] {
        let x = x_for_freq(rect, f);
        p.line_segment([Pos2::new(x, rect.top()), Pos2::new(x, rect.bottom())], Stroke::new(1.0, major));
        let label = if f >= 1000.0 { format!("{}k", (f / 1000.0) as i32) } else { format!("{}", f as i32) };
        p.text(
            Pos2::new(x + 3.0, rect.bottom() - 4.0),
            Align2::LEFT_BOTTOM,
            label,
            FontId::monospace(9.5),
            Color32::from_rgb(110, 106, 116),
        );
    }
    for f in [75.0, 150.0, 300.0, 750.0, 1500.0, 3000.0, 7500.0, 14000.0] {
        let x = x_for_freq(rect, f);
        p.line_segment([Pos2::new(x, rect.top()), Pos2::new(x, rect.bottom())], Stroke::new(1.0, minor));
    }
    for db in [-24.0, -12.0, 0.0, 12.0, 24.0, 36.0] {
        let y = y_for_db(rect, db);
        let col = if db == 0.0 { Color32::from_rgba_unmultiplied(110, 105, 118, 70) } else { minor };
        p.line_segment([Pos2::new(rect.left(), y), Pos2::new(rect.right(), y)], Stroke::new(1.0, col));
        p.text(
            Pos2::new(rect.right() - 4.0, y - 2.0),
            Align2::RIGHT_BOTTOM,
            format!("{db:+.0}"),
            FontId::monospace(9.5),
            Color32::from_rgb(110, 106, 116),
        );
    }
}

fn nearest_handle(pos: Pos2, hits: &[(Pos2, usize, HandleKind)]) -> Option<(usize, HandleKind)> {
    let mut best = None;
    let mut bd = 18.0;
    for (hp, stage, kind) in hits {
        let d = hp.distance(pos);
        if d < bd {
            bd = d;
            best = Some((*stage, *kind));
        }
    }
    best
}

// ── DSP (mirrors trench-core packed interpolation; bytes from pack_body) ─────

fn live_biquads(words: &[[[u16; 5]; STAGES]; CORNERS], morph: f32, q: f32) -> [[f32; 5]; STAGES] {
    let mut out = [[0.0; 5]; STAGES];
    for stage in 0..STAGES {
        let mut w = [0u16; 5];
        for k in 0..5 {
            let low = lerp_word(words[0][stage][k], words[1][stage][k], morph);
            let high = lerp_word(words[2][stage][k], words[3][stage][k], morph);
            w[k] = lerp_word(low, high, q);
        }
        out[stage] = words_to_biquad(w);
    }
    out
}

fn lerp_word(a: u16, b: u16, t: f32) -> u16 {
    let product = (b as i32 - a as i32) as f32 * t;
    let trunc = product.trunc() as i32;
    let delta = (trunc + 0x8000).rem_euclid(0x1_0000) - 0x8000;
    ((a as i32 + delta) & 0xffff) as u16
}

fn words_to_biquad(w: [u16; 5]) -> [f32; 5] {
    let d = w.map(|x| trench_core::minifloat::decode(x) as f32);
    let c0 = 4.0 * d[0] + d[1];
    let c1 = d[1];
    let c2 = 4.0 * d[2] + d[3];
    let c3 = d[3];
    let c4 = 4.0 * d[4];
    [c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3]
}

fn cascade_db(stages: &[[f32; 5]; STAGES], freq: f32) -> f32 {
    stages.iter().map(|bq| biquad_db(*bq, freq)).sum()
}

fn biquad_db(b: [f32; 5], freq: f32) -> f32 {
    let w = TAU32 * freq / SR;
    let c1 = w.cos();
    let s1 = w.sin();
    let c2 = (2.0 * w).cos();
    let s2 = (2.0 * w).sin();
    let nr = b[0] + b[1] * c1 + b[2] * c2;
    let ni = -(b[1] * s1 + b[2] * s2);
    let dr = 1.0 + b[3] * c1 + b[4] * c2;
    let di = -(b[3] * s1 + b[4] * s2);
    20.0 * (nr.hypot(ni) / dr.hypot(di).max(1e-9)).max(1e-9).log10()
}

fn stages_max_pole_radius(stages: &[[f32; 5]; STAGES]) -> f32 {
    let mut worst = 0.0f32;
    for bq in stages {
        let (a1, a2) = (bq[3], bq[4]);
        let disc = a1 * a1 - 4.0 * a2;
        let r = if disc < 0.0 {
            a2.max(0.0).sqrt()
        } else {
            let sq = disc.sqrt();
            ((-a1 + sq) / 2.0).abs().max(((-a1 - sq) / 2.0).abs())
        };
        if !r.is_finite() {
            return f32::INFINITY;
        }
        worst = worst.max(r);
    }
    worst
}

fn freq_at(i: usize, n: usize) -> f32 {
    F_MIN * (F_MAX / F_MIN).powf(i as f32 / (n - 1) as f32)
}

fn db_to_lin(db: f32) -> f32 {
    10.0_f32.powf(db / 20.0)
}

fn format_freq(freq: f32) -> String {
    if freq >= 1000.0 {
        format!("{:.1}k", freq / 1000.0)
    } else {
        format!("{:.0} Hz", freq)
    }
}

fn x_for_freq(rect: Rect, freq: f32) -> f32 {
    let t = (freq / F_MIN).log2() / (F_MAX / F_MIN).log2();
    rect.left() + t.clamp(0.0, 1.0) * rect.width()
}

fn y_for_db(rect: Rect, db: f32) -> f32 {
    let t = ((db.clamp(DB_MIN, DB_MAX) - DB_MIN) / (DB_MAX - DB_MIN)).clamp(0.0, 1.0);
    rect.bottom() - t * rect.height()
}

/// Absolute heat ramp: ≤−12 dB → background · 0 → violet · +20 → rust ·
/// +33 → amber · +44 → pale; holds hot above. Never autoscaled.
fn heat_color(db: f32) -> Color32 {
    let stops = [
        (-12.0, [11.0, 11.0, 13.0]),
        (0.0, [52.0, 27.0, 77.0]),
        (20.0, [138.0, 61.0, 42.0]),
        (33.0, [199.0, 116.0, 31.0]),
        (44.0, [246.0, 232.0, 200.0]),
    ];
    if db <= stops[0].0 {
        return Color32::from_rgb(stops[0].1[0] as u8, stops[0].1[1] as u8, stops[0].1[2] as u8);
    }
    for i in 1..stops.len() {
        if db <= stops[i].0 {
            let (d0, c0) = stops[i - 1];
            let (d1, c1) = stops[i];
            let t = ((db - d0) / (d1 - d0)).clamp(0.0, 1.0);
            return Color32::from_rgb(
                (c0[0] + (c1[0] - c0[0]) * t) as u8,
                (c0[1] + (c1[1] - c0[1]) * t) as u8,
                (c0[2] + (c1[2] - c0[2]) * t) as u8,
            );
        }
    }
    Color32::from_rgb(250, 245, 235)
}

// ── minimal WAV reader (PCM 16/24/32 + float32, first channel) ────────────────

fn parse_wav(bytes: &[u8]) -> Option<(Vec<f64>, f64)> {
    if bytes.len() < 44 || &bytes[0..4] != b"RIFF" || &bytes[8..12] != b"WAVE" {
        return None;
    }
    let mut pos = 12;
    let mut format = 0u16;
    let mut channels = 1u16;
    let mut sample_rate = 0u32;
    let mut bits = 0u16;
    let mut data: Option<&[u8]> = None;
    while pos + 8 <= bytes.len() {
        let id = &bytes[pos..pos + 4];
        let size = u32::from_le_bytes(bytes[pos + 4..pos + 8].try_into().ok()?) as usize;
        let body = bytes.get(pos + 8..pos + 8 + size)?;
        match id {
            b"fmt " if size >= 16 => {
                format = u16::from_le_bytes([body[0], body[1]]);
                channels = u16::from_le_bytes([body[2], body[3]]).max(1);
                sample_rate = u32::from_le_bytes([body[4], body[5], body[6], body[7]]);
                bits = u16::from_le_bytes([body[14], body[15]]);
            }
            b"data" => data = Some(body),
            _ => {}
        }
        pos += 8 + size + (size & 1);
    }
    let data = data?;
    if sample_rate == 0 {
        return None;
    }
    let ch = channels as usize;
    let mut out = Vec::new();
    match (format, bits) {
        (1, 16) => {
            for frame in data.chunks_exact(2 * ch) {
                out.push(i16::from_le_bytes([frame[0], frame[1]]) as f64 / 32768.0);
            }
        }
        (1, 24) => {
            for frame in data.chunks_exact(3 * ch) {
                let v = ((frame[2] as i32) << 24 | (frame[1] as i32) << 16 | (frame[0] as i32) << 8) >> 8;
                out.push(v as f64 / 8_388_608.0);
            }
        }
        (1, 32) => {
            for frame in data.chunks_exact(4 * ch) {
                out.push(i32::from_le_bytes([frame[0], frame[1], frame[2], frame[3]]) as f64 / 2_147_483_648.0);
            }
        }
        (3, 32) => {
            for frame in data.chunks_exact(4 * ch) {
                out.push(f32::from_le_bytes([frame[0], frame[1], frame[2], frame[3]]) as f64);
            }
        }
        _ => return None,
    }
    if out.is_empty() {
        return None;
    }
    Some((out, sample_rate as f64))
}
