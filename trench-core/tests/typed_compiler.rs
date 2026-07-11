use trench_core::compiler::{
    pack_typed_body, section_biquad, AUTHORING_SR, TAU, TYPED_PARAM_LEN, TYPE_BANDPASS,
    TYPE_HIGHPASS, TYPE_HIGH_SHELF, TYPE_LOWPASS, TYPE_LOW_SHELF_CONTROLLED, TYPE_NOTCH, TYPE_PEAK,
};
use trench_core::minifloat::{pole_radius, PackedCorners};

fn mag_db(bq: [f64; 5], hz: f64) -> f64 {
    let [b0, b1, b2, a1, a2] = bq;
    let w = TAU * hz / AUTHORING_SR;
    let (s1, c1) = w.sin_cos();
    let (s2, c2) = (2.0 * w).sin_cos();
    let nr = b0 + b1 * c1 + b2 * c2;
    let ni = -(b1 * s1 + b2 * s2);
    let dr = 1.0 + a1 * c1 + a2 * c2;
    let di = -(a1 * s1 + a2 * s2);
    20.0 * (nr.hypot(ni) / dr.hypot(di).max(1e-12)).max(1e-12).log10()
}

fn pole_hz(bq: [f64; 5]) -> f64 {
    let [_, _, _, a1, a2] = bq;
    let r = pole_radius(a1, a2);
    let cos_theta = (-a1 / (2.0 * r)).clamp(-1.0, 1.0);
    cos_theta.acos() * AUTHORING_SR / TAU
}

#[test]
fn typed_sections_are_finite_positive_and_stable() {
    for (type_id, gain_db) in [
        (TYPE_PEAK, 12.0),
        (TYPE_LOW_SHELF_CONTROLLED, 6.0),
        (TYPE_NOTCH, -18.0),
        (TYPE_LOWPASS, 0.0),
        (TYPE_HIGHPASS, 0.0),
        (TYPE_BANDPASS, 0.0),
        (TYPE_HIGH_SHELF, -6.0),
    ] {
        let bq = section_biquad(type_id, 1200.0, 4.0, gain_db);
        assert!(bq.iter().all(|v| v.is_finite()), "type {type_id}: {bq:?}");
        assert!(bq[0] > 0.0, "type {type_id} b0 must stay packable: {bq:?}");
        assert!(
            pole_radius(bq[3], bq[4]) < 1.0,
            "type {type_id} unstable: {bq:?}"
        );
    }
}

#[test]
fn peak_and_notch_have_the_expected_local_shape() {
    let peak = section_biquad(TYPE_PEAK, 1200.0, 6.0, 12.0);
    assert!(mag_db(peak, 1200.0) > mag_db(peak, 200.0) + 8.0);
    assert!(mag_db(peak, 1200.0) > mag_db(peak, 7000.0) + 8.0);

    let notch = section_biquad(TYPE_NOTCH, 1800.0, 8.0, -24.0);
    assert!(mag_db(notch, 1800.0) < mag_db(notch, 350.0) - 10.0);
    assert!(mag_db(notch, 1800.0) < mag_db(notch, 8000.0) - 10.0);
}

#[test]
fn six_typed_cards_pack_to_a_valid_body_with_log_morph_edges() {
    let cards = [
        TYPE_LOW_SHELF_CONTROLLED as f64,
        75.0,
        75.0,
        0.7,
        0.7,
        6.0,
        1.0,
        TYPE_PEAK as f64,
        300.0,
        950.0,
        5.0,
        12.0,
        14.0,
        1.0,
        TYPE_PEAK as f64,
        1900.0,
        650.0,
        5.0,
        12.0,
        13.0,
        1.0,
        TYPE_PEAK as f64,
        2500.0,
        2500.0,
        6.0,
        10.0,
        9.0,
        1.0,
        TYPE_PEAK as f64,
        3400.0,
        3400.0,
        6.0,
        9.0,
        6.0,
        1.0,
        TYPE_HIGH_SHELF as f64,
        9000.0,
        9000.0,
        0.7,
        0.7,
        -5.0,
        1.0,
    ];
    assert_eq!(cards.len(), TYPED_PARAM_LEN);
    let body = pack_typed_body(&cards);
    assert_eq!(body.len(), 240);

    let packed = PackedCorners::from_body_bytes(&body).expect("typed body parses");
    let home = packed.interpolate_biquad(0.0, 0.0);
    let away = packed.interpolate_biquad(1.0, 0.0);
    let tight = packed.interpolate_biquad(1.0, 1.0);

    let home_hz = pole_hz(home[1]);
    let away_hz = pole_hz(away[1]);
    assert!((home_hz - 300.0).abs() < 12.0, "home_hz={home_hz}");
    assert!((away_hz - 950.0).abs() < 25.0, "away_hz={away_hz}");

    for row in home.iter().chain(away.iter()).chain(tight.iter()) {
        assert!(row.iter().all(|v| v.is_finite()), "{row:?}");
        assert!(pole_radius(row[3], row[4]) < 1.0, "{row:?}");
    }
}
