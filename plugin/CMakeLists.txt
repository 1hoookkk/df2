cmake_minimum_required(VERSION 3.25)

project(TRENCH_WorkstationProject VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Use the pinned JUCE checkout already used by the shipping build when it is
# present. A normal FetchContent fallback keeps this clean workstation
# checkout reproducible on another machine without copying the old checkout.
set(TRENCH_JUCE_DIR "$ENV{USERPROFILE}/.cache/CPM/juce/628b" CACHE PATH
    "Pinned JUCE 8.0.13 source directory")
if(EXISTS "${TRENCH_JUCE_DIR}/CMakeLists.txt")
    add_subdirectory("${TRENCH_JUCE_DIR}" "${CMAKE_BINARY_DIR}/JUCE")
else()
    include(FetchContent)
    FetchContent_Declare(
        JUCE
        GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
        GIT_TAG 8.0.13
        GIT_SHALLOW TRUE)
    FetchContent_MakeAvailable(JUCE)
endif()

set(TRENCH_COMMON_DEFINITIONS
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JucePlugin_Name="TRENCH"
    JucePlugin_Desc="TRENCH filter processor"
    JucePlugin_Manufacturer="Trench"
    JucePlugin_ManufacturerCode=0x54726563
    JucePlugin_PluginCode=0x54303031
    JucePlugin_IsSynth=0
    JucePlugin_WantsMidiInput=0
    JucePlugin_ProducesMidiOutput=0
    JucePlugin_IsMidiEffect=0
    JucePlugin_EditorRequiresKeyboardFocus=0
    JucePlugin_VersionString="1.0.0"
    JucePlugin_Version=0x10000
    JucePlugin_VST3Category=Fx)

juce_add_binary_data(TRENCHAssets
    SOURCES
        assets/df2_panel_beige.png
        assets/trench_roller_strip.png
        assets/display_log_grid.png
        assets/bodies/identity.body240)

set(TRENCH_PLUGIN_SOURCES
    source/PluginProcessor.h
    source/PluginProcessor.cpp
    source/PluginEditor.h
    source/PluginEditor.cpp
    source/TrenchRates.h
    source/TrenchBodyRoster.h
    source/SmartMotion.h
    source/UiLayout.h
    source/parameters/TrenchParameters.h
    source/parameters/TrenchParameters.cpp
    source/parameters/MovePresets.h
    source/dsp/BiteStage.h
    source/dsp/CapturePlan.h
    source/dsp/CaptureRing.h
    source/dsp/FixedRateTrenchIsland.h
    source/dsp/FixedRateTrenchIsland.cpp
    source/dsp/GestureEngine.h
    source/dsp/MotionEngine.h
    source/dsp/MoveMatrix.h
    source/dsp/SlamStage.h
    source/dsp/TakeWriter.h
    source/dsp/TeleportEngine.h
    source/dsp/TrenchCleanBody.h
    source/dsp/TrenchDspBridge.h
    source/ui/AmountFader.h
    source/ui/DecalsLayer.h
    source/ui/FaceplateView.h
    source/ui/FiveDButton.h
    source/ui/GraphDisplay.h
    source/ui/LabelsLayer.h
    source/ui/MoveChip.h
    source/ui/MoveView.h
    source/ui/ParamInteraction.h
    source/ui/ResponseCurve.h
    source/ui/SeedButton.h
    source/ui/SelectorLookAndFeel.h
    source/ui/SlotPad.h
    source/ui/TakeButton.h
    source/ui/TakeView.h
    source/ui/Theme.h
    source/ui/TypeSelectorView.h
    source/ui/ValueReadout.h
    source/ui/WheelControl.h)

add_library(TRENCHPluginCommon STATIC ${TRENCH_PLUGIN_SOURCES})
target_include_directories(TRENCHPluginCommon PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/source")
target_compile_definitions(TRENCHPluginCommon PUBLIC ${TRENCH_COMMON_DEFINITIONS})
target_link_libraries(TRENCHPluginCommon
    PUBLIC
        TRENCHAssets
        juce_audio_utils
        juce_audio_processors
        juce_audio_formats
        juce_dsp
        juce_gui_basics
        juce_gui_extra
        juce::juce_recommended_config_flags
        juce::juce_recommended_warning_flags)

set(TRENCH_WORKSPACE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/..")
set(TRENCH_RUST_LIB_DIR "${TRENCH_WORKSPACE_DIR}/target/release")
if(WIN32)
    set(TRENCH_CORE_LIB "${TRENCH_RUST_LIB_DIR}/trench_core.lib")
    set(TRENCH_WORKSTATION_LIB "${TRENCH_RUST_LIB_DIR}/trench_workstation.lib")
else()
    set(TRENCH_CORE_LIB "${TRENCH_RUST_LIB_DIR}/libtrench_core.a")
    set(TRENCH_WORKSTATION_LIB "${TRENCH_RUST_LIB_DIR}/libtrench_workstation.a")
endif()

find_program(CARGO_EXECUTABLE cargo REQUIRED)
file(GLOB_RECURSE TRENCH_RUST_SOURCES CONFIGURE_DEPENDS
    "${TRENCH_WORKSPACE_DIR}/trench-core/src/*.rs"
    "${TRENCH_WORKSPACE_DIR}/workstation/src/*.rs")
set(TRENCH_RUST_MANIFESTS
    "${TRENCH_WORKSPACE_DIR}/Cargo.toml"
    "${TRENCH_WORKSPACE_DIR}/Cargo.lock"
    "${TRENCH_WORKSPACE_DIR}/trench-core/Cargo.toml"
    "${TRENCH_WORKSPACE_DIR}/workstation/Cargo.toml")

add_custom_command(
    OUTPUT "${TRENCH_CORE_LIB}"
    COMMAND "${CARGO_EXECUTABLE}" rustc -p trench-core --release --lib --crate-type staticlib
    WORKING_DIRECTORY "${TRENCH_WORKSPACE_DIR}"
    DEPENDS ${TRENCH_RUST_SOURCES} ${TRENCH_RUST_MANIFESTS}
    COMMENT "Building the shipping trench-core static library"
    VERBATIM
    USES_TERMINAL)
add_custom_target(trench_core_build DEPENDS "${TRENCH_CORE_LIB}")

add_custom_command(
    OUTPUT "${TRENCH_WORKSTATION_LIB}"
    COMMAND "${CARGO_EXECUTABLE}" rustc -p trench-workstation --release --lib --crate-type staticlib
    WORKING_DIRECTORY "${TRENCH_WORKSPACE_DIR}"
    DEPENDS ${TRENCH_RUST_SOURCES} ${TRENCH_RUST_MANIFESTS}
    COMMENT "Building the workstation authoring static library"
    VERBATIM
    USES_TERMINAL)
add_custom_target(trench_workstation_build DEPENDS "${TRENCH_WORKSTATION_LIB}")

set(TRENCH_WINDOWS_LIBS ntdll userenv ws2_32 bcrypt)

juce_add_plugin(TRENCH
    COMPANY_NAME "Trench"
    BUNDLE_ID "com.trench.field"
    PLUGIN_MANUFACTURER_CODE Trec
    PLUGIN_CODE T001
    FORMATS VST3
    PRODUCT_NAME "TRENCH"
    COPY_PLUGIN_AFTER_BUILD FALSE)
target_link_libraries(TRENCH PRIVATE TRENCHPluginCommon "${TRENCH_CORE_LIB}" ${TRENCH_WINDOWS_LIBS})
add_dependencies(TRENCH trench_core_build)
if(TARGET TRENCH_VST3)
    add_dependencies(TRENCH_VST3 trench_core_build)
endif()

juce_add_gui_app(TRENCH_Workstation
    PRODUCT_NAME "TRENCH Workstation"
    COMPANY_NAME "Trench"
    BUNDLE_ID "com.trench.workstation"
    VERSION "1.0.0")
target_sources(TRENCH_Workstation PRIVATE
    native/WorkstationApplication.cpp
    native/WorkstationEditor.cpp
    native/WorkstationEditor.h)
target_include_directories(TRENCH_Workstation PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/source"
    "${CMAKE_CURRENT_SOURCE_DIR}/native")
target_compile_definitions(TRENCH_Workstation PRIVATE
    ${TRENCH_COMMON_DEFINITIONS}
    TRENCH_WORKSTATION_REPO_ROOT="${TRENCH_WORKSPACE_DIR}")
target_link_libraries(TRENCH_Workstation PRIVATE
    TRENCHPluginCommon
    "${TRENCH_WORKSTATION_LIB}"
    ${TRENCH_WINDOWS_LIBS}
    juce_audio_utils
    juce_gui_basics
    juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags)
add_dependencies(TRENCH_Workstation trench_workstation_build)

set_target_properties(TRENCH_Workstation PROPERTIES OUTPUT_NAME "TRENCH Workstation")
