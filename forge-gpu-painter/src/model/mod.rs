// model — the authoring document layer.
//
// Grows as the monolith decomposes: peak_shelf is the Dillusion-style
// authoring grammar (two morph frames × FREQ/SHELF/PEAK + MORPH/PRESSURE/
// MASTER) that compiles to the six pole-zero sections the packed runtime
// actually runs. Nothing in here touches packed words directly — output is
// always Vec<Section>, which flows through the one true pipeline
// (params168 → trench_core::compiler::pack_body).

pub mod peak_shelf;
