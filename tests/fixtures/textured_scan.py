"""A scan the way Object Capture gives one at High, for tests/exports_test.py: a Suzanne with UVs, a color texture
without black, a roughness map (glTF green channel), a bumpy normal map and holes the solid closes.

blender -b --factory-startup -P tests/fixtures/textured_scan.py -- OUT.glb
"""
import sys

import bpy
import numpy as np

out = sys.argv[sys.argv.index("--") + 1]
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.mesh.primitive_monkey_add(size=2, calc_uvs=True)
monkey = bpy.context.active_object
mod = monkey.modifiers.new("s", "SUBSURF")
mod.levels = 2
bpy.ops.object.modifier_apply(modifier=mod.name)
bpy.ops.object.shade_smooth()
# holes under the chin: nothing to see there for the bakes, the watertight solid closes them
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="DESELECT")
bpy.ops.object.mode_set(mode="OBJECT")
for p in monkey.data.polygons:
    p.select = p.center.z < -0.55 and abs(p.center.x) < 0.25
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.delete(type="FACE")
bpy.ops.object.mode_set(mode="OBJECT")


def image(name, rgb, data):
    h, w, _ = rgb.shape
    img = bpy.data.images.new(name, w, h, is_data=data)
    img.pixels.foreach_set(np.concatenate([rgb, np.ones((h, w, 1))], 2).astype(np.float32).ravel())
    img.pack()
    return img


n = 512
y, x = np.mgrid[0:n, 0:n] / n
color = np.stack([0.3 + 0.6 * x, 0.25 + 0.5 * (np.sin(x * 40) > 0), 0.3 + 0.6 * y], 2)
rough = np.stack([np.ones_like(x), 0.2 + 0.6 * x, np.zeros_like(x)], 2)  # glTF: roughness in green, metal in blue
bump = np.stack([-0.35 * np.cos(x * 90), -0.35 * np.cos(y * 90), np.ones_like(x)], 2)
normal = bump / np.linalg.norm(bump, axis=2, keepdims=True) * 0.5 + 0.5

mat = bpy.data.materials.new("scan")
if mat.node_tree is None:
    mat.use_nodes = True
nodes, links = mat.node_tree.nodes, mat.node_tree.links
bsdf = next(nd for nd in nodes if nd.type == "BSDF_PRINCIPLED")
tex = {}
for key, pixels, data in (("color", color, False), ("rough", rough, True), ("normal", normal, True)):
    tex[key] = nodes.new("ShaderNodeTexImage")
    tex[key].image = image(key, pixels, data)
links.new(tex["color"].outputs["Color"], bsdf.inputs["Base Color"])
sep = nodes.new("ShaderNodeSeparateColor")
links.new(tex["rough"].outputs["Color"], sep.inputs["Color"])
links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
nmap = nodes.new("ShaderNodeNormalMap")
links.new(tex["normal"].outputs["Color"], nmap.inputs["Color"])
links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
monkey.data.materials.append(mat)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_yup=True, export_tangents=False)
print("SCAN", out, len(monkey.data.polygons))
