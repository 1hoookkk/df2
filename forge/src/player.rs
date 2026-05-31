use eframe::egui::{self, Align2, Pos2, Rect, Shape, Stroke, Vec2};

use crate::paint;
use crate::style::{
    self, alpha, AMBER, BONE, BONE_DIM, CUBE_COLORS, CUBE_NAMES, CYAN, GRID, PHOSPHOR, WELL,
};

pub struct HitAreas {
    pub morph: Rect,
    pub path: Rect,
    pub cube: Rect,
}

pub fn draw(
    painter: &egui::Painter,
    field: Rect,
    morph: f32,
    q: f32,
    z: f32,
    path_t: f32,
    yaw: f32,
    pitch: f32,
    weights: [f32; 8],
    live_response: &[[f64; 2]],
) -> HitAreas {
    paint::workspace_header(
        painter,
        field,
        3,
        "PLAYER",
        "AUDITION THE BODY  /  MORPH × AUTHORED PATH × TRANSFORM",
    );
    let cube = Rect::from_min_max(
        field.min + Vec2::new(24.0, 74.0),
        field.max - Vec2::new(178.0, 138.0),
    );
    let center = cube.center();
    let scale = (cube.height() * 0.36).min(250.0);
    let (cy, sy) = (yaw.cos(), yaw.sin());
    let (cp, sp) = (pitch.cos(), pitch.sin());
    let project = |px: f32, py: f32, pz: f32| -> (Pos2, f32) {
        let x1 = px * cy + pz * sy;
        let z1 = -px * sy + pz * cy;
        let y2 = py * cp - z1 * sp;
        let z2 = py * sp + z1 * cp;
        (Pos2::new(center.x + scale * x1, center.y - scale * y2), z2)
    };
    let vertex = |i: usize| {
        (
            if i & 1 == 1 { 1.0 } else { -1.0 },
            if (i >> 1) & 1 == 1 { 1.0 } else { -1.0 },
            if (i >> 2) & 1 == 1 { 1.0 } else { -1.0 },
        )
    };
    let points: Vec<(Pos2, f32)> = (0..8)
        .map(|i| {
            let (x, y, z) = vertex(i);
            project(x, y, z)
        })
        .collect();
    for i in 0..8 {
        for bit in [1usize, 2, 4] {
            let j = i ^ bit;
            if j > i {
                painter.line_segment(
                    [points[i].0, points[j].0],
                    Stroke::new(
                        1.4,
                        alpha(
                            GRID,
                            if points[i].1 + points[j].1 < 0.0 {
                                100
                            } else {
                                220
                            },
                        ),
                    ),
                );
            }
        }
    }
    let (live, _) = project(2.0 * morph - 1.0, 2.0 * q - 1.0, 2.0 * z - 1.0);
    for i in 0..8 {
        if weights[i] >= 0.015 {
            painter.line_segment(
                [live, points[i].0],
                Stroke::new(
                    1.0 + 2.8 * weights[i],
                    alpha(CUBE_COLORS[i], (35.0 + 160.0 * weights[i]) as u8),
                ),
            );
        }
    }
    let mut order: Vec<usize> = (0..8).collect();
    order.sort_by(|&a, &b| {
        points[a]
            .1
            .partial_cmp(&points[b].1)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    for i in order {
        let (pos, depth) = points[i];
        let radius = 6.0 + (depth + 1.0) * 2.0;
        painter.circle_filled(
            pos,
            radius,
            alpha(CUBE_COLORS[i], if depth < 0.0 { 150 } else { 245 }),
        );
        painter.text(
            pos + Vec2::new(radius + 4.0, 0.0),
            Align2::LEFT_CENTER,
            CUBE_NAMES[i],
            style::mono(9.0),
            alpha(BONE, if depth < 0.0 { 150 } else { 225 }),
        );
    }
    painter.circle_filled(live, 5.0, PHOSPHOR);
    painter.circle_stroke(live, 10.0, Stroke::new(2.0, alpha(PHOSPHOR, 210)));
    draw_live_response(
        painter,
        Rect::from_min_size(
            Pos2::new(field.right() - 264.0, field.top() + 90.0),
            Vec2::new(234.0, 138.0),
        ),
        live_response,
    );

    let morph_rect = Rect::from_min_size(
        Pos2::new(field.left() + 68.0, field.bottom() - 84.0),
        Vec2::new(field.width() * 0.35, 24.0),
    );
    let path_rect = Rect::from_min_size(
        Pos2::new(field.center().x + 12.0, field.bottom() - 84.0),
        Vec2::new(field.width() * 0.35, 24.0),
    );
    draw_slider_display(painter, morph_rect, "MORPH", morph, CYAN);
    draw_slider_display(painter, path_rect, "PATH", path_t, AMBER);
    paint::readout(
        painter,
        Rect::from_min_size(
            Pos2::new(field.center().x - 76.0, field.bottom() - 42.0),
            Vec2::new(152.0, 28.0),
        ),
        "LIVE VECTOR",
        &format!(
            "X {:03} / Y {:03} / Z {:03}",
            (morph * 100.0) as u32,
            (q * 100.0) as u32,
            (z * 100.0) as u32
        ),
        true,
    );
    HitAreas {
        morph: morph_rect,
        path: path_rect,
        cube,
    }
}

fn draw_live_response(painter: &egui::Painter, rect: Rect, response: &[[f64; 2]]) {
    painter.rect_filled(rect, 7.0, alpha(WELL, 248));
    painter.rect_stroke(rect, 7.0, Stroke::new(1.0, alpha(GRID, 230)));
    for index in 1..4 {
        let x = rect.left() + rect.width() * index as f32 / 4.0;
        painter.line_segment(
            [Pos2::new(x, rect.top()), Pos2::new(x, rect.bottom())],
            Stroke::new(0.7, alpha(GRID, 135)),
        );
    }
    for index in 1..3 {
        let y = rect.top() + rect.height() * index as f32 / 3.0;
        painter.line_segment(
            [Pos2::new(rect.left(), y), Pos2::new(rect.right(), y)],
            Stroke::new(0.7, alpha(GRID, 135)),
        );
    }
    painter.text(
        rect.left_top() + Vec2::new(10.0, 8.0),
        Align2::LEFT_TOP,
        "LIVE RESPONSE",
        style::mono(8.0),
        CYAN,
    );
    if response.len() >= 2 {
        let inset = rect.shrink2(Vec2::new(8.0, 22.0));
        let points: Vec<Pos2> = response
            .iter()
            .enumerate()
            .map(|(index, point)| {
                Pos2::new(
                    inset.left() + inset.width() * index as f32 / (response.len() - 1) as f32,
                    inset.bottom()
                        - inset.height() * (((point[1] as f32) + 48.0) / 78.0).clamp(0.0, 1.0),
                )
            })
            .collect();
        painter.add(Shape::line(
            points.clone(),
            Stroke::new(7.0, alpha(PHOSPHOR, 40)),
        ));
        painter.add(Shape::line(points, Stroke::new(1.8, PHOSPHOR)));
    }
}

fn draw_slider_display(
    painter: &egui::Painter,
    rect: Rect,
    label: &str,
    value: f32,
    color: egui::Color32,
) {
    painter.rect_filled(rect, 3.0, alpha(GRID, 150));
    painter.line_segment(
        [
            rect.left_center() + Vec2::new(5.0, 0.0),
            rect.right_center() - Vec2::new(5.0, 0.0),
        ],
        Stroke::new(1.0, alpha(BONE_DIM, 160)),
    );
    let x = rect.left() + rect.width() * value;
    painter.line_segment(
        [
            rect.left_center() + Vec2::new(5.0, 0.0),
            Pos2::new(x, rect.center().y),
        ],
        Stroke::new(3.0, color),
    );
    painter.circle_filled(Pos2::new(x, rect.center().y), 7.0, color);
    painter.text(
        rect.left_top() + Vec2::new(0.0, -7.0),
        Align2::LEFT_BOTTOM,
        label,
        style::mono(10.0),
        color,
    );
    painter.text(
        rect.right_top() + Vec2::new(0.0, -7.0),
        Align2::RIGHT_BOTTOM,
        format!("{:03}", (value * 100.0) as u32),
        style::mono(9.0),
        BONE,
    );
}
