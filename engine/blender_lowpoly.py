"""Headless Blender step: any mesh -> watertight low-poly STL sized for the printer.

Blender -b --factory-startup --python-exit-code 1 -P blender_lowpoly.py -- --input IN --outdir DIR [options]
--factory-startup keeps user add-ons (MCP servers on port 9876) from loading in this background instance.
"""
import argparse
import contextlib
import json
import math
import os
import shutil
import sys
import time
import zipfile

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import couleurs  # noqa: E402
import i18n  # noqa: E402
import sysmem  # noqa: E402


# LowPoly -> detailed: (default triangles, voxels along the largest side, smoothing passes)
LEVELS = {
    "lowpoly": (1000, 300, 2),
    "medium": (20000, 400, 2),
    "detailed": (300000, 650, 1),
}
# extra smoothing on demand, as a blur of the volume: (filter width in voxels, iterations). Surface filters were
# tried first on a 69-photo bust: Blender's Laplacian solver took minutes, Taubin left 5 mm bumps untouched.
SMOOTH = {1: (2, 1), 2: (3, 1), 3: (4, 2)}
# texture for the color print services, per level: the facets of LowPoly need less
TEXTURE_SIZE = {"lowpoly": 2048, "medium": 4096, "detailed": 4096}
# photos at Max resolution: the textured OBJ and the 3D software profile ask for 8192. Every bake gets the largest
# size up to the one asked whose bake fits in free memory. Per texel, measured with Blender 5.2.2 on the 3D software
# profile of a 507,000-face scan: peaks of 3.3, 4.0, 7.0 and 18.8 GB from 1024 to 8192, 235 B more per texel
HIRES_TEXTURES = (8192, 6144)
TEXTURE_STEPS = (8192, 6144, 4096, 2048, 1024)
POWERS_OF_TWO = (8192, 4096, 2048, 1024)  # games and the web: mipmaps everywhere
BAKE_BYTES_PER_PIXEL = 240
MEMORY_RESERVE = 1.5 * 2 ** 30
# export profiles outside printing: (faces, quads, texture px, extra levels of detail as fractions of the faces).
# software comes last: it empties the scene to save its .blend
PROFILES = {
    "web": (50000, False, 2048, ()),
    "game": (50000, False, 2048, (0.5, 0.25)),
    "software": (20000, True, 4096, ()),
}
# roughness of each finish; matte is also what Object Capture gives a scan without a roughness map
FINISHES = {"matte": 0.9, "satin": 0.6, "gloss": 0.3}
IMAGE_EXT = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--name", default="model")
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
    ap.add_argument("--colors", action="store_true", help="also write NAME_colors.glb, the scan's colors on the result")
    ap.add_argument("--filaments", type=int, default=4, help="with --colors: filament colors of the 3MF and colored OBJ")
    ap.add_argument("--color-files", default="3mf,obj,texture",
                    help="with --colors: comma list among 3mf, obj (colored, for OrcaSlicer), texture; '-' for none")
    ap.add_argument("--profiles-only", help="comma list among software, game, web: write only these export "
                    "profiles (meters, Y up, base at the origin), no print files")
    ap.add_argument("--orient", type=float, nargs=9, help="row-major 3x3 rotation applied first (stands a COLMAP scan up)")
    ap.add_argument("--raw-axes", action="store_true", help="import OBJ coordinates as they are, without the Y-up conversion")
    ap.add_argument("--photo-res", default="", help="resolution of the photos behind the scan: max enlarges the textures")
    ap.add_argument("--texture-size", choices=["auto", "1024", "2048", "4096", "8192"], default="auto",
                    help="baked textures, lowered to what the free memory allows; auto: by level and profile, "
                    "8192 for the textured OBJ and 3D software with --photo-res max")
    ap.add_argument("--bake-samples", type=int, default=4, help="rays per texel of the texture bakes, spread over the "
                    "texel: 1 gives jagged edges, 4 and up smooth them (antialiasing) for more time")
    ap.add_argument("--real-height-mm", type=float, default=0.0, help="export profiles: the object's real height, "
                    "0 = the printed height")
    ap.add_argument("--relief", choices=["scan", "solid"], default="scan", help="export profiles: normal map baked "
                    "from the scan (its fine relief, and its grain) or from the smoothed solid")
    ap.add_argument("--finish", choices=["auto"] + list(FINISHES), default="auto", help="export profiles: roughness; "
                    "auto bakes the scan's roughness map, matte without one")
    ap.add_argument("--web-images", choices=["jpeg", "webp"], default="jpeg")
    ap.add_argument("--density", type=float, default=1.0, help="export profiles: their faces times this")
    return ap.parse_args(argv)


def log(msg):
    print(f"[blender] {msg}", flush=True)


def texture_size(a, size, steps=TEXTURE_STEPS):
    """The size asked, or with auto the level's or profile's (8192 with Max photos, LowPoly's facets keeping their
    2048), lowered to the largest step whose bake fits in free memory."""
    if a.texture_size != "auto":
        size = int(a.texture_size)
    elif a.photo_res == "max" and size >= 4096:
        size = HIRES_TEXTURES[0]
    free = sysmem.free_memory()
    fit = next((t for t in steps if t <= size and (free is None or t * t * BAKE_BYTES_PER_PIXEL + MEMORY_RESERVE <= free)),
               steps[-1])
    if fit < size:
        log(i18n.tr("srv.bl_texture_memory", size=fit, wanted=size, gb=f"{free / 2 ** 30:.1f}"))
    return fit


def new_image(name, size, data=False, color=(0.0, 0.0, 0.0, 0.0)):
    """A bake target. Alpha 0 marks the texels no ray reaches: the bake writes alpha 1 where it hits."""
    img = bpy.data.images.new(name, size, size, alpha=True, is_data=data)
    img.generated_color = color
    return img


def save_image(img, path, fmt, quality):
    img.filepath_raw = path
    img.file_format = fmt
    img.save(quality=quality)


def _halve(c, w):
    """Sums of 2 x 2 texels, the weights clamped to 1: a fully seen block counts as one texel at the next level."""
    if c.shape[0] % 2 or c.shape[1] % 2:
        pad = ((0, c.shape[0] % 2), (0, c.shape[1] % 2))
        c, w = np.pad(c, pad + ((0, 0),)), np.pad(w, pad)
    c = c[0::2, 0::2] + c[1::2, 0::2] + c[0::2, 1::2] + c[1::2, 1::2]
    w = w[0::2, 0::2] + w[1::2, 0::2] + w[0::2, 1::2] + w[1::2, 1::2]
    k = np.minimum(w, 1.0) / np.maximum(w, 1e-12)
    return c * k[..., None], w * k


def _double(x):
    """Bilinear, twice the size: 9/16 of the nearest texel, 3/16 of each side neighbor, 1/16 of the corner."""
    p = np.pad(x, ((1, 1), (1, 1), (0, 0)), mode="edge")
    out = np.empty((2 * x.shape[0], 2 * x.shape[1], x.shape[2]), dtype=x.dtype)
    for i, rows in ((0, slice(0, -2)), (1, slice(2, None))):
        for j, cols in ((0, slice(0, -2)), (1, slice(2, None))):
            out[i::2, j::2] = (9 * p[1:-1, 1:-1] + 3 * p[rows, 1:-1] + 3 * p[1:-1, cols] + p[rows, cols]) / 16
    return out


def fill_unseen(img, blue=None):
    """Texels no ray reached, holes of the scan (under a bust, a missed armpit) and gaps between UV islands, take the
    colors around them, spread by push-pull over halved copies, instead of black. blue, if given, then fills that
    channel. Returns the mean of channel 0 over the texels seen."""
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    seen = px[..., 3] > 0.5
    if not seen.any():
        return 0.0
    mean = float(px[..., 0][seen].mean())
    if not seen.all():
        # the first level by slices: no full-size premultiplied copy of an 8192 image
        s = seen.astype(np.float32)
        c = sum(px[i::2, j::2, :3] * s[i::2, j::2, None] for i in (0, 1) for j in (0, 1))
        wt = sum(s[i::2, j::2] for i in (0, 1) for j in (0, 1))
        k = np.minimum(wt, 1.0) / np.maximum(wt, 1e-12)
        pyramid = [(c * k[..., None], wt * k)]
        del s, c, wt, k
        while max(pyramid[-1][1].shape) > 1:
            pyramid.append(_halve(*pyramid[-1]))
        c, wt = pyramid.pop()
        out = c / np.maximum(wt, 1e-12)[..., None]
        while pyramid:
            c, wt = pyramid.pop()
            out = c + (1.0 - wt)[..., None] * _double(out)[:wt.shape[0], :wt.shape[1]]
        unseen = ~seen
        px[..., :3][unseen] = _double(out)[:h, :w][unseen]
    px[..., 3] = 1.0
    if blue is not None:
        px[..., 2] = blue
    img.pixels.foreach_set(px.ravel())
    return mean


def flipped_green(img, name):
    """The normal map in DirectX's convention, green inverted: Unreal Engine reads FBX normal maps that way."""
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px[1::4] = 1.0 - px[1::4]
    dx = bpy.data.images.new(name, w, h, alpha=True, is_data=True)
    dx.pixels.foreach_set(px)
    return dx


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
        raise SystemExit(i18n.tr("srv.bl_format_unsupported", ext=ext))
    meshes = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if not meshes:
        raise SystemExit(i18n.tr("srv.bl_no_mesh"))
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
        raise SystemExit(i18n.tr("srv.bl_empty_mesh"))
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
        raise SystemExit(i18n.tr("srv.bl_nothing_left"))
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
        log(i18n.tr("srv.bl_voxel_inconsistent", size=tuple(round(v, 1) for v in size1), volume=f"{vol1:.0f}"))
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
    ng = bpy.data.node_groups.new("smoothing", "GeometryNodeTree")
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
    mod = obj.modifiers.new("smoothing", "NODES")
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
    mat = bpy.data.materials.new("scan_colors")
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
    attr = target.data.color_attributes.new("color", "BYTE_COLOR", "CORNER")
    target.data.color_attributes.active_color = attr
    if not target.data.materials:
        target.data.materials.append(bpy.data.materials.new("color"))
    for o in bpy.context.view_layer.objects:
        o.select_set(o in sources or o is target)
    bpy.context.view_layer.objects.active = target
    try:
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_selected_to_active=True, margin=0,
                            cage_extrusion=reach, max_ray_distance=2 * reach, target="VERTEX_COLORS")
    except RuntimeError as e:
        log(i18n.tr("srv.bl_colors_unavailable", error=e))
        return False
    return True


def describe_textures(sources):
    for img in {n.image for o in sources for s in o.material_slots if s.material and s.material.node_tree
                for n in s.material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image}:
        w, h = img.size  # reading the size loads the file
        name = os.path.basename(img.filepath)
        log(i18n.tr("srv.bl_scan_texture", name=name, w=w, h=h) if w else
            i18n.tr("srv.bl_scan_texture_unreadable", name=name, w=w, h=h))
    if not any(o.data.uv_layers for o in sources if base_color_linked(o)):
        log(i18n.tr("srv.bl_scan_texture_no_uv"))


UNSEEN_GREY = 0.716  # photogrammetry_win.UNSEEN (0xDCDCDC) in linear values, as the color attribute returns them


def colors_problem(obj):
    """Why the baked colors are unusable, or None: no colors beats a wrong model."""
    data = obj.data.color_attributes.active_color.data
    cols = [0.0] * (len(data) * 4)
    data.foreach_get("color", cols)
    corners = [cols[i:i + 3] for i in range(0, len(cols), 4)]
    seen = [c for c in corners if not all(abs(v - UNSEEN_GREY) < 0.03 for v in c)]
    if len(seen) < 0.1 * len(corners):
        return i18n.tr("srv.bl_colors_unseen")
    # judged on the seen faces only, so some unseen grey cannot hide a black model
    if sum(max(c) < 0.007 for c in seen) > 0.5 * len(seen):  # under about 20/255: rays that hit nothing, black texels
        return i18n.tr("srv.bl_colors_black")
    if sum(c[0] > 0.8 and c[1] < 0.05 and c[2] > 0.8 for c in seen) > 0.5 * len(seen):  # Blender's missing image
        return i18n.tr("srv.bl_colors_bad_texture")
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
    path = os.path.join(outdir, f"{name}_colors.glb")
    for o in bpy.context.view_layer.objects:
        o.select_set(o is obj)
    bpy.context.view_layer.objects.active = obj
    # Z up like the STL, so the viewer places both the same way; normals are recomputed there
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_yup=False,
                              export_materials="NONE", export_vertex_color="ACTIVE",
                              export_active_vertex_color_when_no_material=True, export_normals=False,
                              export_texcoords=False)
    return path


def split_filaments(obj, count, min_island_area):
    """The colors reduced to a few filaments, one per triangle of the fan triangulation the STL export makes."""
    me = obj.data
    n = len(me.polygons)
    start, total, areas = np.zeros(n, dtype=np.int64), np.zeros(n, dtype=np.int64), np.zeros(n)
    me.polygons.foreach_get("loop_start", start)
    me.polygons.foreach_get("loop_total", total)
    me.polygons.foreach_get("area", areas)
    cols = np.zeros(len(me.loops) * 4, dtype=np.float32)
    me.color_attributes.active_color.data.foreach_get("color", cols)
    face_colors = np.add.reduceat(cols.reshape(-1, 4)[:, :3], start) / total[:, None]
    corner_vertex = np.zeros(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("vertex_index", corner_vertex)
    verts = np.zeros(len(me.vertices) * 3)
    me.vertices.foreach_get("co", verts)
    tris, owner = [], []
    for f in range(n):  # fan, as the STL export triangulates
        s, t = start[f], total[f]
        tris.extend((corner_vertex[s], corner_vertex[s + k], corner_vertex[s + k + 1]) for k in range(1, t - 1))
        owner.extend([f] * (t - 2))
    owner = np.array(owner)
    labels, palette = couleurs.filaments(face_colors[owner], areas[owner] / (total[owner] - 2), tris, count,
                                         min_island_area)
    return verts.reshape(-1, 3), tris, labels, palette


def bake_texture(target, sources, reach, size, path, samples):
    """The preview's projection again, into an image laid out by Smart UV Project: color print services print a
    texture, much finer than one color per vertex."""
    unwrap(target, size)
    img = new_image("texture", size)
    mat = bpy.data.materials.new("texture")
    if mat.node_tree is None:
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    mat.node_tree.links.new(tex.outputs["Color"], next(n for n in nodes if n.type == "BSDF_PRINCIPLED").inputs[0])
    target.data.materials.clear()
    target.data.materials.append(mat)
    bake_image(target, sources, "DIFFUSE", img, reach, samples)
    fill_unseen(img)
    save_image(img, path, "PNG", 100)


def export_textured(obj, outdir, name, png):
    """OBJ + MTL + PNG in mm, Z up like the STL, zipped without folders: what Sculpteo or i.materialise take."""
    obj_path = os.path.join(outdir, f"{name}_colors.obj")
    for o in bpy.context.view_layer.objects:
        o.select_set(o is obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.wm.obj_export(filepath=obj_path, export_selected_objects=True, forward_axis="Y", up_axis="Z",
                          global_scale=1.0, export_uv=True, export_normals=False, export_materials=True,
                          path_mode="STRIP", export_colors=False)
    files = [obj_path, obj_path[:-4] + ".mtl", png]
    path = os.path.join(outdir, f"{name}_colors_texture.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, os.path.basename(f))
    for f in files:
        os.remove(f)
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
    for label, d in (("front", (0, -1, 0.25)), ("right", (1, 0, 0.25)), ("back", (0, 1, 0.25)),
                     ("three_quarter", (0.8, -0.9, 0.5))):
        cam.location = center + Vector(d).normalized() * dist
        cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(outdir, f"{name}_{label}.png")
        bpy.ops.render.render(write_still=True)
        paths.append(sc.render.filepath)
    for o in [cam] + extra:
        bpy.data.objects.remove(o, do_unlink=True)
    return paths


def select_only(objs, active):
    for o in bpy.context.view_layer.objects:
        o.select_set(o in objs or o is active)
    bpy.context.view_layer.objects.active = active


def retopo_quads(obj, faces):
    """QuadriFlow, Blender's quad remesher. It refuses edges under 1e-4 per axis (some come out of the voxel remesh)
    and, run from a script, reads only target_faces and fails without raising: the result is checked."""
    dims, _ = bm_stats(obj)
    bm = object_to_bm(obj)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=max(dims) * 1e-4)
    bm.to_mesh(obj.data)
    bm.free()
    decimate(obj, 10 * faces)  # its time grows with the input
    select_only([], obj)
    with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
        done = bpy.ops.object.quadriflow_remesh(mode="FACES", target_faces=faces, use_mesh_symmetry=False,
                                                use_preserve_sharp=False, use_preserve_boundary=False,
                                                preserve_attributes=False, smooth_normals=False, seed=0)
    return "FINISHED" in done


def unwrap(obj, size):
    """Smart UV Project, then its islands packed again by their real outline, turned at any angle. On the 50,000
    triangles of a bust scan, the texture's used share goes from 55 to 62 % for one second more, and the gaps between
    islands, at their first percentile, from 4.6 to 8.7 texels, which mipmaps need. The exact FRACTION margin takes
    13 s."""
    select_only([], obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.002)
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(rotate=True, rotate_method="ANY", scale=True, margin_method="ADD", margin=4 / size,
                            shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")


def bake_image(target, sources, kind, image, reach, samples=1):
    """Selected-to-active bake into the target's image node that holds image: the scan's colors or roughness, or the
    relief of the scan or of the smooth solid as a tangent-space normal map. Rays spread over each texel when there
    are several, which smooths edges."""
    nodes = target.active_material.node_tree.nodes
    nodes.active = next(n for n in nodes if n.type == "TEX_IMAGE" and n.image is image)
    select_only(sources, target)
    bpy.context.scene.cycles.samples = max(1, samples)
    extra = {"DIFFUSE": {"pass_filter": {"COLOR"}}, "NORMAL": {"normal_space": "TANGENT"}}.get(kind, {})
    bpy.ops.object.bake(type=kind, use_selected_to_active=True, margin=8, cage_extrusion=reach,
                        max_ray_distance=2 * reach, target="IMAGE_TEXTURES", **extra)


def colors_usable(high, sources, reach):
    """The print step's verdict on the scan's colors, judged on a light copy."""
    if not sources:
        return False
    probe = high.copy()
    probe.data = high.data.copy()
    bpy.context.scene.collection.objects.link(probe)
    decimate(probe, 20000)
    problem = colors_problem(probe) if bake_colors(probe, sources, reach) else i18n.tr("srv.bl_colors_no_bake")
    if problem:
        log(i18n.tr("srv.bl_colors_unusable_profiles", problem=problem))
    bpy.data.objects.remove(probe, do_unlink=True)
    return problem is None


def linked_image(socket, depth=4):
    """An image texture feeds this socket, directly or through a few nodes (Separate Color, Normal Map)."""
    for link in socket.links if depth else ():
        node = link.from_node
        if node.type == "TEX_IMAGE" and node.image or any(linked_image(s, depth - 1) for s in node.inputs):
            return True
    return False


def roughness_mapped(sources):
    """The scan has a roughness map of its own (Object Capture at High), to bake like its colors."""
    return any(linked_image(n.inputs["Roughness"]) for o in sources for s in o.material_slots
               if s.material and s.material.node_tree for n in s.material.node_tree.nodes
               if n.type == "BSDF_PRINCIPLED")


def profile_material(obj, images, roughness):
    """Principled BSDF with the color texture, the normal map and the roughness, what the glTF, FBX and OBJ
    exporters read. One side only: a closed solid, so the GLB says doubleSided false."""
    mat = bpy.data.materials.new(obj.name)
    if mat.node_tree is None:
        mat.use_nodes = True
    mat.use_backface_culling = True
    nodes = mat.node_tree.nodes
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = 0.0
    texs = {}
    for kind, img in images.items():
        texs[kind] = nodes.new("ShaderNodeTexImage")
        texs[kind].image = img
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return mat, bsdf, texs


def image_formats(a, p):
    """Format and quality of each map: lossless for 3D software; for games a JPEG color keeps the three GLB of the
    levels of detail light and normal maps stay lossless; JPEG or WebP throughout for the web."""
    if p == "web":
        fmt = "WEBP" if a.web_images == "webp" else "JPEG"
        return {"color": (fmt, 90), "normal": (fmt, 95), "roughness": (fmt, 90)}
    return {"color": ("JPEG", 95) if p == "game" else ("PNG", 100), "normal": ("PNG", 100), "roughness": ("PNG", 100)}


def export_profile(a, p, high, sources, colors, reach, workdir, size, scale, rough_map, roughness):
    name = a.name
    faces, quads, _, lods = PROFILES[p]
    faces = max(200, min(int(faces * a.density), len(high.data.polygons)))
    t1 = time.time()
    low = high.copy()
    low.data = high.data.copy()
    low.name = low.data.name = f"{name}_{p}" + ("_LOD0" if lods else "")
    bpy.context.scene.collection.objects.link(low)
    if quads and not retopo_quads(low, faces):
        log(i18n.tr("srv.bl_profile_no_quads", profile=p))
        quads = False
    if not quads:
        decimate(low, faces)
    bm = object_to_bm(low)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(low.data)
    bm.free()
    # smooth shading: vertices shared between faces, and the normals a baked normal map is measured against
    low.data.shade_smooth()
    seconds = f"{time.time() - t1:.1f}"
    log(i18n.tr("srv.bl_profile_retopo", profile=p, s=seconds) if quads else
        i18n.tr("srv.bl_profile_decimate", profile=p, s=seconds))
    t1 = time.time()
    unwrap(low, size)

    relief = sources if a.relief == "scan" and sources else [high]
    images = {"normal": new_image(f"{name}_{p}_normal", size, data=True, color=(0.5, 0.5, 1.0, 1.0))}
    if colors:
        images["color"] = new_image(f"{name}_{p}_color", size)
    if rough_map:  # roughness varies slowly: half the size
        images["roughness"] = new_image(f"{name}_{p}_roughness", max(size // 2, 1024), data=True)
    mat, bsdf, texs = profile_material(low, images, roughness)
    if colors:
        bake_image(low, sources, "DIFFUSE", images["color"], reach, a.bake_samples)
        fill_unseen(images["color"])
    # the scan lies farther from the low mesh than the solid it was made from; a missed ray leaves the low normal
    bake_image(low, relief, "NORMAL", images["normal"], reach if relief is sources else reach / 2, a.bake_samples)
    if rough_map:
        bake_image(low, sources, "ROUGHNESS", images["roughness"], reach, a.bake_samples)
        # web: metalness 0 in blue, glTF's channel for it, next to the roughness in green
        roughness = mat["roughness_mean"] = fill_unseen(images["roughness"], 0.0 if p == "web" else None)
    links = mat.node_tree.links
    if colors:
        links.new(texs["color"].outputs["Color"], bsdf.inputs["Base Color"])
    nmap = mat.node_tree.nodes.new("ShaderNodeNormalMap")
    links.new(texs["normal"].outputs["Color"], nmap.inputs["Color"])
    links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    if rough_map:
        sep = mat.node_tree.nodes.new("ShaderNodeSeparateColor")
        links.new(texs["roughness"].outputs["Color"], sep.inputs["Color"])
        links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        if p == "web":
            # both read from one file: the glTF exporter takes it as it is, a JPEG or WebP; with roughness alone it
            # packs a new PNG, white in blue, three times heavier
            links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    formats = image_formats(a, p)
    for kind, img in images.items():
        fmt, quality = formats[kind]
        save_image(img, os.path.join(workdir, f"{name}_{p}_{kind}.{IMAGE_EXT[fmt]}"), fmt, quality)
    if p == "game":
        dx = flipped_green(images["normal"], f"{name}_{p}_normal_dx")
        save_image(dx, os.path.join(workdir, f"{name}_{p}_normal_dx.png"), "PNG", 100)
    log(i18n.tr("srv.bl_profile_textures", profile=p, size=size, n=a.bake_samples, s=f"{time.time() - t1:.1f}"))
    if relief is sources:
        log(i18n.tr("srv.bl_profile_relief_scan", profile=p))
    if rough_map:
        log(i18n.tr("srv.bl_profile_roughness_map", profile=p, size=images["roughness"].size[0],
                    value=f"{roughness:.2f}"))

    low.data.transform(Matrix.Scale(scale, 4))
    levels = [low]
    for frac in lods:
        lod = low.copy()
        lod.data = low.data.copy()
        lod.name = lod.data.name = f"{name}_{p}_LOD{len(levels)}"
        bpy.context.scene.collection.objects.link(lod)
        decimate(lod, int(faces * frac))
        levels.append(lod)
    count = sum(len(f.vertices) - 2 for f in low.data.polygons) if not quads else len(low.data.polygons)
    info = {"faces": count, "quads": quads, "lods": len(levels), "colors": colors, "size": size,
            "relief": "scan" if relief is sources else "solid", "roughness": round(roughness, 2),
            "roughness_map": rough_map}
    return levels, info


@contextlib.contextmanager
def roughness_constant(obj):
    """FBX has no roughness slot: Blender's exporter puts the map in the Phong shininess one, which the FBX import of
    Unreal 5.7 (Interchange, ufbx) takes as a shininess map. The FBX gets the map's mean instead; the map itself goes
    beside it and stays in the GLB."""
    mat = obj.active_material
    socket = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Roughness"]
    if not socket.is_linked:
        yield
        return
    source = socket.links[0].from_socket
    mat.node_tree.links.remove(socket.links[0])
    socket.default_value = mat.get("roughness_mean", socket.default_value)
    try:
        yield
    finally:
        mat.node_tree.links.new(source, socket)


def export_fbx(path):
    """With tangents, the MikkTSpace frame the normal map was baked in. They need triangles or quads only, which the
    profiles have; on a refusal the FBX goes out without them."""
    opts = dict(filepath=path, use_selection=True, path_mode="STRIP", embed_textures=False, apply_unit_scale=True)
    try:
        bpy.ops.export_scene.fbx(use_tspace=True, **opts)
    except RuntimeError as e:
        log(i18n.tr("srv.bl_profile_fbx_no_tangents", error=e))
        bpy.ops.export_scene.fbx(**opts)
    return path


def compressed_glbs(stem, glb):
    """The web GLB again, compressed by Draco and by meshopt, each kept only if it really is: without the library,
    Blender's exporter writes an uncompressed file and still reports success, and older versions lack meshopt.
    Draco keeps UVs at 14 bits: its default 12 rounds them to half a texel of a 2048 texture."""
    files = []
    for suffix, opts, tag, missing in (
            ("_draco", {"export_draco_mesh_compression_enable": True, "export_draco_texcoord_quantization": 14},
             b"KHR_draco_mesh_compression", "srv.bl_profile_no_draco"),
            ("_meshopt", {"export_meshopt_compression_enable": True}, b"EXT_meshopt_compression",
             "srv.bl_profile_no_meshopt")):
        path = stem + suffix + ".glb"
        try:
            bpy.ops.export_scene.gltf(filepath=path, **glb, **opts)
            with open(path, "rb") as f:
                done = tag in f.read(1 << 16)
        except (TypeError, OSError):
            done = False
        if done:
            files.append(path)
        else:
            if os.path.exists(path):
                os.remove(path)
            log(i18n.tr(missing))
    return files


def write_profile_files(a, p, levels, workdir):
    """The formats of each profile, in meters. GLB: Y up as glTF requires, with tangents, without which three.js
    derives its own frame from screen derivatives instead of the MikkTSpace one the normal map was baked in. FBX and
    OBJ: the exporters' Y up axes, what Maya, Unity or Unreal expect."""
    name = a.name
    files = []
    stems = [os.path.join(workdir, obj.name if p == "game" else f"{name}_{p}") for obj in levels]
    # AUTO keeps each map as the JPEG, WebP or PNG file saved above, with no second encoding
    glb = dict(export_format="GLB", use_selection=True, export_yup=True, export_materials="EXPORT",
               export_tangents=True, export_image_format="AUTO", export_image_quality=95)
    if p in ("web", "game"):
        for obj, stem in zip(levels, stems):
            select_only([], obj)
            bpy.ops.export_scene.gltf(filepath=stem + ".glb", **glb)
            files.append(stem + ".glb")
    if p == "web":
        files += compressed_glbs(stems[0], glb)
    if p in ("game", "software"):
        with roughness_constant(levels[0]):
            for obj, stem in zip(levels, stems):
                select_only([], obj)
                files.append(export_fbx(stem + ".fbx"))
    if p == "software":
        select_only([], levels[0])
        bpy.ops.wm.obj_export(filepath=stems[0] + ".obj", export_selected_objects=True, export_uv=True,
                              export_normals=True, export_materials=True, path_mode="STRIP")
        files += [stems[0] + ".obj", stems[0] + ".mtl"]
    if p != "web":
        files += sorted(os.path.join(workdir, f) for f in os.listdir(workdir) if f.startswith(f"{name}_{p}_")
                        and f.endswith(tuple("." + e for e in IMAGE_EXT.values())))
    if p == "software":
        obj = levels[0]
        for o in list(bpy.data.objects):
            if o is not obj:
                bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.orphans_purge(do_recursive=True)
        us = bpy.context.scene.unit_settings
        us.system, us.scale_length, us.length_unit = "METRIC", 1.0, "CENTIMETERS"
        blend = os.path.join(workdir, f"{name}_{p}.blend")
        bpy.ops.wm.save_as_mainfile(filepath=blend, copy=True, relative_remap=True)
        files.append(blend)
    return files


def write_readme(a, p, info, files, workdir):
    """README.txt in the app's language: units, maps and their conventions, what each file is for."""
    t = i18n.tr
    names = {os.path.basename(f) for f in files}
    titles = {"software": "ui.opt_software", "game": "ui.opt_game", "web": "ui.opt_web"}
    lines = [a.name, t(titles[p]), "", t("srv.readme_units", height=f"{info['height_m']:.4g}"),
             t("srv.readme_mesh_quads" if info["quads"] else "srv.readme_mesh_triangles", faces=info["faces"])]
    if info["lods"] > 1:
        lines.append(t("srv.readme_lods"))
    lines += ["", t("srv.readme_textures", size=info["size"])]
    if info["colors"]:
        lines.append("- " + t("srv.readme_color"))
    lines.append("- " + t("srv.readme_normal"))
    lines.append("  " + t("srv.readme_relief_scan" if info["relief"] == "scan" else "srv.readme_relief_solid"))
    if p == "game":
        lines.append("- " + t("srv.readme_normal_dx"))
    if info["roughness_map"] and p != "web":
        lines.append("- " + t("srv.readme_roughness_map" if p == "game" else "srv.readme_roughness_file",
                              value=info["roughness"]))
    else:
        lines.append(t("srv.readme_roughness_embedded") if info["roughness_map"] else
                     t("srv.readme_roughness_value", value=info["roughness"]))
    if p == "web" and a.web_images == "webp":
        lines.append(t("srv.readme_webp"))
    lines += ["", t("srv.readme_files")]
    lines += ["- " + t(key) for ext, key in ((".glb", "srv.readme_glb"), ("_draco.glb", "srv.readme_draco"),
                                             ("_meshopt.glb", "srv.readme_meshopt"), (".fbx", "srv.readme_fbx"),
                                             (".obj", "srv.readme_obj"), (".blend", "srv.readme_blend"))
              if any(n.endswith(ext) for n in names)]
    path = os.path.join(workdir, "README.txt")
    # BOM and CRLF: Windows Notepad shows the accents and the line breaks right
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def export_profiles(a, high, sources, placed, fit, turn, height):
    """The cleaned solid for 3D software, game engines and the web: base centered at the origin, in meters, at the
    printed size or the real one, the scan's colors and roughness, and the relief of the scan or of the solid baked
    into textures. One zip per profile."""
    lo, hi = bounds(object_to_bm(high))
    base = Matrix.Translation((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z))
    high.data.transform(base)
    for o, mw in zip(sources, placed):
        o.matrix_world = base @ fit @ turn @ mw
    sc = bpy.context.scene
    sc.render.engine, sc.cycles.device, sc.cycles.samples = "CYCLES", "CPU", 1  # only Cycles bakes
    reach = 0.03 * height
    colors = has_colors(sources) and colors_usable(high, sources, reach)
    if a.relief == "scan":
        # without normals of its own, flat faces would print the scan's triangles into the normal map
        for o in sources:
            if not o.data.has_custom_normals:
                o.data.shade_smooth()
    rough_map = a.finish == "auto" and roughness_mapped(sources)
    roughness = FINISHES.get(a.finish, FINISHES["matte"])
    scale = 0.001 * (a.real_height_mm / (hi.z - lo.z) if a.real_height_mm > 0 else 1.0)  # mm -> m
    if a.real_height_mm > 0:
        log(i18n.tr("srv.bl_profiles_real_height", m=f"{(hi.z - lo.z) * scale:.4g}", mm=f"{hi.z - lo.z:.0f}"))
    wanted = [p for p in PROFILES if p in a.profiles_only.split(",")]
    results = {}
    for p in wanted:
        t1 = time.time()
        workdir = os.path.join(a.outdir, f"{a.name}_{p}")
        os.makedirs(workdir, exist_ok=True)
        try:
            size = texture_size(a, PROFILES[p][2], TEXTURE_STEPS if p == "software" else POWERS_OF_TWO)
            levels, info = export_profile(a, p, high, sources, colors, reach, workdir, size, scale, rough_map,
                                          roughness)
            info["height_m"] = round((hi.z - lo.z) * scale, 4)
            files = write_profile_files(a, p, levels, workdir)
            files.append(write_readme(a, p, info, files, workdir))
            path = os.path.join(a.outdir, f"{a.name}_{p}.zip")
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                for f in files:
                    z.write(f, os.path.basename(f))
            results[p] = {"path": path, **info}
            seconds = f"{time.time() - t1:.1f}"
            count = info["faces"]
            if info["lods"] > 1:
                log(i18n.tr("srv.bl_profile_done_lods", profile=p, faces=count, n=info["lods"], s=seconds))
            else:
                log(i18n.tr("srv.bl_profile_done_quads", profile=p, faces=count, s=seconds) if info["quads"] else
                    i18n.tr("srv.bl_profile_done_triangles", profile=p, faces=count, s=seconds))
        except (RuntimeError, OSError) as e:
            log(i18n.tr("srv.bl_profile_failed", profile=p, error=e))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            if p != "software":
                for o in list(bpy.data.objects):
                    if o is not high and o not in sources:
                        bpy.data.objects.remove(o, do_unlink=True)
                # an 8192 map weighs 256 MB: the next profile's bakes get that memory back
                for img in [i for i in bpy.data.images if i.name.startswith(f"{a.name}_{p}_")]:
                    bpy.data.images.remove(img)
    print("PROFILES " + json.dumps(results), flush=True)


def clean_solid(a):
    """Import, orientation, size in mm, watertight solid, main shells, smoothing: what printing and the export
    profiles share."""
    meshes = import_any(a.input, a.raw_axes)
    bm = merge_to_bmesh(meshes)
    # the colored scan stays aside, frozen where it is, to color the result at the end, and the export profiles keep
    # it to bake its relief too
    colored = a.colors and has_colors(meshes)
    sources = meshes if colored or (a.profiles_only and a.relief == "scan") else []
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
    log(i18n.tr("srv.bl_import_colors", n=len(meshes), faces=len(bm.faces)) if colored else
        i18n.tr("srv.bl_import", n=len(meshes), faces=len(bm.faces)))
    if colored:
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
        raise SystemExit(i18n.tr("srv.bl_flat_mesh"))
    bed = Vector(a.bed) - Vector((a.margin, a.margin, a.margin / 2))
    height = min(a.height_mm, bed.z)
    s = min(height / size.z, bed.x / size.x, bed.y / size.y)
    fit = Matrix.Scale(s, 4) @ Matrix.Translation(-(lo + hi) / 2)
    bm.transform(fit)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=max(size) * s * 1e-5)
    obj = bm_to_object(bm, a.name)
    bm.free()

    dims, _ = bm_stats(obj)
    _, voxel_div, smooth_passes = LEVELS[a.level]
    voxel = min(max(max(dims) / voxel_div, 0.2), 0.5)
    method, holes = make_watertight(obj, voxel, a.force_closing)
    stats = {"n": holes, "voxel": f"{voxel:.2f}", "faces": len(obj.data.polygons)}
    log(i18n.tr("srv.bl_watertight_voxel", **stats) if method == "voxel" else
        i18n.tr("srv.bl_watertight_closing", **stats))

    bm = object_to_bm(obj)
    n_islands, kept = keep_shells(bm, a.keep_parts)
    bm.to_mesh(obj.data)
    bm.free()
    log(i18n.tr("srv.bl_shells", n=n_islands, kept=kept))

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
        log(i18n.tr("srv.bl_smoothing", level=a.smooth, mm=f"{width * voxel:.1f}", n=iterations,
                    faces=len(obj.data.polygons), s=f"{time.time() - t1:.1f}"))
    return obj, sources, placed, fit, turn, height, bed, voxel, method


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

    obj, sources, placed, fit, turn, height, bed, voxel, method = clean_solid(a)
    if a.profiles_only:
        export_profiles(a, obj, sources, placed, fit, turn, height)
        return

    target = a.faces or LEVELS[a.level][0]
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
        log(i18n.tr("srv.bl_attempt", attempt=attempt + 1, target=int(target), topo=topo))
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
    report.update(colors=None, filaments=None, obj_colors=None, palette=None, texture=None)
    wanted = set(a.color_files.split(",")) - {"-", ""}
    if sources:
        for o, mw in zip(sources, placed):
            o.matrix_world = refit @ fit @ turn @ mw
        # the result moved off the scan by remeshing, smoothing and decimation: a few percent of the height
        if bake_colors(work, sources, reach=0.03 * height):
            problem = colors_problem(work)
            if problem:
                log(i18n.tr("srv.bl_colors_unusable_preview", problem=problem))
            else:
                if a.level == "lowpoly":
                    flatten_face_colors(work)
                report["colors"] = export_colors(work, a.outdir, a.name)
                log(i18n.tr("srv.bl_colors_baked"))
                if wanted & {"3mf", "obj"}:
                    verts, tris, labels, report["palette"] = split_filaments(work, a.filaments, (4 * a.nozzle) ** 2)
                    log(i18n.tr("srv.bl_filaments", n=len(report["palette"]),
                                colors=", ".join("#%02X%02X%02X" % c for c in report["palette"])))
                    if "3mf" in wanted:
                        report["filaments"] = os.path.join(a.outdir, f"{a.name}_filaments.3mf")
                        couleurs.write_3mf(report["filaments"], verts, tris, labels, report["palette"])
                    if "obj" in wanted:
                        report["obj_colors"] = os.path.join(a.outdir, f"{a.name}_colors_orca.obj")
                        couleurs.write_obj(report["obj_colors"], verts, tris, labels, report["palette"])
                if "texture" in wanted:
                    try:
                        png = os.path.join(a.outdir, f"{a.name}_colors.png")
                        t1, size = time.time(), texture_size(a, TEXTURE_SIZE[a.level])
                        bake_texture(work, sources, 0.03 * height, size, png, a.bake_samples)
                        report["texture"] = export_textured(work, a.outdir, a.name, png)
                        log(i18n.tr("srv.bl_texture_done", size=size, s=f"{time.time() - t1:.1f}"))
                    except (RuntimeError, OSError) as e:
                        log(i18n.tr("srv.bl_texture_failed", error=e))
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
        raise SystemExit(i18n.tr("srv.bl_stl_incomplete", written=written, total=report["triangles"]))

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
    log(i18n.tr("srv.bl_exported", path=stl))
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
