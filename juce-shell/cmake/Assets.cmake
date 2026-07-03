# Runtime cartridges plus the clean editor surface.
file(GLOB_RECURSE CartridgeFiles CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/assets/cartridges/*.json")
file(GLOB_RECURSE UiAssetFiles CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/assets/ui/*.png")
# Shipping clean-room bodies as raw 240-byte packed bodies (BinaryData <stem>_body240).
file(GLOB_RECURSE BodyFiles CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/assets/bodies/*.body240")
list (FILTER CartridgeFiles EXCLUDE REGEX "/\\.DS_Store$") # We don't want the .DS_Store on macOS though...
list (FILTER UiAssetFiles EXCLUDE REGEX "/\\.DS_Store$")

option(TRENCH_INCLUDE_DEV_ROSTER "Bake older clean-room development cartridges into the plugin asset bundle" OFF)
option(TRENCH_INCLUDE_STUDY_ROSTER "Bake study/reference cartridges into the plugin asset bundle" OFF)

if (NOT TRENCH_INCLUDE_DEV_ROSTER)
    # Product binary: the curated roster below ships as compiled cartridge JSON.
    # Leave scratch/dev .body240 files in the repo without baking them into the plugin.
    list (FILTER BodyFiles INCLUDE REGEX "[/\\\\]assets[/\\\\]bodies[/\\\\]$^")
endif ()

if (NOT TRENCH_INCLUDE_DEV_ROSTER AND NOT TRENCH_INCLUDE_STUDY_ROSTER)
    list (FILTER CartridgeFiles INCLUDE REGEX "[/\\\\]assets[/\\\\]cartridges[/\\\\](P2k_004_meaty_gizmo|P2k_013_talking_hedz|P2k_029_lucifer_s_q)\\.json$")
elseif (NOT TRENCH_INCLUDE_STUDY_ROSTER)
    list (FILTER CartridgeFiles EXCLUDE REGEX "[/\\\\]assets[/\\\\]cartridges[/\\\\]P2k_.*\\.json$")
endif ()

set(AssetFiles ${CartridgeFiles} ${UiAssetFiles} ${BodyFiles})

# Setup our binary data as a target called Assets
juce_add_binary_data(Assets SOURCES ${AssetFiles})

# Required for Linux happiness:
# See https://forum.juce.com/t/loading-pytorch-model-using-binarydata/39997/2
set_target_properties(Assets PROPERTIES POSITION_INDEPENDENT_CODE TRUE)
