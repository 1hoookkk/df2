import bpy, math
scene=bpy.context.scene
scene.render.engine='BLENDER_EEVEE'; scene.render.film_transparent=True
o=bpy.data.objects['geometry_0']; dx,dy,dz=o.dimensions

mat=bpy.data.materials['Material_0']; nt=mat.node_tree
bsdf=next(n for n in nt.nodes if n.type=='BSDF_PRINCIPLED')
bsdf.inputs['Base Color'].default_value=(0.88,0.88,0.85,1.0)
bsdf.inputs['Roughness'].default_value=0.33   # glossier -> crisp top line
# glow OFF for the lighting check
amp=nt.nodes.get('AMP')
if amp: amp.inputs[1].default_value=0.0

# wipe prior lights
for n in list(bpy.data.objects):
    if n.type=='LIGHT': n.data.energy=0.0
def area(name,loc,rot,energy,sx,sy=None):
    obj=bpy.data.objects.get(name)
    if obj is None:
        d=bpy.data.lights.new(name,'AREA'); obj=bpy.data.objects.new(name,d); scene.collection.objects.link(obj)
    obj.data.energy=energy; obj.data.shape='RECTANGLE' if sy else 'SQUARE'
    obj.data.size=sx
    if sy: obj.data.size_y=sy
    obj.location=loc; obj.rotation_euler=rot; obj.data.color=(1,1,1); return obj

# studio rig (camera looks +Y at the -Y face; up=+Z)
area('S_Key',  (0,-2.4, 1.6), (math.radians(34),0,0), 160, 3.0)        # key above-front
area('S_FillL',(-2.2,-2.0,0.3),(math.radians(86),0,math.radians(-40)),70, 3.0)
area('S_FillR',( 2.2,-2.0,0.3),(math.radians(86),0,math.radians( 40)),70, 3.0)
area('S_Back', (0, 2.4, 1.4), (math.radians(-150),0,0), 90, 3.0)       # back/kick
# strong thin OVERHEAD line -> bright specular streak along the top crest
area('S_TopLine',(0,0,2.2),(0,0,0),900,1.4,0.06)

scene.world.use_nodes=True
bg=scene.world.node_tree.nodes.get('Background')
if bg: bg.inputs['Strength'].default_value=0.35   # bright, even

cam=bpy.data.objects['UICam']; cam.data.type='ORTHO'; scene.camera=cam
cam.location=(0,-3,0); cam.rotation_euler=(math.radians(90),0,0); cam.data.ortho_scale=max(dx,dz)*1.08
scene.render.resolution_x=700; scene.render.resolution_y=int(700*dz/dx)
scene.render.filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/view_studio.png'
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/thumbwheel_work.blend')
print('studio render done')
