import bpy, json
mat = bpy.data.materials['Material_0']
nt = mat.node_tree
nodes = [{'name':n.name,'type':n.type} for n in nt.nodes]
links = [{'from':f"{l.from_node.name}.{l.from_socket.name}", 'to':f"{l.to_node.name}.{l.to_socket.name}"} for l in nt.links]
# any color attributes / textures
attrs = [n.layer_name for n in nt.nodes if n.type=='VERTEX_COLOR'] if False else []
vc = [n.name for n in nt.nodes if 'ATTRIBUTE' in n.type or 'VERTEX' in n.type or n.type=='TEX_IMAGE']
print(json.dumps({'nodes':nodes,'links':links,'colorish':vc,
  'mesh_attrs':[a.name+':'+a.data_type for a in bpy.data.objects['geometry_0'].data.color_attributes]}))
