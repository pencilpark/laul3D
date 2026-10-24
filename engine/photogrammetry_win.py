"""Windows photogrammetry, in place of Apple Object Capture: COLMAP finds the cameras, OpenMVS builds the mesh.

Both are installed by setup_tools under DATA/tools (colmap, openmvs) and run on the CPU. Commands and options are
those of COLMAP 4.2.1 and OpenMVS 2.4.0.
"""
import glob
import hashlib
import json
import os
import shutil
import time

import numpy as np

import pipeline as pl

COLMAP_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
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
    # COLMAP and OpenMVS read their arguments in the Windows code page: their workspace keeps a plain ASCII path
    name = f"colmap_{level}"
    if work_dir.isascii():
        return os.path.join(work_dir, name)
    short = _short_path(work_dir)
    if short and short.isascii():
        return os.path.join(short, name)
    key = hashlib.sha1(work_dir.encode("utf-8")).hexdigest()[:12]
    return os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "BerriaCraft", key, name)


def _stage(photo_dir, photos, images, stage_photos):
    stage_photos(photo_dir, photos, images, COLMAP_EXT)
    for i, name in enumerate(sorted(os.listdir(images)), 1):
        os.replace(os.path.join(images, name), os.path.join(images, f"img_{i:04d}{os.path.splitext(name)[1].lower()}"))


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
    front = min(poses)[2] - middle
    front -= up * front.dot(up)
    if np.linalg.norm(front) < 1e-9:
        front = np.cross(up, [1.0, 0.0, 0.0] if abs(up[0]) < 0.9 else [0.0, 1.0, 0.0])
    front /= np.linalg.norm(front)
    y, z = -front, up
    return np.stack([np.cross(y, z), y, z]).tolist()


def _cached(work_dir, level):
    found = glob.glob(os.path.join(work_dir, f"scan_{level}", "*.obj")) + glob.glob(os.path.join(work_dir, f"scan_{level}.ply"))
    return found[0] if found else None


def reconstruct(photo_dir, photos, work_dir, level, log, run, stage_photos, error_cls):
    if not available():
        raise error_cls("La photogrammétrie n'est pas encore installée : clique « Plusieurs photos : installer » en haut "
                        "de la fenêtre, ou passe le moteur en IA (une seule photo).")
    cached = _cached(work_dir, level)
    if cached:
        log(f"reconstruction {level} déjà en cache")
        return cached
    cfg = LEVELS[level]
    w = _workspace(work_dir, level)
    shutil.rmtree(w, ignore_errors=True)
    images, sparse, dense = (os.path.join(w, d) for d in ("images", "sparse", "dense"))
    os.makedirs(sparse)  # the mapper needs it to exist
    _stage(photo_dir, photos, images, stage_photos)
    db = os.path.join(w, "database.db")
    env = {**os.environ, "QT_PLUGIN_PATH": os.path.join(pl.TOOLS, "colmap", "plugins")}
    t0 = time.time()

    def step(what, cmd):
        code, _ = run(cmd, log, cwd=w, env=env)
        if code != 0:
            raise error_cls(f"La photogrammétrie a échoué ({what}). " + _advice(len(photos)))

    log(f"COLMAP + OpenMVS : {len(photos)} photos, niveau {level}")
    step("points communs", [colmap(), "feature_extractor", "--database_path", db, "--image_path", images,
                            "--ImageReader.single_camera", "1", "--FeatureExtraction.use_gpu", "0",
                            "--FeatureExtraction.max_image_size", str(cfg["max_image"])])
    step("appariement", [colmap(), "exhaustive_matcher", "--database_path", db, "--FeatureMatching.use_gpu", "0"])
    step("position des photos", [colmap(), "mapper", "--database_path", db, "--image_path", images, "--output_path", sparse])
    model = _largest_model(sparse)
    if not model:
        raise error_cls("La photogrammétrie n'a pas pu placer les photos. " + _advice(len(photos)))
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
    if code == 0 and any(p.endswith(".obj") for p in textured):
        folder = os.path.join(work_dir, f"scan_{level}")
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
        for p in textured:  # the .obj names its .mtl, which names the textures: they move together
            shutil.move(p, folder)
        out = next(p for p in glob.glob(os.path.join(folder, "*.obj")))
    else:
        log("texture des photos indisponible : le modèle reste sans couleurs")
        out = os.path.join(work_dir, f"scan_{level}.ply")
        shutil.move(mesh, out)
    # read by blender_prep: COLMAP coordinates as they are, then this rotation
    with open(out + ".orient.json", "w", encoding="utf-8") as f:
        json.dump({"matrix": orient, "raw_axes": True}, f)
    shutil.rmtree(w, ignore_errors=True)  # undistorted photos and depth maps: several hundred MB
    log(f"reconstruction terminée en {time.time() - t0:.0f} s")
    return out


def _largest_model(sparse):
    # the mapper may split the photos into several models: keep the one that placed the most
    models = [d for d in glob.glob(os.path.join(sparse, "*")) if os.path.exists(os.path.join(d, "images.bin"))]
    return max(models, key=lambda d: os.path.getsize(os.path.join(d, "images.bin")), default=None)


def _advice(n):
    return (f"Avec {n} photos, vise 50 ou plus : tour complet, environ 70 % de recouvrement, deux ou trois hauteurs, "
            "sujet immobile, lumière égale. Ou passe le moteur en IA (une seule photo).")
