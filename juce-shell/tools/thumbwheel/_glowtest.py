import bpy
nt=bpy.data.materials['Material_0'].node_tree
amp=nt.nodes.get('AMP'); pos=nt.nodes.get('GLOWPOS')
amp.inputs[1].default_value=28.0      # glow ON
pos.outputs[0].default_value=0.55
sc=bpy.context.scene
sc.render.filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/glow_test.png'
bpy.ops.render.render(write_still=True)
print('glow test rendered')
