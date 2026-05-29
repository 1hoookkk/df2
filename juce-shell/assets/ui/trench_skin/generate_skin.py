"""Render an original X3-era TRENCH plugin skin asset.

Run from the repository root with:
    blender --background --python assets/ui/trench_skin/generate_skin.py

The asset is intentionally static: no labels, values, response curve, handles, or
live state are baked into the PNGs.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RANDOM_SEED = 180013
RENDER_WIDTH = 920
RENDER_HEIGHT = 1320
PANEL_WIDTH = 4.60
PANEL_HEIGHT = 6.60

LAYER_PANEL = "panel_base"
LAYER_PLASTIC = "plastic_shell"
LAYER_DISPLAY = "display_bezels"
LAYER_SLOTS = "slot_bezels"
ALL_LAYERS = (LAYER_PANEL, LAYER_PLASTIC, LAYER_DISPLAY, LAYER_SLOTS)


def clean_scene() -> None:
    if bpy.context.active_object and bpy.context.active_object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    for collection in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.curves,
        bpy.data.images,
    ):
        for block in list(collection):
            collection.remove(block)


def set_input(node: bpy.types.Node, input_name: str, value) -> None:
    if input_name in node.inputs:
        node.inputs[input_name].default_value = value


def make_material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    metallic: float = 0.0,
    roughness: float = 0.7,
    alpha: float | None = None,
    emission: tuple[float, float, float, float] | None = None,
    emission_strength: float = 0.0,
    noise_scale: float | None = None,
    bump_strength: float = 0.02,
    bump_distance: float = 0.010,
) -> bpy.types.Material:
    if alpha is not None:
        color = (color[0], color[1], color[2], alpha)

    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    mat.blend_method = "BLEND"
    mat.use_screen_refraction = True
    mat.show_transparent_back = True

    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        set_input(bsdf, "Base Color", color)
        set_input(bsdf, "Metallic", metallic)
        set_input(bsdf, "Roughness", roughness)
        set_input(bsdf, "Alpha", color[3])
        if emission is not None:
            set_input(bsdf, "Emission Color", emission)
            set_input(bsdf, "Emission Strength", emission_strength)
        if noise_scale is not None and "Normal" in bsdf.inputs:
            noise = mat.node_tree.nodes.new("ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = noise_scale
            noise.inputs["Detail"].default_value = 12.0
            noise.inputs["Roughness"].default_value = 0.68

            bump = mat.node_tree.nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = bump_strength
            bump.inputs["Distance"].default_value = bump_distance

            mat.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
            mat.node_tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    return mat


def material(name: str) -> bpy.types.Material:
    return bpy.data.materials[name]


def assign_layer(obj: bpy.types.Object, layer: str) -> bpy.types.Object:
    obj["skin_layer"] = layer
    return obj


def shade_with_bevel(obj: bpy.types.Object, bevel: float, segments: int = 3) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.shade_smooth()
    obj.select_set(False)

    bevel_mod = obj.modifiers.new("small raster-skin bevel", "BEVEL")
    bevel_mod.width = bevel
    bevel_mod.segments = segments
    bevel_mod.affect = "EDGES"

    weighted = obj.modifiers.new("weighted normals", "WEIGHTED_NORMAL")
    weighted.keep_sharp = True


def add_box(
    name: str,
    x: float,
    z: float,
    width: float,
    height: float,
    depth: float,
    y: float,
    mat: bpy.types.Material,
    *,
    layer: str,
    bevel: float = 0.0,
    bevel_segments: int = 3,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z))
    obj = bpy.context.object
    obj.name = name
    obj.data.name = f"{name}Mesh"
    obj.dimensions = (width, depth, height)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    assign_layer(obj, layer)
    if bevel > 0.0:
        shade_with_bevel(obj, bevel, bevel_segments)
    return obj


def add_disc(
    name: str,
    x: float,
    z: float,
    radius: float,
    depth: float,
    y: float,
    mat: bpy.types.Material,
    *,
    layer: str,
    vertices: int = 48,
    bevel: float = 0.0,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices,
        radius=radius,
        depth=depth,
        end_fill_type="NGON",
        location=(x, y, z),
        rotation=(math.pi / 2.0, 0.0, 0.0),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.name = f"{name}Mesh"
    obj.data.materials.append(mat)
    assign_layer(obj, layer)
    if bevel > 0.0:
        shade_with_bevel(obj, bevel, 2)
    return obj


def add_curve_line(
    name: str,
    points: list[tuple[float, float]],
    y: float,
    width: float,
    mat: bpy.types.Material,
    *,
    layer: str,
) -> bpy.types.Object:
    curve = bpy.data.curves.new(f"{name}Curve", "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_depth = width
    curve.bevel_resolution = 0

    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, (x, z) in zip(spline.points, points):
        point.co = (x, y, z, 1.0)

    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    assign_layer(obj, layer)
    return obj


def add_frame(
    prefix: str,
    x: float,
    z: float,
    width: float,
    height: float,
    *,
    layer: str,
    rail: float,
    y: float,
    rail_mat: bpy.types.Material,
    well_mat: bpy.types.Material,
    rail_depth: float = 0.060,
    well_depth: float = 0.022,
    bevel: float = 0.030,
) -> None:
    add_box(
        f"{prefix}_raised_rim",
        x,
        z,
        width,
        height,
        rail_depth,
        y,
        rail_mat,
        layer=layer,
        bevel=bevel,
        bevel_segments=4,
    )
    add_box(
        f"{prefix}_recessed_well",
        x,
        z,
        width - rail * 2.0,
        height - rail * 2.0,
        well_depth,
        y - 0.060,
        well_mat,
        layer=layer,
        bevel=bevel * 0.72,
        bevel_segments=3,
    )


def create_materials() -> None:
    make_material("transparent smoke wash", (0.075, 0.082, 0.078, 0.18), roughness=0.34, alpha=0.18, noise_scale=42.0)
    make_material("old brushed graphite", (0.440, 0.455, 0.435, 1.0), metallic=0.22, roughness=0.76, noise_scale=96.0, bump_strength=0.016)
    make_material("brushed highlight hair", (0.90, 0.94, 0.88, 0.16), roughness=0.9, alpha=0.16)
    make_material("brushed shadow hair", (0.02, 0.025, 0.024, 0.13), roughness=0.9, alpha=0.13)
    make_material("left dark metal strip", (0.095, 0.105, 0.100, 1.0), metallic=0.35, roughness=0.72)
    make_material("inner bevel shadow", (0.015, 0.017, 0.016, 0.55), roughness=0.82, alpha=0.55)
    make_material("dull clear plastic rail", (0.62, 0.68, 0.64, 0.58), roughness=0.28, alpha=0.58, noise_scale=22.0, bump_strength=0.011)
    make_material("clear edge glint", (0.82, 0.88, 0.80, 0.28), roughness=0.20, alpha=0.28)
    make_material("black old lcd well", (0.003, 0.006, 0.006, 1.0), roughness=0.78, noise_scale=44.0, bump_strength=0.006)
    make_material(
        "dead green teal lcd",
        (0.010, 0.095, 0.085, 1.0),
        roughness=0.58,
        emission=(0.015, 0.070, 0.060, 1.0),
        emission_strength=0.050,
        noise_scale=82.0,
        bump_strength=0.004,
    )
    make_material("faint lcd grid", (0.42, 0.92, 0.78, 0.16), roughness=0.7, alpha=0.16)
    make_material("mechanical slot black", (0.004, 0.004, 0.004, 1.0), roughness=0.82, noise_scale=38.0, bump_strength=0.007)
    make_material("rubber rib shadow", (0.0, 0.0, 0.0, 0.46), roughness=0.9, alpha=0.46)
    make_material("subtle red pcb underlay", (0.055, 0.028, 0.024, 0.10), roughness=0.86, alpha=0.10)
    make_material("buried red trace", (0.42, 0.085, 0.045, 0.18), roughness=0.78, alpha=0.18)
    make_material("dust and scuff", (0.88, 0.86, 0.74, 0.16), roughness=0.9, alpha=0.16)
    make_material("dark screw nickel", (0.16, 0.15, 0.12, 0.86), metallic=0.58, roughness=0.38, alpha=0.86)
    make_material("screw black cut", (0.0, 0.0, 0.0, 0.85), roughness=0.8, alpha=0.85)


def setup_render() -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True

    scene.render.film_transparent = True
    scene.render.resolution_x = RENDER_WIDTH
    scene.render.resolution_y = RENDER_HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.compression = 15
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    cam_data = bpy.data.cameras.new("orthographic_front_camera")
    cam = bpy.data.objects.new("orthographic_front_camera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = (0.0, -8.0, 0.0)
    direction = Vector((0.0, 0.0, 0.0)) - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = PANEL_HEIGHT
    scene.camera = cam

    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = False
    world.color = (0.0, 0.0, 0.0)

    bpy.ops.object.light_add(type="AREA", location=(-1.8, -5.0, 3.6))
    key = bpy.context.object
    key.name = "soft old-plugin upper-left"
    key.data.energy = 420.0
    key.data.size = 4.6

    bpy.ops.object.light_add(type="AREA", location=(2.5, -4.5, -1.2))
    fill = bpy.context.object
    fill.name = "low plastic edge fill"
    fill.data.energy = 72.0
    fill.data.size = 3.0


def build_panel_base(rng: random.Random) -> None:
    # X3-like vertical module: brushed software faceplate first, hardware material cues second.
    add_box("main_x3_rounded_faceplate", 0.0, 0.0, 4.34, 6.44, 0.105, 0.000, material("old brushed graphite"), layer=LAYER_PANEL, bevel=0.135, bevel_segments=12)
    add_box("left_neighbor_shadow_strip", -2.24, 0.0, 0.20, 6.34, 0.055, -0.030, material("left dark metal strip"), layer=LAYER_PANEL, bevel=0.040, bevel_segments=4)
    add_box("inner_left_black_seam", -2.02, 0.0, 0.035, 6.18, 0.034, -0.085, material("inner bevel shadow"), layer=LAYER_PANEL, bevel=0.012, bevel_segments=2)
    add_box("inner_right_black_seam", 2.05, 0.0, 0.035, 6.08, 0.034, -0.085, material("inner bevel shadow"), layer=LAYER_PANEL, bevel=0.012, bevel_segments=2)

    add_box("buried_red_board_hint", 0.0, -1.38, 3.22, 2.40, 0.024, -0.100, material("subtle red pcb underlay"), layer=LAYER_PANEL, bevel=0.060, bevel_segments=6)

    for idx in range(128):
        x = rng.uniform(-1.94, 1.94)
        z = rng.uniform(-3.00, 3.05)
        length = rng.uniform(0.22, 0.72)
        mat = material("brushed highlight hair") if idx % 4 == 0 else material("brushed shadow hair")
        add_curve_line(f"x3_vertical_brush_{idx:03d}", [(x, z - length / 2.0), (x + rng.uniform(-0.006, 0.006), z + length / 2.0)], -0.150, rng.uniform(0.0017, 0.0038), mat, layer=LAYER_PANEL)

    for idx in range(16):
        z = rng.uniform(-2.82, 2.80)
        x1 = rng.uniform(-1.80, -0.35)
        x2 = rng.uniform(0.40, 1.82)
        add_curve_line(f"buried_red_trace_{idx:02d}", [(x1, z), (x2, z + rng.uniform(-0.08, 0.08))], -0.165, 0.004, material("buried red trace"), layer=LAYER_PANEL)
        add_disc(f"buried_red_via_l_{idx:02d}", x1, z, 0.018, 0.004, -0.170, material("buried red trace"), layer=LAYER_PANEL, vertices=14)
        add_disc(f"buried_red_via_r_{idx:02d}", x2, z, 0.018, 0.004, -0.170, material("buried red trace"), layer=LAYER_PANEL, vertices=14)

    for idx, (x, z) in enumerate(((-1.84, 2.94), (1.84, 2.94), (-1.84, -2.94), (1.84, -2.94))):
        add_disc(f"small_corner_screw_{idx}", x, z, 0.105, 0.026, -0.190, material("dark screw nickel"), layer=LAYER_PANEL, vertices=48, bevel=0.006)
        add_box(f"small_corner_screw_cross_h_{idx}", x, z, 0.115, 0.017, 0.011, -0.210, material("screw black cut"), layer=LAYER_PANEL, bevel=0.002)
        add_box(f"small_corner_screw_cross_v_{idx}", x, z, 0.017, 0.115, 0.011, -0.211, material("screw black cut"), layer=LAYER_PANEL, bevel=0.002)


def build_plastic_shell(rng: random.Random) -> None:
    add_box("smoked_clear_skin_over_face", 0.0, 0.0, 4.24, 6.34, 0.030, -0.230, material("transparent smoke wash"), layer=LAYER_PLASTIC, bevel=0.120, bevel_segments=10)
    add_box("top_cloudy_lip", 0.0, 3.09, 3.82, 0.045, 0.044, -0.270, material("dull clear plastic rail"), layer=LAYER_PLASTIC, bevel=0.022, bevel_segments=4)
    add_box("bottom_cloudy_lip", 0.0, -3.10, 3.76, 0.045, 0.044, -0.270, material("dull clear plastic rail"), layer=LAYER_PLASTIC, bevel=0.022, bevel_segments=4)
    add_box("left_cloudy_lip", -1.98, 0.0, 0.040, 5.78, 0.044, -0.270, material("dull clear plastic rail"), layer=LAYER_PLASTIC, bevel=0.022, bevel_segments=4)
    add_box("right_cloudy_lip", 1.98, 0.0, 0.040, 5.78, 0.044, -0.270, material("dull clear plastic rail"), layer=LAYER_PLASTIC, bevel=0.022, bevel_segments=4)

    for idx in range(46):
        x = rng.uniform(-1.82, 1.82)
        z = rng.uniform(-2.86, 2.86)
        if -1.74 < x < 1.74 and 0.68 < z < 2.46 and rng.random() < 0.75:
            continue
        if -1.52 < x < 1.56 and -0.28 < z < 0.82 and rng.random() < 0.55:
            continue
        length = rng.uniform(0.08, 0.40)
        angle = rng.choice((0.0, math.radians(2.5), math.radians(-3.0), math.radians(12.0)))
        dx = math.cos(angle) * length / 2.0
        dz = math.sin(angle) * length / 2.0
        add_curve_line(f"smoked_plastic_scratch_{idx:02d}", [(x - dx, z - dz), (x + dx, z + dz)], -0.315, rng.uniform(0.0018, 0.0036), material("dust and scuff"), layer=LAYER_PLASTIC)


def build_display_bezel() -> None:
    add_frame(
        "x3_compact_lcd",
        0.0,
        1.72,
        3.64,
        1.58,
        layer=LAYER_DISPLAY,
        rail=0.105,
        y=-0.305,
        rail_mat=material("dull clear plastic rail"),
        well_mat=material("black old lcd well"),
        rail_depth=0.060,
        bevel=0.038,
    )
    add_box("dead_teal_lcd_field", 0.0, 1.72, 3.34, 1.33, 0.018, -0.385, material("dead green teal lcd"), layer=LAYER_DISPLAY, bevel=0.030, bevel_segments=3)

    left, right = -1.60, 1.60
    bottom, top = 1.10, 2.34
    for idx in range(1, 13):
        x = left + (right - left) * idx / 13.0
        add_box(f"lcd_reference_grid_v_{idx:02d}", x, (bottom + top) / 2.0, 0.0035, top - bottom, 0.006, -0.410, material("faint lcd grid"), layer=LAYER_DISPLAY)
    for idx in range(1, 6):
        z = bottom + (top - bottom) * idx / 6.0
        add_box(f"lcd_reference_grid_h_{idx:02d}", 0.0, z, right - left, 0.0035, 0.006, -0.411, material("faint lcd grid"), layer=LAYER_DISPLAY)


def build_slot_bezels() -> None:
    add_frame(
        "x3_type_slot",
        0.0,
        2.59,
        3.64,
        0.31,
        layer=LAYER_SLOTS,
        rail=0.060,
        y=-0.305,
        rail_mat=material("dull clear plastic rail"),
        well_mat=material("mechanical slot black"),
        rail_depth=0.052,
        bevel=0.028,
    )

    for prefix, z in (("x3_morph_slot", 0.44), ("x3_q_slot", -0.29)):
        add_frame(
            prefix,
            -0.48,
            z,
            2.48,
            0.34,
            layer=LAYER_SLOTS,
            rail=0.070,
            y=-0.305,
            rail_mat=material("dull clear plastic rail"),
            well_mat=material("mechanical slot black"),
            rail_depth=0.054,
            bevel=0.032,
        )
        for idx in range(17):
            x = -1.55 + idx * 0.135
            add_box(f"{prefix}_rib_{idx:02d}", x, z, 0.026, 0.185, 0.006, -0.392, material("rubber rib shadow"), layer=LAYER_SLOTS, bevel=0.002)

        add_frame(
            f"{prefix}_readout_well",
            1.34,
            z,
            0.76,
            0.39,
            layer=LAYER_SLOTS,
            rail=0.070,
            y=-0.306,
            rail_mat=material("dull clear plastic rail"),
            well_mat=material("mechanical slot black"),
            rail_depth=0.054,
            bevel=0.030,
        )

    for name, x, z, w, h in (
        ("type_top_edge_glint", 0.0, 2.74, 3.54, 0.012),
        ("lcd_top_edge_glint", 0.0, 2.48, 3.54, 0.014),
        ("morph_top_edge_glint", -0.48, 0.59, 2.36, 0.012),
        ("q_top_edge_glint", -0.48, -0.14, 2.36, 0.012),
    ):
        add_box(name, x, z, w, h, 0.010, -0.420, material("clear edge glint"), layer=LAYER_SLOTS, bevel=0.003)


def build_scene() -> None:
    rng = random.Random(RANDOM_SEED)
    clean_scene()
    create_materials()
    setup_render()
    build_panel_base(rng)
    build_plastic_shell(rng)
    build_display_bezel()
    build_slot_bezels()


def set_layer_visibility(visible_layers: set[str]) -> None:
    for obj in bpy.context.scene.objects:
        layer = obj.get("skin_layer")
        obj.hide_render = layer is not None and layer not in visible_layers


def render_layer(filename: str, visible_layers: set[str]) -> None:
    set_layer_visibility(visible_layers)
    bpy.context.scene.render.filepath = str(OUTPUT_DIR / filename)
    bpy.ops.render.render(write_still=True)


def main() -> None:
    build_scene()
    render_layer("panel_base.png", {LAYER_PANEL})
    render_layer("plastic_shell.png", {LAYER_PLASTIC})
    render_layer("display_bezels.png", {LAYER_DISPLAY})
    render_layer("slot_bezels.png", {LAYER_SLOTS})
    render_layer("full_preview.png", set(ALL_LAYERS))


if __name__ == "__main__":
    main()
