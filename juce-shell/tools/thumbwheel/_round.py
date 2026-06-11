import bpy, math
sc=bpy.context.scene
o=bpy.data.objects['geometry_0']
o.scale[2]=1.75                       # round out the flattened cross-section
bpy.context.view_layer.update()
dx,dy,dz=o.dimensions
cam=bpy.data.objects['UICam']; cam.data.ortho_scale=max(dx,dz)*1.08
sc.render.resolution_x=700; sc.render.resolution_y=int(700*dz/dx)
nt=bpy.data.materials['Material_0'].node_tree
nt.nodes.get('GLOWPOS').outputs[0].default_value=0.55
sc.render.filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/view_round.png'
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/thumbwheel_work.blend')
print('round done', round(dx,3), round(dz,3), sc.render.resolution_y)
