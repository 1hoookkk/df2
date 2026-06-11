import bpy, math
sc=bpy.context.scene
# drop my from-scratch parts
for nm in ['tw_clean','UVCore']:
    if nm in bpy.data.objects: bpy.data.objects.remove(bpy.data.objects[nm],do_unlink=True)
# restore the real model, un-rounded
g=bpy.data.objects['geometry_0']; g.hide_render=False; g.hide_viewport=False
g.scale=(1,1,1); bpy.context.view_layer.update()
dx,dy,dz=g.dimensions
# glow: violet, not blown white
nt=bpy.data.materials['Material_0'].node_tree
amp=nt.nodes.get('AMP');  amp.inputs[1].default_value=6.0
nt.nodes.get('GLOWPOS').outputs[0].default_value=0.55
# head-on ortho at NATURAL aspect
cam=bpy.data.objects['UICam']; cam.data.type='ORTHO'; sc.camera=cam
cam.location=(0,-3,0); cam.rotation_euler=(math.radians(90),0,0)
cam.data.ortho_scale=max(dx,dz)*1.04
sc.render.resolution_x=900; sc.render.resolution_y=int(900*dz/dx)
sc.render.engine='BLENDER_EEVEE'; sc.render.film_transparent=True
sc.render.filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/view_model.png'
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/thumbwheel_work.blend')
print('reverted+render', round(dx,3), round(dz,3), 'aspect', round(dx/dz,2), sc.render.resolution_y)
