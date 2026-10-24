import bpy, bmesh, math, sys
from mathutils import Vector
out = sys.argv[sys.argv.index("--") + 1]
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1, location=(0, 0, 1.55))
head = bpy.context.active_object; head.scale = (0.78, 0.86, 1.0)
bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.38, depth=0.8, location=(0, 0, 0.55))
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=1, location=(0, 0, -0.25))
sh = bpy.context.active_object; sh.scale = (1.55, 0.8, 0.75)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -0.95)); cut = bpy.context.active_object; cut.scale = (6, 6, 1)
for o in [head, bpy.data.objects["Cylinder"], sh]: o.select_set(True)
bpy.ops.object.select_all(action="DESELECT")
for o in [head, bpy.data.objects["Cylinder"], sh]: o.select_set(True)
bpy.context.view_layer.objects.active = head
bpy.ops.object.join()
m = head.modifiers.new("r", "REMESH"); m.mode = "VOXEL"; m.voxel_size = 0.05
bpy.ops.object.modifier_apply(modifier="r")
b = head.modifiers.new("b", "BOOLEAN"); b.operation = "DIFFERENCE"; b.object = cut
bpy.ops.object.modifier_apply(modifier="b"); bpy.data.objects.remove(cut, do_unlink=True)
d = head.modifiers.new("d", "DECIMATE"); d.ratio = 0.012
bpy.ops.object.modifier_apply(modifier="d")
bpy.ops.object.shade_flat()
print("faces", len(head.data.polygons))
mat = bpy.data.materials.new("m"); mat.use_nodes = True
bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
bsdf.inputs["Base Color"].default_value = (0.96, 0.92, 0.86, 1); bsdf.inputs["Roughness"].default_value = 0.55
head.data.materials.append(mat)
sc = bpy.context.scene
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); sc.collection.objects.link(sun)
sun.data.energy = 4.0; sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(35))
fill = bpy.data.objects.new("fill", bpy.data.lights.new("fill", "SUN")); sc.collection.objects.link(fill)
fill.data.energy = 1.2; fill.rotation_euler = (math.radians(70), 0, math.radians(-120))
world = bpy.data.worlds.new("w"); sc.world = world; world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND"); bg.inputs["Strength"].default_value = 0.35
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = "ORTHO"; cam.data.ortho_scale = 4.3
cam.location = Vector((3.2, -6.0, 1.6)); target = Vector((0, 0, 0.75))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
sc.render.engine = "BLENDER_EEVEE"; sc.render.film_transparent = True
sc.render.resolution_x = sc.render.resolution_y = 1024
sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_mode = "RGBA"
sc.view_settings.view_transform = "Standard"
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
