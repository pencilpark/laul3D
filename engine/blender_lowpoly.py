"""Headless Blender step: any mesh -> watertight low-poly STL sized for the printer.

Blender -b --factory-startup --python-exit-code 1 -P blender_lowpoly.py -- --input IN --outdir DIR [options]
--factory-startup keeps user add-ons (MCP servers on port 9876) from loading in this background instance.
"""
import argparse
import json
import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector
from mathutils.bvhtree import BVHTree


# LowPoly -> detailed: (default triangles, voxels along the largest side, smoothing passes)
LEVELS = {
    "lowpoly": (1000, 300, 2),
    "medium": (20000, 400, 2),
    "detailed": (300000, 650, 1),
}
# extra smoothing on demand, as a blur of the volume: (filter width in voxels, iterations). Surface filters were
# tried first on a 69-photo bust: Blender's Laplacian solver took minutes, Taubin left 5 mm bumps untouched.
SMOOTH = {1: (2, 1), 2: (3, 1), 3: (4, 2)}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--name", default="modele")
    ap.add_argument("--height-mm", type=float, default=80.0)
    ap.add_argument("--level", choices=list(LEVELS), default="lowpoly")
    ap.add_argument("--faces", type=int, default=0, help="target triangle count, 0 = level default")
    ap.add_argument("--base-cut", type=float, default=0.03, help="fraction of height cut flat at the bottom, 0 = none")
    ap.add_argument("--rot", type=float, nargs=3, default=[0, 0, 0], metavar=("X", "Y", "Z"))
    ap.add_argument("--rot-seq", default="-", help="quarter turns about world axes, applied in order, e.g. 'zx'")
    ap.add_argument("--bed", type=float, nargs=3, default=[220, 220, 250], metavar=("X", "Y", "Z"))
    ap.add_argument("--margin", type=float, default=10.0)
    ap.add_argument("--nozzle", type=float, default=0.4)
    ap.add_argument("--keep-parts", action="store_true", help="keep detached parts above 2%% of faces")
    ap.add_argument("--force-closing", action="store_true", help="skip plain voxel remesh, always use morphological closing")
    ap.add_argument("--save-blend", action="store_true")
    ap.add_argument("--previews", action="store_true", help="render 4 PNG views of the result")
    ap.add_argument("--previews-only", action="store_true", help="only render the 4 views of --input (an STL)")
    ap.add_argument("--preview-engine", choices=["workbench", "cycles"], default="workbench",
                    help="cycles renders on the CPU and needs no OpenGL context")
    ap.add_argument("--smooth", type=int, choices=sorted(SMOOTH) + [0], default=0, help="extra smoothing: 0 none to 3 strong")
    ap.add_argument("--colors", action="store_true", help="also write NAME_couleurs.glb, the scan's colors on the result")
    ap.add_argument("--orient", type=float, nargs=9, help="row-major 3x3 rotation applied first (stands a COLMAP scan up)")
    ap.add_argument("--raw-axes", action="store_true", help="import OBJ coordinates as they are, without the Y-up conversion")
    return ap.parse_args(argv)


def log(msg):
    print(f"[blender] {msg}", flush=True)


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def import_any(path, raw_axes=False):
    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)
    if ext in (".usdz", ".usd", ".usdc", ".usda"):
        bpy.ops.wm.usd_import(filepath=path)
    elif ext == ".obj" and raw_axes:
        bpy.ops.wm.obj_import(filepath=path, forward_axis="Y", up_axis="Z")
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".ply":
        bpy.ops.wm.ply_import(filepath=path)
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=path)
    else:
        raise SystemExit(f"format non pris en charge : {ext}")
    meshes = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if not meshes:
        raise SystemExit("aucun maillage dans le fichier importé")
    return meshes


def merge_to_bmesh(objects):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    for o in objects:
        me = o.evaluated_get(depsgraph).to_mesh().copy()
        me.transform(o.matrix_world)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    return bm


def bm_to_object(bm, name):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def object_to_bm(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    return bm


def bounds(bm):
    if not bm.verts:
        raise SystemExit("maillage vide")
    cs = [v.co for v in bm.verts]
    lo = Vector((min(c.x for c in cs), min(c.y for c in cs), min(c.z for c in cs)))
    hi = Vector((max(c.x for c in cs), max(c.y for c in cs), max(c.z for c in cs)))
    return lo, hi


def bm_stats(obj):
    # obj.dimensions can be stale right after bm.to_mesh, so measure vertices
    bm = object_to_bm(obj)
    if not bm.verts:
        bm.free()
        return Vector((0, 0, 0)), 0.0
    lo, hi = bounds(bm)
    vol = abs(bm.calc_volume(signed=True))
    bm.free()
    return hi - lo, vol


def apply_modifier(obj, mod):
    with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
        bpy.ops.object.modifier_apply(modifier=mod.name)


def islands_of(bm):
    bm.faces.index_update()
    bm.faces.ensure_lookup_table()
    seen, islands = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, comp = [f], []
        seen.add(f.index)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for e in cur.edges:
                for nf in e.link_faces:
                    if nf.index not in seen:
                        seen.add(nf.index)
                        stack.append(nf)
        islands.append(comp)
    return islands


def box_volume(faces):
    cs = [v.co for f in faces for v in f.verts]
    d = [max(c[i] for c in cs) - min(c[i] for c in cs) for i in range(3)]
    return d[0] * d[1] * d[2]


def keep_shells(bm, keep_parts):
    islands = islands_of(bm)
    if not islands:
        raise SystemExit("plus aucune géométrie après nettoyage")
    islands.sort(key=box_volume, reverse=True)
    total = len(bm.faces)
    if keep_parts:
        kept = [c for c in islands if len(c) >= 0.02 * total] or islands[:1]
    else:
        kept = islands[:1]
    kept_ids = {f.index for c in kept for f in c}
    drop = [f for c in islands for f in c if f.index not in kept_ids]
    if drop:
        bmesh.ops.delete(bm, geom=drop, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    return len(islands), len(kept)


def fill_holes(obj):
    bm = object_to_bm(obj)
    boundary = [e for e in bm.edges if e.is_boundary]
    if boundary:
        bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
    bm.to_mesh(obj.data)
    bm.free()
    return len(boundary)


def voxel_remesh(obj, voxel):
    mod = obj.modifiers.new("watertight", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel
    mod.adaptivity = 0.0
    mod.use_smooth_shade = False
    apply_modifier(obj, mod)


def set_input(node, name, value):
    if name in node.inputs:
        node.inputs[name].default_value = value


def close_by_dilation(obj, radius, voxel):
    """Morphological closing for leaky scans: dilate surface samples into a volume, keep the outer shell, shrink back."""
    ng = bpy.data.node_groups.new("close", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links
    gi, go = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    dist = nodes.new("GeometryNodeDistributePointsOnFaces")
    set_input(dist, "Density", 1.0 / (radius * 0.4) ** 2)
    p2v = nodes.new("GeometryNodePointsToVolume")
    set_input(p2v, "Radius", radius)
    if hasattr(p2v, "resolution_mode"):
        p2v.resolution_mode = "VOXEL_SIZE"
    elif "Resolution Mode" in p2v.inputs:
        p2v.inputs["Resolution Mode"].default_value = "Size"
    set_input(p2v, "Voxel Size", voxel)
    set_input(p2v, "Density", 1.0)
    v2m = nodes.new("GeometryNodeVolumeToMesh")
    links.new(gi.outputs[0], dist.inputs["Mesh"])
    links.new(dist.outputs["Points"], p2v.inputs["Points"])
    links.new(p2v.outputs["Volume"], v2m.inputs["Volume"])
    links.new(v2m.outputs["Mesh"], go.inputs[0])
    mod = obj.modifiers.new("close", "NODES")
    mod.node_group = ng
    apply_modifier(obj, mod)

    bm = object_to_bm(obj)
    keep_shells(bm, keep_parts=False)  # the dilated volume's inner wall is a separate, smaller shell
    bm.to_mesh(obj.data)
    bm.free()

    disp = obj.modifiers.new("shrink", "DISPLACE")
    disp.direction = "NORMAL"
    disp.mid_level = 0.0
    disp.strength = -radius * 0.9
    apply_modifier(obj, disp)
    voxel_remesh(obj, voxel)


def make_watertight(obj, voxel, force_closing=False):
    size0, _ = bm_stats(obj)
    holes = fill_holes(obj)
    backup = obj.data.copy()
    if not force_closing:
        voxel_remesh(obj, voxel)
        size1, vol1 = bm_stats(obj)
        box0 = size0.x * size0.y * size0.z
        if all(size1[i] >= 0.8 * size0[i] for i in range(3)) and vol1 >= 0.03 * box0:
            return "voxel", holes
        log(f"voxel incohérent (taille {tuple(round(v, 1) for v in size1)}, volume {vol1:.0f} mm3), fermeture morphologique")
        obj.data = backup.copy()
    close_by_dilation(obj, radius=max(max(size0) * 0.012, voxel * 2.5), voxel=voxel)
    return "fermeture", holes


def decimate(obj, target_tris):
    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if tris <= target_tris:
        return
    mod = obj.modifiers.new("lowpoly", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = max(target_tris / tris, 0.0005)
    mod.use_collapse_triangulate = True
    apply_modifier(obj, mod)


def cut_flat_base(bm, frac):
    lo, hi = bounds(bm)
    z = lo.z + (hi.z - lo.z) * frac
    geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
    bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-6, plane_co=(0, 0, z), plane_no=(0, 0, 1), clear_inner=True)
    edges = [e for e in bm.edges if e.is_boundary]
    if edges:
        bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=edges)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)


def sdf_smooth(obj, voxel, width, iterations):
    """Blurs the model's volume (OpenVDB mean filter on its distance field): bumps narrower than about
    width x voxel melt, larger forms stay, and the result is closed by construction."""
    ng = bpy.data.node_groups.new("lissage", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links
    gi, go = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    to_sdf = nodes.new("GeometryNodeMeshToSDFGrid")
    set_input(to_sdf, "Voxel Size", voxel)
    set_input(to_sdf, "Band Width", width + 3)
    mean = nodes.new("GeometryNodeSDFGridMean")
    set_input(mean, "Width", width)
    set_input(mean, "Iterations", iterations)
    to_mesh = nodes.new("GeometryNodeGridToMesh")
    set_input(to_mesh, "Threshold", 0.0)
    set_input(to_mesh, "Adaptivity", 0.0)
    links.new(gi.outputs[0], to_sdf.inputs["Mesh"])
    links.new(to_sdf.outputs[0], mean.inputs["Grid"])
    links.new(mean.outputs[0], to_mesh.inputs["Grid"])
    links.new(to_mesh.outputs[0], go.inputs[0])
    mod = obj.modifiers.new("lissage", "NODES")
    mod.node_group = ng
    apply_modifier(obj, mod)


def base_color_linked(obj):
    for slot in obj.material_slots:
        m = slot.material
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.node_tree else None
        if bsdf and bsdf.inputs[0].is_linked:
            return True
    return False


def has_colors(objects):
    """The scan carries colors: a texture behind its base color, or a color attribute (TripoSR)."""
    return any(o.data.color_attributes or base_color_linked(o) for o in objects)


def color_attribute_material(obj):
    mat = bpy.data.materials.new("couleurs_scan")
    if mat.node_tree is None:
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    attr = nodes.new("ShaderNodeVertexColor")
    attr.layer_name = obj.data.color_attributes[0].name
    mat.node_tree.links.new(attr.outputs[0], bsdf.inputs[0])
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def bake_colors(target, sources, reach):
    """Projects the scan's colors onto the printable mesh: Cycles bake into a face-corner color attribute."""
    for o in sources:
        if o.data.color_attributes and not base_color_linked(o):
            color_attribute_material(o)
        o.hide_render = False
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 1
    attr = target.data.color_attributes.new("couleur", "BYTE_COLOR", "CORNER")
    target.data.color_attributes.active_color = attr
    if not target.data.materials:
        target.data.materials.append(bpy.data.materials.new("couleur"))
    for o in bpy.context.view_layer.objects:
        o.select_set(o in sources or o is target)
    bpy.context.view_layer.objects.active = target
    try:
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_selected_to_active=True, margin=0,
                            cage_extrusion=reach, max_ray_distance=2 * reach, target="VERTEX_COLORS")
    except RuntimeError as e:
        log(f"couleurs indisponibles : {e}")
        return False
    return True


def describe_textures(sources):
    for img in {n.image for o in sources for s in o.material_slots if s.material and s.material.node_tree
                for n in s.material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image}:
        w, h = img.size  # reading the size loads the file
        log(f"texture du scan : {os.path.basename(img.filepath)}, {w} x {h}{'' if w else ' (illisible)'}")
    if not any(o.data.uv_layers for o in sources if base_color_linked(o)):
        log("texture du scan sans coordonnées de texture")


UNSEEN_GREY = 0.716  # photogrammetry_win.UNSEEN (0xDCDCDC) in linear values, as the color attribute returns them


def colors_problem(obj):
    """Why the baked colors are unusable, or None: no colors beats a wrong model."""
    data = obj.data.color_attributes.active_color.data
    cols = [0.0] * (len(data) * 4)
    data.foreach_get("color", cols)
    corners = [cols[i:i + 3] for i in range(0, len(cols), 4)]
    seen = [c for c in corners if not all(abs(v - UNSEEN_GREY) < 0.03 for v in c)]
    if len(seen) < 0.1 * len(corners):
        return "faces absentes des photos"
    # judged on the seen faces only, so some unseen grey cannot hide a black model
    if sum(max(c) < 0.007 for c in seen) > 0.5 * len(seen):  # under about 20/255: rays that hit nothing, black texels
        return "noires"
    if sum(c[0] > 0.8 and c[1] < 0.05 and c[2] > 0.8 for c in seen) > 0.5 * len(seen):  # Blender's missing image
        return "texture illisible"
    return None


def flatten_face_colors(obj):
    """LowPoly: one color per facet, the look of a painted figurine."""
    data = obj.data.color_attributes.active_color.data
    cols = [0.0] * (len(data) * 4)
    data.foreach_get("color", cols)
    for p in obj.data.polygons:
        start, n = p.loop_start * 4, p.loop_total
        mean = [sum(cols[start + k * 4 + c] for k in range(n)) / n for c in range(4)]
        cols[start:start + n * 4] = mean * n
    data.foreach_set("color", cols)


def export_colors(obj, outdir, name):
    path = os.path.join(outdir, f"{name}_couleurs.glb")
    for o in bpy.context.view_layer.objects:
        o.select_set(o is obj)
    bpy.context.view_layer.objects.active = obj
    # Z up like the STL, so the viewer places both the same way; normals are recomputed there
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_yup=False,
                              export_materials="NONE", export_vertex_color="ACTIVE",
                              export_active_vertex_color_when_no_material=True, export_normals=False,
                              export_texcoords=False)
    return path


def topology_checks(bm):
    bm.normal_update()
    tree = BVHTree.FromBMesh(bm, epsilon=0.00001)
    return {
        "non_manifold_edges": sum(1 for e in bm.edges if not e.is_manifold),
        "boundary_edges": sum(1 for e in bm.edges if e.is_boundary),
        "self_intersections": len(tree.overlap(tree)),
        "triangles": sum(len(f.verts) - 2 for f in bm.faces),
    }


def print_checks(bm, min_wall):
    """Final-size checks in mm: wall thickness by inward ray casts, overhang share, shells, volume."""
    bm.normal_update()
    tree = BVHTree.FromBMesh(bm)
    lo, _ = bounds(bm)
    thin = 0
    total_area = overhang_area = 0.0
    cos45 = math.cos(math.radians(45))
    for f in bm.faces:
        area = f.calc_area()
        total_area += area
        n = f.normal
        if n.length < 0.5:
            continue
        c = f.calc_center_median()
        hit = tree.ray_cast(c - n * 1e-4, -n, min_wall)
        if hit[0] is not None:
            thin += 1
        if n.z < -cos45 and c.z > lo.z + 0.2:
            overhang_area += area
    return {
        "thin_faces": thin,
        "overhang_pct": round(100.0 * overhang_area / max(total_area, 1e-9), 1),
        "shells": len(islands_of(bm)),
        "volume_cm3": round(abs(bm.calc_volume(signed=True)) / 1000.0, 2),
        "min_wall_mm": min_wall,
    }


def render_previews(obj, outdir, name, engine="workbench"):
    sc = bpy.context.scene
    extra = []
    try:
        sc.render.engine = "CYCLES" if engine == "cycles" else "BLENDER_WORKBENCH"
    except TypeError:
        return []
    if engine == "cycles":
        sc.cycles.device = "CPU"
        sc.cycles.samples = 24
        sc.cycles.use_denoising = False
        try:
            sc.view_settings.view_transform = "Standard"
        except TypeError:
            pass
        mat = bpy.data.materials.new("preview")
        if mat.node_tree is None:
            mat.use_nodes = True
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs[0].default_value = (0.82, 0.80, 0.76, 1.0)
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        sc.world = sc.world or bpy.data.worlds.new("preview")
        if sc.world.node_tree is None:
            sc.world.use_nodes = True
        bg = next(n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND")
        bg.inputs[0].default_value = (0.18, 0.18, 0.18, 1.0)
        sun = bpy.data.objects.new("preview_sun", bpy.data.lights.new("preview_sun", "SUN"))
        sun.data.energy = 4.0
        sun.rotation_euler = (math.radians(55), 0.0, math.radians(35))
        sc.collection.objects.link(sun)
        extra.append(sun)
    else:
        shading = sc.display.shading
        shading.light = "STUDIO"
        shading.color_type = "SINGLE"
        shading.single_color = (0.82, 0.80, 0.76)
        shading.show_cavity = True
    sc.render.film_transparent = True
    sc.render.resolution_x = sc.render.resolution_y = 480
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    cam = bpy.data.objects.new("preview_cam", bpy.data.cameras.new("preview_cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.lens = 50
    cs = [v.co for v in obj.data.vertices]
    lo = Vector([min(c[i] for c in cs) for i in range(3)])
    hi = Vector([max(c[i] for c in cs) for i in range(3)])
    center, radius = (lo + hi) / 2, (hi - lo).length / 2
    dist = radius / math.tan(cam.data.angle / 2) * 1.1
    cam.data.clip_end = dist * 4
    paths = []
    for label, d in (("face", (0, -1, 0.25)), ("droite", (1, 0, 0.25)), ("dos", (0, 1, 0.25)), ("trois_quarts", (0.8, -0.9, 0.5))):
        cam.location = center + Vector(d).normalized() * dist
        cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(outdir, f"{name}_{label}.png")
        bpy.ops.render.render(write_still=True)
        paths.append(sc.render.filepath)
    for o in [cam] + extra:
        bpy.data.objects.remove(o, do_unlink=True)
    return paths


def main():
    a = parse_args()
    t0 = time.time()
    os.makedirs(a.outdir, exist_ok=True)
    clear_scene()

    if a.previews_only:
        bpy.ops.wm.stl_import(filepath=a.input)
        obj = next(o for o in bpy.data.objects if o.type == "MESH")
        print("PREVIEWS " + json.dumps(render_previews(obj, a.outdir, a.name, a.preview_engine)), flush=True)
        return

    meshes = import_any(a.input, a.raw_axes)
    bm = merge_to_bmesh(meshes)
    # the colored scan stays aside, frozen where it is, to color the result at the end
    sources = meshes if a.colors and has_colors(meshes) else []
    placed = []
    for o in sources:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        o.hide_render = True
        placed.append(mw)
    for o in list(bpy.data.objects):
        if o not in sources:
            bpy.data.objects.remove(o, do_unlink=True)
    log(f"import : {len(meshes)} maillage(s), {len(bm.faces)} faces{', couleurs du scan gardées' if sources else ''}")
    if sources:
        describe_textures(sources)

    turn = Euler([math.radians(r) for r in a.rot], "XYZ").to_matrix().to_4x4()
    if a.orient:
        turn = turn @ Matrix([a.orient[0:3], a.orient[3:6], a.orient[6:9]]).to_4x4()
    for axis in a.rot_seq.lower():
        if axis in "xyz":
            turn = Matrix.Rotation(math.radians(90), 4, axis.upper()) @ turn
    bm.transform(turn)
    lo, hi = bounds(bm)
    size = hi - lo
    if min(size) <= 0:
        raise SystemExit("maillage vide ou plat")
    bed = Vector(a.bed) - Vector((a.margin, a.margin, a.margin / 2))
    height = min(a.height_mm, bed.z)
    s = min(height / size.z, bed.x / size.x, bed.y / size.y)
    fit = Matrix.Scale(s, 4) @ Matrix.Translation(-(lo + hi) / 2)
    bm.transform(fit)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=max(size) * s * 1e-5)
    obj = bm_to_object(bm, a.name)
    bm.free()

    dims, _ = bm_stats(obj)
    default_faces, voxel_div, smooth_passes = LEVELS[a.level]
    voxel = min(max(max(dims) / voxel_div, 0.2), 0.5)
    method, holes = make_watertight(obj, voxel, a.force_closing)
    log(f"étanchéité : {method}, {holes} arêtes de bord comblées, voxel {voxel:.2f} mm, {len(obj.data.polygons)} faces")

    bm = object_to_bm(obj)
    n_islands, kept = keep_shells(bm, a.keep_parts)
    bm.to_mesh(obj.data)
    bm.free()
    log(f"coques : {n_islands} trouvées, {kept} gardée(s)")

    sm = obj.modifiers.new("relax", "SMOOTH")
    sm.factor = 0.5
    sm.iterations = smooth_passes
    apply_modifier(obj, sm)
    if a.smooth:
        t1 = time.time()
        width, iterations = SMOOTH[a.smooth]
        sdf_smooth(obj, voxel, width, iterations)
        bm = object_to_bm(obj)
        keep_shells(bm, a.keep_parts)  # a thin strand may have come loose
        bm.to_mesh(obj.data)
        bm.free()
        log(f"lissage {a.smooth} : flou du volume sur {width * voxel:.1f} mm, {iterations} passe(s), "
            f"{len(obj.data.polygons)} faces, {time.time() - t1:.1f} s")

    target = a.faces or default_faces
    work = bm = None
    for attempt in range(4):
        if work is not None:
            bm.free()
            bpy.data.objects.remove(work, do_unlink=True)
        work = obj.copy()
        work.data = obj.data.copy()
        bpy.context.scene.collection.objects.link(work)
        decimate(work, int(target))
        bm = object_to_bm(work)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        if a.base_cut > 0:
            cut_flat_base(bm, a.base_cut)
            bmesh.ops.triangulate(bm, faces=bm.faces)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        topo = topology_checks(bm)
        log(f"essai {attempt + 1} : cible {int(target)} triangles -> {topo}")
        if (topo["non_manifold_edges"] == 0 and topo["self_intersections"] == 0) or attempt == 3:
            break
        target *= 1.4

    lo, hi = bounds(bm)
    size = hi - lo
    s2 = min(height / size.z, bed.x / size.x, bed.y / size.y)
    refit = Matrix.Translation((0, 0, size.z * s2 / 2)) @ Matrix.Scale(s2, 4) @ Matrix.Translation(-(lo + hi) / 2)
    bm.transform(refit)
    lo, hi = bounds(bm)
    report = topology_checks(bm)
    report.update(print_checks(bm, 2 * a.nozzle))
    bm.to_mesh(work.data)
    bm.free()
    report["colors"] = None
    if sources:
        for o, mw in zip(sources, placed):
            o.matrix_world = refit @ fit @ turn @ mw
        # the result moved off the scan by remeshing, smoothing and decimation: a few percent of the height
        if bake_colors(work, sources, reach=0.03 * height):
            problem = colors_problem(work)
            if problem:
                log(f"couleurs du scan inexploitables ({problem}) : aperçu Rendu désactivé pour ce modèle")
            else:
                if a.level == "lowpoly":
                    flatten_face_colors(work)
                report["colors"] = export_colors(work, a.outdir, a.name)
                log("couleurs du scan projetées")
    for o in list(bpy.data.objects):
        if o is not work:
            bpy.data.objects.remove(o, do_unlink=True)
    work.name = a.name

    stl = os.path.join(a.outdir, f"{a.name}.stl")
    work.select_set(True)
    bpy.context.view_layer.objects.active = work
    bpy.ops.wm.stl_export(filepath=stl, export_selected_objects=False, ascii_format=False,
                          global_scale=1.0, use_scene_unit=False, apply_modifiers=True)
    with open(stl, "rb") as f:
        f.seek(80)
        written = int.from_bytes(f.read(4), "little")
    if written != report["triangles"]:
        raise SystemExit(f"export STL incomplet : {written} triangles écrits sur {report['triangles']}")

    if a.save_blend:
        us = bpy.context.scene.unit_settings
        us.system, us.scale_length, us.length_unit = "METRIC", 0.001, "MILLIMETERS"
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(a.outdir, f"{a.name}.blend"), copy=True)

    report.update({
        "stl": stl,
        "previews": [],
        "dimensions_mm": [round(v, 1) for v in (hi - lo)],
        "printable": report["non_manifold_edges"] == 0 and report["self_intersections"] == 0 and report["shells"] >= 1,
        "watertight_method": method,
        "level": a.level,
        "seconds": round(time.time() - t0, 1),
    })

    def write_report():
        with open(os.path.join(a.outdir, f"{a.name}.json"), "w") as f:
            json.dump(report, f, indent=2)

    write_report()
    log(f"export {stl}")
    print("REPORT " + json.dumps(report), flush=True)

    if a.previews:
        # without OpenGL Blender can crash right here: the STL and the report are already out
        report["previews"] = render_previews(work, a.outdir, a.name, a.preview_engine)
        write_report()
        print("PREVIEWS " + json.dumps(report["previews"]), flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        # JSON keeps the line ASCII, so a non-UTF-8 console (Windows) cannot garble it
        if e.code not in (0, None):
            print("FATAL " + json.dumps(str(e.code)), flush=True)
        raise
    except Exception as e:
        print("FATAL " + json.dumps(f"{type(e).__name__}: {e}"), flush=True)
        raise
