"""Local Berria Craft server: drop photos, get a printable STL. Started by the desktop app (or start.command)."""
import copy
import itertools
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import List, Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))
import i18n  # noqa: E402
import pipeline as pl  # noqa: E402
import setup_ai  # noqa: E402
import setup_tools  # noqa: E402

PROJECTS = os.environ.get("LOWPOLY_PROJECTS", os.path.join(ROOT, "projects"))
STATIC = os.path.join(ROOT, "app", "static")
LEVELS = ("lowpoly", "medium", "detailed")
MODES = ("auto", "photogrammetry", "ia")
DEFAULTS = {"height_mm": 80.0, "level": "lowpoly", "faces": 1000, "base_cut": 3.0,
            "rot_seq": "", "keep_parts": False, "nozzle": 0.4, "smooth": 0, "filaments": 4,
            "color_3mf": True, "color_obj": True, "color_texture": True,
            "export_software": False, "export_game": False, "export_web": False, "photo_res": "auto",
            "texture_size": "auto", "bake_samples": 4, "real_height_cm": 0.0, "relief": "auto", "finish": "auto",
            "web_images": "jpeg", "export_density": 1.0}
# baked textures and export profiles: the choices the interface offers, the first one as fallback
CHOICES = {"texture_size": ("auto", "1024", "2048", "4096", "8192"), "relief": ("auto", "scan", "solid"),
           "finish": ("auto", "matte", "satin", "gloss"), "web_images": ("jpeg", "webp")}
BAKE_SAMPLES = (1, 4, 16)
DENSITIES = (0.5, 1.0, 2.0, 4.0)
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

i18n.startup_language(pl.DATA)
app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC), name="static")
JOBS = {}
LOCK = threading.RLock()
TASKS = queue.Queue()


@app.middleware("http")
async def local_only(request: Request, call_next):
    # Host check blocks DNS rebinding; the custom header blocks cross-site form posts.
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if host not in ALLOWED_HOSTS:
        return JSONResponse(status_code=403, content={"detail": i18n.tr("srv.host_refused")})
    if request.method not in ("GET", "HEAD") and request.headers.get("x-lowpoly") != "1":
        return JSONResponse(status_code=403, content={"detail": i18n.tr("srv.request_refused")})
    return await call_next(request)


slug = pl.slug


def canonical_rot(seq):
    out = []
    for axis in str(seq or "").lower():
        if axis not in "xyz":
            continue
        out.append(axis)
        if len(out) >= 4 and len(set(out[-4:])) == 1:
            del out[-4:]
    return "".join(out)[-24:]


def clean_settings(raw, base=None):
    base = dict(DEFAULTS, **(base or {}))
    s = dict(base)
    s.update({k: v for k, v in (raw or {}).items() if k in DEFAULTS})

    def num(key, lo, hi, cast=float):
        try:
            value = cast(float(s[key]))
        except (TypeError, ValueError):
            value = cast(float(base[key]))
        return min(max(value, lo), hi)

    s["height_mm"] = num("height_mm", 10.0, 245.0)
    s["base_cut"] = num("base_cut", 0.0, 20.0)
    s["faces"] = num("faces", 100, 20000, int)
    s["nozzle"] = num("nozzle", 0.2, 1.0)
    s["smooth"] = num("smooth", 0, 3, int)
    s["filaments"] = num("filaments", 2, 8, int)
    s["rot_seq"] = canonical_rot(s["rot_seq"])
    for key in ("keep_parts", "color_3mf", "color_obj", "color_texture", "export_software", "export_game",
                "export_web"):
        s[key] = bool(s[key])
    if s["level"] not in LEVELS:
        s["level"] = "lowpoly"
    if s["photo_res"] not in pl.PHOTO_RES:
        s["photo_res"] = "auto"
    # 0: the exports keep the printed height
    real = num("real_height_cm", 0.0, 100000.0)
    s["real_height_cm"] = max(real, 0.1) if real > 0 else 0.0
    s["bake_samples"] = min(BAKE_SAMPLES, key=lambda v: abs(v - num("bake_samples", 1, 16, int)))
    s["export_density"] = min(DENSITIES, key=lambda v: abs(v - num("export_density", 0.5, 4.0)))
    for key, choices in CHOICES.items():
        s[key] = str(s[key]) if str(s[key]) in choices else choices[0]
    return s


def job_dir(jid):
    return os.path.join(PROJECTS, jid)


SAVE_SEQ = itertools.count(1)
SAVED = {}  # job id -> number of the snapshot on disk


def save(job):
    # the worker and request threads can save the same job at once: one temp file per
    # snapshot, and an older snapshot never replaces a newer one
    with LOCK:
        data = copy.deepcopy(job)
        seq = next(SAVE_SEQ)
    data["log"] = data["log"][-400:]
    path = os.path.join(job_dir(job["id"]), "job.json")
    tmp = f"{path}.{seq}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    with LOCK:
        if seq < SAVED.get(job["id"], 0):
            os.remove(tmp)
            return
        os.replace(tmp, path)
        SAVED[job["id"]] = seq


def safe_save(job, log=None):
    try:
        save(job)
    except Exception:
        (log or print)(i18n.tr("srv.save_failed") + "\n" + traceback.format_exc())


def logger(job):
    def log(line):
        with LOCK:
            job["log"].append(f"{datetime.now():%H:%M:%S}  {line}")
            if len(job["log"]) > 2000:
                del job["log"][:500]
    return log


def public(job, full=True):
    with LOCK:
        data = copy.deepcopy({k: v for k, v in job.items() if k != "log"})
        if full:
            data["log"] = job["log"][-250:]
    return data


def set_step(job, step):
    with LOCK:
        job["step"] = step


def process(job, level, log):
    with LOCK:
        if JOBS.get(job["id"]) is not job:  # deleted while queued
            return
        job.update(state="running", running_level=level, error=None, started=time.time())
    d = job_dir(job["id"])
    work = os.path.join(d, "work")
    os.makedirs(work, exist_ok=True)
    if not job.get("photos"):
        set_step(job, i18n.tr("srv.step_photos"))
        photos = pl.scan_photos(os.path.join(d, "photos"), os.path.join(d, "thumbs"))
        with LOCK:
            job["photos"] = photos
    n_ok = sum(1 for p in job["photos"] if "error" not in p)
    if n_ok == 0:
        raise pl.PipelineError(i18n.tr("srv.no_readable_photo"))
    engine = pl.choose_engine(job["mode"], n_ok, tools_now())
    with LOCK:
        job["engine"] = engine
    if engine == "photogrammetry" and n_ok < pl.MIN_PHOTOGRAMMETRY:
        log(i18n.tr("srv.few_photos", n=n_ok))
    safe_save(job, log)

    with LOCK:
        s = dict(job["settings"])
    main_photo, scan = None, None
    if engine == "photogrammetry":
        set_step(job, i18n.tr("srv.step_photogrammetry"))
        raw, scan = pl.photogrammetry(os.path.join(d, "photos"), job["photos"], work,
                                      pl.photo_res(level, s["photo_res"]), log)
    else:
        set_step(job, i18n.tr("srv.step_ai"))
        raw, main_photo = pl.triposr(os.path.join(d, "photos"), job["photos"], job.get("main_photo"), work, log)
        with LOCK:
            job["main_photo"] = main_photo

    set_step(job, i18n.tr("srv.step_blender"))
    version = int(time.time() * 1000)
    name = f"{slug(job['name'])}_{level}_{int(round(s['height_mm']))}mm"
    out = os.path.join(d, "export", level, str(version))
    try:
        report = pl.blender_prep(raw, out, name, level, s, log, scan and scan["res"])
    except Exception:
        shutil.rmtree(out, ignore_errors=True)
        raise
    rel = lambda p: os.path.relpath(os.path.join(out, os.path.basename(p)), d).replace(os.sep, "/")
    report["stl"] = rel(report["stl"])
    report["previews"] = [rel(p) for p in report.get("previews", [])]
    for key in ("colors", "filaments", "obj_colors", "texture", "export_software", "export_game", "export_web"):
        report[key] = rel(report[key]) if report.get(key) else None
    if scan:
        scan["path"] = os.path.relpath(raw, d).replace(os.sep, "/")
    report.update(settings=s, engine=engine, main_photo=main_photo, version=version, scan=scan)
    with LOCK:
        job["results"][level] = report
        job.update(state="done", step=i18n.tr("srv.step_done"), running_level=None)
    for old in os.listdir(os.path.join(d, "export", level)):
        if old != str(version):
            shutil.rmtree(os.path.join(d, "export", level, old), ignore_errors=True)
    log(i18n.tr("srv.stl_ready", path=report["stl"], dims=report["dimensions_mm"], triangles=report["triangles"]))


def worker():
    while True:
        jid, level = TASKS.get()
        job = JOBS.get(jid)
        if job is None:
            continue
        log = logger(job)
        try:
            process(job, level, log)
        except pl.PipelineError as e:
            with LOCK:
                job.update(state="error", error=str(e), running_level=None)
            log(i18n.tr("srv.error_line", error=e))
        except Exception as e:
            with LOCK:
                job.update(state="error", error=i18n.tr("srv.unexpected_error", error=e), running_level=None)
            log(traceback.format_exc())
        finally:
            if JOBS.get(jid) is job:
                safe_save(job, log)


def migrate(job):
    s = job.get("settings", {})
    if "rot_seq" not in s and "rot" in s:
        s["rot_seq"] = "".join(axis * (int(round(float(r) / 90)) % 4) for axis, r in zip("xyz", s.pop("rot")))
    job["settings"] = clean_settings(s)
    for r in job.get("results", {}).values():
        rs = r.get("settings", {})
        if "rot_seq" not in rs and "rot" in rs:
            rs["rot_seq"] = "".join(axis * (int(round(float(v) / 90)) % 4) for axis, v in zip("xyz", rs.pop("rot")))
    return job


TRASH = ".suppression"


def load_projects():
    os.makedirs(PROJECTS, exist_ok=True)
    for jid in sorted(os.listdir(PROJECTS)):
        if jid.endswith(TRASH):  # a deletion cut short when the app closed
            shutil.rmtree(os.path.join(PROJECTS, jid), ignore_errors=True)
            continue
        p = os.path.join(PROJECTS, jid, "job.json")
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                job = migrate(json.load(f))
        except Exception:
            print(i18n.tr("srv.project_unreadable", path=p) + "\n" + traceback.format_exc())
            continue
        if job.get("state") in ("running", "queued"):
            job.update(state="error", error=i18n.tr("srv.interrupted"), running_level=None)
        JOBS[jid] = job


@app.on_event("startup")
def startup():
    load_projects()
    threading.Thread(target=worker, daemon=True).start()


@app.get("/api/prefs")
def get_prefs():
    return {"language": i18n.language(), "languages": i18n.LANGUAGES}


@app.post("/api/prefs")
def set_prefs(body: dict = Body(...)):
    lang = body.get("language")
    if lang not in i18n.LANGUAGES:
        raise HTTPException(400, i18n.tr("srv.unknown_language"))
    i18n.save_language(pl.DATA, lang)
    os.environ["LOWPOLY_LANG"] = lang
    return get_prefs()


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-store"})


def tools_now():
    # the AI libraries land before the models: the module counts as installed once the installer has finished
    tools = pl.tools_status()
    tools["ia"] = tools["ia"] and not setup_ai.running()
    return tools


@app.get("/api/status")
def status():
    return {"tools": tools_now(), "tools_setup": setup_tools.snapshot(), "ai_install": setup_ai.snapshot(),
            "queue": TASKS.qsize(), "printer": {"name": "Creality Ender-3 V3", "bed_mm": [220, 220, 250]}}


@app.post("/api/setup/ai")
def install_ai():
    setup_ai.start()
    return setup_ai.snapshot()


@app.post("/api/setup/tools")
def install_tools(body: dict = Body(...)):
    setup_tools.start([str(t) for t in body.get("ids", [])])
    return setup_tools.snapshot()


@app.get("/api/jobs")
def list_jobs():
    with LOCK:
        jobs = sorted(JOBS.values(), key=lambda j: j["created"], reverse=True)
        return [public(j, full=False) for j in jobs]


@app.post("/api/jobs")
async def create_job(files: List[UploadFile] = File(...), name: str = Form("model"),
                     mode: str = Form("auto"), settings: str = Form("{}"), main_photo: Optional[str] = Form(None)):
    try:
        raw_settings = json.loads(settings or "{}")
    except ValueError:
        raise HTTPException(400, i18n.tr("srv.bad_settings"))
    with LOCK:
        base = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + slug(name)
        jid, i = base, 2
        while jid in JOBS or os.path.exists(job_dir(jid)):
            jid, i = f"{base}-{i}", i + 1
        pdir = os.path.join(job_dir(jid), "photos")
        os.makedirs(pdir)
    saved, chosen = [], None
    for up in files:
        original = os.path.basename(up.filename or "photo")
        stem, ext = os.path.splitext(original)
        if ext.lower() not in pl.IMAGE_EXT:
            continue
        fname, i = slug(stem) + ext.lower(), 1
        while fname.lower() in {s.lower() for s in saved}:
            fname, i = f"{slug(stem)}_{i}{ext.lower()}", i + 1
        with open(os.path.join(pdir, fname), "xb") as f:
            while chunk := await up.read(1 << 20):
                f.write(chunk)
        saved.append(fname)
        if original == main_photo:
            chosen = fname
    if not saved:
        shutil.rmtree(job_dir(jid), ignore_errors=True)
        raise HTTPException(400, i18n.tr("srv.no_image"))
    s = clean_settings(raw_settings)
    job = {"id": jid, "name": name.strip() or "model", "created": time.time(),
           "mode": mode if mode in MODES else "auto", "main_photo": chosen, "engine": None,
           "settings": s, "photos": [], "results": {}, "state": "queued", "step": i18n.tr("srv.step_waiting"),
           "error": None, "running_level": s["level"], "log": []}
    with LOCK:
        JOBS[jid] = job
        TASKS.put((jid, s["level"]))
    safe_save(job)
    return public(job)


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    with LOCK:
        if jid not in JOBS:
            raise HTTPException(404)
        return public(JOBS[jid])


@app.delete("/api/jobs/{jid}")
def delete_job(jid: str):
    with LOCK:
        job = JOBS.get(jid)
        if job is None:
            raise HTTPException(404)
        if job["state"] == "running":
            raise HTTPException(409, i18n.tr("srv.delete_running"))
        del JOBS[jid]
        SAVED.pop(jid, None)
        trash = job_dir(jid) + TRASH
        shutil.rmtree(trash, ignore_errors=True)
        try:
            # one rename first: a file held open (Windows) refuses it and the project stays whole
            if os.path.exists(job_dir(jid)):
                os.replace(job_dir(jid), trash)
        except OSError:
            JOBS[jid] = job
            raise HTTPException(409, i18n.tr("srv.delete_locked"))
    shutil.rmtree(trash, ignore_errors=True)
    return {"ok": True}


@app.post("/api/jobs/{jid}/run")
def rerun(jid: str, body: dict = Body(...)):
    with LOCK:
        job = JOBS.get(jid)
        if job is None:
            raise HTTPException(404)
        if job["state"] in ("running", "queued"):
            raise HTTPException(409, i18n.tr("srv.already_running"))
        level = body.get("level") or job["settings"]["level"]
        if level not in LEVELS:
            raise HTTPException(400, i18n.tr("srv.unknown_level"))
        job["settings"] = clean_settings(body.get("settings"), job["settings"])
        if body.get("mode") in MODES:
            job["mode"] = body["mode"]
        if body.get("main_photo") and any(p.get("name") == body["main_photo"] for p in job["photos"]):
            job["main_photo"] = body["main_photo"]
        job.update(state="queued", step=i18n.tr("srv.step_waiting"), running_level=level, error=None)
        TASKS.put((jid, level))
        snapshot = public(job)
    safe_save(job)
    return snapshot


EXPORT_KINDS = ("stl", "blend", "3mf", "obj", "zip", "software", "game", "web", "scan")


def result_path(jid, level, kind="stl"):
    with LOCK:
        job = JOBS.get(jid)
        if job is None or level not in job["results"]:
            raise HTTPException(404, i18n.tr("srv.no_result"))
        r = job["results"][level]
        rel = {"stl": r["stl"], "blend": r["stl"][:-4] + ".blend", "3mf": r.get("filaments"),
               "obj": r.get("obj_colors"), "zip": r.get("texture"), "software": r.get("export_software"),
               "game": r.get("export_game"), "web": r.get("export_web"),
               "scan": (r.get("scan") or {}).get("path")}[kind]
    if not rel:
        raise HTTPException(404, i18n.tr("srv.not_computed"))
    path = os.path.join(job_dir(jid), *rel.split("/"))
    if not os.path.isfile(path):
        raise HTTPException(404, i18n.tr("srv.file_missing"))
    return path


@app.post("/api/jobs/{jid}/orca")
def orca(jid: str, body: dict = Body(...)):
    try:
        pl.open_in_orca(result_path(jid, body.get("level"), body.get("kind") if body.get("kind") in ("3mf", "obj") else "stl"))
    except pl.PipelineError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/jobs/{jid}/reveal")
def reveal(jid: str, body: dict = Body(...)):
    pl.reveal(result_path(jid, body.get("level")))
    return {"ok": True}


@app.post("/api/jobs/{jid}/export")
def export(jid: str, body: dict = Body(...)):
    kind = body.get("kind") if body.get("kind") in EXPORT_KINDS else "stl"
    path = result_path(jid, body.get("level"), kind)
    if kind == "scan":
        with LOCK:
            job = JOBS[jid]
            stem = f"{slug(job['name'])}_scan_{job['results'][body['level']]['scan']['res']}"
        dest = pl.export_scan(path, stem)
    else:
        dest = pl.export_obj(path) if kind == "obj" else pl.export_copy(path)
    pl.reveal(dest)
    return {"path": dest}


@app.get("/files/{jid}/{path:path}")
def files(jid: str, path: str):
    with LOCK:
        if jid not in JOBS:
            raise HTTPException(404)
    base = os.path.realpath(job_dir(jid))
    target = os.path.realpath(os.path.join(base, path))
    if os.path.commonpath([base, target]) != base or target == base or not os.path.isfile(target):
        raise HTTPException(404)
    return FileResponse(target, headers={"Cache-Control": "no-store"})
