use eframe::egui::{self, Color32, FontFamily, FontId};

pub const VOID: Color32 = Color32::from_rgb(0x05, 0x05, 0x05);
pub const FIELD: Color32 = Color32::from_rgb(0x14, 0x18, 0x21);
pub const SCREEN: Color32 = Color32::from_rgb(0x08, 0x0b, 0x0e);
pub const WELL: Color32 = Color32::from_rgb(0x0d, 0x13, 0x18);
pub const HAIRLINE: Color32 = Color32::from_rgb(0x2f, 0x5a, 0x6e);
pub const BONE: Color32 = Color32::from_rgb(0xe5, 0xdc, 0xcb);
pub const BONE_DIM: Color32 = Color32::from_rgb(0x9a, 0xa0, 0x96);
pub const BONE_FAINT: Color32 = Color32::from_rgb(0x5a, 0x60, 0x5c);
pub const PHOSPHOR: Color32 = Color32::from_rgb(0x9a, 0xef, 0x5a);
pub const PHOSPHOR_DIM: Color32 = Color32::from_rgb(0x5d, 0xa8, 0x38);
pub const CYAN: Color32 = Color32::from_rgb(0x8f, 0xc8, 0xff);
pub const AMBER: Color32 = Color32::from_rgb(0xff, 0xa8, 0x38);
pub const CLIP: Color32 = Color32::from_rgb(0xff, 0x6a, 0x3a);
pub const GRID: Color32 = Color32::from_rgb(0x22, 0x35, 0x3f);

pub const CUBE_NAMES: [&str; 8] = [
    "MELLOW", "OPEN", "THROAT", "VOWEL", "GROWL", "ROAR", "HOWL", "SCREAM",
];
pub const CUBE_COLORS: [Color32; 8] = [
    Color32::from_rgb(0xc9, 0x8a, 0x4a),
    Color32::from_rgb(0xff, 0xd2, 0x4a),
    Color32::from_rgb(0x5a, 0xd1, 0xff),
    Color32::from_rgb(0x9a, 0xef, 0x5a),
    Color32::from_rgb(0xff, 0x8a, 0x2a),
    Color32::from_rgb(0xff, 0x5a, 0x5a),
    Color32::from_rgb(0xc0, 0x6c, 0xff),
    Color32::from_rgb(0xff, 0x30, 0x30),
];

pub fn alpha(c: Color32, a: u8) -> Color32 {
    Color32::from_rgba_unmultiplied(c.r(), c.g(), c.b(), a)
}

pub fn mono(size: f32) -> FontId {
    FontId::new(size, FontFamily::Monospace)
}

pub fn title(size: f32) -> FontId {
    FontId::new(size, FontFamily::Proportional)
}

pub fn install(ctx: &egui::Context) {
    let mut fonts = egui::FontDefinitions::default();
    let read =
        |paths: &[&str]| -> Option<Vec<u8>> { paths.iter().find_map(|p| std::fs::read(p).ok()) };
    if let Some(bytes) = read(&[
        "C:/Windows/Fonts/bahnschrift.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]) {
        fonts
            .font_data
            .insert("display".into(), egui::FontData::from_owned(bytes));
        fonts
            .families
            .entry(FontFamily::Proportional)
            .or_default()
            .insert(0, "display".into());
    }
    if let Some(bytes) = read(&[
        "C:/Windows/Fonts/CascadiaMono.ttf",
        "C:/Windows/Fonts/consola.ttf",
    ]) {
        fonts
            .font_data
            .insert("mono".into(), egui::FontData::from_owned(bytes));
        fonts
            .families
            .entry(FontFamily::Monospace)
            .or_default()
            .insert(0, "mono".into());
    }
    ctx.set_fonts(fonts);

    let mut visuals = egui::Visuals::dark();
    visuals.panel_fill = FIELD;
    visuals.override_text_color = Some(BONE);
    ctx.set_visuals(visuals);
}
