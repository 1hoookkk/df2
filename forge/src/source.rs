use eframe::egui::{self, Align2, Pos2, Rect, Stroke, Vec2};

use crate::generators::Architecture;
use crate::paint;
use crate::style::{self, alpha, AMBER, BONE, BONE_DIM, CYAN, GRID, PHOSPHOR, WELL};

pub fn spectrum_color(t: f32) -> egui::Color32 {
    let h = t.clamp(0.0, 1.0) * 0.66 * 6.0;
    let x = 1.0 - (h.rem_euclid(2.0) - 1.0).abs();
    let (r, g, b) = match h as i32 {
        0 => (1.0, x, 0.0),
        1 => (x, 1.0, 0.0),
        2 => (0.0, 1.0, x),
        3 => (0.0, x, 1.0),
        _ => (0.1, 0.2, 1.0),
    };
    egui::Color32::from_rgb(
        (r * 210.0) as u8 + 30,
        (g * 210.0) as u8 + 30,
        (b * 210.0) as u8 + 30,
    )
}

pub fn node_layout(field: Rect, positions: &[(f32, f32)]) -> Vec<Rect> {
    let plane = field.shrink2(Vec2::new(44.0, 84.0));
    positions
        .iter()
        .map(|(brightness, openness)| {
            let pos = Pos2::new(
                plane.left() + brightness * plane.width(),
                plane.top() + (1.0 - openness) * plane.height(),
            );
            Rect::from_center_size(pos, Vec2::splat(30.0))
        })
        .collect()
}

pub fn draw(
    painter: &egui::Painter,
    field: Rect,
    positions: &[(f32, f32)],
    current: Option<Architecture>,
) -> Vec<Rect> {
    paint::workspace_header(
        painter,
        field,
        1,
        "SOURCE",
        "PICK A FIELD GENERATOR  /  LOW → HIGH  ×  OPEN → CLOSED",
    );
    let plane = field.shrink2(Vec2::new(44.0, 84.0));
    for k in 0..80 {
        let t = k as f32 / 79.0;
        let x = plane.left() + t * plane.width();
        painter.line_segment(
            [Pos2::new(x, plane.top()), Pos2::new(x, plane.bottom())],
            Stroke::new(plane.width() / 80.0 + 1.0, alpha(spectrum_color(t), 15)),
        );
    }
    painter.rect_stroke(plane, 3.0, Stroke::new(1.0, alpha(GRID, 220)));
    paint::axis(
        painter,
        Pos2::new(plane.left(), plane.bottom() + 16.0),
        Pos2::new(plane.right(), plane.bottom() + 16.0),
        "FREQUENCY / BRIGHTNESS",
    );
    paint::axis(
        painter,
        Pos2::new(plane.left() - 16.0, plane.bottom()),
        Pos2::new(plane.left() - 16.0, plane.top()),
        "OPENNESS",
    );

    let rects = node_layout(field, positions);
    for (i, arch) in Architecture::ALL.iter().enumerate() {
        let rect = rects[i];
        let pos = rect.center();
        let active = current == Some(*arch);
        let color = spectrum_color(positions[i].0);
        painter.circle_filled(pos, if active { 8.0 } else { 5.5 }, color);
        painter.circle_stroke(
            pos,
            if active { 13.0 } else { 8.5 },
            Stroke::new(
                if active { 2.0 } else { 0.8 },
                alpha(if active { PHOSPHOR } else { color }, 230),
            ),
        );
        painter.text(
            pos + Vec2::new(0.0, -13.0),
            Align2::CENTER_BOTTOM,
            format!("{:02}", i + 1),
            style::mono(8.0),
            if active { BONE } else { alpha(BONE_DIM, 225) },
        );
    }
    painter.text(
        plane.left_top() + Vec2::new(8.0, 8.0),
        Align2::LEFT_TOP,
        "PERCEPTUAL SOURCE FIELD",
        style::mono(9.0),
        alpha(CYAN, 200),
    );
    draw_legend(painter, field, current);
    rects
}

pub fn draw_legend(painter: &egui::Painter, field: Rect, selected: Option<Architecture>) {
    let legend = Rect::from_min_size(
        Pos2::new(field.right() - 220.0, field.top() + 84.0),
        Vec2::new(196.0, 302.0),
    );
    painter.rect_filled(legend, 4.0, alpha(WELL, 238));
    painter.rect_stroke(legend, 4.0, Stroke::new(1.0, alpha(GRID, 230)));
    painter.text(
        legend.left_top() + Vec2::new(12.0, 10.0),
        Align2::LEFT_TOP,
        "FIELD INDEX",
        style::mono(9.0),
        CYAN,
    );
    for (i, architecture) in Architecture::ALL.iter().enumerate() {
        let active = selected == Some(*architecture);
        let y = legend.top() + 30.0 + i as f32 * 16.0;
        painter.text(
            Pos2::new(legend.left() + 12.0, y),
            Align2::LEFT_TOP,
            format!("{:02}", i + 1),
            style::mono(8.5),
            if active { AMBER } else { BONE_DIM },
        );
        painter.text(
            Pos2::new(legend.left() + 38.0, y),
            Align2::LEFT_TOP,
            architecture.label().to_uppercase(),
            style::mono(8.5),
            if active { PHOSPHOR } else { BONE },
        );
    }
}
