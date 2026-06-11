import bpy, math
scene=bpy.context.scene
s=bpy.data.objects['KeySun']
s.rotation_euler=(math.radians(48),0,0)   # above + front (lights -Y face + top)
s.data.energy=4.5
bg=scene.world.node_tree.nodes.get('Background')
if bg: bg.inputs['Strength'].default_value=0.20
bpy.data.objects['Fill2'].data.energy=20
scene.render.filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/view_bone2.png'
bpy.ops.render.render(write_still=True)
print('ok')
