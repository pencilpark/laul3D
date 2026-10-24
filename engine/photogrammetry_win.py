"""Windows photogrammetry, in place of Apple Object Capture: COLMAP finds the cameras, OpenMVS builds the mesh.

Both are installed by setup_tools under DATA/tools (colmap, openmvs) and run on the CPU. Commands and options are
those of COLMAP 4.2.1 and OpenMVS 2.4.0.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import time

import numpy as np
from PIL import Image, ImageOps

import pipeline as pl

COLMAP_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
ORIENTATION, MAKE, MODEL, EXIF_IFD, FOCAL, FOCAL_35MM = 0x0112, 0x010F, 0x0110, 0x8769, 0x920A, 0xA405
# CPU time grows fast with image size: the levels follow Object Capture's preview / medium / full
LEVELS = {"lowpoly": {"max_image": 1600, "resolution_level": 2},
          "medium": {"max_image": 2000, "resolution_level": 1},
          "detailed": {"max_image": 3200, "resolution_level": 1}}


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


def _workspace(work_dir, level):
    """(workspace, private root to create or None). COLMAP and OpenMVS read their arguments in the Windows code page,
    so the workspace keeps a plain ASCII path; the last resort is the shared Public folder, made private."""
    name = f"colmap_{level}"
    if work_dir.isascii():
        return os.path.join(work_dir, name), None
    short = _short_path(work_dir)
    if short and short.isascii():
        return os.path.join(short, name), None
    root = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "BerriaCraft",
                        hashlib.sha1(work_dir.encode("utf-8")).hexdigest()[:12])
    return os.path.join(root, name), root


def _private_dir(path):
    """Only the current account and Windows itself may open the folder (other accounts can read Public)."""
    os.makedirs(path, exist_ok=True)
    who = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, creationflags=pl.NO_WINDOW).stdout
    sid = re.search(rb"S-1-[0-9-]+", who)
    if not sid:
        raise RuntimeError("compte Windows introuvable pour protéger le dossier de travail")
    r = subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", f"*{sid.group().decode()}:(OI)(CI)F",
                        "*S-1-5-18:(OI)(CI)F"], capture_output=True, creationflags=pl.NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"le dossier de travail n'a pas pu être protégé (icacls, code {r.returncode})")


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


def _cached(work_dir, level):
    # the folder only appears complete (see _publish): mesh, its textures and its orientation together
    folder = os.path.join(work_dir, f"scan_{level}")
    found = glob.glob(os.path.join(folder, "*.obj")) + glob.glob(os.path.join(folder, "*.ply"))
    return found[0] if found and os.path.exists(found[0] + ".orient.json") else None


def _publish(work_dir, level, files, orient):
    """Moves the result into scan_<level> in one step, so an interruption never leaves a partial cache."""
    final = os.path.join(work_dir, f"scan_{level}")
    staged = final + ".partial"
    shutil.rmtree(staged, ignore_errors=True)
    os.makedirs(staged)
    for p in files:  # the .obj names its .mtl, which names the textures: they move together
        shutil.move(p, staged)
    mesh = next(p for p in glob.glob(os.path.join(staged, "*")) if p.endswith((".obj", ".ply")))
    with open(mesh + ".orient.json", "w", encoding="utf-8") as f:  # read by blender_prep: COLMAP axes, then this rotation
        json.dump({"matrix": orient, "raw_axes": True}, f)
    shutil.rmtree(final, ignore_errors=True)
    os.replace(staged, final)
    return os.path.join(final, os.path.basename(mesh))


def reconstruct(photo_dir, photos, work_dir, level, log, run, error_cls):
    if not available():
        raise error_cls("La photogrammétrie n'est pas encore installée : clique « Plusieurs photos : installer » en haut "
                        "de la fenêtre, ou passe le moteur en IA (une seule photo).")
    cached = _cached(work_dir, level)
    if cached:
        log(f"reconstruction {level} déjà en cache")
        return cached
    w, private_root = _workspace(work_dir, level)
    try:
        if private_root:
            _private_dir(private_root)
        return _reconstruct(photo_dir, photos, work_dir, level, log, run, error_cls, w)
    finally:  # converted photos and depth maps: several hundred MB, and private
        shutil.rmtree(w, ignore_errors=True)
        if private_root:
            try:
                os.rmdir(private_root)  # only once empty: another level of the project may still be running
            except OSError:
                pass


def _reconstruct(photo_dir, photos, work_dir, level, log, run, error_cls, w):
    cfg = LEVELS[level]
    shutil.rmtree(w, ignore_errors=True)
    images, sparse, dense = (os.path.join(w, d) for d in ("images", "sparse", "dense"))
    os.makedirs(sparse)  # the mapper needs it to exist
    cameras = _stage(photo_dir, photos, images)
    db = os.path.join(w, "database.db")
    env = {**os.environ, "QT_PLUGIN_PATH": os.path.join(pl.TOOLS, "colmap", "plugins")}
    t0 = time.time()

    def step(what, cmd):
        code, _ = run(cmd, log, cwd=w, env=env)
        if code != 0:
            raise error_cls(f"La photogrammétrie a échoué ({what}). " + _advice(len(photos)))

    log(f"COLMAP + OpenMVS : {len(photos)} photos, {cameras} réglage(s) d'appareil, niveau {level}")
    step("points communs", [colmap(), "feature_extractor", "--database_path", db, "--image_path", images,
                            "--ImageReader.single_camera_per_folder", "1", "--FeatureExtraction.use_gpu", "0",
                            "--FeatureExtraction.max_image_size", str(cfg["max_image"])])
    step("appariement", [colmap(), "exhaustive_matcher", "--database_path", db, "--FeatureMatching.use_gpu", "0"])
    step("position des photos", [colmap(), "mapper", "--database_path", db, "--image_path", images, "--output_path", sparse])
    model = _largest_model(sparse)
    if not model:
        raise error_cls("La photogrammétrie n'a pas pu placer les photos. " + _advice(len(photos)))
    log(f"{_registered(model)} photos placées sur {len(photos)}")
    poses = os.path.join(w, "poses")
    os.makedirs(poses)
    step("lecture des positions", [colmap(), "model_converter", "--input_path", model, "--output_path", poses, "--output_type", "TXT"])
    orient = orientation(os.path.join(poses, "images.txt"))
    step("correction des photos", [colmap(), "image_undistorter", "--image_path", images, "--input_path", model,
                                   "--output_path", dense, "--output_type", "COLMAP", "--max_image_size", str(cfg["max_image"])])
    scene = os.path.join(w, "scene.mvs")
    step("import OpenMVS", [openmvs("InterfaceCOLMAP"), "-w", w, "-i", dense, "-o", scene])
    step("nuage de points", [openmvs("DensifyPointCloud"), "-w", w, "-i", scene, "--resolution-level", str(cfg["resolution_level"]),
                             "--max-resolution", "2560", "--tower-mode", "0"])
    step("maillage", [openmvs("ReconstructMesh"), "-w", w, "-i", os.path.join(w, "scene_dense.mvs"),
                      "-p", os.path.join(w, "scene_dense.ply")])
    mesh = os.path.join(w, "scene_dense_mesh.ply")
    if not os.path.exists(mesh):
        raise error_cls("La photogrammétrie n'a pas produit de maillage. " + _advice(len(photos)))
    # the photos' colors on the mesh, for the colored preview; a failure only loses the colors
    code, _ = run([openmvs("TextureMesh"), "-w", w, "-i", os.path.join(w, "scene_dense_mesh.mvs"),
                   "-o", os.path.join(w, "scene_texture.mvs"), "--export-type", "obj",
                   "--resolution-level", str(cfg["resolution_level"]), "--max-texture-size", "4096"], log, cwd=w, env=env)
    textured = [p for p in glob.glob(os.path.join(w, "scene_texture*")) if not p.endswith((".mvs", ".log"))]
    if code != 0 or not any(p.endswith(".obj") for p in textured):
        log("texture des photos indisponible : le modèle reste sans couleurs")
        textured = [mesh]
    out = _publish(work_dir, level, textured, orient)
    log(f"reconstruction terminée en {time.time() - t0:.0f} s")
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
    return (f"Avec {n} photos, vise 50 ou plus : tour complet, environ 70 % de recouvrement, deux ou trois hauteurs, "
            "sujet immobile, lumière égale. Ou passe le moteur en IA (une seule photo).")
