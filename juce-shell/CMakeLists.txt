cmake_minimum_required(VERSION 3.25)

# --- VST3 Output Setup ---
#
# PL-6: a single install location for every build configuration. Both Debug
# and Release auto-copy into Program Files; we no longer maintain a parallel
# LOCALAPPDATA destination for Debug. The reason — STATE.md `Now`,
# 2026-05-28 — is that DAWs scan whatever they find first, and a stale
# LOCALAPPDATA copy from a previous Debug build silently masked Release
# builds for hours. Dev iteration should go through TRENCH_Standalone.exe
# (see juce-shell/README.md), not the auto-installed VST3.
#
# If you previously built Debug here, manually delete
#   %LOCALAPPDATA%\Programs\Common\VST3\TRENCH.vst3
# so DAW scanners don't find it.

# This tells cmake we have goodies in the /cmake folder
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include (PamplejuceVersion)

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

# Force JUCE to work with sccache
set(CMAKE_POLICY_DEFAULT_CMP0141        NEW      CACHE STRING "" FORCE)
set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT Embedded CACHE STRING "" FORCE)

project(${PROJECT_NAME} VERSION ${CURRENT_VERSION})

# Log build environment info (after project() so compiler info is available)
include(PamplejuceLog)

add_subdirectory(JUCE)

# Add CLAP format
add_subdirectory(modules/clap-juce-extensions EXCLUDE_FROM_ALL)

# Melatonin inspector
add_subdirectory (modules/melatonin_inspector)

juce_add_plugin("${PROJECT_NAME}"
    ICON_BIG "${CMAKE_CURRENT_SOURCE_DIR}/packaging/icon.png"
    COMPANY_NAME "${COMPANY_NAME}"
    BUNDLE_ID "${BUNDLE_ID}"
    COPY_PLUGIN_AFTER_BUILD TRUE
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
set(RUST_LIB_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../target/release")
# On Windows, we link trench_core.lib. On Unix, libtrench_core.a.
if(WIN32)
    set(RUST_LIB_NAME "trench_core.lib")
else()
    set(RUST_LIB_NAME "libtrench_core.a")
endif()

set(TRENCH_CORE_LIB "${RUST_LIB_DIR}/${RUST_LIB_NAME}")

if(NOT EXISTS "${TRENCH_CORE_LIB}")
    message(WARNING "TRENCH: Rust library not found at ${TRENCH_CORE_LIB}. Run 'cargo build --release' in trench-core/")
endif()

# Manually list all .h and .cpp files for the plugin
set(SourceFiles
    source/PluginProcessor.h
    source/PluginProcessor.cpp
    source/PluginEditor.h
    source/PluginEditor.cpp
    source/TrenchRates.h
    source/TrenchChassisLayout.h
    source/TrenchStyle.h
    source/TrenchLookAndFeel.h
    source/TrenchAuthoringSlot.h
    source/TrenchShuttleControl.h
    source/TrenchShuttleControl.cpp
    source/TrenchValueBox.h
    source/TrenchBodyStrip.h
    source/TrenchResponseDisplay.h
    source/TrenchResponseDisplay.cpp
    source/parameters/TrenchParameters.h
    source/parameters/TrenchParameters.cpp
    source/dsp/TrenchDspBridge.h
    source/dsp/TrenchCleanBody.h
    source/dsp/FixedRateTrenchIsland.h
    source/dsp/FixedRateTrenchIsland.cpp
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

# Dumb DAW tap: passes audio through and writes captured WAVs for Forge.
set(CAPTURE_PROJECT_NAME "TRENCH_CAPTURE")
juce_add_plugin("${CAPTURE_PROJECT_NAME}"
    COMPANY_NAME "${COMPANY_NAME}"
    BUNDLE_ID "com.trench.capture"
    COPY_PLUGIN_AFTER_BUILD TRUE
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

# PL-6: no per-configuration VST3_DESTINATION override. Every build copies to
# the same Program Files VST3 path (JUCE's default for Windows). The previous
# Debug-only LOCALAPPDATA destination is gone — see the comment at the top of
# this file for why.

include(PamplejuceIPP)
include(Tests)
include(Benchmarks)
include(GitHubENV)
