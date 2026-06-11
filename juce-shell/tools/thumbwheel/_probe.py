import bpy, json
o = bpy.data.objects['geometry_0']
bb = [list(o.matrix_world @ __import__('mathutils').Vector(c)) for c in o.bound_box]
xs=[p[0] for p in bb]; ys=[p[1] for p in bb]; zs=[p[2] for p in bb]
info = {
 'dims': list(o.dimensions),
 'loc': list(o.location),
 'rot_euler': list(o.rotation_euler),
 'bbox_min': [min(xs),min(ys),min(zs)],
 'bbox_max': [max(xs),max(ys),max(zs)],
 'verts': len(o.data.vertices),
 'mats': [m.name for m in o.data.materials],
 'cam': list(bpy.data.objects['Camera'].location),
 'cam_rot': list(bpy.data.objects['Camera'].rotation_euler),
 'cam_type': bpy.data.objects['Camera'].data.type,
 'light': {'type':bpy.data.objects['Light'].data.type,'loc':list(bpy.data.objects['Light'].location),'energy':bpy.data.objects['Light'].data.energy},
 'engine': bpy.context.scene.render.engine,
 'res': [bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y],
}
print(json.dumps(info))
