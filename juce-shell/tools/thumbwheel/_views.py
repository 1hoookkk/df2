import bpy, math, mathutils
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.render.film_transparent = True
o = bpy.data.objects['geometry_0']
# ensure an ortho cam
cam = bpy.data.objects.get('UICam')
if cam is None:
    cd = bpy.data.cameras.new('UICam'); cam = bpy.data.objects.new('UICam', cd); scene.collection.objects.link(cam)
cam.data.type = 'ORTHO'
scene.camera = cam
dx,dy,dz = o.dimensions

def render(name, loc, rot, scale, rx, ry):
    cam.location = loc; cam.rotation_euler = rot; cam.data.ortho_scale = scale
    scene.render.resolution_x = rx; scene.render.resolution_y = ry
    scene.render.filepath = bpy.path.abspath(f'//_tw_{name}.png') if False else f'C:/Users/hooki/df2/juce-shell/tools/thumbwheel/_preview/blender/view_{name}.png'
    bpy.ops.render.render(write_still=True)

# TOP: look down -Z, long axis Y -> horizontal
render('top', (0,0,3), (0,0,0), max(dx,dy)*1.1, 640, int(640*dx/dy))
# FRONT: look along +Y (-Y dir), see X(horiz) x Z(vert)
render('front', (0,-3,0), (math.radians(90),0,0), max(dx,dz)*1.1, 640, int(640*dz/dx))
print('done', dx,dy,dz)
