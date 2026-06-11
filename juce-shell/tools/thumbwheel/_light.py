import bpy, math
scene = bpy.context.scene
mat = bpy.data.materials['Material_0']; nt=mat.node_tree
bsdf = next(n for n in nt.nodes if n.type=='BSDF_PRINCIPLED')
# detach whatever drives Base Color, force bone-white
for l in list(nt.links):
    if l.to_node==bsdf and l.to_socket.name=='Base Color':
        nt.links.remove(l)
bsdf.inputs['Base Color'].default_value=(0.86,0.86,0.83,1.0)
if 'Subsurface Weight' in bsdf.inputs: bsdf.inputs['Subsurface Weight'].default_value=0.18

# raking key from above+front via SUN; small fill; kill others
for n in ['KeyTopFront','Fill','Light']:
    if n in bpy.data.objects: bpy.data.objects[n].data.energy=0.0
def sun(name, rot, energy):
    s=bpy.data.objects.get(name)
    if s is None:
        d=bpy.data.lights.new(name,'SUN'); s=bpy.data.objects.new(name,d); scene.collection.objects.link(s)
    s.data.energy=energy; s.rotation_euler=rot; return s
# sun pointing down+toward camera(-Y): tilt 42deg from vertical toward -Y
sun('KeySun', (math.radians(-48),0,0), 3.2)
a=bpy.data.objects.get('Fill2')
if a is None:
    d=bpy.data.lights.new('Fill2','AREA'); a=bpy.data.objects.new('Fill2',d); scene.collection.objects.link(a)
a.data.energy=12; a.data.size=4; a.location=(0,-3,0.5); a.rotation_euler=(math.radians(90),0,0)
bg=scene.world.node_tree.nodes.get('Background')
if bg: bg.inputs['Strength'].default_value=0.12
scene.render.filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/view_bone.png'
bpy.ops.render.render(write_still=True)
print('bone render done')
