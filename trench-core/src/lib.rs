pub mod minifloat;

pub mod agc;
pub mod arma;
pub mod cartridge;
pub mod cascade;
pub mod cluster;
pub mod compiler;
pub mod cvsd_input;
pub mod desk_drive;
pub mod dsp;
pub mod emu_resonator;
pub mod engine;
pub mod ffi;
pub mod function_generator;
pub mod hedz_rom;
pub mod lpc;
pub mod motor;
pub mod phantom_voice;
pub mod qsound_spatial;
pub mod response;
pub mod role;
pub mod seed;
pub mod stage_law;
pub mod transition;
pub mod trench_matrix;

pub use agc::agc_step;
pub use cartridge::{Cartridge, CornerData};
pub use cascade::{Cascade, EncodedCoeffs, BLOCK_SIZE, NUM_COEFFS, NUM_STAGES, TOTAL_STAGES};
pub use cluster::{Cluster, ClusterPlan, ClusterStage, InterferenceLink, StageFunction};
pub use engine::{DebugToggles, FilterEngine, InputMode, SpatialMode};
pub use motor::{ForceCurve, Motor, MotorId};
pub use phantom_voice::{
    LfoShape, ModDest, ModSource, Patchcord, PhantomEnvelope, PhantomLfo, PhantomVoice,
    RoutingMatrix, MAX_CORDS, NUM_ENVS, NUM_LFOS,
};
pub use response::{
    audit_kernel_surface, biquad_response_curve, kernel_response_curve, ResponseSurfaceAudit,
};
pub use role::Role;
pub use stage_law::{
    geometry_from_words, roots_from_words, words_from_roots, RootPair, StageGeometry, StageRoots,
};
