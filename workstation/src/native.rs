use crate::app::AppState;
use crate::model::{
    ActorProvenance, EditField, EditRequest, EvidenceReference, Session, WorkstationError,
};
use crate::source_xml::SourceEndpoint;
use std::ffi::{c_char, c_int, CStr};
use std::ptr;

const FFI_ERROR: usize = usize::MAX;

#[repr(C)]
pub struct WorkstationState {
    app: AppState,
    last_error: String,
}

fn state_mut<'a>(
    state: *mut WorkstationState,
) -> Result<&'a mut WorkstationState, WorkstationError> {
    if state.is_null() {
        return Err(WorkstationError("null workstation state".to_owned()));
    }
    Ok(unsafe { &mut *state })
}

fn repo_root(path: *const c_char) -> Result<std::path::PathBuf, WorkstationError> {
    if path.is_null() {
        return Err(WorkstationError("null repository path".to_owned()));
    }
    let value = unsafe { CStr::from_ptr(path) }
        .to_str()
        .map_err(|_| WorkstationError("repository path is not UTF-8".to_owned()))?;
    std::fs::canonicalize(value).map_err(|error| {
        WorkstationError(format!(
            "repository path '{}' could not be canonicalized: {error}",
            value
        ))
    })
}

fn record<T>(
    state: &mut WorkstationState,
    operation: impl FnOnce(&mut AppState) -> Result<T, WorkstationError>,
) -> Result<T, WorkstationError> {
    match operation(&mut state.app) {
        Ok(value) => {
            state.last_error.clear();
            Ok(value)
        }
        Err(error) => {
            state.last_error = error.to_string();
            Err(error)
        }
    }
}

fn copy_bytes(out: *mut u8, capacity: usize, bytes: &[u8]) -> usize {
    if !out.is_null() && capacity > 0 {
        let count = capacity.min(bytes.len());
        unsafe { ptr::copy_nonoverlapping(bytes.as_ptr(), out, count) };
    }
    bytes.len()
}

fn copy_json(
    state: *mut WorkstationState,
    out: *mut u8,
    capacity: usize,
    value: Result<String, WorkstationError>,
) -> usize {
    let Ok(state) = (unsafe { state.as_mut() })
        .ok_or_else(|| WorkstationError("null workstation state".to_owned()))
    else {
        return FFI_ERROR;
    };
    match value {
        Ok(value) => {
            state.last_error.clear();
            copy_bytes(out, capacity, value.as_bytes())
        }
        Err(error) => {
            state.last_error = error.to_string();
            FFI_ERROR
        }
    }
}

fn field(value: c_int) -> Result<EditField, WorkstationError> {
    match value {
        0 => Ok(EditField::ZeroHz),
        1 => Ok(EditField::ZeroRadius),
        2 => Ok(EditField::ZeroRootA),
        3 => Ok(EditField::ZeroRootB),
        4 => Ok(EditField::PoleHz),
        5 => Ok(EditField::PoleRadius),
        6 => Ok(EditField::PoleRootA),
        7 => Ok(EditField::PoleRootB),
        8 => Ok(EditField::Scale),
        9 => Ok(EditField::Identity),
        _ => Err(WorkstationError("unknown edit field".to_owned())),
    }
}

fn write_error(state: *mut WorkstationState, out: *mut u8, capacity: usize) -> usize {
    let Some(state) = (unsafe { state.as_ref() }) else {
        return FFI_ERROR;
    };
    copy_bytes(out, capacity, state.last_error.as_bytes())
}

#[no_mangle]
pub extern "C" fn workstation_state_create(path: *const c_char) -> *mut WorkstationState {
    let Ok(root) = repo_root(path) else {
        return ptr::null_mut();
    };
    let Ok(app) = AppState::new(root) else {
        return ptr::null_mut();
    };
    Box::into_raw(Box::new(WorkstationState {
        app,
        last_error: String::new(),
    }))
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_destroy(state: *mut WorkstationState) {
    if !state.is_null() {
        drop(Box::from_raw(state));
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_last_error(
    state: *mut WorkstationState,
    out: *mut u8,
    capacity: usize,
) -> usize {
    write_error(state, out, capacity)
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_snapshot_json(
    state: *mut WorkstationState,
    out: *mut u8,
    capacity: usize,
) -> usize {
    let Ok(state_ref) = state_mut(state) else {
        return FFI_ERROR;
    };
    let value = state_ref
        .app
        .snapshot()
        .and_then(|snapshot| serde_json::to_string(&snapshot).map_err(WorkstationError::from));
    copy_json(state, out, capacity, value)
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_session_json(
    state: *mut WorkstationState,
    out: *mut u8,
    capacity: usize,
) -> usize {
    let Ok(state_ref) = state_mut(state) else {
        return FFI_ERROR;
    };
    copy_json(state, out, capacity, state_ref.app.session.to_json())
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_load_session_json(
    state: *mut WorkstationState,
    json: *const u8,
    json_len: usize,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    if json.is_null() || json_len == 0 || json_len > 8 * 1024 * 1024 {
        state_ref.last_error = "session JSON must contain 1..8388608 UTF-8 bytes".to_owned();
        return -1;
    }
    let bytes = std::slice::from_raw_parts(json, json_len);
    let Ok(json) = std::str::from_utf8(bytes) else {
        state_ref.last_error = "session JSON is not UTF-8".to_owned();
        return -1;
    };
    match record(state_ref, |app| app.load_session_json(json)) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

fn utf8_path<'a>(path: *const c_char, label: &str) -> Result<&'a str, WorkstationError> {
    if path.is_null() {
        return Err(WorkstationError(format!("{label} path is null")));
    }
    unsafe { CStr::from_ptr(path) }
        .to_str()
        .map_err(|_| WorkstationError(format!("{label} path is not UTF-8")))
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_load_body_source(
    state: *mut WorkstationState,
    path: *const c_char,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    let Ok(path) = utf8_path(path, "body source") else {
        state_ref.last_error = "body source path is null or not UTF-8".to_owned();
        return -1;
    };
    match record(state_ref, |app| app.load_body_source(path).map(|_| ())) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_load_body_as_session(
    state: *mut WorkstationState,
    path: *const c_char,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    let Ok(path) = utf8_path(path, "body") else {
        state_ref.last_error = "body path is null or not UTF-8".to_owned();
        return -1;
    };
    match record(state_ref, |app| app.load_body_as_session(path).map(|_| ())) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_stitch_body_corner(
    state: *mut WorkstationState,
    source_corner: usize,
    target_corner: usize,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match record(state_ref, |app| {
        app.stitch_body_corner(source_corner, target_corner)
            .map(|_| ())
    }) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_load_actor_audio(
    state: *mut WorkstationState,
    samples: *const f32,
    sample_count: usize,
    sample_rate_hz: f64,
    source_path: *const c_char,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    if samples.is_null() || source_path.is_null() {
        state_ref.last_error = "actor import requires mono samples and a source path".to_owned();
        return -1;
    }
    let Ok(source_path) = CStr::from_ptr(source_path).to_str() else {
        state_ref.last_error = "actor source path is not UTF-8".to_owned();
        return -1;
    };
    let samples = std::slice::from_raw_parts(samples, sample_count);
    match record(state_ref, |app| {
        app.load_fixed_actor_audio(samples, sample_rate_hz, source_path)
            .map(|_| ())
    }) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_load_verified_actor_audio(
    state: *mut WorkstationState,
    samples: *const f32,
    sample_count: usize,
    sample_rate_hz: f64,
    source_path: *const c_char,
    provenance_json: *const c_char,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    if samples.is_null() || source_path.is_null() || provenance_json.is_null() {
        state_ref.last_error =
            "verified actor import requires mono samples, a source path, and provenance JSON"
                .to_owned();
        return -1;
    }
    let Ok(source_path) = CStr::from_ptr(source_path).to_str() else {
        state_ref.last_error = "actor source path is not UTF-8".to_owned();
        return -1;
    };
    let Ok(provenance_json) = CStr::from_ptr(provenance_json).to_str() else {
        state_ref.last_error = "actor provenance JSON is not UTF-8".to_owned();
        return -1;
    };
    let provenance: ActorProvenance = match serde_json::from_str(provenance_json) {
        Ok(value) => value,
        Err(error) => {
            state_ref.last_error = format!("actor provenance JSON is invalid: {error}");
            return -1;
        }
    };
    let samples = std::slice::from_raw_parts(samples, sample_count);
    match record(state_ref, |app| {
        app.load_verified_actor_audio(samples, sample_rate_hz, source_path, provenance)
            .map(|_| ())
    }) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_keep_json(
    state: *mut WorkstationState,
    out: *mut u8,
    capacity: usize,
) -> usize {
    let Ok(state_ref) = state_mut(state) else {
        return FFI_ERROR;
    };
    let value = record(state_ref, AppState::keep)
        .and_then(|receipt| serde_json::to_string(&receipt).map_err(WorkstationError::from));
    copy_json(state, out, capacity, value)
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_cartridge_json(
    state: *mut WorkstationState,
    out: *mut u8,
    capacity: usize,
) -> usize {
    let Ok(state_ref) = state_mut(state) else {
        return FFI_ERROR;
    };
    copy_json(
        state,
        out,
        capacity,
        state_ref.app.session.to_cartridge_json(),
    )
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_current_body(
    state: *mut WorkstationState,
    out: *mut u8,
    capacity: usize,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match state_ref.app.session.to_body_bytes() {
        Ok(bytes) if capacity >= bytes.len() && !out.is_null() => {
            ptr::copy_nonoverlapping(bytes.as_ptr(), out, bytes.len());
            state_ref.last_error.clear();
            0
        }
        Ok(_) => {
            state_ref.last_error = "body output must provide 240 bytes".to_owned();
            -1
        }
        Err(error) => {
            state_ref.last_error = error.to_string();
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_pending_body(
    state: *mut WorkstationState,
    out: *mut u8,
    capacity: usize,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    let result = state_ref
        .app
        .pending_edit
        .as_ref()
        .map(|edit| edit.after_session.to_body_bytes())
        .unwrap_or_else(|| state_ref.app.session.to_body_bytes());
    match result {
        Ok(bytes) if capacity >= bytes.len() && !out.is_null() => {
            ptr::copy_nonoverlapping(bytes.as_ptr(), out, bytes.len());
            state_ref.last_error.clear();
            0
        }
        Ok(_) => {
            state_ref.last_error = "body output must provide 240 bytes".to_owned();
            -1
        }
        Err(error) => {
            state_ref.last_error = error.to_string();
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_stage_solo_body(
    state: *mut WorkstationState,
    pending: c_int,
    out: *mut u8,
    capacity: usize,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match state_ref.app.stage_solo_body(pending != 0) {
        Ok(bytes) if capacity >= bytes.len() && !out.is_null() => {
            ptr::copy_nonoverlapping(bytes.as_ptr(), out, bytes.len());
            state_ref.last_error.clear();
            0
        }
        Ok(_) => {
            state_ref.last_error = "stage-solo output must provide 240 bytes".to_owned();
            -1
        }
        Err(error) => {
            state_ref.last_error = error.to_string();
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_select(
    state: *mut WorkstationState,
    corner: usize,
    lane: usize,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match record(state_ref, |app| app.select(corner, lane)) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_fill_corner_source(
    state: *mut WorkstationState,
    corner: usize,
    source_index: usize,
    endpoint: c_int,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    let Ok(endpoint) = SourceEndpoint::from_int(endpoint) else {
        state_ref.last_error = "source endpoint must be LOW or HIGH".to_owned();
        return -1;
    };
    match record(state_ref, |app| {
        app.fill_corner_from_source(corner, source_index, endpoint)
            .map(|_| ())
    }) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_assign_lane_source(
    state: *mut WorkstationState,
    corner: usize,
    lane: usize,
    source_index: usize,
    endpoint: c_int,
    source_section: usize,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    let Ok(endpoint) = SourceEndpoint::from_int(endpoint) else {
        state_ref.last_error = "source endpoint must be LOW or HIGH".to_owned();
        return -1;
    };
    match record(state_ref, |app| {
        app.assign_lane_from_source(corner, lane, source_index, endpoint, source_section)
            .map(|_| ())
    }) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_apply_recipe(
    state: *mut WorkstationState,
    candidate_index: usize,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match record(state_ref, |app| {
        app.apply_recipe(candidate_index).map(|_| ())
    }) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_new_filter(state: *mut WorkstationState) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match record(state_ref, AppState::new_filter) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_make_filter(state: *mut WorkstationState) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match record(state_ref, AppState::make_filter) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_preview_field(
    state: *mut WorkstationState,
    edit_field: c_int,
    value: f64,
    all_corners: c_int,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    let Ok(edit_field) = field(edit_field) else {
        state_ref.last_error = "unknown edit field".to_owned();
        return -1;
    };
    let corners = if all_corners != 0 {
        vec![0, 1, 2, 3]
    } else {
        vec![state_ref.app.selected_corner]
    };
    let request = EditRequest {
        corner_indices: corners,
        lane_indices: vec![state_ref.app.selected_lane],
        field: edit_field,
        value,
        secondary_value: None,
        relative: false,
    };
    match record(state_ref, |app| app.preview(request).map(|_| ())) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_preview_conjugate_root(
    state: *mut WorkstationState,
    pole: c_int,
    hz: f64,
    radius: f64,
    all_corners: c_int,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    let corners = if all_corners != 0 {
        vec![0, 1, 2, 3]
    } else {
        vec![state_ref.app.selected_corner]
    };
    let request =
        EditRequest::conjugate(corners, state_ref.app.selected_lane, pole != 0, hz, radius);
    match record(state_ref, |app| app.preview(request).map(|_| ())) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_preview_relative_conjugate_root(
    state: *mut WorkstationState,
    pole: c_int,
    octave_delta: f64,
    radius_delta: f64,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    let request = EditRequest::relative_conjugate(
        state_ref.app.selected_lane,
        pole != 0,
        octave_delta,
        radius_delta,
    );
    match record(state_ref, |app| app.preview(request).map(|_| ())) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_apply(state: *mut WorkstationState) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match record(state_ref, |app| app.apply().map(|_| ())) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_discard_preview(state: *mut WorkstationState) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    state_ref.app.discard_preview();
    state_ref.last_error.clear();
    0
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_undo(state: *mut WorkstationState) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match record(state_ref, AppState::undo) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_redo(state: *mut WorkstationState) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match record(state_ref, AppState::redo) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_set_morph_q(
    state: *mut WorkstationState,
    morph: f64,
    q: f64,
) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match record(state_ref, |app| app.set_morph_q(morph, q)) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_validate(state: *mut WorkstationState) -> c_int {
    let Ok(state_ref) = state_mut(state) else {
        return -1;
    };
    match record(state_ref, |app| {
        if app.pending_edit.is_some() {
            return Err(WorkstationError(
                "APPLY or cancel the pending zero preview first".to_owned(),
            ));
        }
        let body = app.session.to_body_bytes()?;
        let session_json = app.session.to_json()?;
        let reopened = Session::from_json(&session_json)?;
        if reopened.to_body_bytes()? != body {
            return Err(WorkstationError(
                "session save/reopen changed body bytes".to_owned(),
            ));
        }
        if !app.session.cartridge_parity()? {
            return Err(WorkstationError(
                "body/cartridge packed-word parity failed".to_owned(),
            ));
        }
        Ok(())
    }) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn workstation_state_screen_for_body_json(
    state: *mut WorkstationState,
    body: *const u8,
    body_len: usize,
    out: *mut u8,
    capacity: usize,
) -> usize {
    let Ok(state_ref) = state_mut(state) else {
        return FFI_ERROR;
    };
    if body.is_null() || body_len != 240 {
        state_ref.last_error = "screen probe requires exactly 240 body bytes".to_owned();
        return FFI_ERROR;
    }
    let bytes = std::slice::from_raw_parts(body, body_len);
    let evidence = EvidenceReference {
        external_repository_commit: "synthetic".to_owned(),
        relative_path: "fixtures/manifest.json".to_owned(),
        file_sha256: String::new(),
        evidence_type: "packed-runtime-probe".to_owned(),
        note: "Screen is computed from the exact packed bytes installed in PluginProcessor."
            .to_owned(),
    };
    let result = Session::from_body_bytes("installed body", "", bytes, evidence)
        .and_then(|session| {
            session.screen_with_audit(
                state_ref.app.selected_corner,
                state_ref.app.selected_lane,
                state_ref.app.morph,
                state_ref.app.q,
                state_ref.app.audit.clone(),
            )
        })
        .and_then(|screen| {
            let mut value = serde_json::to_value(screen).map_err(WorkstationError::from)?;
            if let Some(object) = value.as_object_mut() {
                object.remove("audit");
                object.insert(
                    "sampledAuditCurrent".to_owned(),
                    serde_json::Value::Bool(false),
                );
            }
            serde_json::to_string(&value).map_err(WorkstationError::from)
        });
    copy_json(state, out, capacity, result)
}

#[no_mangle]
pub extern "C" fn workstation_authoring_build_identifier() -> *const c_char {
    b"trench-workstation-authoring-v1\0".as_ptr() as *const c_char
}

#[cfg(test)]
mod tests {
    use super::repo_root;
    use std::ffi::CString;

    #[test]
    fn native_root_is_canonical_before_external_well_discovery() {
        let source = std::path::Path::new(file!());
        let root = if source.is_absolute() {
            source.ancestors().nth(3).unwrap().to_path_buf()
        } else {
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap()
                .to_path_buf()
        };
        let lexical = root.join("plugin").join("..");
        let text = CString::new(lexical.to_string_lossy().as_bytes()).unwrap();
        assert_eq!(
            repo_root(text.as_ptr()).unwrap(),
            root.canonicalize().unwrap()
        );
    }
}
