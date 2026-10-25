"""Windows photogrammetry, in place of Apple Object Capture: COLMAP finds the cameras, OpenMVS builds the mesh.

Both are installed by setup_tools under DATA/tools (colmap, openmvs) and run on the CPU. Commands and options are
those of COLMAP 4.2.1 and OpenMVS 2.4.0.
"""
import glob
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image, ImageOps

import i18n
import pipeline as pl
import sysmem

COLMAP_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
ORIENTATION, MAKE, MODEL, EXIF_IFD, FOCAL, FOCAL_35MM = 0x0112, 0x010F, 0x0110, 0x8769, 0x920A, 0xA405
UNSEEN = 0xDCDCDC  # faces no photo shows: the solid preview's grey rather than OpenMVS's orange
SCAN_VERSION = 2  # raised when the same photos give a different scan: older caches are computed again
# COLMAP's CPU SIFT (VLFeat) keeps 22 float planes of the image doubled in both directions (first_octave -1):
# 352 bytes per pixel of the scaled photo, plus a margin for the rest of the extractor
SIFT_BYTES_PER_PIXEL = 400
MEMORY_RESERVE = 1.5 * 2 ** 30  # left to Windows and the open apps
# CPU time grows fast with image size: low, mid and high follow Object Capture's preview / medium / full;
# max keeps the photos' full size as far as the free memory allows (_max_config)
RESOLUTIONS = {"low": {"max_image": 1600, "resolution_level": 2, "texture": 4096},
               "mid": {"max_image": 2000, "resolution_level": 1, "texture": 4096},
               "high": {"max_image": 3200, "resolution_level": 1, "texture": 4096}}
# low, mid and high keep the folder names of the level each one fed before the choice existed: no scan redone
CACHE_NAMES = {"low": "lowpoly", "mid": "medium", "high": "detailed", "max": "max"}
OPENMVS_MIN_RESOLUTION = 640  # OpenMVS's default --min-resolution
# peak bytes of DensifyPointCloud, ReconstructMesh and TextureMesh (8192 texture) at resolution level 0:
# base + a * pixels of the largest photo + b * pixels of all photos, measured with OpenMVS 2.4.0
MEMORY_MODEL = {"densify": (128 * 2 ** 20, 0, 50), "mesh": (64 * 2 ** 20, 0, 64), "texture": (512 * 2 ** 20, 0, 48)}


def colmap():
    return pl._first_existing([os.path.join(pl.TOOLS, "colmap", "bin", "colmap.exe")])


def openmvs(name):
    return os.path.join(pl.TOOLS, "openmvs", f"{name}.exe")


def available():
    return bool(colmap()) and all(os.path.exists(openmvs(n)) for n in ("InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh"))


def _short_path(path):
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        return buf.value if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024) else None
    except (AttributeError, OSError):
        return None


def _ascii_workspace(work_dir, name):
    """COLMAP and OpenMVS read their arguments in the Windows code page: the workspace needs a plain ASCII path."""
    name = f"colmap_{name}"
    if work_dir.isascii():
        return os.path.join(work_dir, name)
    short = _short_path(work_dir)
    return os.path.join(short, name) if short and short.isascii() else None


def _public_root():
    """Last resort: a folder of the shared Public folder, one per run, that only this account and Windows can open."""
    base = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "BerriaCraft")
    os.makedirs(base, exist_ok=True)
    root = tempfile.mkdtemp(prefix="work-", dir=base)
    try:
        _private_dir(root)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return root


def _private_dir(path):
    """Removes the inherited entries (other accounts can read Public) and grants this account and Windows."""
    who = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, creationflags=pl.NO_WINDOW).stdout
    sid = re.search(rb"S-1-[0-9-]+", who)
    if not sid:
        raise RuntimeError(i18n.tr("srv.pgw_no_account"))
    r = subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", f"*{sid.group().decode()}:(OI)(CI)F",
                        "*S-1-5-18:(OI)(CI)F"], capture_output=True, creationflags=pl.NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(i18n.tr("srv.pgw_protect_failed", code=r.returncode))


_free_memory = sysmem.free_memory


def _photo_sizes(photo_dir, photos):
    sizes = []
    for p in photos:
        try:
            with Image.open(os.path.join(photo_dir, p["name"])) as im:
                sizes.append(im.size)
        except Exception:  # noqa: BLE001  an unreadable photo is reported by COLMAP itself
            continue
    return sizes


def _largest_scaled(sizes, max_image):
    """Pixels of the largest photo once COLMAP has scaled it down to max_image."""
    return max((w * h * min(1.0, max_image / max(w, h)) ** 2 for w, h in sizes), default=max_image * max_image * 0.75)


def _sift_threads(photo_dir, photos, max_image):
    """SIFT extraction threads that fit in free memory, with the free memory, or (None, None) when unknown.

    COLMAP runs one single-threaded extractor per thread, each on a whole photo: fewer threads only lengthen
    this step, the features found stay the same. By default it takes every core, and in the detailed level an
    8 GB PC would page for minutes.
    """
    free = _free_memory()
    if not free:
        return None, None
    per_thread = SIFT_BYTES_PER_PIXEL * _largest_scaled(_photo_sizes(photo_dir, photos), max_image)
    return max(1, min(os.cpu_count() or 1, int((free - MEMORY_RESERVE) // per_thread))), free


def _dense_side(side, level, max_resolution):
    """Largest side OpenMVS works at: the photo halved level times, not under 640 px, not over max_resolution."""
    while level and side >> level < OPENMVS_MIN_RESOLUTION:
        level -= 1
    return min(side >> level, max_resolution)


def _peak_memory(side, aspect, n):
    """Bytes the busiest step needs with n photos of this largest side, SIFT on one thread."""
    px = side * side * aspect
    sift = SIFT_BYTES_PER_PIXEL * px if side > RESOLUTIONS["high"]["max_image"] else 0  # up to there, as high
    return max([sift] + [base + a * px + b * n * px for base, a, b in MEMORY_MODEL.values()])


def _max_config(sizes, free):
    """Max: the photos' own size, lowered until every step fits in free memory. None when that is no more than high."""
    if not sizes:
        return None
    w, h = max(sizes, key=lambda s: s[0] * s[1])
    side, aspect = max(w, h), min(w, h) / max(w, h)
    high = RESOLUTIONS["high"]
    floor = _dense_side(min(side, high["max_image"]), high["resolution_level"], 2560)
    if free:
        while side > floor and _peak_memory(side, aspect, len(sizes)) > free - MEMORY_RESERVE:
            side = int(side * 0.9)
    if side <= floor:
        return None
    # cameras found on photos at least as large as high's, depth and colors at this size
    return {"sift": max(side, min(max(w, h), high["max_image"])), "max_image": side, "resolution_level": 0,
            "max_resolution": side, "texture": 8192}


def _natural(name):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name.lower())]


def _exif(im):
    try:
        exif = im.getexif()
        return exif, exif.get_ifd(EXIF_IFD)
    except Exception:  # noqa: BLE001  damaged EXIF (some editing apps): the photo counts, as seen
        return Image.Exif(), {}


def _camera_key(size, exif, lens):
    """Size once upright, plus the EXIF settings COLMAP itself groups by (make, model, focal length)."""
    w, h = size
    if exif.get(ORIENTATION) in (5, 6, 7, 8):
        w, h = h, w
    focal = lens.get(FOCAL_35MM) or lens.get(FOCAL)
    text = lambda v: str(v).strip("\x00 ") if v else None  # noqa: E731
    return w, h, text(exif.get(MAKE)), text(exif.get(MODEL)), float(focal) if focal else None


def _stage(photo_dir, photos, images):
    """Upright copies in shooting order, one folder per camera setting.

    COLMAP 4.2.1 ignores the EXIF orientation, so turned photos are written upright, EXIF kept for the focal length.
    Each folder gets its own calibration (--ImageReader.single_camera_per_folder): mixed phones, zooms or sizes
    work, and photos without EXIF still share one camera. Names never collide: img_0001 is the first photo.
    """
    shutil.rmtree(images, ignore_errors=True)
    folders = {}
    for i, p in enumerate(sorted(photos, key=lambda p: _natural(p["name"])), 1):
        src = os.path.join(photo_dir, p["name"])
        with Image.open(src) as im:
            exif, lens = _exif(im)
            folder = os.path.join(images, folders.setdefault(_camera_key(im.size, exif, lens), f"cam{len(folders) + 1}"))
            os.makedirs(folder, exist_ok=True)
            ext = os.path.splitext(p["name"])[1].lower()
            turned = exif.get(ORIENTATION, 1) != 1
            if ext in COLMAP_EXT and not turned:
                target = os.path.join(folder, f"img_{i:04d}{ext}")
                try:
                    os.link(src, target)
                except OSError:
                    shutil.copy2(src, target)
                continue
            upright = ImageOps.exif_transpose(im) if turned else im
            upright.convert("RGB").save(os.path.join(folder, f"img_{i:04d}.jpg"), quality=95,
                                        exif=upright.getexif() if turned else exif)
    return len(folders)


def _quat_matrix(w, x, y, z):
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def orientation(images_txt):
    """Rotation that stands the scan up and turns its front to the viewer, from the camera poses.

    COLMAP's frame is arbitrary. The photos are taken upright, so their mean "up" is the vertical; the first photo
    (in name order) is usually taken from the front, so its side becomes the front, facing -Y as in Blender.
    """
    with open(images_txt, encoding="utf-8") as f:
        data = [line.split() for line in f if not line.startswith("#")]
    poses = []
    for v in data[0::2]:  # a pose line, then a points line that may be empty
        if len(v) >= 10:
            r = _quat_matrix(*map(float, v[1:5]))  # camera from world
            poses.append((v[9], r, -r.T @ np.array(list(map(float, v[5:8])))))
    if len(poses) < 2:
        return None
    up = sum(r.T @ np.array([0.0, -1.0, 0.0]) for _, r, _ in poses)  # image y points down
    up /= np.linalg.norm(up)
    middle = np.mean([c for _, _, c in poses], axis=0)
    front = min(poses, key=lambda p: p[0].replace("\\", "/").rsplit("/", 1)[-1])[2] - middle  # img_0001: first photo
    front -= up * front.dot(up)
    if np.linalg.norm(front) < 1e-9:
        front = np.cross(up, [1.0, 0.0, 0.0] if abs(up[0]) < 0.9 else [0.0, 1.0, 0.0])
    front /= np.linalg.norm(front)
    y, z = -front, up
    return np.stack([np.cross(y, z), y, z]).tolist()


def _cached(work_dir, name):
    # the folder only appears complete (see _publish): mesh, its textures and its orientation together
    folder = os.path.join(work_dir, f"scan_{name}")
    found = glob.glob(os.path.join(folder, "*.obj")) + glob.glob(os.path.join(folder, "*.ply"))
    if not found:
        return None
    try:
        with open(found[0] + ".orient.json", encoding="utf-8") as f:
            current = json.load(f).get("version") == SCAN_VERSION
    except (OSError, ValueError):
        return None
    return found[0] if current else None


def _scan_px(mesh):
    try:
        with open(mesh + ".orient.json", encoding="utf-8") as f:
            return json.load(f).get("px")
    except (OSError, ValueError):
        return None


def _dense_px(sizes, cfg):
    side = min(max((max(s) for s in sizes), default=cfg["max_image"]), cfg["max_image"])
    return _dense_side(side, cfg["resolution_level"], cfg.get("max_resolution", 2560))


def _publish(work_dir, name, files, orient, px=None):
    """Moves the result into scan_<name> in one step, so an interruption never leaves a partial cache."""
    final = os.path.join(work_dir, f"scan_{name}")
    staged = final + ".partial"
    shutil.rmtree(staged, ignore_errors=True)
    os.makedirs(staged)
    for p in files:  # the .obj names its .mtl, which names the textures: they move together
        shutil.move(p, staged)
    mesh = next(p for p in glob.glob(os.path.join(staged, "*")) if p.endswith((".obj", ".ply")))
    with open(mesh + ".orient.json", "w", encoding="utf-8") as f:  # read by blender_prep: COLMAP axes, then this rotation
        json.dump({"matrix": orient, "raw_axes": True, "version": SCAN_VERSION, "px": px}, f)
    shutil.rmtree(final, ignore_errors=True)
    os.replace(staged, final)
    return os.path.join(final, os.path.basename(mesh))


def reconstruct(photo_dir, photos, work_dir, res, log, run, error_cls):
    """The scan at resolution res (low, mid, high or max), with what it used: (mesh, {"res", "px"})."""
    if not available():
        raise error_cls(i18n.tr("srv.pgw_missing"))
    sizes = _photo_sizes(photo_dir, photos)
    cfg = RESOLUTIONS.get(res)
    if res == "max" and not _cached(work_dir, CACHE_NAMES[res]):
        free = _free_memory()
        cfg = _max_config(sizes, free)
        gb = f"{free / 2 ** 30:.1f}" if free else "?"
        if cfg is None:  # the same scan as high: its cache serves
            res, cfg = "high", RESOLUTIONS["high"]
            log(i18n.tr("srv.pgw_max_as_high", gb=gb))
        else:
            log(i18n.tr("srv.pgw_max", px=cfg["max_image"], native=max(max(s) for s in sizes), gb=gb))
    name = CACHE_NAMES[res]
    cached = _cached(work_dir, name)
    if cached:
        log(i18n.tr("srv.pg_cached", detail=res))
        return cached, {"res": res, "px": _scan_px(cached) or (_dense_px(sizes, cfg) if cfg else None)}
    w = _ascii_workspace(work_dir, name)
    root = None if w else _public_root()
    w = w or os.path.join(root, f"colmap_{name}")
    try:
        px = _dense_px(sizes, cfg)
        return _reconstruct(photo_dir, photos, work_dir, name, cfg, px, log, run, error_cls, w), {"res": res, "px": px}
    finally:  # converted photos and depth maps: several hundred MB, and private
        shutil.rmtree(root or w, ignore_errors=True)


def _reconstruct(photo_dir, photos, work_dir, name, cfg, px, log, run, error_cls, w):
    shutil.rmtree(w, ignore_errors=True)
    images, sparse, dense = (os.path.join(w, d) for d in ("images", "sparse", "dense"))
    os.makedirs(sparse)  # the mapper needs it to exist
    cameras = _stage(photo_dir, photos, images)
    db = os.path.join(w, "database.db")
    env = {**os.environ, "QT_PLUGIN_PATH": os.path.join(pl.TOOLS, "colmap", "plugins")}
    t0 = time.time()

    def tool_log(tool):
        # OpenMVS writes its messages to <tool>-<id>.log in the workspace, which goes at the end, not to the console
        logs = sorted(glob.glob(os.path.join(w, f"{tool}-*.log")), key=os.path.getmtime)
        if logs:
            with open(logs[-1], encoding="utf-8", errors="replace") as f:
                for line in f.read().splitlines()[-15:]:
                    log(f"  {tool} : {line}")

    def step(what, cmd):
        code, _ = run(cmd, log, cwd=w, env=env, low_priority=True)
        if code != 0:
            tool_log(os.path.splitext(os.path.basename(cmd[0]))[0])
            raise error_cls(i18n.tr("srv.pgw_step_failed", step=what, advice=_advice(len(photos))))

    log(i18n.tr("srv.pgw_start", n=len(photos), cameras=cameras, px=px))
    sift = cfg.get("sift", cfg["max_image"])
    threads, free = _sift_threads(photo_dir, photos, sift)
    if threads:
        log(i18n.tr("srv.pgw_threads", n=threads, cores=os.cpu_count(), gb=f"{free / 2 ** 30:.1f}"))
    step(i18n.tr("srv.pgw_step_features"),
         [colmap(), "feature_extractor", "--database_path", db, "--image_path", images,
          "--ImageReader.single_camera_per_folder", "1", "--FeatureExtraction.use_gpu", "0",
          "--FeatureExtraction.max_image_size", str(sift),
          *(["--FeatureExtraction.num_threads", str(threads)] if threads else [])])
    step(i18n.tr("srv.pgw_step_matching"),
         [colmap(), "exhaustive_matcher", "--database_path", db, "--FeatureMatching.use_gpu", "0"])
    step(i18n.tr("srv.pgw_step_mapping"),
         [colmap(), "mapper", "--database_path", db, "--image_path", images, "--output_path", sparse])
    model = _largest_model(sparse)
    if not model:
        raise error_cls(i18n.tr("srv.pgw_not_placed", advice=_advice(len(photos))))
    log(i18n.tr("srv.pgw_placed", n=_registered(model), total=len(photos)))
    poses = os.path.join(w, "poses")
    os.makedirs(poses)
    step(i18n.tr("srv.pgw_step_read_poses"),
         [colmap(), "model_converter", "--input_path", model, "--output_path", poses, "--output_type", "TXT"])
    orient = orientation(os.path.join(poses, "images.txt"))
    step(i18n.tr("srv.pgw_step_undistort"),
         [colmap(), "image_undistorter", "--image_path", images, "--input_path", model, "--output_path", dense,
          "--output_type", "COLMAP", "--max_image_size", str(cfg["max_image"])])
    scene = os.path.join(w, "scene.mvs")
    step(i18n.tr("srv.pgw_step_import"), [openmvs("InterfaceCOLMAP"), "-w", w, "-i", dense, "-o", scene])
    step(i18n.tr("srv.pgw_step_densify"),
         [openmvs("DensifyPointCloud"), "-w", w, "-i", scene, "--resolution-level", str(cfg["resolution_level"]),
          "--max-resolution", str(cfg.get("max_resolution", 2560)), "--tower-mode", "0"])
    step(i18n.tr("srv.pgw_step_mesh"),
         [openmvs("ReconstructMesh"), "-w", w, "-i", os.path.join(w, "scene_dense.mvs"),
          "-p", os.path.join(w, "scene_dense.ply")])
    mesh = os.path.join(w, "scene_dense_mesh.ply")
    if not os.path.exists(mesh):
        raise error_cls(i18n.tr("srv.pgw_no_mesh", advice=_advice(len(photos))))
    # the photos' colors on the mesh, for the colored preview; a failure only loses the colors.
    # As in OpenMVS's own pipeline: the dense scene (cameras, images) plus, apart, the mesh to texture.
    # Seam leveling off: in 2.4.0 it samples 8-bit images as floats and turns the faces black (OpenMVS issue #1257,
    # fixed on develop only). The colors end on the vertices of the printable mesh, where seams barely show.
    code, _ = run([openmvs("TextureMesh"), "-w", w, "-i", os.path.join(w, "scene_dense.mvs"), "-m", mesh,
                   "-o", os.path.join(w, "scene_texture.mvs"), "--export-type", "obj", "--empty-color", str(UNSEEN),
                   "--resolution-level", str(cfg["resolution_level"]), "--max-texture-size", str(cfg["texture"]),
                   "--global-seam-leveling", "0", "--local-seam-leveling", "0"],
                  log, cwd=w, env=env, low_priority=True)
    textured = [p for p in glob.glob(os.path.join(w, "scene_texture*")) if not p.endswith((".mvs", ".log"))]
    tool_log("TextureMesh")  # how many views and faces it textured
    if code != 0 or not any(p.endswith(".obj") for p in textured):
        log(i18n.tr("srv.pgw_no_texture", code=code))
        textured = [mesh]
    # OpenMVS's own logs stay with the scan, for a diagnosis after the workspace is gone
    out = _publish(work_dir, name, textured + glob.glob(os.path.join(w, "*.log")), orient, px)
    log(i18n.tr("srv.pg_done", s=f"{time.time() - t0:.0f}"))
    return out


def _registered(model):
    # images.bin starts with the number of placed photos (uint64, little endian), whatever their point counts
    with open(os.path.join(model, "images.bin"), "rb") as f:
        head = f.read(8)
    return struct.unpack("<Q", head)[0] if len(head) == 8 else 0


def _largest_model(sparse):
    # the mapper may split the photos into several models: keep the one that placed the most
    models = [d for d in glob.glob(os.path.join(sparse, "*")) if os.path.exists(os.path.join(d, "images.bin"))]
    return max(models, key=_registered, default=None)


def _advice(n):
    return i18n.tr("srv.pgw_advice", n=n)
