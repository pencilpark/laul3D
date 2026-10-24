"""Windows photogrammetry, in place of Apple Object Capture: COLMAP finds the cameras, OpenMVS builds the mesh.

Both are installed by setup_tools under DATA/tools (colmap, openmvs) and run on the CPU. Commands and options are
those of COLMAP 4.2.1 and OpenMVS 2.4.0.
"""
import glob
import hashlib
import os
import shutil
import time

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


def reconstruct(photo_dir, photos, work_dir, level, log, run, stage_photos, error_cls):
    if not available():
        raise error_cls("La photogrammétrie n'est pas encore installée : clique « Plusieurs photos : installer » en haut "
                        "de la fenêtre, ou passe le moteur en IA (une seule photo).")
    out = os.path.join(work_dir, f"scan_{level}.ply")
    if os.path.exists(out):
        log(f"reconstruction {level} déjà en cache")
        return out
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
    shutil.move(mesh, out)
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
