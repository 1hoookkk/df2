cmake_minimum_required(VERSION 3.25)

# --- VST3 Output Setup ---
#
# PL-6: no Debug-only LOCALAPPDATA destination. DAWs scan whatever they find
# first, and a stale LOCALAPPDATA copy from a previous Debug build silently
# masked Release builds for hours. Local packaging should use the build artefact;
# pass -DTRENCH_COPY_PLUGIN_AFTER_BUILD=ON only when intentionally installing
# into the system VST3 folder.
#
# If you previously built Debug here, manually delete
#   %LOCALAPPDATA%\Programs\Common\VST3\TRENCH.vst3
# so DAW scanners don't find it.

# This tells cmake we have goodies in the /cmake folder
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include (PamplejuceVersion)

# Cache fetched dependencies outside the build tree so fresh build directories
# reuse the same pinned JUCE checkout.
if (NOT DEFINED CPM_SOURCE_CACHE OR CPM_SOURCE_CACHE STREQUAL "OFF")
    if (WIN32)
        set(CPM_SOURCE_CACHE "$ENV{USERPROFILE}/.cache/CPM" CACHE PATH
            "Shared CPM source cache" FORCE)
    else ()
        set(CPM_SOURCE_CACHE "$ENV{HOME}/.cache/CPM" CACHE PATH
            "Shared CPM source cache" FORCE)
    endif ()
endif ()

# Modern concise way to add dependencies to your project
include (CPM)

# Configures universal binaries and decides which version of macOS to support
include(PamplejuceMacOS)

# Couple tweaks that IMO should be JUCE defaults
include(JUCEDefaults)

# Change me!
set(PROJECT_NAME "TRENCH")
set(PRODUCT_NAME "TRENCH")
set(COMPANY_NAME "Trench")
set(BUNDLE_ID "com.trench.field")
set(FORMATS VST3 Standalone)
option(TRENCH_ENABLE_MELATONIN_INSPECTOR "Enable the Melatonin Inspector dev hook in the plugin editor" OFF)
option(TRENCH_COPY_PLUGIN_AFTER_BUILD "Copy built plugins into the system plugin folders after build" OFF)

# Force JUCE to work with sccache
set(CMAKE_POLICY_DEFAULT_CMP0141        NEW      CACHE STRING "" FORCE)
set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT Embedded CACHE STRING "" FORCE)

project(${PROJECT_NAME} VERSION ${CURRENT_VERSION})

# Log build environment info (after project() so compiler info is available)
include(PamplejuceLog)

# Pin the current stable JUCE release. CPM keeps the checkout in the shared
# source cache above, avoiding fragile workspace junctions and repeated clones.
CPMAddPackage(
    NAME JUCE
    GITHUB_REPOSITORY juce-framework/JUCE
    GIT_TAG 8.0.13
    VERSION 8.0.13
    GIT_SHALLOW TRUE
    EXCLUDE_FROM_ALL YES)

# Add CLAP format
add_subdirectory(modules/clap-juce-extensions EXCLUDE_FROM_ALL)

# Melatonin inspector
add_subdirectory (modules/melatonin_inspector)

juce_add_plugin("${PROJECT_NAME}"
    ICON_BIG "${CMAKE_CURRENT_SOURCE_DIR}/packaging/icon.png"
    COMPANY_NAME "${COMPANY_NAME}"
    BUNDLE_ID "${BUNDLE_ID}"
    COPY_PLUGIN_AFTER_BUILD ${TRENCH_COPY_PLUGIN_AFTER_BUILD}
    PLUGIN_MANUFACTURER_CODE Trec
    PLUGIN_CODE T001
    FORMATS "${FORMATS}"
    PRODUCT_NAME "${PRODUCT_NAME}")

add_library(SharedCode INTERFACE)

clap_juce_extensions_plugin(TARGET "${PROJECT_NAME}"
    CLAP_ID "${BUNDLE_ID}"
    CLAP_FEATURES audio-effect)

include(SharedCodeDefaults)

# --- Rust Backend Integration ---
#
# CMake OWNS the Rust staticlib build. A custom command runs `cargo rustc` to
# produce trench_core.lib, re-running only when the Rust sources or manifests
# change (DEPENDS + CONFIGURE_DEPENDS glob). The plugin format targets depend on
# the `trench_core_build` target, so the staticlib is always rebuilt before the
# JUCE link — no more silently linking a stale lib left over from a prior build.
set(RUST_WORKSPACE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/..")
set(RUST_LIB_DIR "${RUST_WORKSPACE_DIR}/target/release")
# On Windows, we link trench_core.lib. On Unix, libtrench_core.a.
if(WIN32)
    set(RUST_LIB_NAME "trench_core.lib")
else()
    set(RUST_LIB_NAME "libtrench_core.a")
endif()

set(TRENCH_CORE_LIB "${RUST_LIB_DIR}/${RUST_LIB_NAME}")

find_program(CARGO_EXECUTABLE cargo)
if(NOT CARGO_EXECUTABLE)
    message(FATAL_ERROR
        "TRENCH: 'cargo' was not found on PATH. The Rust DSP staticlib (trench-core) "
        "is required to build the plugin. Install the Rust toolchain (https://rustup.rs).")
endif()

# Reglob on every CMake run so a newly added .rs file becomes a dependency.
file(GLOB_RECURSE RUST_SOURCES CONFIGURE_DEPENDS
    "${RUST_WORKSPACE_DIR}/trench-core/src/*.rs")
set(RUST_MANIFESTS
    "${RUST_WORKSPACE_DIR}/Cargo.toml"
    "${RUST_WORKSPACE_DIR}/trench-core/Cargo.toml")
if(EXISTS "${RUST_WORKSPACE_DIR}/Cargo.lock")
    list(APPEND RUST_MANIFESTS "${RUST_WORKSPACE_DIR}/Cargo.lock")
endif()

# Build only the staticlib crate-type (matches build-standalone.ps1): this avoids
# touching trench_core.dll while browser/forge helpers may be using it.
add_custom_command(
    OUTPUT "${TRENCH_CORE_LIB}"
    COMMAND "${CARGO_EXECUTABLE}" rustc -p trench-core --release --lib --crate-type staticlib
    WORKING_DIRECTORY "${RUST_WORKSPACE_DIR}"
    DEPENDS ${RUST_SOURCES} ${RUST_MANIFESTS}
    COMMENT "Building trench-core Rust staticlib (cargo rustc --crate-type staticlib --release)"
    VERBATIM
    USES_TERMINAL)

add_custom_target(trench_core_build DEPENDS "${TRENCH_CORE_LIB}")

# Manually list all .h and .cpp files for the plugin
set(SourceFiles
    source/PluginProcessor.h
    source/PluginProcessor.cpp
    source/PluginEditor.h
    source/PluginEditor.cpp
    source/TrenchRates.h
    source/TrenchBodyRoster.h
    source/UiLayout.h
    source/parameters/TrenchParameters.h
    source/parameters/TrenchParameters.cpp
    source/dsp/MotionEngine.h
    source/dsp/TrenchDspBridge.h
    source/dsp/TrenchCleanBody.h
    source/dsp/FixedRateTrenchIsland.h
    source/dsp/FixedRateTrenchIsland.cpp
    source/ui/FaceplateView.h
    source/ui/GraphDisplay.h
    source/ui/DecalsLayer.h
    source/ui/LabelsLayer.h
    source/ui/MotionSelector.h
    source/ui/TimeSelector.h
    source/ui/SelectorLookAndFeel.h
    source/ui/ResponseCurve.h
    source/ui/SlotPad.h
    source/ui/Theme.h
    source/ui/TypeSelectorView.h
    source/ui/ValueReadout.h
    source/ui/TakeView.h
    source/ui/WheelControl.h
)
target_sources(SharedCode INTERFACE ${SourceFiles})

include(Assets)
include(XcodePrettify)

target_compile_definitions(SharedCode
    INTERFACE
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    CMAKE_BUILD_TYPE="${CMAKE_BUILD_TYPE}"
    VERSION="${CURRENT_VERSION}"
    PRODUCT_NAME_WITHOUT_VERSION="TRENCH"
    TRENCH_ENABLE_MELATONIN_INSPECTOR=$<BOOL:${TRENCH_ENABLE_MELATONIN_INSPECTOR}>
    TRENCH_INCLUDE_DEV_ROSTER=$<BOOL:${TRENCH_INCLUDE_DEV_ROSTER}>
    TRENCH_INCLUDE_STUDY_ROSTER=$<BOOL:${TRENCH_INCLUDE_STUDY_ROSTER}>
)

target_include_directories(SharedCode INTERFACE "${CMAKE_CURRENT_SOURCE_DIR}/source")

set(TRENCH_PLATFORM_LIBS "")
if(WIN32)
    list(APPEND TRENCH_PLATFORM_LIBS ntdll userenv ws2_32 bcrypt)
endif()

target_link_libraries(SharedCode
    INTERFACE
    "${TRENCH_CORE_LIB}"
    ${TRENCH_PLATFORM_LIBS}
    Assets
    melatonin_inspector
    juce_audio_utils
    juce_audio_processors
    juce_dsp
    juce_gui_basics
    juce_gui_extra
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags)

target_link_libraries("${PROJECT_NAME}" PRIVATE SharedCode)

# Make every concrete plugin target build the Rust staticlib first, so the JUCE
# link never resolves trench-core symbols against a stale lib. JUCE generates a
# per-format target (<name>_VST3, <name>_Standalone, ...) plus the shared <name>
# target; the CLAP extension adds <name>_CLAP. Wire whichever exist.
add_dependencies("${PROJECT_NAME}" trench_core_build)
foreach(_fmt ${FORMATS} CLAP)
    if(TARGET "${PROJECT_NAME}_${_fmt}")
        add_dependencies("${PROJECT_NAME}_${_fmt}" trench_core_build)
    endif()
endforeach()

# Replace JUCE's default standalone wrapper. The custom host makes the plugin
# faceplate the whole visible window: no Options button, mute-warning strip, or
# native titlebar.
target_sources("${PROJECT_NAME}_Standalone" PRIVATE source/TrenchStandaloneApp.cpp)
# TRENCH_PLAYER_DIAGNOSTICS compiles the live @audition file-watch hot-reload into
# the standalone (Documents/TRENCH/authoring_slot.json). OFF by default so the
# shipping build does no file polling; turn ON for a dev/recording standalone.
option(TRENCH_PLAYER_DIAGNOSTICS "Compile the live @audition hot-reload into the standalone (dev/recording)" OFF)
# TRENCH_FORGE compiles the in-plugin Forge builder (table-gated typed-lane authoring +
# compile/audition/save). DEV-ONLY tool — OFF by default so it NEVER ships in the plugin.
option(TRENCH_FORGE "Compile the in-plugin Forge dev builder (dev-only; never ship)" OFF)
target_compile_definitions("${PROJECT_NAME}_Standalone"
    PRIVATE
    JUCE_USE_CUSTOM_PLUGIN_STANDALONE_APP=1
    $<$<BOOL:${TRENCH_PLAYER_DIAGNOSTICS}>:TRENCH_PLAYER_DIAGNOSTICS=1>
    $<$<BOOL:${TRENCH_FORGE}>:TRENCH_FORGE=1>)

# Diagnostics features (@audition hot-reload + the See-Your-Plugin layout bridge)
# live in SHARED code (PluginProcessor/PluginEditor), which compiles into the
# shared TRENCH lib — NOT the Standalone wrapper. So the define must reach
# SharedCode or the #ifdefs are dead (this is exactly why they were). Gated by
# the option, so a shipping build (option OFF, the default) stays clean.
target_compile_definitions(SharedCode INTERFACE
    $<$<BOOL:${TRENCH_PLAYER_DIAGNOSTICS}>:TRENCH_PLAYER_DIAGNOSTICS=1>
    $<$<BOOL:${TRENCH_FORGE}>:TRENCH_FORGE=1>)

# Dumb DAW tap: passes audio through and writes captured WAVs for Forge.
set(CAPTURE_PROJECT_NAME "TRENCH_CAPTURE")
juce_add_plugin("${CAPTURE_PROJECT_NAME}"
    COMPANY_NAME "${COMPANY_NAME}"
    BUNDLE_ID "com.trench.capture"
    COPY_PLUGIN_AFTER_BUILD ${TRENCH_COPY_PLUGIN_AFTER_BUILD}
    PLUGIN_MANUFACTURER_CODE Trec
    PLUGIN_CODE T0C1
    FORMATS VST3
    PRODUCT_NAME "Trench Capture")

target_sources("${CAPTURE_PROJECT_NAME}"
    PRIVATE
    source/capture_vst/TrenchCaptureProcessor.h
    source/capture_vst/TrenchCaptureProcessor.cpp
    source/capture_vst/TrenchCaptureEditor.h
    source/capture_vst/TrenchCaptureEditor.cpp)

target_compile_definitions("${CAPTURE_PROJECT_NAME}"
    PRIVATE
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0)

target_include_directories("${CAPTURE_PROJECT_NAME}" PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/source/capture_vst")

target_link_libraries("${CAPTURE_PROJECT_NAME}"
    PRIVATE
    juce_audio_formats
    juce_audio_processors
    juce_audio_utils
    juce_gui_basics
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags)

# PL-6: no per-configuration VST3_DESTINATION override. System-folder copying is
# controlled only by TRENCH_COPY_PLUGIN_AFTER_BUILD — see the comment at the top
# of this file for why.

include(PamplejuceIPP)
include(Tests)
include(Benchmarks)
include(GitHubENV)
