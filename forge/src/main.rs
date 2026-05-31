//! Filter Factory — private df2 authoring bench.

#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

mod app;
mod audio;
mod capture;
mod corner_library;
mod dsp;
mod forge_core;
mod generators;
mod paint;
mod player;
mod push;
mod shape;
mod source;
mod style;

fn main() -> eframe::Result<()> {
    app::run()
}
