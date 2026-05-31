use eframe::egui::{self, Align2, Pos2, Rect, Shape, Stroke, Vec2};

use crate::corner_library::CornerLibraryEntry;
use crate::paint;
use crate::source;
use crate::style::{
    self, alpha, AMBER, BONE, BONE_DIM, CLIP, CUBE_COLORS, CUBE_NAMES, CYAN, GRID, PHOSPHOR, SCREEN,
    WELL,
};

pub fn card_layout(field: Rect) -> [Rect; 8] {
    // Two columns of four wide plot cells: left = Z0 floor corners 0..3, right =
    // Z1 ceiling 4..7. Index i keeps the cube ordering (col = i/4, row = i%4).
    let work = Rect::from_min_max(
        field.min + Vec2::new(30.0, 126.0),
        field.max - Vec2::new(26.0, 22.0),
    );
    let gap = Vec2::new(22.0, 12.0);
    let cell_w = (work.width() - gap.x) / 2.0;
    let cell_h = (work.height() - gap.y * 3.0) / 4.0;
    std::array::from_fn(|i| {
        Rect::from_min_size(
            work.min
                + Vec2::new(
                    (i / 4) as f32 * (cell_w + gap.x),
                    (i % 4) as f32 * (cell_h + gap.y),
                ),
            Vec2::new(cell_w, cell_h),
        )
    })
}

pub fn picker_layout(field: Rect, positions: &[(f32, f32)]) -> Vec<Rect> {
    let plane = picker_plane(field);
    positions
        .iter()
        .map(|(brightness, openness)| {
            let pos = Pos2::new(
                plane.left() + brightness * plane.width(),
                plane.top() + (1.0 - openness) * plane.height(),
            );
            Rect::from_center_size(pos, Vec2::splat(22.0))
        })
        .collect()
}

fn picker_plane(field: Rect) -> Rect {
    Rect::from_min_max(
        field.min + Vec2::new(44.0, 84.0),
        field.max - Vec2::new(252.0, 84.0),
    )
}

pub fn draw_cards(
    painter: &egui::Painter,
    field: Rect,
    mini: &[Vec<[f64; 2]>],
    selected: Option<usize>,
    arch_label: &str,
) -> [Rect; 8] {
    paint::workspace_header(
        painter,
        field,
        1,
        "SHAPE",
        "WIRE THE OPENED CUBE  /  CLICK A CORNER TO OPEN THE AUDITED ATLAS",
    );
    let cards = card_layout(field);
    painter.text(
        Pos2::new(cards[0].center().x, cards[0].top() - 12.0),
        Align2::CENTER_BOTTOM,
        "Z0 · FLOOR",
        style::mono(8.0),
        alpha(AMBER, 220),
    );
    painter.text(
        Pos2::new(cards[4].center().x, cards[4].top() - 12.0),
        Align2::CENTER_BOTTOM,
        "Z1 · CEILING",
        style::mono(8.0),
        alpha(CYAN, 220),
    );

    for (i, cell) in cards.iter().enumerate() {
        let active = selected == Some(i);
        let accent = CUBE_COLORS[i];
        let curve = mini.get(i).map(Vec::as_slice).unwrap_or(&[]);
        draw_elegant_plot(painter, *cell, curve, accent, active);
        painter.text(
            cell.left_top() + Vec2::new(11.0, 7.0),
            Align2::LEFT_TOP,
            format!("C{:02}", i + 1),
            style::mono(7.5),
            alpha(accent, 235),
        );
        painter.text(
            cell.left_top() + Vec2::new(38.0, 5.0),
            Align2::LEFT_TOP,
            cube_coordinate(i),
            style::title(11.0),
            if active { accent } else { BONE },
        );
        painter.text(
            cell.right_top() + Vec2::new(-11.0, 7.0),
            Align2::RIGHT_TOP,
            CUBE_NAMES[i],
            style::mono(8.0),
            alpha(if active { accent } else { BONE_DIM }, 225),
        );
    }

    paint::status_chip(
        painter,
        Pos2::new(field.right() - 126.0, field.top() + 31.0),
        &format!("GEN / {}", arch_label.to_uppercase()),
        CYAN,
    );
    cards
}

/// One corner's response, drawn as a striking gradient-filled curve: a dark
/// well, a vertical gradient under the line (accent → transparent), a soft glow
/// pass, then a crisp bright stroke. The active corner brightens and frames.
fn draw_elegant_plot(
    painter: &egui::Painter,
    cell: Rect,
    curve: &[[f64; 2]],
    accent: egui::Color32,
    active: bool,
) {
    painter.rect_filled(cell, 8.0, SCREEN);
    if active {
        painter.rect_stroke(cell.expand(2.0), 10.0, Stroke::new(1.0, alpha(accent, 70)));
    }
    painter.rect_stroke(
        cell,
        8.0,
        Stroke::new(
            if active { 1.6 } else { 1.0 },
            alpha(if active { accent } else { GRID }, if active { 235 } else { 185 }),
        ),
    );

    let plot = Rect::from_min_max(
        cell.min + Vec2::new(12.0, 24.0),
        cell.max - Vec2::new(12.0, 10.0),
    );
    let db_to_y = |db: f64| {
        plot.bottom() - plot.height() * (((db as f32) + 48.0) / 78.0).clamp(0.0, 1.0)
    };
    for k in 1..4 {
        let x = plot.left() + plot.width() * k as f32 / 4.0;
        painter.line_segment(
            [Pos2::new(x, plot.top()), Pos2::new(x, plot.bottom())],
            Stroke::new(0.5, alpha(GRID, 80)),
        );
    }
    let zero_y = db_to_y(0.0);
    painter.line_segment(
        [Pos2::new(plot.left(), zero_y), Pos2::new(plot.right(), zero_y)],
        Stroke::new(0.7, alpha(GRID, 160)),
    );

    if curve.len() < 2 {
        return;
    }
    let n = curve.len();
    let px = |i: usize| plot.left() + plot.width() * i as f32 / (n - 1) as f32;
    let py = |i: usize| db_to_y(curve[i][1]);

    let mut mesh = egui::Mesh::default();
    for i in 0..n {
        mesh.colored_vertex(Pos2::new(px(i), py(i)), alpha(accent, if active { 130 } else { 85 }));
        mesh.colored_vertex(Pos2::new(px(i), plot.bottom()), alpha(accent, 0));
        if i > 0 {
            let t = (2 * (i - 1)) as u32;
            mesh.add_triangle(t, t + 1, t + 2);
            mesh.add_triangle(t + 2, t + 1, t + 3);
        }
    }
    painter.add(Shape::mesh(mesh));

    let points: Vec<Pos2> = (0..n).map(|i| Pos2::new(px(i), py(i))).collect();
    painter.add(Shape::line(
        points.clone(),
        Stroke::new(
            if active { 7.0 } else { 4.5 },
            alpha(accent, if active { 55 } else { 34 }),
        ),
    ));
    painter.add(Shape::line(
        points,
        Stroke::new(if active { 2.4 } else { 1.8 }, accent),
    ));
}

fn cube_coordinate(index: usize) -> &'static str {
    match index % 4 {
        0 => "M0 / Q0",
        1 => "M100 / Q0",
        2 => "M0 / Q100",
        _ => "M100 / Q100",
    }
}

pub fn draw_picker(
    painter: &egui::Painter,
    field: Rect,
    corner: usize,
    entries: &[CornerLibraryEntry],
    positions: &[(f32, f32)],
    hover: Option<Pos2>,
) -> Vec<Rect> {
    painter.rect_filled(field, 5.0, alpha(WELL, 252));
    paint::workspace_header(
        painter,
        field,
        1,
        "SHAPE / SOURCE MAP",
        &format!(
            "ASSIGN {}  /  CLICK A NODE  /  CLICK EMPTY SPACE TO CLOSE",
            CUBE_NAMES[corner]
        ),
    );
    let plane = picker_plane(field);
    for k in 0..80 {
        let t = k as f32 / 79.0;
        let x = plane.left() + t * plane.width();
        painter.line_segment(
            [Pos2::new(x, plane.top()), Pos2::new(x, plane.bottom())],
            Stroke::new(
                plane.width() / 80.0 + 1.0,
                alpha(source::spectrum_color(t), 17),
            ),
        );
    }
    painter.rect_stroke(plane, 3.0, Stroke::new(1.0, alpha(GRID, 230)));
    paint::axis(
        painter,
        Pos2::new(plane.left(), plane.bottom() + 16.0),
        Pos2::new(plane.right(), plane.bottom() + 16.0),
        "LOW → HIGH",
    );
    paint::axis(
        painter,
        Pos2::new(plane.left() - 16.0, plane.bottom()),
        Pos2::new(plane.left() - 16.0, plane.top()),
        "OPEN → CLOSED",
    );
    let rects = picker_layout(field, positions);
    let hovered = hover.and_then(|pointer| rects.iter().position(|rect| rect.contains(pointer)));
    for (i, entry) in entries.iter().enumerate() {
        let pos = rects[i].center();
        let active = hovered == Some(i);
        let color = category_color(&entry.category);
        if active {
            painter.line_segment(
                [pos, Pos2::new(plane.right(), pos.y)],
                Stroke::new(1.0, alpha(color, 105)),
            );
        }
        painter.circle_filled(pos, if active { 7.0 } else { 4.5 }, color);
        painter.circle_stroke(
            pos,
            if active { 11.0 } else { 7.0 },
            Stroke::new(if active { 2.0 } else { 0.8 }, alpha(BONE, 190)),
        );
        if active {
            painter.text(
                pos + Vec2::new(0.0, -14.0),
                Align2::CENTER_BOTTOM,
                format!("{:02}", i + 1),
                style::mono(8.0),
                BONE,
            );
        }
    }
    draw_picker_rail(painter, field, entries, hovered);
    rects
}

fn category_color(category: &str) -> egui::Color32 {
    match category {
        "authored" => PHOSPHOR,
        "design" => AMBER,
        "physics" => CYAN,
        "voice-local" => egui::Color32::from_rgb(0xff, 0xd2, 0x4a),
        "synth-local" => egui::Color32::from_rgb(0xff, 0x8a, 0x2a),
        "loose-local" => BONE_DIM,
        "heritage-study" => egui::Color32::from_rgb(0xc0, 0x6c, 0xff),
        "rom-study" => CLIP,
        _ => BONE_DIM,
    }
}

fn draw_picker_rail(
    painter: &egui::Painter,
    field: Rect,
    entries: &[CornerLibraryEntry],
    hovered: Option<usize>,
) {
    let rail = Rect::from_min_size(
        Pos2::new(field.right() - 226.0, field.top() + 84.0),
        Vec2::new(202.0, field.height() - 168.0),
    );
    painter.rect_filled(rail, 4.0, alpha(WELL, 246));
    painter.rect_stroke(rail, 4.0, Stroke::new(1.0, alpha(GRID, 230)));
    painter.text(
        rail.left_top() + Vec2::new(12.0, 10.0),
        Align2::LEFT_TOP,
        format!("AUDITED CORNERS / {:02}", entries.len()),
        style::mono(9.0),
        CYAN,
    );

    let mut categories = Vec::<(&str, usize)>::new();
    for entry in entries {
        if let Some((_, count)) = categories
            .iter_mut()
            .find(|(category, _)| *category == entry.category)
        {
            *count += 1;
        } else {
            categories.push((&entry.category, 1));
        }
    }
    for (i, (category, count)) in categories.iter().enumerate() {
        let y = rail.top() + 34.0 + i as f32 * 16.0;
        painter.circle_filled(
            Pos2::new(rail.left() + 14.0, y + 5.0),
            3.5,
            category_color(category),
        );
        painter.text(
            Pos2::new(rail.left() + 25.0, y),
            Align2::LEFT_TOP,
            format!("{category:<15} {count:>2}"),
            style::mono(8.0),
            BONE_DIM,
        );
    }

    let split = rail.top() + 34.0 + categories.len() as f32 * 16.0 + 12.0;
    paint::rail(
        painter,
        Pos2::new(rail.left() + 12.0, split),
        Pos2::new(rail.right() - 12.0, split),
        alpha(GRID, 220),
    );
    if let Some(entry) = hovered.and_then(|index| entries.get(index)) {
        let color = category_color(&entry.category);
        painter.text(
            Pos2::new(rail.left() + 12.0, split + 14.0),
            Align2::LEFT_TOP,
            entry.name.to_uppercase(),
            style::mono(8.0),
            BONE,
        );
        painter.text(
            Pos2::new(rail.left() + 12.0, split + 34.0),
            Align2::LEFT_TOP,
            format!(
                "{} / {}\nLOW-HIGH {:>3.0}%  /  OPEN-CLOSED {:>3.0}%",
                entry.category.to_uppercase(),
                entry.provenance.to_uppercase(),
                entry.brightness * 100.0,
                (1.0 - entry.openness) * 100.0,
            ),
            style::mono(7.5),
            PHOSPHOR,
        );
        let plot = Rect::from_min_max(
            Pos2::new(rail.left() + 12.0, split + 72.0),
            Pos2::new(rail.right() - 12.0, rail.bottom() - 42.0),
        );
        draw_response_schematic(painter, plot, entry, color);
    } else {
        painter.text(
            Pos2::new(rail.left() + 12.0, split + 14.0),
            Align2::LEFT_TOP,
            "HOVER A NODE\nTO INSPECT SOURCE\nAND PROVENANCE",
            style::mono(8.0),
            BONE_DIM,
        );
    }
}

fn draw_response_schematic(
    painter: &egui::Painter,
    plot: Rect,
    entry: &CornerLibraryEntry,
    color: egui::Color32,
) {
    painter.rect_filled(plot, 3.0, alpha(WELL, 255));
    painter.rect_stroke(plot, 3.0, Stroke::new(1.0, alpha(GRID, 235)));
    for index in 1..4 {
        let x = plot.left() + plot.width() * index as f32 / 4.0;
        painter.line_segment(
            [Pos2::new(x, plot.top()), Pos2::new(x, plot.bottom())],
            Stroke::new(0.7, alpha(GRID, 170)),
        );
    }
    for index in 1..4 {
        let y = plot.top() + plot.height() * index as f32 / 4.0;
        painter.line_segment(
            [Pos2::new(plot.left(), y), Pos2::new(plot.right(), y)],
            Stroke::new(0.7, alpha(GRID, 170)),
        );
    }
    painter.text(
        plot.left_top() + Vec2::new(7.0, 6.0),
        Align2::LEFT_TOP,
        "EXACT PACKED TRACE",
        style::mono(7.0),
        alpha(CYAN, 220),
    );
    painter.text(
        plot.right_top() + Vec2::new(-7.0, 6.0),
        Align2::RIGHT_TOP,
        format!("{:+.0} dB", entry.response_max_db),
        style::mono(7.0),
        alpha(BONE_DIM, 230),
    );
    painter.text(
        plot.right_bottom() + Vec2::new(-7.0, -6.0),
        Align2::RIGHT_BOTTOM,
        format!("{:+.0} dB", entry.response_min_db),
        style::mono(7.0),
        alpha(BONE_DIM, 230),
    );

    let span = (entry.response_max_db - entry.response_min_db).max(1.0);
    let trace = &entry.response_trace_db;
    if trace.len() >= 2 {
        let inset = plot.shrink2(Vec2::new(6.0, 20.0));
        let points: Vec<Pos2> = trace
            .iter()
            .enumerate()
            .map(|(index, db)| {
                let x = inset.left() + inset.width() * index as f32 / (trace.len() - 1) as f32;
                let y = inset.bottom()
                    - inset.height() * ((*db - entry.response_min_db) / span).clamp(0.0, 1.0);
                Pos2::new(x, y)
            })
            .collect();
        painter.add(Shape::line(
            points.clone(),
            Stroke::new(5.0, alpha(color, 48)),
        ));
        painter.add(Shape::line(points, Stroke::new(1.8, alpha(color, 250))));
    }
    painter.text(
        plot.left_bottom() + Vec2::new(7.0, -6.0),
        Align2::LEFT_BOTTOM,
        format!("PEAKS {:02}", entry.peak_count),
        style::mono(7.0),
        color,
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shape_layout_is_two_columns_of_four() {
        let cards = card_layout(Rect::from_min_max(Pos2::ZERO, Pos2::new(1000.0, 800.0)));
        assert_eq!(cards.len(), 8);
        // Left column = corners 0..4 (Z0 floor); right column = 4..8 (Z1 ceiling).
        for i in 1..4 {
            assert!((cards[i].center().x - cards[0].center().x).abs() < 0.5);
        }
        for i in 5..8 {
            assert!((cards[i].center().x - cards[4].center().x).abs() < 0.5);
        }
        assert!(cards[0].center().x < cards[4].center().x);
        // Four rows descend within each column; rows align across the two columns.
        assert!(cards[0].center().y < cards[1].center().y);
        assert!(cards[1].center().y < cards[2].center().y);
        assert!(cards[2].center().y < cards[3].center().y);
        assert!((cards[0].center().y - cards[4].center().y).abs() < 0.5);
        for i in 0..cards.len() {
            for j in i + 1..cards.len() {
                assert!(!cards[i].intersects(cards[j]));
            }
        }
    }

    #[test]
    fn picker_layout_tracks_every_library_entry_and_keeps_the_final_hitbox() {
        let positions = vec![(0.5, 0.5); 68];
        let rects = picker_layout(
            Rect::from_min_max(Pos2::ZERO, Pos2::new(1000.0, 800.0)),
            &positions,
        );
        assert_eq!(rects.len(), positions.len());
        assert!(rects
            .last()
            .expect("last picker hitbox")
            .contains(rects[67].center()));
    }
}
