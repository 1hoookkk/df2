use trench_core::cartridge::Cartridge;
use trench_core::minifloat::{stage_words_to_biquad, PackedCorners, PackedStage};

#[test]
fn existing_cartridge_without_new_blocks_loads_with_safe_defaults() {
    let json = format!("{{ {stub} }}", stub = KEYFRAMES_STUB);
    let cart = Cartridge::from_json(&json).expect("parse");
    assert_eq!(cart.drive.input_gain_db, 0.0);
    assert_eq!(cart.drive.model, "mackie_1202");
    assert!(cart.spatial_profile.is_none());
    assert!(cart.mod_fn.is_none());
}

#[test]
fn cartridge_with_drive_mod_fn_spatial_parses() {
    // Minimum keyframes stub that passes the existing compiled-v1 parser.
    let json = r#"{
      "format": "compiled-v1",
      "name": "test",
      "sampleRate": 48000,
      "keyframes": [
        {"label": "M0_Q0", "stages": [
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}
        ]},
        {"label": "M100_Q0", "stages": [
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}
        ]},
        {"label": "M0_Q100", "stages": [
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}
        ]},
        {"label": "M100_Q100", "stages": [
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}
        ]}
      ],
      "drive": { "input_gain_dB": 9.0, "model": "mackie_1202" },
      "mod_fn": {
        "segments": [{ "level": 1.0, "time_ms": 50, "shape": "exp" }],
        "key-sync": 1, "tempo-sync": 1
      }
    }"#;
    let cart = Cartridge::from_json(json).expect("parse");
    assert_eq!(cart.drive.input_gain_db, 9.0);
    let mf = cart.mod_fn.as_ref().expect("mod_fn present");
    assert_eq!(mf.segments[0].level, 1.0);
    assert!(mf.key_sync());
    assert!(mf.tempo_sync());
}

#[test]
fn packed_words_take_precedence_and_interpolate_in_packed_domain() {
    const PASS: PackedStage = [0xDFFF, 0xFFFF, 0xDFFF, 0xFFFF, 0xDFFF];
    const FIRST_ROWS: [PackedStage; 4] = [
        [7549, 44668, 27391, 50821, 56688],
        [7549, 44668, 40758, 50193, 56688],
        [7549, 44668, 31012, 47431, 57015],
        [7549, 44668, 45317, 46149, 57015],
    ];

    let mut packed = [[[0u16; 5]; 6]; 4];
    let labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
    let keyframes = labels
        .iter()
        .enumerate()
        .map(|(ci, label)| {
            let mut rows = vec![PASS.to_vec(); 6];
            rows[0] = FIRST_ROWS[ci].to_vec();
            for si in 0..6 {
                packed[ci][si].copy_from_slice(&rows[si]);
            }
            serde_json::json!({
                "label": label,
                "stages": [
                    {"c0":99,"c1":99,"c2":99,"c3":99,"c4":99},
                    {"c0":99,"c1":99,"c2":99,"c3":99,"c4":99},
                    {"c0":99,"c1":99,"c2":99,"c3":99,"c4":99},
                    {"c0":99,"c1":99,"c2":99,"c3":99,"c4":99},
                    {"c0":99,"c1":99,"c2":99,"c3":99,"c4":99},
                    {"c0":99,"c1":99,"c2":99,"c3":99,"c4":99}
                ],
                "packedWords": rows
            })
        })
        .collect::<Vec<_>>();

    let json = serde_json::json!({
        "format": "compiled-v1",
        "name": "packed precedence",
        "sampleRate": 39062.5,
        "keyframes": keyframes
    })
    .to_string();
    let cart = Cartridge::from_json(&json).expect("packed cart parses");

    let home = cart.interpolate(0.0, 0.0);
    assert_eq!(home[0], stage_words_to_biquad(FIRST_ROWS[0]));

    let expected_mid = PackedCorners { words: packed }.interpolate_biquad(0.5, 0.5);
    let got_mid = cart.interpolate(0.5, 0.5);
    for si in 0..6 {
        for wi in 0..5 {
            assert!(
                (got_mid[si][wi] - expected_mid[si][wi]).abs() < 1.0e-12,
                "stage {si} coeff {wi}: got {} expected {}",
                got_mid[si][wi],
                expected_mid[si][wi]
            );
        }
    }
}

const KEYFRAMES_STUB: &str = r#"
      "format": "compiled-v1",
      "name": "space test",
      "sampleRate": 48000,
      "keyframes": [
        {"label": "M0_Q0", "stages": [
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}
        ]},
        {"label": "M100_Q0", "stages": [
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}
        ]},
        {"label": "M0_Q100", "stages": [
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}
        ]},
        {"label": "M100_Q100", "stages": [
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
          {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}
        ]}
      ]"#;

/// Canonical recon coefficients from docs/archive/qsound_spatial.md. These
/// are the shape the C++ parser must also accept (byte-for-byte parity tested
/// on the JUCE side in `PluginBasics.cpp`).
fn canonical_spatial_profile_block() -> &'static str {
    r#""spatial_profile": {
        "azimuth": 0.5235987755982988,
        "distance": 1.0,
        "elevation": 0.0,
        "itd_coeffs": [
            3578.7646232504208, -99.11300089026597, -960.7096166779854,
             631.0360877559084, -229.78233226297414, -173.11867492761178
        ],
        "ild_coeffs": [
            6.819731516349544, -2.5008130981129657, 0.8210199212077876,
           -0.198121089137829,  0.021401263894609834, 8.819077411548193e-05
        ],
        "band_coeffs": {
            "l": {
                "low":  [-72.211726, 0.386310, -1.609965, -2.942365, 4.905630, 0.894425, -1.686776, -0.082666, 0.833466, 0.0, 0.0, 0.0],
                "mid":  [-74.892487, 0.460364, -1.645200, -2.794224, 9.547364, 1.100615, -2.989885, -0.168168, 1.485241, 0.0, 0.0, 0.0],
                "high": [-73.911507, 0.438043, -1.634712, -2.835356, 8.046734, 1.041892, -2.546882, -0.132837, 1.302472, 0.0, 0.0, 0.0]
            },
            "r": {
                "low":  [-72.211726, 0.386310, -1.609965,  2.942365, 4.905630, -0.894425, -1.686776,  0.082666, 0.833466, 0.0, 0.0, 0.0],
                "mid":  [-74.892487, 0.460364, -1.645200,  2.794224, 9.547364, -1.100615, -2.989885,  0.168168, 1.485241, 0.0, 0.0, 0.0],
                "high": [-73.911507, 0.438043, -1.634712,  2.835356, 8.046734, -1.041892, -2.546882,  0.132837, 1.302472, 0.0, 0.0, 0.0]
            }
        }
    }"#
}

#[test]
fn cartridge_with_typed_spatial_profile_parses() {
    let json = format!(
        "{{ {stub}, {spatial} }}",
        stub = KEYFRAMES_STUB,
        spatial = canonical_spatial_profile_block()
    );
    let cart = Cartridge::from_json(&json).expect("parse");
    let sp = cart
        .spatial_profile
        .as_ref()
        .expect("spatial_profile present");

    assert!((sp.azimuth - 0.523_598_78_f32).abs() < 1e-5);
    assert_eq!(sp.distance, 1.0);
    assert_eq!(sp.elevation, 0.0);

    // ITD / ILD: spot-check first and last coefficients.
    assert!((sp.itd_coeffs[0] - 3578.764_6_f32).abs() < 1e-2);
    assert!((sp.itd_coeffs[5] - -173.118_67_f32).abs() < 1e-2);
    assert!((sp.ild_coeffs[0] - 6.819_731_5_f32).abs() < 1e-5);
    assert!((sp.ild_coeffs[5] - 8.819_077e-5_f32).abs() < 1e-8);

    // Band: l.low[0] and r.low[3] are mirrored across channels.
    assert!((sp.band_coeffs.l.low[0] - -72.211_726_f32).abs() < 1e-3);
    assert!((sp.band_coeffs.l.low[3] - -2.942_365_f32).abs() < 1e-5);
    assert!((sp.band_coeffs.r.low[3] - 2.942_365_f32).abs() < 1e-5);
    assert!((sp.band_coeffs.l.high[8] - 1.302_472_f32).abs() < 1e-5);
}

#[test]
fn spatial_profile_missing_required_field_is_rejected() {
    // Drop `elevation` from a valid block — serde must refuse the cartridge
    // rather than silently substituting a default.
    let bad = r#""spatial_profile": {
        "azimuth": 0.0,
        "distance": 1.0,
        "itd_coeffs": [0,0,0,0,0,0],
        "ild_coeffs": [0,0,0,0,0,0],
        "band_coeffs": {
            "l": { "low":[0,0,0,0,0,0,0,0,0,0,0,0], "mid":[0,0,0,0,0,0,0,0,0,0,0,0], "high":[0,0,0,0,0,0,0,0,0,0,0,0] },
            "r": { "low":[0,0,0,0,0,0,0,0,0,0,0,0], "mid":[0,0,0,0,0,0,0,0,0,0,0,0], "high":[0,0,0,0,0,0,0,0,0,0,0,0] }
        }
    }"#;
    let json = format!("{{ {stub}, {bad} }}", stub = KEYFRAMES_STUB, bad = bad);
    assert!(Cartridge::from_json(&json).is_err());
}

#[test]
fn spatial_profile_wrong_array_length_is_rejected() {
    // itd_coeffs is 5 elements instead of 6.
    let bad = r#""spatial_profile": {
        "azimuth": 0.0,
        "distance": 1.0,
        "elevation": 0.0,
        "itd_coeffs": [0,0,0,0,0],
        "ild_coeffs": [0,0,0,0,0,0],
        "band_coeffs": {
            "l": { "low":[0,0,0,0,0,0,0,0,0,0,0,0], "mid":[0,0,0,0,0,0,0,0,0,0,0,0], "high":[0,0,0,0,0,0,0,0,0,0,0,0] },
            "r": { "low":[0,0,0,0,0,0,0,0,0,0,0,0], "mid":[0,0,0,0,0,0,0,0,0,0,0,0], "high":[0,0,0,0,0,0,0,0,0,0,0,0] }
        }
    }"#;
    let json = format!("{{ {stub}, {bad} }}", stub = KEYFRAMES_STUB, bad = bad);
    assert!(Cartridge::from_json(&json).is_err());
}
