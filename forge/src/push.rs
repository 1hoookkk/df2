use eframe::egui::{self, Align2, Pos2, Rect, Stroke, Vec2};

use crate::corner_library::CornerLibraryEntry;
use crate::paint;
use crate::style::{self, alpha, AMBER, BONE, BONE_DIM, CLIP, CYAN, GRID, PHOSPHOR, WELL};

pub fn draw(
    painter: &egui::Painter,
    field: Rect,
    publish_error: Option<&str>,
    stability: Option<(f64, (f64, f64))>,
    entries: &[CornerLibraryEntry],
    active_field: &str,
    last_push: Option<&str>,
) {
    paint::workspace_header(
        painter,
        field,
        4,
        "PUSH",
        "VALIDATE THE PACKED BODY  /  PUBLISH ONLY EXPLICIT AUTHORING WORK",
    );
    let ready = publish_error.is_none();
    let left = Rect::from_min_max(
        field.min + Vec2::new(30.0, 96.0),
        Pos2::new(field.center().x + 92.0, field.bottom() - 34.0),
    );
    let right = Rect::from_min_max(
        Pos2::new(left.right() + 20.0, left.top()),
        Pos2::new(field.right() - 30.0, left.bottom()),
    );
    panel(painter, left);
    panel(painter, right);

    painter.text(
        left.left_top() + Vec2::new(18.0, 16.0),
        Align2::LEFT_TOP,
        if ready {
            "BODY READY"
        } else {
            "BODY INCOMPLETE"
        },
        style::title(25.0),
        if ready { PHOSPHOR } else { CLIP },
    );
    painter.text(
        left.left_top() + Vec2::new(18.0, 52.0),
        Align2::LEFT_TOP,
        if ready {
            "EXPLICIT CORNERS CONFIRMED\nPACKED AUTHORITY AVAILABLE"
        } else {
            "PREVIEW REMAINS AVAILABLE\nPUBLISH IS CORRECTLY BLOCKED"
        },
        style::mono(9.0),
        BONE,
    );
    let status = if ready {
        "SHIP GATE / PASS"
    } else {
        "SHIP GATE / HOLD"
    };
    paint::status_chip(
        painter,
        left.left_top() + Vec2::new(86.0, 112.0),
        status,
        if ready { PHOSPHOR } else { CLIP },
    );

    let rows = [
        ("ACTIVE FIELD", active_field.to_uppercase(), CYAN),
        (
            "AUDITED SOURCES",
            format!("{:02} SURVIVORS", entries.len()),
            AMBER,
        ),
        (
            "PACKED SURFACE",
            if ready {
                "AUTHORITATIVE"
            } else {
                "PREVIEW ONLY"
            }
            .to_owned(),
            if ready { PHOSPHOR } else { CLIP },
        ),
    ];
    for (index, (label, value, color)) in rows.iter().enumerate() {
        let rect = Rect::from_min_size(
            left.left_top() + Vec2::new(18.0, 150.0 + index as f32 * 54.0),
            Vec2::new(left.width() - 36.0, 40.0),
        );
        paint::readout(painter, rect, label, value, *color == PHOSPHOR);
    }

    painter.text(
        right.left_top() + Vec2::new(16.0, 16.0),
        Align2::LEFT_TOP,
        "PUBLISH AUDIT",
        style::mono(10.0),
        CYAN,
    );
    let mut y = right.top() + 52.0;
    audit_row(
        painter,
        right,
        &mut y,
        "CORNER SOURCE",
        ready,
        if ready { "EXPLICIT" } else { "MISSING" },
    );
    let (stable, stability_value) = match stability {
        Some((radius, (morph, q))) => (
            radius <= crate::dsp::STABILITY_RADIUS_LIMIT,
            format!(
                "R {:.4} @ {:02}/{:02}",
                radius,
                (morph * 100.0) as u32,
                (q * 100.0) as u32
            ),
        ),
        None => (false, "NO SURFACE".to_owned()),
    };
    audit_row(
        painter,
        right,
        &mut y,
        "MORPH STABILITY",
        stable,
        &stability_value,
    );
    audit_row(
        painter,
        right,
        &mut y,
        "BODY240",
        ready,
        if ready { "READY" } else { "BLOCKED" },
    );

    paint::rail(
        painter,
        Pos2::new(right.left() + 16.0, y + 6.0),
        Pos2::new(right.right() - 16.0, y + 6.0),
        alpha(GRID, 220),
    );
    painter.text(
        Pos2::new(right.left() + 16.0, y + 22.0),
        Align2::LEFT_TOP,
        "LAST PUSH",
        style::mono(8.0),
        BONE_DIM,
    );
    painter.text(
        Pos2::new(right.left() + 16.0, y + 40.0),
        Align2::LEFT_TOP,
        last_push.unwrap_or("NOT YET PUBLISHED"),
        style::mono(8.0),
        if last_push
            .map(|value| value.starts_with("WRITTEN"))
            .unwrap_or(false)
        {
            PHOSPHOR
        } else {
            AMBER
        },
    );
    if publish_error.is_some() {
        painter.text(
            Pos2::new(right.left() + 16.0, right.bottom() - 18.0),
            Align2::LEFT_BOTTOM,
            "LOAD ALL FOUR EXPLICIT CORNERS.\nSYNTHESISED FALLBACK REMAINS PREVIEW-ONLY.",
            style::mono(7.0),
            alpha(CLIP, 230),
        );
    }
}

fn panel(painter: &egui::Painter, rect: Rect) {
    painter.rect_filled(rect, 6.0, alpha(WELL, 246));
    painter.rect_stroke(rect, 6.0, Stroke::new(1.0, alpha(GRID, 230)));
}

fn audit_row(
    painter: &egui::Painter,
    panel: Rect,
    y: &mut f32,
    label: &str,
    pass: bool,
    value: &str,
) {
    let color = if pass { PHOSPHOR } else { CLIP };
    painter.circle_filled(Pos2::new(panel.left() + 21.0, *y + 5.0), 4.0, color);
    painter.text(
        Pos2::new(panel.left() + 36.0, *y),
        Align2::LEFT_TOP,
        label,
        style::mono(9.0),
        BONE,
    );
    painter.text(
        Pos2::new(panel.right() - 16.0, *y),
        Align2::RIGHT_TOP,
        value,
        style::mono(9.0),
        color,
    );
    *y += 34.0;
}
