import bpy, math
scene=bpy.context.scene
scene.render.engine='BLENDER_EEVEE'
scene.render.film_transparent=True
o=bpy.data.objects['geometry_0']; dx,dy,dz=o.dimensions

# --- material: bone-white, keep PBR maps, detach base-color texture ---
mat=bpy.data.materials['Material_0']; mat.use_nodes=True; nt=mat.node_tree
bsdf=next(n for n in nt.nodes if n.type=='BSDF_PRINCIPLED')
for l in list(nt.links):
    if l.to_node==bsdf and l.to_socket.name=='Base Color': nt.links.remove(l)
bsdf.inputs['Base Color'].default_value=(0.86,0.86,0.83,1.0)
bsdf.inputs['Metallic'].default_value=0.0
if 'Subsurface Weight' in bsdf.inputs: bsdf.inputs['Subsurface Weight'].default_value=0.18

# --- lights: raking key from ABOVE+FRONT (+X tilt), soft front fill ---
if 'Light' in bpy.data.objects: bpy.data.objects['Light'].data.energy=0.0
def mk(name,kind):
    obj=bpy.data.objects.get(name)
    if obj is None:
        d=(bpy.data.lights.new(name,kind)); obj=bpy.data.objects.new(name,d); scene.collection.objects.link(obj)
    return obj
ks=mk('KeySun','SUN'); ks.data.energy=4.5; ks.rotation_euler=(math.radians(48),0,0)
fl=mk('Fill2','AREA'); fl.data.energy=20; fl.data.size=4; fl.location=(0,-3,0.6); fl.rotation_euler=(math.radians(90),0,0)
scene.world.use_nodes=True
bg=scene.world.node_tree.nodes.get('Background')
if bg: bg.inputs['Strength'].default_value=0.20

# --- head-on ortho camera ---
cam=mk('UICam','SUN') if False else bpy.data.objects.get('UICam')
if cam is None:
    cd=bpy.data.cameras.new('UICam'); cam=bpy.data.objects.new('UICam',cd); scene.collection.objects.link(cam)
cam.data.type='ORTHO'; scene.camera=cam
cam.location=(0,-3,0); cam.rotation_euler=(math.radians(90),0,0)
cam.data.ortho_scale=max(dx,dz)*1.08
scene.render.resolution_x=700; scene.render.resolution_y=int(700*dz/dx)

scene.render.filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/view_bone.png'
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/thumbwheel_work.blend')
print('setup+render+save done', scene.render.resolution_x, scene.render.resolution_y)
