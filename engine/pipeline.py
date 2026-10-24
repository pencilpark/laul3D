"""Photos -> raw mesh (Object Capture / COLMAP+OpenMVS / TripoSR) -> printable STL (headless Blender)."""
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata

import numpy as np
from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
PYTHON = sys.executable
DATA = os.environ.get("LOWPOLY_DATA", os.path.join(ROOT, "data"))

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp"}
OBJECT_CAPTURE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
MIN_PHOTOGRAMMETRY = 20
# LowPoly -> detailed: Object Capture detail used to feed each level
PG_DETAIL = {"lowpoly": "preview", "medium": "medium", "detailed": "full"}
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0


class PipelineError(Exception):
    pass


def slug(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip())[:40].strip("_")
    return s or "modele"


def _first_existing(paths):
    return next((p for p in paths if p and os.path.exists(p)), None)


TOOLS = os.path.join(DATA, "tools")  # what the app installs itself (setup_tools)


def blender_path():
    env = os.environ.get("LOWPOLY_BLENDER")
    if env:
        return env
    if IS_MAC:
        return _first_existing(["/Applications/Blender.app/Contents/MacOS/Blender",
                                os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
                                os.path.join(TOOLS, "Blender.app", "Contents", "MacOS", "Blender")])
    if IS_WIN:
        found = sorted(glob.glob(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                              "Blender Foundation", "Blender*", "blender.exe")))
        return found[-1] if found else _first_existing([os.path.join(TOOLS, "blender", "blender.exe")])
    return shutil.which("blender")


def orca_path():
    env = os.environ.get("LOWPOLY_ORCA")
    if env:
        return env
    if IS_MAC:
        return _first_existing(["/Applications/OrcaSlicer.app", os.path.expanduser("~/Applications/OrcaSlicer.app")])
    if IS_WIN:
        return _first_existing([os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "OrcaSlicer", "orca-slicer.exe"),
                                os.path.join(TOOLS, "OrcaSlicer", "orca-slicer.exe")])
    return shutil.which("orca-slicer")


def object_capture_path():
    return os.environ.get("LOWPOLY_PHOTOGRAMMETRY") or _first_existing([os.path.expanduser("~/.local/bin/HelloPhotogrammetry")])


def local_model_env():
    """Model files installed by the app (setup_ai) under DATA/models, as the variables triposr_infer reads."""
    m = os.path.join(DATA, "models")
    env = {}
    if all(os.path.exists(os.path.join(m, "triposr", f)) for f in ("model.ckpt", "config.yaml")):
        env["LOWPOLY_TRIPOSR_WEIGHTS"] = os.path.join(m, "triposr")
    if os.path.exists(os.path.join(m, "dino-vitb16", "config.json")):
        env["LOWPOLY_DINO_CONFIG"] = os.path.join(m, "dino-vitb16", "config.json")
    if os.path.exists(os.path.join(m, "u2net", "u2net.onnx")):
        env["U2NET_HOME"] = os.path.join(m, "u2net")
    return env


def triposr_weights():
    local = os.environ.get("LOWPOLY_TRIPOSR_WEIGHTS") or local_model_env().get("LOWPOLY_TRIPOSR_WEIGHTS")
    if local and os.path.exists(os.path.join(local, "model.ckpt")):
        return local
    return None


def tools_status():
    import photogrammetry_win
    weights_cached = triposr_weights() is not None or os.path.isdir(
        os.path.expanduser("~/.cache/huggingface/hub/models--stabilityai--TripoSR"))
    if IS_MAC:
        pg = bool(object_capture_path()) and os.access(object_capture_path(), os.X_OK)
    else:
        pg = photogrammetry_win.available()
    return {
        "platform": "mac" if IS_MAC else "windows" if IS_WIN else "linux",
        "blender": bool(blender_path()) and os.path.exists(blender_path()),
        "photogrammetry": pg,
        "photogrammetry_engine": "Object Capture" if IS_MAC else "COLMAP + OpenMVS",
        "ia": os.path.exists(os.path.join(ROOT, "vendor", "TripoSR", "tsr")) and importlib.util.find_spec("torch") is not None,
        "triposr_weights_cached": weights_cached,
        "orcaslicer": bool(orca_path()),
    }


def sharpness(img):
    g = np.asarray(img.convert("L").resize((640, max(1, int(640 * img.height / img.width)))), dtype=np.float32)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def scan_photos(photo_dir, thumb_dir):
    os.makedirs(thumb_dir, exist_ok=True)
    photos = []
    for name in sorted(os.listdir(photo_dir)):
        if os.path.splitext(name)[1].lower() not in IMAGE_EXT:
            continue
        path = os.path.join(photo_dir, name)
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                score = sharpness(im)
                thumb = im.convert("RGB")
                thumb.thumbnail((320, 320))
                thumb_name = name + ".jpg"
                thumb.save(os.path.join(thumb_dir, thumb_name), quality=85)
                photos.append({"name": name, "thumb": thumb_name, "sharpness": round(score, 1),
                               "size": [im.width, im.height]})
        except Exception as e:
            photos.append({"name": name, "error": f"illisible : {e}"})
    return photos


def choose_engine(mode, n_ok, tools):
    if mode == "photogrammetry":
        if not tools["photogrammetry"]:
            raise PipelineError(f"{tools['photogrammetry_engine']} n'est pas installé : ouvre l'assistant d'installation ou passe en mode IA.")
        return mode
    if mode == "ia":
        if not tools["ia"]:
            raise PipelineError("Le module « Une photo (IA) » n'est pas encore installé : clique « Une photo (IA) : installer » en haut de la fenêtre.")
        return mode
    if n_ok >= MIN_PHOTOGRAMMETRY and tools["photogrammetry"]:
        return "photogrammetry"
    if tools["ia"]:
        return "ia"
    if tools["photogrammetry"]:
        # photogrammetry on a handful of photos fails after a long run: say so now
        raise PipelineError(f"Avec {n_ok} photo{'s' if n_ok > 1 else ''}, il faut le module « Une photo (IA) », pas encore installé : "
                            f"clique « Une photo (IA) : installer » en haut de la fenêtre. Sinon, ajoute des photos : au moins "
                            f"{MIN_PHOTOGRAMMETRY}, et 50 ou plus pour un buste fidèle.")
    raise PipelineError("Aucun moteur de reconstruction n'est installé : ouvre l'assistant d'installation.")


def select_sharp(photos, keep_min=MIN_PHOTOGRAMMETRY):
    ok = [p for p in photos if "error" not in p]
    if len(ok) <= keep_min:
        return ok, []
    median = float(np.median([p["sharpness"] for p in ok]))
    keep = [p for p in ok if p["sharpness"] >= 0.35 * median]
    if len(keep) < keep_min:
        keep = sorted(ok, key=lambda p: p["sharpness"], reverse=True)[:keep_min]
    dropped = [p["name"] for p in ok if p not in keep]
    return keep, dropped


def run(cmd, log, cwd=None, env=None):
    log(f"$ {os.path.basename(cmd[0])} {' '.join(cmd[1:])}")
    env = dict(env or os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=NO_WINDOW)
    lines = []
    for line in proc.stdout:
        line = line.rstrip()
        if not line or "Warning (secondary thread)" in line or "FutureWarning" in line:
            continue
        lines.append(line)
        log(line)
    proc.wait()
    return proc.returncode, lines


def stage_photos(photo_dir, photos, dest, allowed_ext):
    """Hard-link usable photos into dest, converting other formats to new JPEG names (never over a link)."""
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    used = set()
    for p in photos:
        src = os.path.join(photo_dir, p["name"])
        stem, ext = os.path.splitext(p["name"])
        if ext.lower() in allowed_ext:
            target = os.path.join(dest, p["name"])
            try:
                os.link(src, target)
            except OSError:
                shutil.copy2(src, target)
            used.add(p["name"].lower())
            continue
        name, i = f"{stem}_conv.jpg", 1
        while name.lower() in used:
            name, i = f"{stem}_conv{i}.jpg", i + 1
        used.add(name.lower())
        with Image.open(src) as im:
            ImageOps.exif_transpose(im).convert("RGB").save(os.path.join(dest, name), quality=95)


def object_capture(photo_dir, photos, work_dir, level, log):
    detail = PG_DETAIL[level]
    out = os.path.join(work_dir, f"scan_{detail}.usdz")
    if os.path.exists(out):
        log(f"reconstruction {detail} déjà en cache")
        return out
    keep, dropped = select_sharp(photos)
    if dropped:
        log(f"{len(dropped)} photo(s) floue(s) écartée(s) : {', '.join(dropped)}")
    src = os.path.join(work_dir, "pg_input")
    stage_photos(photo_dir, keep, src, OBJECT_CAPTURE_EXT)
    tmp = os.path.join(work_dir, f"scan_{detail}.partial.usdz")
    for sensitivity in ("normal", "high"):
        log(f"Object Capture : {len(keep)} photos, détail {detail}, sensibilité {sensitivity}")
        t0 = time.time()
        if os.path.exists(tmp):
            os.remove(tmp)
        code, _ = run([object_capture_path(), src, tmp, "-d", detail, "-f", sensitivity], log)
        if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, out)
            log(f"reconstruction terminée en {time.time() - t0:.0f} s")
            return out
        log(f"échec (code {code})")
    if os.path.exists(tmp):
        os.remove(tmp)
    raise PipelineError(
        "La photogrammétrie n'a pas pu reconstruire l'objet. Ajoute des photos (50 ou plus, tour complet, "
        "environ 70 % de recouvrement, deux ou trois hauteurs, sujet immobile, lumière égale) "
        "ou passe le moteur en IA (une seule photo).")


def photogrammetry(photo_dir, photos, work_dir, level, log):
    if IS_MAC:
        return object_capture(photo_dir, photos, work_dir, level, log)
    import photogrammetry_win
    keep, dropped = select_sharp(photos)
    if dropped:
        log(f"{len(dropped)} photo(s) floue(s) écartée(s) : {', '.join(dropped)}")
    return photogrammetry_win.reconstruct(photo_dir, keep, work_dir, level, log, run, stage_photos, PipelineError)


def prepare_main_image(photo_dir, name, work_dir):
    with Image.open(os.path.join(photo_dir, name)) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        im.thumbnail((1024, 1024))
        if im.mode == "RGB":
            im = ImageOps.autocontrast(im, cutoff=1)
        out = os.path.join(work_dir, "main_input.png")
        im.save(out)
    return out


def triposr(photo_dir, photos, main_photo, work_dir, log):
    out = os.path.join(work_dir, "triposr.obj")
    marker = os.path.join(work_dir, "triposr_source.txt")
    ok = [p for p in photos if "error" not in p]
    if not ok:
        raise PipelineError("aucune photo lisible")
    name = main_photo if any(p["name"] == main_photo for p in ok) else max(ok, key=lambda p: p["sharpness"])["name"]
    if os.path.exists(out) and os.path.exists(marker):
        with open(marker, encoding="utf-8") as f:
            if f.read() == name:
                log(f"reconstruction IA de {name} déjà en cache")
                return out, name
    image = prepare_main_image(photo_dir, name, work_dir)
    note = "" if triposr_weights() else " (premier lancement : téléchargement des poids depuis Hugging Face)"
    log(f"IA TripoSR sur {name}{note}")
    tmp = os.path.join(work_dir, "triposr.partial.obj")
    # variables set explicitly (dev, CI) win over the models installed by the app
    env = {**local_model_env(), **os.environ}
    code, lines = run([PYTHON, os.path.join(ROOT, "engine", "triposr_infer.py"), image, tmp,
                       "--preprocessed-out", os.path.join(work_dir, "main_detoure.png")], log, env=env)
    if code != 0 or not os.path.exists(tmp):
        raise PipelineError("TripoSR a échoué : " + (lines[-1] if lines else f"code {code}"))
    os.replace(tmp, out)
    with open(marker, "w", encoding="utf-8") as f:
        f.write(name)
    return out, name


def blender_prep(raw, out_dir, name, level, s, log):
    blender = blender_path()
    if not blender or not os.path.exists(blender):
        raise PipelineError("Blender est introuvable : ouvre l'assistant d'installation.")
    script = os.path.join(ROOT, "engine", "blender_lowpoly.py")
    base = [blender, "-b", "--factory-startup", "--python-exit-code", "1", "-P", script, "--"]
    engine = "cycles" if os.environ.get("LOWPOLY_PREVIEW_ENGINE") == "cycles" else "workbench"
    cmd = base + ["--input", raw, "--outdir", out_dir, "--name", name, "--level", level,
                  "--height-mm", str(s["height_mm"]), "--base-cut", str(s["base_cut"] / 100.0),
                  "--rot-seq", s.get("rot_seq") or "-", "--nozzle", str(s["nozzle"]), "--previews",
                  "--preview-engine", engine, "--save-blend"]
    if level == "lowpoly" and s.get("faces"):
        cmd += ["--faces", str(int(s["faces"]))]
    if s.get("keep_parts"):
        cmd += ["--keep-parts"]
    code, lines = run(cmd, log)
    report = next((json.loads(l[7:]) for l in lines if l.startswith("REPORT ")), None)
    if report is None:
        fatal = next((l[6:] for l in reversed(lines) if l.startswith("FATAL ")), None)
        if fatal:
            try:
                fatal = json.loads(fatal)
            except ValueError:
                pass
        raise PipelineError("Blender a échoué : " + (fatal or f"code {code}"))
    previews = next((json.loads(l[9:]) for l in lines if l.startswith("PREVIEWS ")), None)
    if code != 0 or previews is None:
        # REPORT comes before the views: only the viewport renderer died (typically no OpenGL),
        # the model is safe; retry the views with Cycles on the CPU
        log("Aperçus indisponibles avec le rendu rapide : nouvel essai en rendu CPU.")
        code, lines = run(base + ["--previews-only", "--input", report["stl"], "--outdir", out_dir,
                                  "--name", name, "--preview-engine", "cycles"], log)
        previews = next((json.loads(l[9:]) for l in lines if l.startswith("PREVIEWS ")), None) if code == 0 else None
        if not previews:
            log("Aperçus indisponibles : le modèle reste utilisable.")
    report["previews"] = previews or []
    return report


def downloads_dir():
    d = os.environ.get("LOWPOLY_DOWNLOADS") or os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(d, exist_ok=True)
    return d


def export_copy(path):
    dest_dir = downloads_dir()
    stem, ext = os.path.splitext(os.path.basename(path))
    dest, i = os.path.join(dest_dir, stem + ext), 2
    while os.path.exists(dest):
        dest, i = os.path.join(dest_dir, f"{stem} ({i}){ext}"), i + 1
    shutil.copy2(path, dest)
    return dest


def open_in_orca(stl):
    orca = orca_path()
    if not orca:
        raise PipelineError("OrcaSlicer est introuvable : ouvre l'assistant d'installation.")
    if IS_MAC:
        subprocess.Popen(["open", "-a", orca, stl])
    else:
        subprocess.Popen([orca, stl], creationflags=NO_WINDOW)


def reveal(path):
    if IS_MAC:
        subprocess.Popen(["open", "-R", path])
    elif IS_WIN:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])
