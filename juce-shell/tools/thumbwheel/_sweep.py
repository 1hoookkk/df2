import bpy, os
sc=bpy.context.scene
sc.render.engine='BLENDER_EEVEE'; sc.render.film_transparent=True
sc.render.resolution_x=520; sc.render.resolution_y=192
nt=bpy.data.materials['Material_0'].node_tree
amp=nt.nodes.get('AMP'); pos=nt.nodes.get('GLOWPOS')
out='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/frames/'
os.makedirs(out,exist_ok=True)
F=129
for i in range(F):
    n=i/(F-1)
    amp.inputs[1].default_value=0.0 if (i==0 or i==F-1) else 9.0
    pos.outputs[0].default_value=n
    sc.render.filepath=out+f'f{i:03d}.png'
    bpy.ops.render.render(write_still=True)
print('swept', F, 'at', sc.render.resolution_x, sc.render.resolution_y)
