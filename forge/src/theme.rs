//! The single visual decision: a dark instrument scope. Near-black field, warm
//! off-white ink, a phosphor-green TARGET (the sound you gave it) read against an
//! amber FIT (what the six actors built), six actor colours. Reads like lab gear
//! on camera. No paper, no chrome, no white.

use eframe::egui;
use egui::{Color32, FontFamily, FontId, Stroke, TextStyle};

// ── Palette ─────────────────────────────────────────────────────────────────
// Dark scope. The field is near-black; "ink" is the light foreground drawn on
// it. One green (the given sound), one amber (the fit), six actor accents.

/// The field — near-black, faintly warm. Never pure black, never white.
pub const PAPER: Color32 = Color32::from_rgb(14, 16, 15);
/// A lifted black, for recessed zones (rail track, inspect panels).
pub const PAPER_DIM: Color32 = Color32::from_rgb(23, 26, 24);
/// Lighter still — pressed / disabled / button fills.
pub const PAPER_LOW: Color32 = Color32::from_rgb(36, 40, 37);

/// Ink — the light foreground (text, structure) on the dark field.
pub const INK: Color32 = Color32::from_rgb(216, 221, 212);
/// Muted — secondary labels.
pub const INK_SOFT: Color32 = Color32::from_rgb(130, 140, 130);
/// Faint hairlines — the measured-display grid on dark.
pub const INK_FAINT: Color32 = Color32::from_rgb(58, 65, 60);

/// Vermillion — the rail, transport accents, ticks. Pops on the dark field.
pub const VERM: Color32 = Color32::from_rgb(228, 78, 46);
/// Vermillion pressed / shadowed.
pub const VERM_DEEP: Color32 = Color32::from_rgb(152, 46, 28);

/// Caution / Review — amber.
pub const CAUTION: Color32 = Color32::from_rgb(216, 160, 60);

/// TARGET — the given sound's spectral silhouette, phosphor green. The thing the
/// fit is chasing; drawn bold so the match (or the gap) reads at a glance.
pub const TARGET: Color32 = Color32::from_rgb(74, 222, 128);
/// FIT — the cascade's response, amber. What the six actors actually built.
pub const FIT: Color32 = Color32::from_rgb(232, 150, 58);

/// The six actors, low → high. Named on the surface, never "stages".
pub const ACTOR_NAMES: [&str; 6] = ["ROOT", "BODY", "MOUTH", "SCAR", "EDGE", "RIP"];
pub const ACTORS: [Color32; 6] = [
    Color32::from_rgb(86, 156, 232),  // ROOT  — blue
    Color32::from_rgb(58, 200, 184),  // BODY  — teal
    Color32::from_rgb(150, 120, 232), // MOUTH — violet
    Color32::from_rgb(224, 196, 76),  // SCAR  — gold
    Color32::from_rgb(240, 110, 70),  // EDGE  — coral
    Color32::from_rgb(228, 96, 168),  // RIP   — magenta
];

pub fn with_alpha(c: Color32, a: u8) -> Color32 {
    Color32::from_rgba_unmultiplied(c.r(), c.g(), c.b(), a)
}

// ── Style ───────────────────────────────────────────────────────────────────

/// Bundle real typefaces. Bahnschrift (DIN — industrial/instrument register) for
/// display, Cascadia Mono for numerics. Falls back to egui defaults if a face
/// isn't present, so the app still runs anywhere.
fn install_fonts(ctx: &egui::Context) {
    let mut fonts = egui::FontDefinitions::default();
    let read =
        |paths: &[&str]| -> Option<Vec<u8>> { paths.iter().find_map(|p| std::fs::read(p).ok()) };

    if let Some(bytes) = read(&[
        "C:/Windows/Fonts/bahnschrift.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]) {
        fonts
            .font_data
            .insert("display".to_owned(), egui::FontData::from_owned(bytes));
        fonts
            .families
            .entry(FontFamily::Proportional)
            .or_default()
            .insert(0, "display".to_owned());
    }
    if let Some(bytes) = read(&[
        "C:/Windows/Fonts/CascadiaMono.ttf",
        "C:/Windows/Fonts/consola.ttf",
    ]) {
        fonts
            .font_data
            .insert("mono".to_owned(), egui::FontData::from_owned(bytes));
        fonts
            .families
            .entry(FontFamily::Monospace)
            .or_default()
            .insert(0, "mono".to_owned());
    }
    ctx.set_fonts(fonts);
}

pub fn install(ctx: &egui::Context) {
    install_fonts(ctx);

    let mut v = egui::Visuals::dark();
    v.panel_fill = PAPER;
    v.window_fill = PAPER_DIM;
    v.window_rounding = egui::Rounding::same(2.0);
    v.window_shadow = egui::Shadow::NONE;
    v.window_stroke = Stroke::new(1.0, INK_FAINT);
    v.extreme_bg_color = PAPER;
    v.override_text_color = Some(INK);
    v.selection.bg_fill = with_alpha(VERM, 70);
    v.selection.stroke = Stroke::new(1.0, VERM);

    let w = &mut v.widgets;
    w.noninteractive.bg_fill = PAPER;
    w.noninteractive.bg_stroke = Stroke::NONE;
    w.noninteractive.fg_stroke = Stroke::new(1.0, INK_SOFT);
    w.inactive.bg_fill = PAPER_LOW;
    w.inactive.weak_bg_fill = PAPER_LOW;
    w.inactive.bg_stroke = Stroke::NONE;
    w.inactive.fg_stroke = Stroke::new(1.0, INK);
    w.inactive.rounding = egui::Rounding::same(2.0);
    w.hovered.bg_fill = PAPER_DIM;
    w.hovered.weak_bg_fill = PAPER_DIM;
    w.hovered.bg_stroke = Stroke::new(1.0, INK_SOFT);
    w.hovered.fg_stroke = Stroke::new(1.0, INK);
    w.hovered.rounding = egui::Rounding::same(2.0);
    w.active.bg_fill = VERM;
    w.active.weak_bg_fill = VERM;
    w.active.bg_stroke = Stroke::NONE;
    w.active.fg_stroke = Stroke::new(1.0, PAPER);
    w.active.rounding = egui::Rounding::same(2.0);
    ctx.set_visuals(v);

    let mut style = (*ctx.style()).clone();
    style.text_styles.insert(
        TextStyle::Heading,
        FontId::new(22.0, FontFamily::Proportional),
    );
    style
        .text_styles
        .insert(TextStyle::Body, FontId::new(13.0, FontFamily::Proportional));
    style.text_styles.insert(
        TextStyle::Button,
        FontId::new(13.0, FontFamily::Proportional),
    );
    style.text_styles.insert(
        TextStyle::Monospace,
        FontId::new(11.0, FontFamily::Monospace),
    );
    style.spacing.item_spacing = egui::vec2(8.0, 8.0);
    style.spacing.button_padding = egui::vec2(14.0, 8.0);
    ctx.set_style(style);
}

// ── Inspect-only helpers (the technical back room) ──────────────────────────

pub fn panel_frame() -> egui::Frame {
    egui::Frame::none()
        .fill(PAPER_DIM)
        .stroke(Stroke::new(1.0, INK_FAINT))
        .rounding(3.0)
        .inner_margin(egui::Margin::same(12.0))
}
