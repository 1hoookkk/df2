//! Workflow vocabulary for the pole/zero design canvas.
//!
//! This module deliberately copies Figma's workflow shape, not its visuals:
//! body kits seed a canvas, actor components drop into persistent lanes,
//! variants are the four packed corners, cheats are intent-preserving edits, and
//! every path still bakes to ordinary 4 x 6 rows before `.body240` export.

use crate::cheats;
pub use crate::grammar::{ActorComponent, BodyKit, Cheat, Variant};
use crate::grammar::{ZeroRelation, LANES};
use crate::model::{constructors, ForgeBody, Roots, Stage, AUTHORING_SR, GAIN_MAX, RMAX};

impl ActorComponent {
    pub fn stage(self) -> Stage {
        let mut stage = match self {
            Self::Pressure55 => constructors::sub_anchor(55.0, 0.93, 0.92),
            Self::Pressure80 => constructors::sub_anchor(80.0, 0.92, 0.95),
            Self::Knock160 => constructors::peak_canyon(160.0, 0.955, 118.0, 0.56, 1.22),
            Self::Wood180 => constructors::peak_canyon(180.0, 0.90, 125.0, 0.55, 0.98),
            Self::Throat320 => constructors::peak_canyon(320.0, 0.91, 250.0, 0.62, 1.02),
            Self::Box500 => constructors::peak_canyon(500.0, 0.91, 380.0, 0.70, 1.05),
            Self::Formant700 => constructors::peak_canyon(700.0, 0.94, 520.0, 0.66, 1.08),
            Self::Nasal900 => constructors::nasal_excavation(900.0),
            Self::Wall1100 => constructors::peak_canyon(1100.0, 0.93, 740.0, 0.62, 0.96),
            Self::Bite1400 => constructors::peak_canyon(1400.0, 0.965, 980.0, 0.62, 1.18),
            Self::Bite2400 => constructors::peak_canyon(2400.0, 0.955, 1700.0, 0.64, 1.16),
            Self::TearZero4200 => constructors::carve(4200.0, 0.987),
            Self::Shred6800 => constructors::peak_canyon(6800.0, 0.90, 6100.0, 0.985, 0.82),
            Self::Air9000 => constructors::peak_canyon(9000.0, 0.83, 13500.0, 0.92, 1.16),
            Self::Comb260 => constructors::peak_canyon(260.0, 0.90, 289.0, 0.94, 0.82),
            Self::Comb390 => constructors::peak_canyon(390.0, 0.90, 433.0, 0.94, 0.82),
            Self::Comb590 => constructors::peak_canyon(590.0, 0.90, 655.0, 0.94, 0.82),
            Self::Metal310 => constructors::peak_canyon(310.0, 0.965, 180.0, 0.58, 1.05),
            Self::Metal900 => constructors::peak_canyon(900.0, 0.975, 1260.0, 0.88, 1.12),
            Self::Metal2300 => constructors::peak_canyon(2300.0, 0.970, 3900.0, 0.90, 1.06),
        };
        stage.role = self.spec().role.into();
        stage.provenance = format!("actor component {}", self.label());
        stage
    }
}

pub fn apply_body_kit(body: &mut ForgeBody, kit: BodyKit) {
    *body = ForgeBody::blank(&format!("{} KIT", kit.label()));
    for (lane, component) in kit.actors().into_iter().enumerate() {
        body.corners[0][lane] = component.stage();
    }
    for ci in 1..4 {
        body.corners[ci] = body.corners[0].clone();
    }
    body.secondary_degenerate = false;
    for lane in 0..LANES {
        for variant in Variant::ALL {
            let ci = variant.corner();
            body.corners[ci][lane] = shape_variant(&body.corners[0][lane], kit, lane, variant);
        }
    }
    repair_for_body240(body);
    body.constructor_history
        .push(format!("body kit {} -> six Hz actors", kit.label()));
}

pub fn drop_actor_component(body: &mut ForgeBody, lane: usize, component: ActorComponent) {
    let lane = lane.min(LANES - 1);
    let base = component.stage();
    for variant in Variant::ALL {
        body.corners[variant.corner()][lane] = shape_variant(&base, BodyKit::Knock, lane, variant);
    }
    body.secondary_degenerate = false;
    repair_for_body240(body);
    body.constructor_history.push(format!(
        "component {} dropped to lane {}",
        component.label(),
        lane + 1
    ));
}

pub fn apply_cheat(body: &mut ForgeBody, cheat: Cheat) -> String {
    match cheat {
        Cheat::MakeCornersWork => {
            repair_for_body240(body);
            "clamped illegal Hz/radius/gain while preserving lane identity".into()
        }
        Cheat::MakeMountainous => {
            make_mountainous(body);
            repair_for_body240(body);
            "raised peaks, deepened canyons, kept six rows".into()
        }
        Cheat::MakeFourCornersDistinct => {
            make_four_corners_distinct(body);
            repair_for_body240(body);
            "pushed HOME/AWAY/TIGHT apart without reordering rows".into()
        }
        Cheat::FixMidpoint => {
            fix_midpoint(body);
            repair_for_body240(body);
            "softened midpoint risk from the same six actors".into()
        }
        Cheat::AddTear => {
            add_tear(body);
            repair_for_body240(body);
            "localized a lane-5 tear zero against the bite lane".into()
        }
        Cheat::AddAir => {
            add_air(body);
            repair_for_body240(body);
            "added a high air actor in lane 6".into()
        }
        Cheat::ProtectSub => {
            protect_sub(body);
            repair_for_body240(body);
            "pinned lane 1 to stay sub-safe".into()
        }
        Cheat::MakeQDoQ => {
            make_q_do_q(body);
            repair_for_body240(body);
            "made Secondary tighten/deepen instead of moving Hz".into()
        }
        Cheat::BakeCheatsToSix => {
            let report = cheats::bake_overlay(body, &cheats::tilt_framed_voice_overlay());
            repair_for_body240(body);
            format!(
                "baked {} virtual actors to six rows ({:.1} dB RMS)",
                report.virtual_actor_count, report.rms_error_db
            )
        }
    }
}

pub fn smart_select_high_actors(body: &ForgeBody, corner: usize) -> Vec<usize> {
    body.corners[corner.min(3)]
        .iter()
        .enumerate()
        .filter_map(|(lane, stage)| {
            stage_pole_hz(stage)
                .filter(|hz| *hz >= 2500.0)
                .map(|_| lane)
        })
        .collect()
}

pub fn smart_select_zeros(body: &ForgeBody, corner: usize) -> Vec<usize> {
    body.corners[corner.min(3)]
        .iter()
        .enumerate()
        .filter_map(|(lane, stage)| {
            if stage.zero.is_some() {
                Some(lane)
            } else {
                None
            }
        })
        .collect()
}

pub fn smart_select_pinned(body: &ForgeBody, corner: usize) -> Vec<usize> {
    body.corners[corner.min(3)]
        .iter()
        .enumerate()
        .filter_map(|(lane, stage)| stage.locked.then_some(lane))
        .collect()
}

fn shape_variant(base: &Stage, kit: BodyKit, lane: usize, variant: Variant) -> Stage {
    let mut out = base.clone();
    let (morph, q) = variant.morph_q();
    let morph = morph as f64;
    let q = q as f64;
    let lane_rank = lane as f64 / (LANES - 1) as f64;
    let kit_spec = kit.spec();
    let kit_spread = kit_spec.morph_spread;
    let pole_oct = (lane_rank - 0.30) * kit_spread * morph;
    let zero_oct = match kit_spec.zero_relation {
        ZeroRelation::OpposesPole => -pole_oct * 0.75,
        ZeroRelation::FollowsPole => pole_oct * 0.45,
    };
    move_roots(&mut out.pole, pole_oct, 0.018 * q, true);
    if let Some(zero) = &mut out.zero {
        move_roots(zero, zero_oct, 0.028 * q, false);
    }
    out.gain = (out.gain * (1.0 + 0.08 * morph + 0.06 * q)).clamp(0.02, GAIN_MAX);
    out.provenance = format!("{} | {}", out.provenance, variant.label());
    out
}

fn make_mountainous(body: &mut ForgeBody) {
    for stage in body.corners.iter_mut().flatten() {
        if stage.locked {
            continue;
        }
        stage.gain = (stage.gain * 1.12 + 0.04).clamp(0.02, GAIN_MAX);
        move_roots(&mut stage.pole, 0.0, 0.025, true);
        if let Some(zero) = &mut stage.zero {
            move_roots(zero, 0.0, 0.020, false);
        }
    }
    body.constructor_history
        .push("cheat make mountainous".into());
}

fn make_four_corners_distinct(body: &mut ForgeBody) {
    for ci in 0..4 {
        let morph = if ci & 1 == 1 { 1.0 } else { 0.0 };
        let q = if ci & 2 == 2 { 1.0 } else { 0.0 };
        for (lane, stage) in body.corners[ci].iter_mut().enumerate() {
            if stage.locked {
                continue;
            }
            let rank = lane as f64 / (LANES - 1) as f64;
            let signed = -0.5 + rank;
            move_roots(&mut stage.pole, signed * 0.42 * morph, 0.025 * q, true);
            if let Some(zero) = &mut stage.zero {
                move_roots(zero, -signed * 0.32 * morph, 0.018 * q, false);
            }
            stage.gain = (stage.gain * (1.0 + signed.abs() * 0.16 * morph)).clamp(0.02, GAIN_MAX);
        }
    }
    body.secondary_degenerate = false;
    body.constructor_history
        .push("cheat make four corners distinct".into());
}

fn fix_midpoint(body: &mut ForgeBody) {
    for stage in body.corners.iter_mut().flatten() {
        if stage.locked {
            continue;
        }
        stage.gain = (stage.gain * 0.96).clamp(0.02, GAIN_MAX);
        if let Roots::Complex { radius, .. } = &mut stage.pole {
            *radius = (*radius - 0.012).clamp(0.0, RMAX);
        }
    }
    body.constructor_history.push("cheat fix midpoint".into());
}

fn add_tear(body: &mut ForgeBody) {
    let lane = 4;
    for ci in 0..4 {
        let bite_hz = stage_pole_hz(&body.corners[ci][3]).unwrap_or(1400.0);
        let tear_hz = (bite_hz * 3.0).clamp(3200.0, 6200.0);
        let mut stage = constructors::carve(tear_hz, 0.990);
        stage.role = "TEAR-".into();
        stage.provenance = format!("cheat add tear against bite {bite_hz:.0}");
        body.corners[ci][lane] = stage;
    }
    body.secondary_degenerate = false;
    body.constructor_history.push("cheat add tear".into());
}

fn add_air(body: &mut ForgeBody) {
    let lane = 5;
    let base = ActorComponent::Air9000.stage();
    for variant in Variant::ALL {
        body.corners[variant.corner()][lane] = shape_variant(&base, BodyKit::Metal, lane, variant);
    }
    body.secondary_degenerate = false;
    body.constructor_history.push("cheat add air".into());
}

fn protect_sub(body: &mut ForgeBody) {
    for corner in &mut body.corners {
        corner[0].locked = true;
        if let Roots::Complex { freq_hz, radius } = &mut corner[0].pole {
            *freq_hz = (*freq_hz).clamp(45.0, 160.0);
            *radius = (*radius).clamp(0.70, 0.955);
        }
        corner[0].gain = corner[0].gain.clamp(0.25, 1.15);
    }
    body.constructor_history.push("cheat protect sub".into());
}

fn make_q_do_q(body: &mut ForgeBody) {
    for morph_edge in 0..2 {
        let source = body.corners[morph_edge].clone();
        let tight = morph_edge + 2;
        body.corners[tight] = source;
        for stage in &mut body.corners[tight] {
            if stage.locked {
                continue;
            }
            if let Roots::Complex { radius, .. } = &mut stage.pole {
                *radius = (*radius + 0.045).clamp(0.0, RMAX);
            }
            if let Some(zero) = &mut stage.zero {
                if let Roots::Complex { radius, .. } = zero {
                    *radius = (*radius + 0.055).clamp(0.0, 0.999);
                }
            }
            stage.gain = (stage.gain * 1.06).clamp(0.02, GAIN_MAX);
        }
    }
    body.secondary_degenerate = false;
    body.constructor_history.push("cheat make q do q".into());
}

fn repair_for_body240(body: &mut ForgeBody) {
    for stage in body.corners.iter_mut().flatten() {
        clamp_stage(stage);
    }
}

fn clamp_stage(stage: &mut Stage) {
    stage.ensure_zero();
    clamp_roots(&mut stage.pole, true);
    if let Some(zero) = &mut stage.zero {
        clamp_roots(zero, false);
    }
    stage.gain = stage.gain.clamp(0.0, GAIN_MAX);
}

fn clamp_roots(roots: &mut Roots, pole: bool) {
    match roots {
        Roots::Complex { freq_hz, radius } => {
            *freq_hz = legal_hz(*freq_hz);
            let max = if pole { RMAX } else { 0.999 };
            *radius = radius.clamp(0.0, max);
        }
        Roots::Real { a, b } => {
            *a = a.clamp(-0.999, 0.999);
            *b = b.clamp(-0.999, 0.999);
        }
    }
}

fn move_roots(roots: &mut Roots, octaves: f64, radius_push: f64, pole: bool) {
    match roots {
        Roots::Complex { freq_hz, radius } => {
            *freq_hz = legal_hz(*freq_hz * 2f64.powf(octaves));
            let max = if pole { RMAX } else { 0.999 };
            *radius = (*radius + radius_push).clamp(0.0, max);
        }
        Roots::Real { .. } => {}
    }
}

fn stage_pole_hz(stage: &Stage) -> Option<f64> {
    match stage.pole {
        Roots::Complex { freq_hz, .. } => Some(freq_hz),
        Roots::Real { .. } => None,
    }
}

fn legal_hz(freq: f64) -> f64 {
    freq.clamp(30.0, AUTHORING_SR * 0.45)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_body_kit_bakes_to_a_valid_body240_surface() {
        for kit in BodyKit::ALL {
            let mut body = ForgeBody::blank("test");
            apply_body_kit(&mut body, kit);
            let compiled = body.compile();
            assert_eq!(compiled.bytes.len(), 240);
            assert!(
                compiled.audit.pass(),
                "{} failed packed audit: {:?}",
                kit.label(),
                compiled.audit.errors
            );
            assert!(!body.secondary_degenerate);
            assert_eq!(body.corners.len(), 4);
            assert_eq!(body.corners[0].len(), LANES);
        }
    }

    #[test]
    fn q_cheat_tightens_without_moving_hz() {
        let mut body = ForgeBody::blank("q");
        apply_body_kit(&mut body, BodyKit::Vowel);
        let before_home = stage_pole_hz(&body.corners[0][2]).unwrap();
        let before_away = stage_pole_hz(&body.corners[1][2]).unwrap();
        apply_cheat(&mut body, Cheat::MakeQDoQ);
        let tight_home = stage_pole_hz(&body.corners[2][2]).unwrap();
        let tight_away = stage_pole_hz(&body.corners[3][2]).unwrap();
        assert!((tight_home - before_home).abs() < 1e-9);
        assert!((tight_away - before_away).abs() < 1e-9);
        assert!(body.compile().audit.pass());
    }

    #[test]
    fn smart_selection_finds_high_zero_and_pinned_lanes() {
        let mut body = ForgeBody::blank("select");
        apply_body_kit(&mut body, BodyKit::Violence);
        apply_cheat(&mut body, Cheat::ProtectSub);
        assert!(smart_select_high_actors(&body, 0).contains(&4));
        assert!(smart_select_zeros(&body, 0).contains(&4));
        assert_eq!(smart_select_pinned(&body, 0), vec![0]);
    }
}
