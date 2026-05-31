use eframe::egui::{
    self, Align2, Color32, Id, Pos2, Rect, Response, Sense, Shape, Stroke, Ui, Vec2,
};

use crate::style::{
    self, alpha, AMBER, BONE, BONE_DIM, CYAN, FIELD, GRID, HAIRLINE, PHOSPHOR, SCREEN, WELL,
};

pub fn schematic_grid(painter: &egui::Painter, rect: Rect) {
    painter.rect_filled(rect, 6.0, SCREEN);
    // A crisp outer frame = the flat cube edge; faint, thin interior wires.
    // Sparse + uniform so it reads as a light wireframe, not graph paper.
    painter.rect_stroke(rect, 6.0, Stroke::new(0.9, alpha(HAIRLINE, 200)));
    for i in 1..8 {
        let x = rect.left() + rect.width() * i as f32 / 8.0;
        painter.line_segment(
            [Pos2::new(x, rect.top()), Pos2::new(x, rect.bottom())],
            Stroke::new(0.4, alpha(GRID, 40)),
        );
    }
    for i in 1..5 {
        let y = rect.top() + rect.height() * i as f32 / 5.0;
        painter.line_segment(
            [Pos2::new(rect.left(), y), Pos2::new(rect.right(), y)],
            Stroke::new(0.4, alpha(GRID, 40)),
        );
    }
}

pub fn workspace_header(
    painter: &egui::Painter,
    rect: Rect,
    index: usize,
    title: &str,
    purpose: &str,
) {
    let y = rect.top() + 16.0;
    painter.text(
        Pos2::new(rect.left() + 18.0, y),
        Align2::LEFT_TOP,
        format!("0{index}"),
        style::title(22.0),
        AMBER,
    );
    painter.text(
        Pos2::new(rect.left() + 58.0, y - 2.0),
        Align2::LEFT_TOP,
        title,
        style::title(24.0),
        BONE,
    );
    painter.text(
        Pos2::new(rect.left() + 58.0, y + 26.0),
        Align2::LEFT_TOP,
        purpose,
        style::mono(10.0),
        alpha(CYAN, 220),
    );
    rail(
        painter,
        Pos2::new(rect.left() + 18.0, y + 51.0),
        Pos2::new(rect.right() - 18.0, y + 51.0),
        alpha(HAIRLINE, 190),
    );
}

pub fn rail(painter: &egui::Painter, from: Pos2, to: Pos2, color: Color32) {
    painter.line_segment([from, to], Stroke::new(1.0, color));
    painter.circle_filled(from, 2.0, color);
    painter.circle_filled(to, 2.0, color);
}

pub fn axis(painter: &egui::Painter, from: Pos2, to: Pos2, label: &str) {
    rail(painter, from, to, alpha(CYAN, 180));
    let vertical = (to.y - from.y).abs() > (to.x - from.x).abs();
    let (label_pos, align) = if vertical {
        (to + Vec2::new(7.0, 0.0), Align2::LEFT_TOP)
    } else {
        (to + Vec2::new(0.0, 7.0), Align2::RIGHT_TOP)
    };
    painter.text(label_pos, align, label, style::mono(9.0), alpha(CYAN, 220));
}

pub fn status_chip(painter: &egui::Painter, center: Pos2, text: &str, color: Color32) {
    let width = text.chars().count() as f32 * 6.3 + 18.0;
    let rect = Rect::from_center_size(center, Vec2::new(width, 20.0));
    painter.rect_filled(rect, 3.0, alpha(WELL, 245));
    painter.rect_stroke(rect, 3.0, Stroke::new(1.0, alpha(color, 190)));
    painter.text(center, Align2::CENTER_CENTER, text, style::mono(9.5), color);
}

pub fn readout(painter: &egui::Painter, rect: Rect, label: &str, value: &str, active: bool) {
    painter.rect_filled(rect, 3.0, alpha(WELL, 245));
    painter.rect_stroke(
        rect,
        3.0,
        Stroke::new(1.0, alpha(if active { PHOSPHOR } else { HAIRLINE }, 190)),
    );
    painter.text(
        rect.left_center() + Vec2::new(8.0, -5.0),
        Align2::LEFT_CENTER,
        label,
        style::mono(8.0),
        alpha(CYAN, 210),
    );
    painter.text(
        rect.left_center() + Vec2::new(8.0, 6.0),
        Align2::LEFT_CENTER,
        value,
        style::mono(11.0),
        if active { PHOSPHOR } else { BONE },
    );
}

pub fn button(
    ui: &mut Ui,
    painter: &egui::Painter,
    id: impl std::hash::Hash,
    rect: Rect,
    label: &str,
    active: bool,
) -> Response {
    let response = ui.interact(rect, Id::new(id), Sense::click());
    let edge = if active {
        PHOSPHOR
    } else if response.hovered() {
        CYAN
    } else {
        HAIRLINE
    };
    let fill = if active {
        alpha(PHOSPHOR, 34)
    } else if response.hovered() {
        alpha(CYAN, 20)
    } else {
        alpha(WELL, 238)
    };
    if active || response.hovered() {
        painter.rect_stroke(rect.expand(2.0), 4.0, Stroke::new(1.0, alpha(edge, 80)));
    }
    painter.rect_filled(rect, 3.0, fill);
    painter.rect_stroke(
        rect,
        3.0,
        Stroke::new(if active { 1.6 } else { 1.0 }, alpha(edge, 220)),
    );
    painter.text(
        rect.center(),
        Align2::CENTER_CENTER,
        label,
        style::mono(10.0),
        if active { PHOSPHOR } else { BONE },
    );
    response
}

pub fn toggle(
    ui: &mut Ui,
    painter: &egui::Painter,
    id: impl std::hash::Hash,
    rect: Rect,
    label: &str,
    active: bool,
) -> Response {
    button(ui, painter, id, rect, label, active)
}

pub fn tab(
    ui: &mut Ui,
    painter: &egui::Painter,
    id: impl std::hash::Hash,
    rect: Rect,
    index: usize,
    label: &str,
    active: bool,
) -> Response {
    let response = ui.interact(rect, Id::new(id), Sense::click());
    let edge = if active {
        PHOSPHOR
    } else if response.hovered() {
        CYAN
    } else {
        HAIRLINE
    };
    painter.rect_filled(
        rect,
        2.0,
        alpha(
            if active { PHOSPHOR } else { FIELD },
            if active { 30 } else { 245 },
        ),
    );
    painter.rect_stroke(
        rect,
        2.0,
        Stroke::new(if active { 1.8 } else { 1.0 }, alpha(edge, 220)),
    );
    painter.text(
        rect.left_center() + Vec2::new(10.0, 0.0),
        Align2::LEFT_CENTER,
        format!("0{index}"),
        style::mono(9.0),
        if active { AMBER } else { BONE_DIM },
    );
    painter.text(
        rect.left_center() + Vec2::new(34.0, 0.0),
        Align2::LEFT_CENTER,
        label,
        style::mono(10.0),
        if active { PHOSPHOR } else { BONE },
    );
    response
}

pub fn card(
    ui: &mut Ui,
    painter: &egui::Painter,
    id: impl std::hash::Hash,
    rect: Rect,
    selected: bool,
    accent: Color32,
) -> Response {
    let response = ui.interact(rect, Id::new(id), Sense::click());
    let edge = if selected {
        accent
    } else if response.hovered() {
        CYAN
    } else {
        HAIRLINE
    };
    if selected {
        painter.rect_stroke(rect.expand(3.0), 5.0, Stroke::new(1.2, alpha(accent, 85)));
    }
    painter.rect_filled(
        rect,
        4.0,
        alpha(WELL, if response.hovered() { 254 } else { 238 }),
    );
    painter.rect_stroke(
        rect,
        4.0,
        Stroke::new(if selected { 2.0 } else { 1.0 }, alpha(edge, 230)),
    );
    response
}

pub fn slider(
    ui: &mut Ui,
    painter: &egui::Painter,
    id: impl std::hash::Hash,
    rect: Rect,
    label: &str,
    value: &mut f32,
) -> Response {
    let mut response = ui.interact(rect, Id::new(id), Sense::click_and_drag());
    if (response.dragged() || response.clicked()) && response.interact_pointer_pos().is_some() {
        let pointer = response.interact_pointer_pos().unwrap();
        *value = ((pointer.x - rect.left()) / rect.width().max(1.0)).clamp(0.0, 1.0);
        response.mark_changed();
    }
    let x = rect.left() + rect.width() * *value;
    painter.rect_filled(rect, 3.0, alpha(WELL, 248));
    painter.rect_stroke(rect, 3.0, Stroke::new(1.0, alpha(HAIRLINE, 230)));
    painter.line_segment(
        [
            Pos2::new(rect.left() + 4.0, rect.center().y),
            Pos2::new(rect.right() - 4.0, rect.center().y),
        ],
        Stroke::new(1.0, alpha(CYAN, 160)),
    );
    painter.line_segment(
        [
            Pos2::new(rect.left() + 4.0, rect.center().y),
            Pos2::new(x, rect.center().y),
        ],
        Stroke::new(2.5, PHOSPHOR),
    );
    painter.circle_filled(Pos2::new(x, rect.center().y), 6.0, PHOSPHOR);
    painter.text(
        rect.left_top() + Vec2::new(0.0, -6.0),
        Align2::LEFT_BOTTOM,
        label,
        style::mono(9.0),
        CYAN,
    );
    painter.text(
        rect.right_top() + Vec2::new(0.0, -6.0),
        Align2::RIGHT_BOTTOM,
        format!("{:03}", (*value * 100.0).round() as u32),
        style::mono(9.0),
        BONE,
    );
    response
}

pub fn knob(
    ui: &mut Ui,
    painter: &egui::Painter,
    id: impl std::hash::Hash,
    rect: Rect,
    label: &str,
    value: &mut f32,
) -> Response {
    let response = ui.interact(rect, Id::new(id), Sense::click_and_drag());
    if response.dragged() {
        *value = (*value - response.drag_delta().y * 0.006).clamp(0.0, 1.0);
    }
    let center = rect.center();
    let radius = rect.width().min(rect.height()) * 0.32;
    let angle = std::f32::consts::PI * (0.75 + 1.5 * *value);
    painter.circle_filled(center, radius, alpha(WELL, 250));
    painter.circle_stroke(center, radius, Stroke::new(1.2, alpha(HAIRLINE, 230)));
    painter.line_segment(
        [center, center + Vec2::angled(angle) * radius * 0.78],
        Stroke::new(2.4, PHOSPHOR),
    );
    painter.text(
        Pos2::new(center.x, rect.bottom()),
        Align2::CENTER_BOTTOM,
        label,
        style::mono(9.0),
        CYAN,
    );
    response
}

pub fn signal_path(painter: &egui::Painter, points: Vec<Pos2>, color: Color32) {
    painter.add(Shape::line(
        points.clone(),
        Stroke::new(8.0, alpha(color, 34)),
    ));
    painter.add(Shape::line(points, Stroke::new(2.2, color)));
}
