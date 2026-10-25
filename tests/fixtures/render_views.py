import bpy, math, sys, os
from mathutils import Vector
args = sys.argv[sys.argv.index("--") + 1:]
out = args[0]
os.makedirs(out, exist_ok=True)
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.mesh.primitive_monkey_add(size=2)
m = bpy.context.active_object
mod = m.modifiers.new("s", "SUBSURF"); mod.levels = 2; mod.render_levels = 2
bpy.ops.object.shade_smooth()
mat = bpy.data.materials.new("tex"); mat.use_nodes = True
nt = mat.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
noise = nt.nodes.new("ShaderNodeTexNoise"); noise.inputs["Scale"].default_value = 18; noise.inputs["Detail"].default_value = 10
vor = nt.nodes.new("ShaderNodeTexVoronoi"); vor.inputs["Scale"].default_value = 40
mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
mix.inputs["Factor"].default_value = 0.5
nt.links.new(noise.outputs["Color"], mix.inputs[6])
nt.links.new(vor.outputs["Color"], mix.inputs[7])
if "--couleurs" in args:
    # saturated cells, so a grey or black texture shows in the colored preview test
    hsv = nt.nodes.new("ShaderNodeHueSaturation"); hsv.inputs["Saturation"].default_value = 2.5
    nt.links.new(vor.outputs["Color"], hsv.inputs["Color"])
    nt.links.new(hsv.outputs["Color"], mix.inputs[7])
    mix.inputs["Factor"].default_value = 0.85
nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.7
m.data.materials.append(mat)
world = bpy.data.worlds.new("w"); bpy.context.scene.world = world; world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (0.85, 0.85, 0.85, 1); bg.inputs["Strength"].default_value = 1.0
sc = bpy.context.scene
engines = [i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
print("engines", engines)
eng = "CYCLES" if "--cycles" in args else next((e for e in engines if "EEVEE" in e), "CYCLES")
sc.render.engine = eng
if eng == "CYCLES": sc.cycles.samples = 32
sc.render.resolution_x, sc.render.resolution_y = 1600, 1200
sc.render.image_settings.file_format = "JPEG"; sc.render.image_settings.quality = 92
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.lens = 35
target = Vector((0, 0, 0)); r = 6.0; i = 0
for elev in (-10, 15, 40):
    for k in range(16):
        az = math.radians(k * 22.5 + (elev % 7))
        e = math.radians(elev)
        cam.location = Vector((r * math.cos(e) * math.cos(az), r * math.cos(e) * math.sin(az), r * math.sin(e)))
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(out, f"IMG_{i:03d}.jpg")
        bpy.ops.render.render(write_still=True); i += 1
print("rendered", i, "with", eng)
