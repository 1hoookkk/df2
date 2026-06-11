import bpy
scene = bpy.context.scene
scene.render.filepath = 'C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/view_lit2.png'
bpy.ops.render.render(write_still=True)
print('ok', scene.render.resolution_x, scene.render.resolution_y)
