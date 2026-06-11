// The visual language: the physical_mountains mini-plot style
// (dev/tmp/physical_mountains/*.png) — thin bright curves on a near-black
// green-tinted ground, monospace, terse data lines, zero chrome. Minimal,
// clean, striking; good enough to record short-form content over.
//
// Corner identity (matches the reference sheets):
//   C0  M0 Q0    amber      C1  M100 Q0    green
//   C2  M0 Q100  teal       C3  M100 Q100  red
// Markers where they appear (DETAILS only): yellow = poles, red = zeros.

use eframe::egui::Color32;

// ground
pub const BG: Color32 = Color32::from_rgb(9, 13, 12);
pub const PANEL: Color32 = Color32::from_rgb(14, 19, 17);
pub const PANEL_HI: Color32 = Color32::from_rgb(21, 28, 25);
pub const EDGE: Color32 = Color32::from_rgb(44, 56, 50);

// type
pub const TEXT: Color32 = Color32::from_rgb(198, 206, 200);
pub const TEXT_DIM: Color32 = Color32::from_rgb(116, 128, 120);

// the hero curve stays warm white — everything else stays out of its way
pub const TRUTH: Color32 = Color32::from_rgb(242, 239, 232);

// accents
pub const ICE: Color32 = Color32::from_rgb(47, 200, 204); // cyan — info/links
pub const EMBER: Color32 = Color32::from_rgb(230, 161, 59); // amber — working/checking
pub const FAULT: Color32 = Color32::from_rgb(224, 82, 60); // red — unstable/refused
#[allow(dead_code)] // wired in with the Peak/Shelf front surface
pub const GOOD: Color32 = Color32::from_rgb(86, 237, 112); // green — stable/pass

// corner / frame identity
#[allow(dead_code)] // wired in with the Peak/Shelf front surface
pub const CORNER: [Color32; 4] = [
    Color32::from_rgb(230, 161, 59), // C0 amber
    Color32::from_rgb(86, 237, 112), // C1 green
    Color32::from_rgb(52, 168, 158), // C2 teal
    Color32::from_rgb(217, 84, 62),  // C3 red
];

// frame ghosts on the hero plot follow the corner identity:
// low frame = amber, high frame = green
pub const GHOST_LO: Color32 = CORNER[0];
pub const GHOST_HI: Color32 = CORNER[1];

// pole / zero markers (DETAILS surfaces only)
#[allow(dead_code)] // wired in with the DETAILS drawer
pub const POLE_MARK: Color32 = Color32::from_rgb(255, 221, 118); // yellow
#[allow(dead_code)]
pub const ZERO_MARK: Color32 = FAULT;

pub fn with_alpha(c: Color32, a: u8) -> Color32 {
    Color32::from_rgba_unmultiplied(c.r(), c.g(), c.b(), a)
}
