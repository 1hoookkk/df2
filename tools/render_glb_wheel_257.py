"""Render the supplied GLB wheel without changing its geometry.

This is intentionally a Blender-side pass generator, not a mesh builder.  The
source blend already contains the authored 257-frame rotation action.  We
evaluate that action, detach it only for the render copy, and add exactly pi
to its existing Z rotation so the opposite circumference is shown.

The two output passes use the same camera, crop, material, and pose:

* wheel_pass: clean unmapped Principled metal/body pass;
* transmission_pass: the same pass with one stationary cyan point light in
  the real central channel.  The wheel mesh remains the occluder.

The source blend is never saved by this script.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import bpy
from mathutils import Euler


FRAME_COUNT = 257
FRAME_LAST = FRAME_COUNT - 1
ONLY_FRAME = os.environ.get("TRENCH_RENDER_ONLY_FRAME")
RENDER_PASS = os.environ.get("TRENCH_RENDER_PASS", "both").strip().lower()
SOURCE_BLEND = Path(
    r"C:\Users\hooki\df2\dev\tmp\thumbwheel_blender\user_live_wheel_locked_spin_embedded_cobalt_257.blend"
)
SOURCE_GLB = Path(r"C:\Users\hooki\Downloads\sample_2026-06-11T101037.998.glb")
REPO = Path(__file__).resolve().parents[1]
BASE_OUT = REPO / "dev" / "tmp" / "thumbwheel_blender" / "glb_wheel_257"
OUTPUT_VARIANT = os.environ.get("TRENCH_RENDER_VARIANT", "").strip()
if OUTPUT_VARIANT and not OUTPUT_VARIANT.replace("_", "").isalnum():
    raise RuntimeError(f"Invalid TRENCH_RENDER_VARIANT={OUTPUT_VARIANT!r}")
OUT = BASE_OUT if not OUTPUT_VARIANT else BASE_OUT / "variants" / OUTPUT_VARIANT
WHEEL_PASS = OUT / "wheel_pass"
TRANSMISSION_PASS = OUT / "transmission_pass"
CAMERA_ELEVATION_DEGREES = float(os.environ.get("TRENCH_CAMERA_ELEVATION_DEGREES", "0"))
CALIBRATE_ALL_LIGHTS = os.environ.get("TRENCH_CALIBRATE_ALL_LIGHTS", "0") == "1"

# The render is deliberately wider/taller than the shipped frame.  The fixed
# aperture is applied later, after both passes have been rendered.  Its raw
# image bounds contain the required 2-3 teeth of motion overscan.
RAW_SIZE = (1200, 360)
FIXED_CROP = (25, 42, 1175, 318)  # includes the authored rounded ends and transparent margin

WHEEL_OBJECT = "WheelT"
ACTION_NAME = "Wheel_Locked_OnePitch_LeftToRight"
ABANDONED_OBJECTS = {
    "CodexCleanFaceGlowHead",
    "WheelGlowCore",
}
ABANDONED_PREFIXES = ("WheelGlowBounce",)

# These are screen-space measurements from the fixed 400 px aperture, taken
# from WheelT's visible tooth/section signal.  They are intentionally
# irregular.  They locate invisible stationary point lights for the separate
# transmission pass; no mesh or moving lamp is created.
TRANSMISSION_SECTION_CENTERS = (
    10.0,
    32.0,
    57.0,
    86.0,
    115.0,
    141.0,
    165.0,
    211.0,
    237.0,
    264.0,
    285.0,
    307.0,
    342.0,
    361.0,
    381.0,
)


def _signed_degrees(radians: float) -> float:
    degrees = math.degrees(radians)
    return ((degrees + 180.0) % 360.0) - 180.0


def _set_input(node: bpy.types.ShaderNodeBsdfPrincipled, name: str, value) -> None:
    socket = node.inputs.get(name)
    if socket is not None:
        socket.default_value = value


def _clean_unmapped_material() -> bpy.types.Material:
    material = bpy.data.materials.get("TRENCH_RenderCleanGunmetal")
    if material is None:
        material = bpy.data.materials.new("TRENCH_RenderCleanGunmetal")
    material.use_nodes = True
    node_tree = material.node_tree
    node_tree.nodes.clear()

    output = node_tree.nodes.new("ShaderNodeOutputMaterial")
    principled = node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    principled.name = "CleanUnmappedPrincipled"
    principled.label = "Clean unmapped Principled only"
    # Cool desaturated violet graphite measured from the approved wheel
    # reference.  The body must not collapse to neutral grey; the black
    # recesses come from the real WheelT occlusion and the shaped lights.
    # No image or generated maps are used.
    _set_input(principled, "Base Color", (0.085, 0.075, 0.125, 1.0))
    _set_input(principled, "Metallic", 0.22)
    _set_input(principled, "Roughness", 0.34)
    _set_input(principled, "IOR", 1.45)
    _set_input(principled, "Specular IOR Level", 0.45)
    _set_input(principled, "Coat Weight", 0.025)
    node_tree.links.new(principled.outputs[0], output.inputs[0])
    return material


def _add_or_update_area_fill(scene: bpy.types.Scene):
    name = "TRENCH_RenderNeutralFill"
    obj = bpy.data.objects.get(name)
    created = obj is None
    if obj is None:
        data = bpy.data.lights.new(name, type="AREA")
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
    data = obj.data
    previous = {
        "location": obj.location.copy(),
        "rotation_euler": obj.rotation_euler.copy(),
        "energy": data.energy,
        "color": tuple(data.color),
        "shape": data.shape,
        "size": data.size,
        "size_y": getattr(data, "size_y", data.size),
        "hide_render": obj.hide_render,
    }
    obj.location = (-1.7, -2.8, -0.55)
    obj.rotation_euler = Euler((math.radians(68.0), 0.0, math.radians(-3.0)), "XYZ")
    data.energy = 86.0
    data.color = (0.56, 0.57, 0.60)
    data.shape = "RECTANGLE"
    data.size = 2.5
    if hasattr(data, "size_y"):
        data.size_y = 1.0
    obj.hide_render = False
    return obj, created, previous


def _apply_reference_gunmetal_lighting(scene: bpy.types.Scene) -> dict[str, dict]:
    """Apply only the light treatment measured from the approved reference."""
    settings = {
        "KeyT.007": {
            "energy": 155.0,
            "size": 3.2,
            "location": (-2.55, -1.78, 2.55),
        },
        "FacetGlintT.004": {"energy": 38.0, "size": 0.35},
        "EdgeT.006": {"energy": 4.0, "size": 5.843803405761719},
        "BottomRightT.001": {"energy": 10.0, "size": 1.8590914011001587},
    }
    previous: dict[str, dict] = {}
    for name, values in settings.items():
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "LIGHT":
            raise RuntimeError(f"Reference gunmetal light {name!r} is missing")
        previous[name] = {
            "energy": obj.data.energy,
            "size": getattr(obj.data, "size", None),
            "location": obj.location.copy(),
            "hide_render": obj.hide_render,
        }
        obj.data.energy = values["energy"]
        if hasattr(obj.data, "size"):
            obj.data.size = values["size"]
        if "location" in values:
            obj.location = values["location"]
        obj.hide_render = False

    fill = bpy.data.objects.get("FillT.007")
    if fill is not None and fill.type == "LIGHT":
        previous[fill.name] = {"hide_render": fill.hide_render}
        fill.hide_render = True
    return previous


def _restore_reference_gunmetal_lighting(previous: dict[str, dict]) -> None:
    for name, values in previous.items():
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        obj.hide_render = values["hide_render"]
        if "energy" in values:
            obj.data.energy = values["energy"]
        if values.get("size") is not None and hasattr(obj.data, "size"):
            obj.data.size = values["size"]
        if "location" in values:
            obj.location = values["location"]


def _add_or_update_transmission_light(scene: bpy.types.Scene):
    lights = []
    # These lights have no meshes and never move.  The supplied WheelT mesh is
    # therefore the only geometry that can occlude their illumination.
    for index, center in enumerate(TRANSMISSION_SECTION_CENTERS):
        name = f"TRENCH_RenderTransmissionSection_{index:02d}"
        data = bpy.data.lights.new(name, type="POINT")
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
        # Just behind the front teeth (front surface is near Y=-0.68).  The
        # older -0.34 bank sat too deep and the opaque center swallowed most
        # of the packet before it reached the visible internal channel.
        obj.location = ((center / 400.0 - 0.5) * 1.0015, -0.55, 0.0)
        data.energy = 0.0
        # TRENCH wheel lamp: the current interface accent (#2BD8C3), not blue.
        data.color = (0.169, 0.847, 0.765)
        data.shadow_soft_size = 0.04
        obj.hide_render = True
        lights.append(obj)
    return lights, True, None


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge0 == edge1:
        return 1.0 if value >= edge1 else 0.0
    t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _transmission_amplitudes(frame: int) -> list[float]:
    """X3 five-frame rise and trail, evaluated on physical internal lights."""
    if frame <= 0:
        return [0.0] * len(TRANSMISSION_SECTION_CENTERS)
    count = len(TRANSMISSION_SECTION_CENTERS)
    last_start = FRAME_LAST - 5.0
    starts = [index * last_start / max(1, count - 1) for index in range(count)]
    lead_index = (frame / float(FRAME_LAST)) * (count - 1)
    amplitudes = []
    for index, start in enumerate(starts):
        ramp = _smoothstep(start, start + 5.0, float(frame))
        age = max(0.0, frame - (start + 5.0))
        # The X3 reference keeps a readable internal tail over roughly the
        # right half of the wheel at 100%, while old off-screen sections fade.
        trail = math.exp(-age / 78.0)
        authored = ramp * (0.035 + 0.965 * trail)
        lead = math.exp(-((index - lead_index) / 0.72) ** 2)
        amplitudes.append(min(1.0, authored * 0.90 + lead * 0.10))
    return amplitudes


def _restore_light(obj, created: bool, previous: dict) -> None:
    if isinstance(obj, list):
        for light in obj:
            data = light.data
            bpy.data.objects.remove(light, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.lights.remove(data)
        return
    if created:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.lights.remove(data)
        return
    obj.location = previous["location"]
    obj.rotation_euler = previous.get("rotation_euler", obj.rotation_euler)
    obj.hide_render = previous["hide_render"]
    data = obj.data
    data.energy = previous["energy"]
    data.color = previous["color"]
    if hasattr(data, "shape") and "shape" in previous:
        data.shape = previous["shape"]
    if hasattr(data, "size") and "size" in previous:
        data.size = previous["size"]
    if hasattr(data, "size_y") and "size_y" in previous:
        data.size_y = previous["size_y"]
    if hasattr(data, "shadow_soft_size") and "shadow_soft_size" in previous:
        data.shadow_soft_size = previous["shadow_soft_size"]


def _render_pass(scene: bpy.types.Scene, folder: Path, point_light) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    lights = point_light if isinstance(point_light, list) else [point_light]
    for light in lights:
        light.hide_render = True
    for frame in range(FRAME_COUNT):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        scene.render.filepath = str(folder / f"frame_{frame:03d}.png")
        bpy.ops.render.render(write_still=True)
        if frame % 32 == 0 or frame == FRAME_LAST:
            print(f"[glb-wheel] rendered {folder.name} frame {frame}/{FRAME_LAST}")


def _authored_fcurves(action: bpy.types.Action, animation_data) -> list:
    """Return the f-curves from either Blender's legacy or layered action API."""
    if getattr(action, "is_action_legacy", False):
        return list(action.fcurves)
    slot = getattr(animation_data, "action_slot", None)
    slot_handle = getattr(slot, "handle", None)
    curves = []
    for layer in action.layers:
        for strip in layer.strips:
            for channelbag in strip.channelbags:
                if slot_handle is None or channelbag.slot_handle == slot_handle:
                    curves.extend(channelbag.fcurves)
    return curves


def main() -> None:
    if not SOURCE_BLEND.exists():
        raise FileNotFoundError(SOURCE_BLEND)
    if not SOURCE_GLB.exists():
        raise FileNotFoundError(SOURCE_GLB)

    scene = bpy.context.scene
    wheel = bpy.data.objects.get(WHEEL_OBJECT)
    if wheel is None or wheel.type != "MESH":
        raise RuntimeError(f"Expected mesh object {WHEEL_OBJECT!r}")
    if wheel.animation_data is None or wheel.animation_data.action is None:
        raise RuntimeError(f"{WHEEL_OBJECT} has no authored action")
    authored_action = wheel.animation_data.action
    if authored_action.name != ACTION_NAME:
        raise RuntimeError(
            f"Unexpected wheel action {authored_action.name!r}; expected {ACTION_NAME!r}"
        )

    z_fcurves = [
        fcurve
        for fcurve in _authored_fcurves(authored_action, wheel.animation_data)
        if fcurve.data_path == "rotation_euler" and fcurve.array_index == 2
    ]
    if len(z_fcurves) != 1:
        raise RuntimeError(
            f"Expected one authored rotation_euler.z curve, found {len(z_fcurves)}"
        )

    OUT.mkdir(parents=True, exist_ok=True)
    WHEEL_PASS.mkdir(parents=True, exist_ok=True)
    TRANSMISSION_PASS.mkdir(parents=True, exist_ok=True)

    old_frame = scene.frame_current
    old_filepath = scene.render.filepath
    old_engine = scene.render.engine
    old_resolution = (
        scene.render.resolution_x,
        scene.render.resolution_y,
        scene.render.resolution_percentage,
    )
    old_film_transparent = scene.render.film_transparent
    old_color_mode = scene.render.image_settings.color_mode
    old_color_depth = scene.render.image_settings.color_depth
    old_exposure = scene.view_settings.exposure
    camera = scene.camera
    old_camera_location = camera.location.copy() if camera is not None else None
    old_camera_rotation = camera.rotation_euler.copy() if camera is not None else None
    old_action = authored_action
    old_action_slot = wheel.animation_data.action_slot
    old_materials = list(wheel.data.materials)
    hidden_objects: dict[str, bool] = {}
    area_fill = None
    reference_lighting = {}
    point_light = None

    try:
        # Evaluate the source action first.  This is the motion authority; the
        # +180 degree offset is applied only after these authored values are
        # captured and the action is detached from the render copy.
        authored_rotations = []
        for frame in range(FRAME_COUNT):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            authored_rotations.append(tuple(float(v) for v in wheel.rotation_euler))

        authored_degrees = [_signed_degrees(rotation[2]) for rotation in authored_rotations]
        opposite_degrees = [
            _signed_degrees(rotation[2] + math.pi) for rotation in authored_rotations
        ]
        checkpoints = {
            "0": opposite_degrees[0],
            "128": opposite_degrees[128],
            "256": opposite_degrees[256],
        }
        expected = (23.0, 30.0, 37.0)
        observed = (opposite_degrees[0], opposite_degrees[128], opposite_degrees[256])
        if any(abs(actual - wanted) > 0.75 for actual, wanted in zip(observed, expected)):
            raise RuntimeError(
                f"Authored +180 degree checkpoints drifted: observed={observed}, expected={expected}"
            )

        wheel.animation_data.action = None
        clean_material = _clean_unmapped_material()
        wheel.data.materials.clear()
        wheel.data.materials.append(clean_material)

        for obj in scene.objects:
            if obj.name in ABANDONED_OBJECTS or obj.name.startswith(ABANDONED_PREFIXES):
                hidden_objects[obj.name] = obj.hide_render
                obj.hide_render = True

        reference_lighting = _apply_reference_gunmetal_lighting(scene)
        point_light, point_created, point_previous = _add_or_update_transmission_light(scene)

        if abs(CAMERA_ELEVATION_DEGREES) > 1.0e-6:
            if camera is None or camera.data.type != "ORTHO":
                raise RuntimeError("Camera-elevation probe requires the authored orthographic camera")
            elevation = math.radians(CAMERA_ELEVATION_DEGREES)
            camera.location.z = old_camera_location.z + math.tan(elevation) * abs(old_camera_location.y)
            camera.rotation_euler.x = old_camera_rotation.x - elevation

        scene.render.engine = "BLENDER_EEVEE"
        scene.cycles.samples = 16
        scene.cycles.use_denoising = True
        scene.render.resolution_x, scene.render.resolution_y = RAW_SIZE
        scene.render.resolution_percentage = 100
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.image_settings.color_depth = "8"
        scene.render.film_transparent = True
        scene.view_settings.exposure = 0.0

        render_frames = (
            [int(ONLY_FRAME)] if ONLY_FRAME is not None else list(range(FRAME_COUNT))
        )
        if any(frame < 0 or frame > FRAME_LAST for frame in render_frames):
            raise RuntimeError(f"Invalid TRENCH_RENDER_ONLY_FRAME={ONLY_FRAME}")
        if RENDER_PASS not in {"both", "wheel", "transmission"}:
            raise RuntimeError(f"Invalid TRENCH_RENDER_PASS={RENDER_PASS!r}")

        # Clean pass: point light is disabled, and the existing authored action
        # is replaced only by its sampled rotation plus the exact pi offset.
        if RENDER_PASS in {"both", "wheel"}:
            for light in point_light:
                light.hide_render = True
            for frame in render_frames:
                rotation = authored_rotations[frame]
                scene.frame_set(frame)
                wheel.rotation_euler = Euler(
                    (rotation[0], rotation[1], rotation[2] + math.pi),
                    wheel.rotation_mode,
                )
                bpy.context.view_layer.update()
                scene.render.filepath = str(WHEEL_PASS / f"frame_{frame:03d}.png")
                bpy.ops.render.render(write_still=True)
                if frame % 32 == 0 or frame == FRAME_LAST:
                    print(f"[glb-wheel] rendered wheel_pass frame {frame}/{FRAME_LAST}")

        # Transmission pass: same exact poses and crop source, with only the
        # stationary point light enabled.  Real WheelT teeth occlude it.
        if RENDER_PASS in {"both", "transmission"}:
            for frame in render_frames:
                amplitudes = (
                    [1.0] * len(point_light)
                    if CALIBRATE_ALL_LIGHTS
                    else _transmission_amplitudes(frame)
                )
                for light, amplitude in zip(point_light, amplitudes):
                    light.hide_render = amplitude <= 0.0005
                    light.data.energy = 0.34 * amplitude
                rotation = authored_rotations[frame]
                scene.frame_set(frame)
                wheel.rotation_euler = Euler(
                    (rotation[0], rotation[1], rotation[2] + math.pi),
                    wheel.rotation_mode,
                )
                bpy.context.view_layer.update()
                scene.render.filepath = str(TRANSMISSION_PASS / f"frame_{frame:03d}.png")
                bpy.ops.render.render(write_still=True)
                if frame % 32 == 0 or frame == FRAME_LAST:
                    print(f"[glb-wheel] rendered transmission_pass frame {frame}/{FRAME_LAST}")

        manifest = {
            "source_blend": str(SOURCE_BLEND),
            "source_glb": str(SOURCE_GLB),
            "scene": scene.name,
            "object": WHEEL_OBJECT,
            "action": ACTION_NAME,
            "channel": "rotation_euler.z",
            "frame_count": FRAME_COUNT,
            "frame_values": list(range(FRAME_COUNT)),
            "rotation_delta_degrees": 180.0,
            "authored_degrees": {
                "0": authored_degrees[0],
                "128": authored_degrees[128],
                "256": authored_degrees[256],
            },
            "opposite_degrees": checkpoints,
            "raw_size": list(RAW_SIZE),
            "fixed_crop": list(FIXED_CROP),
            "camera_elevation_degrees": CAMERA_ELEVATION_DEGREES,
            "render_engine": scene.render.engine,
            "exposure": 0.0,
            "clean_material": {
                "name": clean_material.name,
                "node_types": [node.bl_idname for node in clean_material.node_tree.nodes],
                "image_texture_nodes": 0,
                "normal_maps": 0,
                "roughness_maps": 0,
                "base_color": [0.045, 0.049, 0.056, 1.0],
            },
            "excluded_objects": sorted(ABANDONED_OBJECTS),
            "excluded_prefixes": list(ABANDONED_PREFIXES),
            "transmission_light": {
                "type": "stationary_point_section_bank",
                "mesh": False,
                "peak_energy_each": 0.34,
                "screen_centers": list(TRANSMISSION_SECTION_CENTERS),
                "center_source": "frame-128 all-light transmission calibration through the final camera/crop",
                "progression": "physical X3 five-frame rise and trail",
                "calibration_all_lights": CALIBRATE_ALL_LIGHTS,
            },
            "passes": {
                "wheel": str(WHEEL_PASS),
                "transmission": str(TRANSMISSION_PASS),
            },
        }
        (OUT / "render_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        print(json.dumps({"render_manifest": str(OUT / "render_manifest.json"), "checkpoints": checkpoints}))
    finally:
        if wheel.animation_data is not None:
            wheel.animation_data.action = old_action
            wheel.animation_data.action_slot = old_action_slot
        wheel.data.materials.clear()
        for material in old_materials:
            wheel.data.materials.append(material)
        for name, hide_render in hidden_objects.items():
            obj = bpy.data.objects.get(name)
            if obj is not None:
                obj.hide_render = hide_render
        if area_fill is not None:
            _restore_light(area_fill, area_created, area_previous)
        if point_light is not None:
            _restore_light(point_light, point_created, point_previous)
        _restore_reference_gunmetal_lighting(reference_lighting)
        scene.frame_set(old_frame)
        scene.render.filepath = old_filepath
        scene.render.engine = old_engine
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = old_resolution
        scene.render.film_transparent = old_film_transparent
        scene.render.image_settings.color_mode = old_color_mode
        scene.render.image_settings.color_depth = old_color_depth
        scene.view_settings.exposure = old_exposure
        if camera is not None:
            camera.location = old_camera_location
            camera.rotation_euler = old_camera_rotation


if __name__ == "__main__":
    main()
