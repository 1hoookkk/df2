import bpy
scene=bpy.context.scene
mat=bpy.data.materials['Material_0']; nt=mat.node_tree; N=nt.nodes; L=nt.links
bsdf=next(n for n in N if n.type=='BSDF_PRINCIPLED')

def get(name,typ,loc):
    n=N.get(name)
    if n is None: n=N.new(typ); n.name=name; n.label=name
    n.location=loc; return n

tc=get('TC','ShaderNodeTexCoord',(-1200,400))
sep=get('SEP','ShaderNodeSeparateXYZ',(-1000,400)); L.new(tc.outputs['Generated'],sep.inputs['Vector'])
pos=get('GLOWPOS','ShaderNodeValue',(-1200,200)); pos.outputs[0].default_value=0.55
sub=get('SUB','ShaderNodeMath',(-820,300)); sub.operation='SUBTRACT'
L.new(sep.outputs['X'],sub.inputs[0]); L.new(pos.outputs[0],sub.inputs[1])
# d / sigma
dsig=get('DSIG','ShaderNodeMath',(-640,300)); dsig.operation='DIVIDE'; dsig.inputs[1].default_value=0.07
L.new(sub.outputs[0],dsig.inputs[0])
sq=get('SQ','ShaderNodeMath',(-460,300)); sq.operation='POWER'; sq.inputs[1].default_value=2.0
L.new(dsig.outputs[0],sq.inputs[0])
inv=get('INV','ShaderNodeMath',(-280,300)); inv.operation='SUBTRACT'; inv.inputs[0].default_value=1.0
L.new(sq.outputs[0],inv.inputs[1])
clamp=get('CLMP','ShaderNodeClamp',(-120,300)); clamp.inputs['Min'].default_value=0; clamp.inputs['Max'].default_value=1
L.new(inv.outputs[0],clamp.inputs['Value'])
soft=get('SOFT','ShaderNodeMath',(40,300)); soft.operation='POWER'; soft.inputs[1].default_value=1.6
L.new(clamp.outputs[0],soft.inputs[0])
amp=get('AMP','ShaderNodeMath',(220,300)); amp.operation='MULTIPLY'; amp.inputs[1].default_value=28.0
L.new(soft.outputs[0],amp.inputs[0])
# wire emission
bsdf.inputs['Emission Color'].default_value=(0.72,0.46,1.0,1.0)
L.new(amp.outputs[0],bsdf.inputs['Emission Strength'])

# compositor bloom
scene.use_nodes=True; cn=scene.node_tree; cN=cn.nodes; cL=cn.links
rl=next((n for n in cN if n.type=='R_LAYERS'),None) or cN.new('CompositorNodeRLayers')
comp=next((n for n in cN if n.type=='COMPOSITE'),None) or cN.new('CompositorNodeComposite')
glare=next((n for n in cN if n.type=='GLARE'),None) or cN.new('CompositorNodeGlare')
glare.glare_type='BLOOM'; glare.mix=0.0; glare.threshold=0.6; glare.size=7
for l in list(cL):
    if l.to_node==comp: cL.remove(l)
cL.new(rl.outputs['Image'],glare.inputs['Image']); cL.new(glare.outputs['Image'],comp.inputs['Image'])

scene.render.filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/glow_test.png'
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/thumbwheel_work.blend')
print('glow test done')
