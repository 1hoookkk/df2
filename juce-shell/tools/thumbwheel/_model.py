import bpy, bmesh, math, mathutils
sc=bpy.context.scene
# hide the junk scan (keep it, don't lose your model)
if 'geometry_0' in bpy.data.objects:
    g=bpy.data.objects['geometry_0']; g.hide_render=True; g.hide_viewport=True
if 'tw_clean' in bpy.data.objects:
    bpy.data.objects.remove(bpy.data.objects['tw_clean'], do_unlink=True)

# ---- build a segmented cylinder: N key discs along X ----
N=16; r=0.10; key_w=0.050; pitch=0.064
L=N*pitch
bm=bmesh.new()
rot=mathutils.Matrix.Rotation(math.radians(90),4,'Y')
for i in range(N):
    x=-L/2+pitch*(i+0.5)
    tmp=bmesh.new()
    bmesh.ops.create_cone(tmp,cap_ends=True,segments=64,radius1=r,radius2=r,depth=key_w)
    bmesh.ops.transform(tmp,matrix=rot,verts=tmp.verts)
    bmesh.ops.translate(tmp,vec=(x,0,0),verts=tmp.verts)
    me=bpy.data.meshes.new('t'); tmp.to_mesh(me); tmp.free()
    bm.from_mesh(me); bpy.data.meshes.remove(me)
bmesh.ops.bevel(bm,geom=list(bm.edges),offset=0.005,segments=2,affect='EDGES')
mesh=bpy.data.meshes.new('tw_clean'); bm.to_mesh(mesh); bm.free()
for p in mesh.polygons: p.use_smooth=True
ob=bpy.data.objects.new('tw_clean',mesh); sc.collection.objects.link(ob)

# ---- bone material ----
mat=bpy.data.materials.get('BoneClean') or bpy.data.materials.new('BoneClean')
mat.use_nodes=True; b=mat.node_tree.nodes['Principled BSDF']
b.inputs['Base Color'].default_value=(0.88,0.88,0.85,1)
b.inputs['Roughness'].default_value=0.30; b.inputs['Metallic'].default_value=0.0
ob.data.materials.clear(); ob.data.materials.append(mat)

# ---- internal UV emitter (leaks through the gaps between keys) ----
if 'UVCore' in bpy.data.objects: bpy.data.objects.remove(bpy.data.objects['UVCore'],do_unlink=True)
cm=bmesh.new(); bmesh.ops.create_icosphere(cm,subdivisions=2,radius=r*0.78)
csh=bpy.data.meshes.new('UVCoreM'); cm.to_mesh(csh); cm.free()
core=bpy.data.objects.new('UVCore',csh); sc.collection.objects.link(core)
core.location=(0,0,0)   # centre = pos 0.5 for this test
uv=bpy.data.materials.get('UVEmit') or bpy.data.materials.new('UVEmit')
uv.use_nodes=True
nt=uv.node_tree; nt.nodes.clear()
em=nt.nodes.new('ShaderNodeEmission'); out=nt.nodes.new('ShaderNodeOutputMaterial')
em.inputs['Color'].default_value=(0.62,0.40,1.0,1); em.inputs['Strength'].default_value=80
nt.links.new(em.outputs[0],out.inputs['Surface'])
csh.materials.append(uv)

# ---- camera head-on ----
cam=bpy.data.objects['UICam']; cam.data.type='ORTHO'; sc.camera=cam
cam.location=(0,-3,0); cam.rotation_euler=(math.radians(90),0,0)
cam.data.ortho_scale=L*1.05
sc.render.resolution_x=900; sc.render.resolution_y=int(900*(2*r+0.02)/L)
sc.render.engine='BLENDER_EEVEE'; sc.render.film_transparent=True
sc.render.filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/view_clean.png'
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath='C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/thumbwheel_work.blend')
print('clean model render done', N, round(L,3), sc.render.resolution_x, sc.render.resolution_y)
