use trench_core::cartridge::BODY_BYTES;
use trench_core::minifloat::PackedCorners;
use trench_core::{Cartridge, CornerData, FilterEngine, InputMode, SpatialMode, NUM_STAGES};

fn identity_body240() -> [u8; BODY_BYTES] {
    let identity_stage = [2.0, 1.0, 2.0, 1.0, 1.0];
    let identity_corner: CornerData = [identity_stage; NUM_STAGES];
    PackedCorners::from_corner_data(&[identity_corner; 4]).to_rom_bytes()
}

fn assert_digital_silence(label: &str, samples: &[f32]) {
    for (i, &sample) in samples.iter().enumerate() {
        assert_eq!(
            sample.to_bits(),
            0.0f32.to_bits(),
            "{label} sample {i} was not digital silence: {sample}"
        );
    }
}

#[test]
fn raw_body_engine_silence_in_is_digital_silence_out() {
    let body = identity_body240();
    let mut engine = FilterEngine::new();
    engine.prepare(39062.5);
    engine.load_cartridge(Cartridge::from_body_bytes("identity", &body, 1.0).unwrap());
    engine.set_input_mode(InputMode::None);
    engine.set_spatial_mode(SpatialMode::Off);

    let mut left = vec![0.0f32; 2048];
    let mut right = vec![0.0f32; 2048];
    engine.process_block(&mut left, &mut right, 0.5, 0.5);

    assert_digital_silence("left", &left);
    assert_digital_silence("right", &right);
    assert!(!engine.take_instability_flag());
}

#[test]
fn raw_body_ffi_silence_in_is_digital_silence_out() {
    let body = identity_body240();
    let mut left = vec![0.0f32; 2048];
    let mut right = vec![0.0f32; 2048];

    unsafe {
        let engine = trench_core::ffi::trench_engine_create();
        assert!(!engine.is_null(), "trench_engine_create returned null");
        trench_core::ffi::trench_engine_prepare(engine, 39062.5);
        assert_eq!(
            trench_core::ffi::trench_engine_load_body_bytes(engine, body.as_ptr(), body.len()),
            0
        );
        trench_core::ffi::trench_engine_set_input_mode(engine, 0);
        trench_core::ffi::trench_engine_set_spatial_mode(engine, 2);
        trench_core::ffi::trench_engine_process_block(
            engine,
            left.as_mut_ptr(),
            right.as_mut_ptr(),
            left.len() as i32,
            0.5,
            0.5,
        );
        trench_core::ffi::trench_engine_destroy(engine);
    }

    assert_digital_silence("ffi left", &left);
    assert_digital_silence("ffi right", &right);
}
