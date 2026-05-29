# SOURCE FIELD coding rules

This is a Rust + eframe/egui DSP filter-design app.

Do not add:
- React
- Tauri
- web UI
- CSS
- Bevy
- Slint
- generic dashboard panels
- toolbar/sidebar/inspector layouts

UI rules:
- Main app is one spatial field.
- Use egui Painter primitives.
- Four source wells around the field.
- One central response curve.
- No generic buttons unless explicitly requested.
- No skeuomorphic plugin hardware.
- No sci-fi HUD.

Architecture:
- UI never owns DSP fitting logic.
- DSP lives in source_core.
- Audio IO lives in source_audio.
- UI calls pure model functions and renders their result.
- Every visual element must be reproducible from explicit structs.

Before changing visuals:
- edit `source_ui/src/style.rs`
- edit `source_ui/src/field_view.rs`
- do not scatter colours or geometry constants through the app