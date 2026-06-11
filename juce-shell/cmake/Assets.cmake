# Runtime cartridges plus the clean editor surface.
file(GLOB_RECURSE CartridgeFiles CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/assets/cartridges/*.json")
file(GLOB_RECURSE UiAssetFiles CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/assets/ui/*.png")
list (FILTER CartridgeFiles EXCLUDE REGEX "/\\.DS_Store$") # We don't want the .DS_Store on macOS though...
list (FILTER UiAssetFiles EXCLUDE REGEX "/\\.DS_Store$")

option(TRENCH_INCLUDE_DEV_ROSTER "Bake older clean-room development cartridges into the plugin asset bundle" OFF)
option(TRENCH_INCLUDE_STUDY_ROSTER "Bake study/reference cartridges into the plugin asset bundle" OFF)

if (NOT TRENCH_INCLUDE_DEV_ROSTER AND NOT TRENCH_INCLUDE_STUDY_ROSTER)
    list (FILTER CartridgeFiles INCLUDE REGEX "[/\\\\]assets[/\\\\]cartridges[/\\\\](bypass|v1_.*|voice_walk|vowelshift|talkbox|razor_shell_v1|knock_burst|hollow_chamber|metal_scream|phaser_slide)\\.json$")
elseif (NOT TRENCH_INCLUDE_STUDY_ROSTER)
    list (FILTER CartridgeFiles EXCLUDE REGEX "[/\\\\]assets[/\\\\]cartridges[/\\\\]P2k_.*\\.json$")
endif ()

set(AssetFiles ${CartridgeFiles} ${UiAssetFiles})

# Setup our binary data as a target called Assets
juce_add_binary_data(Assets SOURCES ${AssetFiles})

# Required for Linux happiness:
# See https://forum.juce.com/t/loading-pytorch-model-using-binarydata/39997/2
set_target_properties(Assets PROPERTIES POSITION_INDEPENDENT_CODE TRUE)
