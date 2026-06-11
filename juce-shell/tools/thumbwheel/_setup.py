import bpy, math
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.film_transparent = True
try: scene.eevee.use_raytracing = True
except: pass

o = bpy.data.objects['geometry_0']
dx,dy,dz = o.dimensions

# ---- bone-white translucent material ----
mat = bpy.data.materials['Material_0']
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get('Principled BSDF') or next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
def setin(name,val):
    if name in bsdf.inputs: bsdf.inputs[name].default_value = val
setin('Base Color', (0.80,0.80,0.78,1.0))   # neutral bone, not warm
setin('Roughness', 0.45)
setin('Metallic', 0.0)
setin('Specular IOR Level', 0.4)
setin('Subsurface Weight', 0.25)             # let internal light scatter through
if 'Subsurface Radius' in bsdf.inputs: bsdf.inputs['Subsurface Radius'].default_value=(0.06,0.05,0.08)

# ---- lighting: key from above+front, soft fill, moderate ----
def area(name, loc, energy, size, rot):
    l = bpy.data.objects.get(name)
    if l is None:
        d = bpy.data.lights.new(name,'AREA'); l = bpy.data.objects.new(name,d); scene.collection.objects.link(l)
    l.data.energy=energy; l.data.size=size; l.location=loc; l.rotation_euler=rot
    return l
# kill the harsh default point
if 'Light' in bpy.data.objects: bpy.data.objects['Light'].data.energy = 0.0
area('KeyTopFront', (0,-1.4,2.2), 60, 2.5, (math.radians(32),0,0))   # above + front
area('Fill', (-1.5,-2.0,0.6), 18, 3.0, (math.radians(80),0,math.radians(-30)))
scene.world.use_nodes=True
bg = scene.world.node_tree.nodes.get('Background')
if bg: bg.inputs['Strength'].default_value = 0.25; bg.inputs['Color'].default_value=(0.05,0.05,0.06,1)

# ---- head-on ortho camera ----
cam = bpy.data.objects['UICam']
cam.data.type='ORTHO'; scene.camera=cam
cam.location=(0,-3,0); cam.rotation_euler=(math.radians(90),0,0)
cam.data.ortho_scale = max(dx,dz)*1.08
scene.render.resolution_x = 700; scene.render.resolution_y = int(700*dz/dx)
scene.render.filepath = 'C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/view_lit.png'
bpy.ops.render.render(write_still=True)
print('lit render done', scene.render.resolution_x, scene.render.resolution_y)
