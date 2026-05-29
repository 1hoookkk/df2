"""Procedurally render original TRENCH encoder knob PNG layers.

Run from the repository root with:
    blender --background --python assets/knobs/generate_knob.py
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

RANDOM_SEED = 42719
SEGMENTS = 192


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


def set_input(node, input_name: str, value) -> None:
    if input_name in node.inputs:
        node.inputs[input_name].default_value = value


def make_material(
    name: str,
    base_color: tuple[float, float, float, float],
    *,
    metallic: float = 0.0,
    roughness: float = 0.65,
    noise_scale: float | None = None,
    bump_strength: float = 0.04,
    bump_distance: float = 0.025,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = base_color
    mat.use_nodes = True

    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        set_input(bsdf, "Base Color", base_color)
        set_input(bsdf, "Metallic", metallic)
        set_input(bsdf, "Roughness", roughness)
        set_input(bsdf, "Alpha", base_color[3])
        set_input(bsdf, "Subsurface Weight", 0.08 if "oxblood" in name.lower() else 0.0)

        if noise_scale is not None and "Normal" in bsdf.inputs:
            noise = mat.node_tree.nodes.new("ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = noise_scale
            noise.inputs["Detail"].default_value = 10.0
            noise.inputs["Roughness"].default_value = 0.62

            bump = mat.node_tree.nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = bump_strength
            bump.inputs["Distance"].default_value = bump_distance

            mat.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
            mat.node_tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    return mat


def assign_layer(obj: bpy.types.Object, layer: str) -> bpy.types.Object:
    obj["knob_layer"] = layer
    return obj


def shade_with_bevel(obj: bpy.types.Object, bevel: float, segments: int = 2) -> None:
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.shade_smooth()
    obj.select_set(False)

    bevel_mod = obj.modifiers.new("soft worn bevel", "BEVEL")
    bevel_mod.width = bevel
    bevel_mod.segments = segments
    bevel_mod.affect = "EDGES"

    weighted = obj.modifiers.new("weighted normals", "WEIGHTED_NORMAL")
    weighted.keep_sharp = True


def create_lathe(
    name: str,
    profile: list[tuple[float, float]],
    material: bpy.types.Material,
    *,
    layer: str,
    segments: int = SEGMENTS,
    cap_ends: bool = True,
    bevel: float = 0.0,
) -> bpy.types.Object:
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for z, radius in profile:
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            verts.append((radius * math.cos(angle), radius * math.sin(angle), z))

    for ring in range(len(profile) - 1):
        start = ring * segments
        next_start = (ring + 1) * segments
        for i in range(segments):
            faces.append(
                (
                    start + i,
                    start + (i + 1) % segments,
                    next_start + (i + 1) % segments,
                    next_start + i,
                )
            )

    if cap_ends:
        faces.append(tuple(reversed(range(segments))))
        top_start = (len(profile) - 1) * segments
        faces.append(tuple(top_start + i for i in range(segments)))

    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    assign_layer(obj, layer)

    if bevel > 0.0:
        shade_with_bevel(obj, bevel)

    return obj


def create_annular_cylinder(
    name: str,
    inner_radius: float,
    outer_radius: float,
    z_min: float,
    z_max: float,
    material: bpy.types.Material,
    *,
    layer: str,
    segments: int = SEGMENTS,
    bevel: float = 0.0,
) -> bpy.types.Object:
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for z in (z_min, z_max):
        for radius in (outer_radius, inner_radius):
            for i in range(segments):
                angle = 2.0 * math.pi * i / segments
                verts.append((radius * math.cos(angle), radius * math.sin(angle), z))

    outer_bottom = 0
    inner_bottom = segments
    outer_top = segments * 2
    inner_top = segments * 3

    for i in range(segments):
        ni = (i + 1) % segments
        faces.append((outer_bottom + i, outer_bottom + ni, outer_top + ni, outer_top + i))
        faces.append((inner_bottom + ni, inner_bottom + i, inner_top + i, inner_top + ni))
        faces.append((outer_top + i, outer_top + ni, inner_top + ni, inner_top + i))
        faces.append((outer_bottom + ni, outer_bottom + i, inner_bottom + i, inner_bottom + ni))

    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    assign_layer(obj, layer)

    if bevel > 0.0:
        shade_with_bevel(obj, bevel)

    return obj


def add_cylinder(
    name: str,
    radius: float,
    depth: float,
    z: float,
    material: bpy.types.Material,
    *,
    layer: str,
    vertices: int = SEGMENTS,
    bevel: float = 0.0,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices,
        radius=radius,
        depth=depth,
        end_fill_type="NGON",
        location=(0.0, 0.0, z),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.name = f"{name}Mesh"
    obj.data.materials.append(material)
    assign_layer(obj, layer)

    if bevel > 0.0:
        shade_with_bevel(obj, bevel)

    return obj


def add_knurl_ridges(material: bpy.types.Material) -> None:
    rng = random.Random(RANDOM_SEED + 101)
    ridge_count = 88
    radius = 1.015
    tangent_width = 0.020
    radial_depth = 0.055

    for i in range(ridge_count):
        angle = 2.0 * math.pi * i / ridge_count
        height = 0.275 + rng.uniform(-0.014, 0.010)
        z = 0.270 + rng.uniform(-0.004, 0.004)
        protrude = radial_depth + rng.uniform(-0.008, 0.006)
        r = radius + protrude * 0.45

        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(r * math.cos(angle), r * math.sin(angle), z),
            rotation=(0.0, 0.0, angle),
        )
        ridge = bpy.context.object
        ridge.name = f"knurl_ridge_{i:02d}"
        ridge.dimensions = (tangent_width, protrude, height)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        ridge.data.materials.append(material)
        assign_layer(ridge, "shell")
        shade_with_bevel(ridge, 0.006, 1)


def add_triangle_marker(material: bpy.types.Material) -> None:
    z = 0.557
    verts = [
        (0.0, 0.575, z),
        (-0.070, 0.420, z),
        (0.070, 0.420, z),
        (0.0, 0.575, z + 0.010),
        (-0.070, 0.420, z + 0.010),
        (0.070, 0.420, z + 0.010),
    ]
    faces = [
        (0, 1, 2),
        (5, 4, 3),
        (0, 3, 4, 1),
        (1, 4, 5, 2),
        (2, 5, 3, 0),
    ]

    mesh = bpy.data.meshes.new("indexMarkerMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    marker = bpy.data.objects.new("small_triangular_index_marker", mesh)
    bpy.context.collection.objects.link(marker)
    marker.data.materials.append(material)
    assign_layer(marker, "rotor")
    shade_with_bevel(marker, 0.004, 1)


def add_curve_scratch(
    name: str,
    points: list[tuple[float, float, float]],
    material: bpy.types.Material,
    *,
    layer: str,
    bevel_depth: float,
) -> None:
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 2
    curve.bevel_depth = bevel_depth
    curve.bevel_resolution = 1

    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, co in zip(spline.points, points):
        point.co = (co[0], co[1], co[2], 1.0)

    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    assign_layer(obj, layer)


def add_scratches(shell_mat: bpy.types.Material, rotor_mat: bpy.types.Material) -> None:
    rng = random.Random(RANDOM_SEED + 202)

    for i in range(18):
        radius = rng.uniform(0.36, 0.66)
        angle = rng.uniform(0.0, math.tau)
        length = rng.uniform(0.050, 0.145)
        tangent = Vector((-math.sin(angle), math.cos(angle), 0.0))
        center = Vector((radius * math.cos(angle), radius * math.sin(angle), 0.551))
        wobble = rng.uniform(-0.015, 0.015)
        points = [
            tuple(center - tangent * length * 0.5),
            tuple(center + Vector((wobble, -wobble, 0.0))),
            tuple(center + tangent * length * 0.5),
        ]
        add_curve_scratch(f"rotor_hairline_{i:02d}", points, rotor_mat, layer="rotor", bevel_depth=0.0015)

    for i in range(14):
        radius = rng.uniform(0.78, 1.08)
        angle = rng.uniform(0.0, math.tau)
        length = rng.uniform(0.035, 0.115)
        tangent = Vector((-math.sin(angle), math.cos(angle), 0.0))
        center = Vector((radius * math.cos(angle), radius * math.sin(angle), 0.151))
        points = [
            tuple(center - tangent * length * 0.5),
            tuple(center + tangent * length * 0.5),
        ]
        add_curve_scratch(f"skirt_scuff_{i:02d}", points, shell_mat, layer="shell", bevel_depth=0.0018)


def build_knob() -> None:
    graphite = make_material(
        "dull graphite black",
        (0.010, 0.011, 0.010, 1.0),
        roughness=0.78,
        noise_scale=95.0,
        bump_strength=0.055,
        bump_distance=0.030,
    )
    ridge_graphite = make_material(
        "worn graphite ridge highlights",
        (0.020, 0.021, 0.019, 1.0),
        roughness=0.82,
        noise_scale=140.0,
        bump_strength=0.050,
        bump_distance=0.018,
    )
    nickel = make_material(
        "dull nickel retaining skirt",
        (0.275, 0.260, 0.225, 1.0),
        metallic=1.0,
        roughness=0.84,
        noise_scale=180.0,
        bump_strength=0.080,
        bump_distance=0.014,
    )
    worn_nickel = make_material(
        "worn pale nickel scuffs",
        (0.485, 0.455, 0.385, 1.0),
        metallic=0.3,
        roughness=0.80,
    )
    oxblood = make_material(
        "smoked dark oxblood insert",
        (0.105, 0.020, 0.016, 1.0),
        roughness=0.50,
        noise_scale=70.0,
        bump_strength=0.030,
        bump_distance=0.012,
    )
    center_dark = make_material(
        "recessed old black center disk",
        (0.006, 0.006, 0.005, 1.0),
        roughness=0.86,
        noise_scale=115.0,
        bump_strength=0.035,
        bump_distance=0.012,
    )
    amber_scratch = make_material(
        "faint amber hairline scratches",
        (0.260, 0.100, 0.045, 1.0),
        roughness=0.90,
    )

    create_lathe(
        "shallow_dull_nickel_retaining_skirt",
        [
            (0.000, 0.930),
            (0.018, 1.145),
            (0.070, 1.155),
            (0.116, 1.070),
            (0.145, 0.930),
        ],
        nickel,
        layer="shell",
        bevel=0.008,
    )
    create_lathe(
        "low_graphite_sidewall_body",
        [
            (0.106, 0.970),
            (0.160, 1.000),
            (0.405, 0.965),
            (0.458, 0.885),
        ],
        graphite,
        layer="shell",
        bevel=0.010,
    )
    create_annular_cylinder(
        "fixed_outer_top_rim",
        inner_radius=0.700,
        outer_radius=0.910,
        z_min=0.423,
        z_max=0.490,
        material=graphite,
        layer="shell",
        bevel=0.010,
    )
    create_annular_cylinder(
        "rubbed_nickel_inner_retainer_ring",
        inner_radius=0.678,
        outer_radius=0.718,
        z_min=0.488,
        z_max=0.506,
        material=nickel,
        layer="shell",
        bevel=0.006,
    )
    add_knurl_ridges(ridge_graphite)

    add_cylinder(
        "rotating_smoked_oxblood_top_disk",
        radius=0.668,
        depth=0.062,
        z=0.524,
        material=oxblood,
        layer="rotor",
        bevel=0.018,
    )
    create_annular_cylinder(
        "thin_dark_inner_gasket",
        inner_radius=0.305,
        outer_radius=0.355,
        z_min=0.547,
        z_max=0.558,
        material=center_dark,
        layer="rotor",
        bevel=0.005,
    )
    add_cylinder(
        "recessed_dark_center_disk",
        radius=0.300,
        depth=0.018,
        z=0.549,
        material=center_dark,
        layer="rotor",
        bevel=0.010,
    )
    add_triangle_marker(worn_nickel)
    add_scratches(worn_nickel, amber_scratch)


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_render() -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.film_transparent = True
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1024
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.use_persistent_data = False

    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = 96
        if hasattr(scene.eevee, "use_gtao"):
            scene.eevee.use_gtao = True
            scene.eevee.gtao_distance = 1.2
            scene.eevee.gtao_factor = 0.75

    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        background.inputs["Strength"].default_value = 0.23

    lights = [
        ("large_softbox_left", (-2.8, -3.2, 5.0), 430.0, 4.0),
        ("small_scrape_rim", (2.7, -1.3, 2.3), 95.0, 1.2),
        ("low_front_glint", (-1.1, -3.0, 0.90), 70.0, 1.1),
    ]
    for name, location, energy, size in lights:
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.size = size
        obj = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(obj)
        obj.location = location
        look_at(obj, (0.0, 0.0, 0.28))

    camera_data = bpy.data.cameras.new("KnobOrthoCamera")
    camera = bpy.data.objects.new("KnobOrthoCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (0.0, 0.0, 5.55)
    look_at(camera, (0.0, 0.0, 0.285))
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 2.72
    camera_data.clip_start = 0.01
    camera_data.clip_end = 20.0
    scene.camera = camera


def set_layer_visibility(shell_visible: bool, rotor_visible: bool) -> None:
    for obj in bpy.context.scene.objects:
        layer = obj.get("knob_layer")
        if layer == "shell":
            obj.hide_render = not shell_visible
            obj.hide_viewport = not shell_visible
        elif layer == "rotor":
            obj.hide_render = not rotor_visible
            obj.hide_viewport = not rotor_visible


def render_layer(filename: str, *, shell: bool, rotor: bool) -> None:
    set_layer_visibility(shell, rotor)
    bpy.context.scene.render.filepath = str(OUTPUT_DIR / filename)
    bpy.ops.render.render(write_still=True)


def main() -> None:
    random.seed(RANDOM_SEED)
    clean_scene()
    build_knob()
    setup_render()

    render_layer("knob_shell.png", shell=True, rotor=False)
    render_layer("knob_rotor.png", shell=False, rotor=True)
    render_layer("knob_full.png", shell=True, rotor=True)

    print(f"Rendered knob layers to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
