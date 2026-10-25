"""Photo resolution (Auto, Low, Medium, High, Max) and the raw scan export.

python tests/photo_res_test.py
Object Capture's Max (raw, then full when raw fails), the setting kept by the server, the scan recorded with the
result, and the raw scan saved for Blender: the .usdz as it is, the OpenMVS OBJ stood up and zipped with its textures.
"""
import json
import os
import sys
import tempfile
import zipfile
from unittest import mock

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["LOWPOLY_PROJECTS"] = tempfile.mkdtemp(prefix="berria-res-Frédéric ")
os.environ["LOWPOLY_DATA"] = tempfile.mkdtemp(prefix="berria-res-data-")
os.environ["LOWPOLY_DOWNLOADS"] = tempfile.mkdtemp(prefix="berria-res-dl-")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))
import pipeline as pl  # noqa: E402
from app import server  # noqa: E402


def photos(folder, n=3):
    for i in range(n):
        Image.new("RGB", (64, 48), (40 * i, 90, 160)).save(os.path.join(folder, f"p{i}.jpg"))
    return [{"name": f"p{i}.jpg", "sharpness": 10.0} for i in range(n)]


def fake_capture(fails):
    """Object Capture that fails for the (detail, sensitivity) pairs given, and records its calls."""
    calls = []

    def run(cmd, log, **kw):
        detail, sensitivity = cmd[cmd.index("-d") + 1], cmd[cmd.index("-f") + 1]
        calls.append((detail, sensitivity))
        if (detail, sensitivity) in fails:
            return 1, []
        with open(cmd[2], "wb") as f:
            f.write(b"usdz " + detail.encode())
        return 0, []
    return run, calls


def capture(work, res, fails=()):
    src = tempfile.mkdtemp(prefix="berria-res-photos-")
    run, calls = fake_capture(set(fails))
    lines = []
    with mock.patch.object(pl, "run", run), mock.patch.object(pl, "object_capture_path", return_value="HelloPhotogrammetry"):
        out = pl.object_capture(src, photos(src), work, res, lines.append)
    return out, calls, lines


def test_resolution_choice():
    assert [pl.photo_res(lv, "auto") for lv in ("lowpoly", "medium", "detailed")] == ["low", "mid", "high"]
    assert pl.photo_res("lowpoly", "max") == "max" and pl.photo_res("detailed", "low") == "low"
    assert pl.photo_res("medium", "inconnue") == "mid"
    # Auto feeds each level the scan it had before the choice existed
    assert [pl.PG_DETAIL[pl.photo_res(lv, "auto")] for lv in ("lowpoly", "medium", "detailed")] == ["preview", "medium", "full"]
    assert server.clean_settings({})["photo_res"] == "auto"
    assert server.clean_settings({"photo_res": "max"})["photo_res"] == "max"
    assert server.clean_settings({"photo_res": "8K"}, {"photo_res": "high"})["photo_res"] == "auto"
    assert server.clean_settings({"height_mm": 90}, {"photo_res": "high"})["photo_res"] == "high"
    print("résolution : Auto suit le niveau comme avant, le réglage est gardé par projet")


def test_object_capture_max():
    work = tempfile.mkdtemp(prefix="berria-res-oc-")
    out, calls, lines = capture(work, "max", fails={("raw", "normal")})
    # raw first, then full at the same sensitivity: a raw out of memory does not cost a high-sensitivity run
    assert calls == [("raw", "normal"), ("full", "normal")], calls
    assert out == (os.path.join(work, "scan_full.usdz"), {"res": "high", "detail": "full"}), out
    assert os.path.exists(os.path.join(work, "scan_raw.failed"))
    assert any(pl.i18n.tr("srv.pg_raw_fallback") == line for line in lines), lines
    out, calls, lines = capture(work, "max")
    assert calls == [] and out[1]["detail"] == "full", (calls, out)  # raw is not tried again in this project
    assert pl.i18n.tr("srv.pg_raw_skipped") in lines, lines

    work = tempfile.mkdtemp(prefix="berria-res-oc-")
    out, calls, _ = capture(work, "max", fails={("raw", "normal"), ("full", "normal")})
    # both failing at normal sensitivity is the photos, not the memory: raw gets its high-sensitivity try
    assert calls == [("raw", "normal"), ("full", "normal"), ("raw", "high")], calls
    assert out == (os.path.join(work, "scan_raw.usdz"), {"res": "max", "detail": "raw"}), out
    assert not os.path.exists(os.path.join(work, "scan_raw.failed"))

    work = tempfile.mkdtemp(prefix="berria-res-oc-")
    with open(os.path.join(work, "scan_full.usdz"), "wb") as f:  # a High scan made earlier does not stand in for Max
        f.write(b"usdz full")
    out, calls, _ = capture(work, "max")
    assert calls == [("raw", "normal")] and out[1] == {"res": "max", "detail": "raw"}, (calls, out)
    out, calls, _ = capture(work, "high")
    assert calls == [] and out == (os.path.join(work, "scan_full.usdz"), {"res": "high", "detail": "full"}), out
    print("Object Capture : Max demande raw, puis full si raw échoue sur ce Mac, et ne réessaie plus raw ensuite")


def test_export_scan():
    folder = tempfile.mkdtemp(prefix="berria-res-scan-")
    obj = os.path.join(folder, "scene_texture.obj")
    with open(obj, "w", encoding="utf-8") as f:
        f.write("mtllib scene_texture.mtl\nv 1 2 3\nv 0 0 1 0.5 0.5 0.5\nvn 0 1 0\nvt 0.25 0.75\nf 1/1/1 2/1/1 1/1/1\n")
    for name, data in (("scene_texture.mtl", "newmtl m\nmap_Kd scene_texture_map_Kd.jpg\n"),
                       ("scene_texture_map_Kd.jpg", "jpeg"), ("TextureMesh-1.log", "log")):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(data)
    # COLMAP's z is the scan's front (-y in Blender), its y the up (z): the same rotation as for the printable model
    with open(obj + ".orient.json", "w", encoding="utf-8") as f:
        json.dump({"matrix": [[1, 0, 0], [0, 0, -1], [0, 1, 0]], "raw_axes": True, "version": 2}, f)
    dest = pl.export_scan(obj, "buste_scan_max")
    assert os.path.basename(dest) == "buste_scan_max.zip", dest
    with zipfile.ZipFile(dest) as z:
        assert sorted(z.namelist()) == ["scene_texture.mtl", "scene_texture.obj", "scene_texture_map_Kd.jpg"], z.namelist()
        lines = z.read("scene_texture.obj").decode("utf-8").splitlines()
    # Blender (x, -z, y), then OBJ's Y up (x, z, -y): the COLMAP point comes back as it was
    assert lines[1] == "v 1 2 3" and lines[2] == "v 0 0 1 0.5 0.5 0.5" and lines[3] == "vn 0 1 0", lines
    assert lines[0] == "mtllib scene_texture.mtl" and lines[4:] == ["vt 0.25 0.75", "f 1/1/1 2/1/1 1/1/1"], lines
    with open(obj + ".orient.json", "w", encoding="utf-8") as f:  # an upright scan (identity): Z up becomes Y up
        json.dump({"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}, f)
    with zipfile.ZipFile(pl.export_scan(obj, "buste_scan_max")) as z:
        assert z.read("scene_texture.obj").decode("utf-8").splitlines()[1] == "v 1 3 -2"

    usdz = os.path.join(folder, "scan_raw.usdz")
    with open(usdz, "wb") as f:
        f.write(b"usdz raw")
    dest = pl.export_scan(usdz, "buste_scan_max")
    assert os.path.basename(dest) == "buste_scan_max.usdz" and open(dest, "rb").read() == b"usdz raw", dest
    print("scan brut : le .usdz tel quel, l'OBJ d'OpenMVS redressé, Y en haut, zippé avec MTL et textures")


def test_server_records_scan():
    jid = "buste-res"
    os.makedirs(os.path.join(server.job_dir(jid), "photos"))
    src = os.path.join(server.job_dir(jid), "photos")
    job = {"id": jid, "name": "Buste été", "created": 0, "mode": "photogrammetry", "main_photo": None, "engine": None,
           "settings": server.clean_settings({"photo_res": "max", "level": "medium"}), "photos": photos(src, 25),
           "results": {}, "state": "queued", "step": "", "error": None, "running_level": "medium", "log": []}
    server.JOBS[jid] = job
    seen = {}

    def photogrammetry(photo_dir, photos_, work_dir, res, log):
        seen["res"] = res
        scan = os.path.join(work_dir, "scan_max", "scene_texture.obj")
        os.makedirs(os.path.dirname(scan))
        with open(scan, "w", encoding="utf-8") as f:
            f.write("v 0 0 0\n")
        return scan, {"res": "max", "px": 4032}

    def blender_prep(raw, out_dir, name, level, s, log, res=None):
        seen["blender_res"] = res
        os.makedirs(out_dir)
        stl = os.path.join(out_dir, name + ".stl")
        open(stl, "w").close()
        return {"stl": stl, "previews": [], "dimensions_mm": [1, 1, 1], "triangles": 12}

    tools = {"photogrammetry": True, "ia": False, "photogrammetry_engine": "COLMAP + OpenMVS"}
    with mock.patch.object(pl, "photogrammetry", photogrammetry), mock.patch.object(pl, "blender_prep", blender_prep), \
            mock.patch.object(server, "tools_now", return_value=tools):
        server.process(job, "medium", lambda line: None)
    assert seen == {"res": "max", "blender_res": "max"}, seen
    scan = job["results"]["medium"]["scan"]
    assert scan == {"res": "max", "px": 4032, "path": "work/scan_max/scene_texture.obj"}, scan
    with mock.patch.object(pl, "reveal"):
        dest = server.export(jid, {"level": "medium", "kind": "scan"})["path"]
    assert os.path.basename(dest) == "Buste_ete_scan_max.zip", dest
    print("serveur : résolution transmise au scan et à Blender, scan brut enregistré sous le nom du projet")


def main():
    test_resolution_choice()
    test_object_capture_max()
    test_export_scan()
    test_server_records_scan()


if __name__ == "__main__":
    main()
