import bpy
nt=bpy.data.materials['Material_0'].node_tree; N=nt.nodes; L=nt.links
bsdf=next(n for n in N if n.type=='BSDF_PRINCIPLED')
sep=N.get('SEP'); soft=N.get('SOFT'); amp=N.get('AMP')
# vertical mask: bright low, dark at top caps (Generated Z 0..1 bottom->top)
vm=N.get('VMASK') or N.new('ShaderNodeMath'); vm.name='VMASK'; vm.label='VMASK'; vm.location=(40,120)
vm.operation='SUBTRACT'; vm.inputs[0].default_value=1.15
# clear old input1 link then wire Z
for l in list(L):
    if l.to_node==vm: L.remove(l)
L.new(sep.outputs['Z'], vm.inputs[1])
vmc=N.get('VMC') or N.new('ShaderNodeClamp'); vmc.name='VMC'; vmc.location=(220,120)
L.new(vm.outputs[0], vmc.inputs['Value'])
# combine: soft * vmask -> strength
mul=N.get('GMUL') or N.new('ShaderNodeMath'); mul.name='GMUL'; mul.label='GMUL'; mul.location=(400,200)
mul.operation='MULTIPLY'
L.new(soft.outputs[0], mul.inputs[0]); L.new(vmc.outputs[0], mul.inputs[1])
amp.operation='MULTIPLY'; amp.inputs[1].default_value=13.0
for l in list(L):
    if l.to_node==amp: L.remove(l)
L.new(mul.outputs[0], amp.inputs[0])
L.new(amp.outputs[0], bsdf.inputs['Emission Strength'])
bsdf.inputs['Emission Color'].default_value=(0.60,0.34,1.0,1.0)  # violet
N.get('GLOWPOS').outputs[0].default_value=0.55
sc=bpy.context.scene
sc.render.filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/glow_test2.png'
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/thumbwheel_work.blend')
print('glow2 done')
