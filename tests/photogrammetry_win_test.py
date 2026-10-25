"""Checks of the Windows photogrammetry around COLMAP, and of the fixes from the October review.

python tests/photogrammetry_win_test.py
Staging (names, EXIF orientation, camera folders), model choice, atomic cache, Blender version, Visual C++ lock;
on Windows also the private fallback folder and OrcaSlicer surviving the engine's stop.
"""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from unittest import mock

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["LOWPOLY_DATA"] = tempfile.mkdtemp(prefix="berria-pgw-data-")
os.environ.pop("LOWPOLY_BLENDER", None)
sys.path.insert(0, os.path.join(ROOT, "engine"))
import photogrammetry_win as pgw  # noqa: E402
import pipeline as pl  # noqa: E402
import setup_tools  # noqa: E402

IS_WIN = sys.platform == "win32"


def photo(folder, name, size, orientation=None, make=None, focal=None):
    exif = Image.Exif()
    if orientation:
        exif[pgw.ORIENTATION] = orientation
    if make:
        exif[pgw.MAKE], exif[pgw.MODEL] = make, "EOS R6"
    if focal:
        exif[pgw.EXIF_IFD] = {pgw.FOCAL: focal}
    Image.new("RGB", size, (200, 120, 40)).save(os.path.join(folder, name), quality=90, exif=exif.tobytes())
    return {"name": name}


def staged(images):
    return sorted(os.path.relpath(os.path.join(d, f), images).replace("\\", "/")
                  for d, _, files in os.walk(images) for f in files)


def test_stage():
    src = tempfile.mkdtemp(prefix="berria-pgw-Frédéric ")
    images = os.path.join(tempfile.mkdtemp(prefix="berria-pgw-stage-"), "images")
    # names that collided with the old in-place renaming, plus one turned portrait shot with its lens data
    photos = [photo(src, n, (40, 30)) for n in ("img_0002.jpg", "a.jpg", "img_0001.jpg")]
    photos.append(photo(src, "portrait.jpg", (40, 30), orientation=6, make="Canon", focal=35.0))
    photos.append(photo(src, "zoom.jpg", (40, 30), make="Canon", focal=70.0))
    photos.append(photo(src, "Photo 10.png", (40, 30)))
    photos.append(photo(src, "Photo 9.png", (40, 30)))
    # damaged EXIF, as some editing apps leave it: an IFD announcing 65535 entries
    Image.new("RGB", (40, 30)).save(os.path.join(src, "zz abîmée.jpg"), exif=b"Exif\x00\x00MM\x00*\x00\x00\x00\x08\xff\xff")
    photos.append({"name": "zz abîmée.jpg"})
    cameras = pgw._stage(src, photos, images)
    names = staged(images)
    assert len(names) == len(photos), names
    assert [n.rsplit("/", 1)[-1] for n in sorted(names, key=lambda n: n.rsplit("/", 1)[-1])] == [
        "img_0001.jpg", "img_0002.jpg", "img_0003.jpg", "img_0004.png", "img_0005.png", "img_0006.jpg", "img_0007.jpg",
        "img_0008.jpg"], names
    by_num = {n.rsplit("/", 1)[-1][:8]: n for n in names}
    assert by_num["img_0004"].startswith("cam1/") and by_num["img_0005"].startswith("cam1/"), names  # Photo 9 before Photo 10
    with Image.open(os.path.join(images, by_num["img_0006"])) as im:  # portrait.jpg, written upright
        assert im.size == (30, 40), im.size
        exif = im.getexif()
        assert exif.get(pgw.ORIENTATION, 1) == 1, exif.get(pgw.ORIENTATION)
        assert float(exif.get_ifd(pgw.EXIF_IFD).get(pgw.FOCAL)) == 35.0, dict(exif.get_ifd(pgw.EXIF_IFD))
    folders = {n.split("/")[0] for n in names}
    # plain 40x30, upright portrait with its lens, zoomed shot: three calibrations
    assert cameras == 3 and len(folders) == 3, (cameras, names)
    assert by_num["img_0007"].split("/")[0] not in (by_num["img_0001"].split("/")[0], by_num["img_0006"].split("/")[0]), names
    print("photogrammetry_win : photos numérotées sans écrasement, redressées, une caméra par réglage")


def model(sparse, name, registered, size):
    folder = os.path.join(sparse, name)
    os.makedirs(folder)
    with open(os.path.join(folder, "images.bin"), "wb") as f:
        f.write(struct.pack("<Q", registered) + b"\0" * size)


def test_largest_model():
    sparse = tempfile.mkdtemp(prefix="berria-pgw-sparse-")
    model(sparse, "0", 40, 1000)
    model(sparse, "1", 6, 50000)  # few photos rich in points: a bigger file
    assert os.path.basename(pgw._largest_model(sparse)) == "0"
    print("photogrammetry_win : le modèle retenu est celui qui place le plus de photos")


def test_cache():
    work = tempfile.mkdtemp(prefix="berria-pgw-work-é ")
    w = tempfile.mkdtemp(prefix="berria-pgw-ws-")
    partial = os.path.join(work, "scan_lowpoly.partial")
    os.makedirs(partial)
    open(os.path.join(partial, "scene_texture.obj"), "w").close()  # an interrupted publication
    assert pgw._cached(work, "lowpoly") is None
    files = []
    for n in ("scene_texture.obj", "scene_texture.mtl", "scene_texture_material_00_map_Kd.jpg"):
        files.append(os.path.join(w, n))
        open(files[-1], "w").close()
    out = pgw._publish(work, "lowpoly", files, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    assert out == os.path.join(work, "scan_lowpoly", "scene_texture.obj"), out
    assert pgw._cached(work, "lowpoly") == out and not os.path.exists(partial)
    assert sorted(os.listdir(os.path.dirname(out))) == ["scene_texture.mtl", "scene_texture.obj",
                                                       "scene_texture.obj.orient.json", "scene_texture_material_00_map_Kd.jpg"]
    with open(out + ".orient.json", "w", encoding="utf-8") as f:  # a scan from before the black texture fix
        f.write('{"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "raw_axes": true}')
    assert pgw._cached(work, "lowpoly") is None
    os.remove(out + ".orient.json")  # an older cache, without its orientation
    assert pgw._cached(work, "lowpoly") is None
    print("photogrammetry_win : le cache n'apparaît que complet, et les scans d'une version antérieure sont refaits")


def reconstruct_commands(name, cfg, px):
    """The commands _reconstruct runs for one resolution, COLMAP and OpenMVS replaced by files they would write."""
    src = tempfile.mkdtemp(prefix="berria-pgw-tex-")
    photos = [photo(src, f"p{i}.jpg", (40, 30)) for i in range(3)]
    work = tempfile.mkdtemp(prefix="berria-pgw-texwork-")
    w = os.path.join(work, f"colmap_{name}")
    calls = []

    def fake_run(cmd, log, cwd=None, env=None, low_priority=False):
        assert low_priority, cmd
        calls.append([str(c) for c in cmd])
        tool = os.path.splitext(os.path.basename(str(cmd[0])))[0]
        if "mapper" in cmd:
            os.makedirs(os.path.join(w, "sparse", "0"))
            with open(os.path.join(w, "sparse", "0", "images.bin"), "wb") as f:
                f.write(struct.pack("<Q", 3))
        elif "model_converter" in cmd:
            with open(os.path.join(w, "poses", "images.txt"), "w", encoding="utf-8") as f:
                for i in range(3):
                    f.write(f"{i + 1} 1 0 0 0 {i} 0 5 1 cam1/img_000{i + 1}.jpg\n\n")
        elif tool == "ReconstructMesh":
            open(os.path.join(w, "scene_dense_mesh.ply"), "w").close()
        elif tool == "TextureMesh":
            open(os.path.join(w, "scene_texture.obj"), "w").close()
        return 0, []

    with mock.patch.object(pgw, "_free_memory", return_value=8 * 2 ** 30):
        out = pgw._reconstruct(src, photos, work, name, cfg, px, lambda line: None, fake_run, RuntimeError, w)
    assert out.endswith("scene_texture.obj") and pgw._cached(work, name) == out, out
    assert pgw._scan_px(out) == px, pgw._scan_px(out)
    tool = lambda name: next(c for c in calls if os.path.basename(c[0]).startswith(name) or name in c)  # noqa: E731
    opt = lambda cmd, name: cmd[cmd.index(name) + 1]  # noqa: E731
    return {"sift": tool("feature_extractor"), "undistort": tool("image_undistorter"),
            "densify": tool("DensifyPointCloud"), "texture": tool("TextureMesh")}, opt


def test_texture_command():
    cmds, opt = reconstruct_commands("lowpoly", pgw.RESOLUTIONS["low"], 800)
    assert int(opt(cmds["sift"], "--FeatureExtraction.num_threads")) >= 1, cmds["sift"]
    for name in ("--global-seam-leveling", "--local-seam-leveling"):
        assert opt(cmds["texture"], name) == "0", cmds["texture"]
    # the commands of the levels before the choice existed: Low is LowPoly's
    assert opt(cmds["sift"], "--FeatureExtraction.max_image_size") == "1600"
    assert opt(cmds["densify"], "--resolution-level") == "2" and opt(cmds["densify"], "--max-resolution") == "2560"
    assert opt(cmds["texture"], "--max-texture-size") == "4096"

    cfg = pgw._max_config([(4032, 3024)], None)
    cmds, opt = reconstruct_commands("max", cfg, 4032)
    assert opt(cmds["sift"], "--FeatureExtraction.max_image_size") == "4032", cmds["sift"]
    assert opt(cmds["undistort"], "--max_image_size") == "4032", cmds["undistort"]
    assert opt(cmds["densify"], "--resolution-level") == "0" and opt(cmds["densify"], "--max-resolution") == "4032"
    assert opt(cmds["texture"], "--resolution-level") == "0" and opt(cmds["texture"], "--max-texture-size") == "8192"
    print("photogrammetry_win : TextureMesh sans nivellement des coutures (textures noires d'OpenMVS 2.4.0), "
          "COLMAP et OpenMVS en priorité basse ; Max en pleine résolution, textures 8192")


def test_max_config():
    iphone = [(4032, 3024)] * 60
    assert pgw._max_config(iphone, None)["max_image"] == 4032  # memory unknown: the photos' own size
    assert pgw._max_config(iphone, 256 * 2 ** 30)["max_image"] == 4032
    assert pgw._max_config(iphone, 2 * 2 ** 30) is None  # no better than High: High's scan
    assert pgw._max_config([(1200, 900)] * 60, 256 * 2 ** 30) is None  # small photos: High already keeps them whole
    budget_free = 16 * 2 ** 30
    cfg = pgw._max_config(iphone, budget_free)
    side, budget = cfg["max_image"], budget_free - pgw.MEMORY_RESERVE
    assert 1600 < side < 4032 and pgw._peak_memory(side, 0.75, 60) <= budget, cfg
    s = 4032
    while int(s * 0.9) > side:
        s = int(s * 0.9)
    assert pgw._peak_memory(s, 0.75, 60) > budget, (s, side)  # the size above did not fit
    # cameras found on photos at least as large as High's, even when the depth maps are smaller
    assert cfg["sift"] == max(side, 3200) and cfg["texture"] == 8192 and cfg["resolution_level"] == 0, cfg
    print(f"photogrammetry_win : Max à {side} px sur 4032 pour {budget_free / 2 ** 30:.0f} Go libres et 60 photos, "
          "Haute quand la mémoire ne permet pas mieux")


def test_max_choice():
    src = tempfile.mkdtemp(prefix="berria-pgw-max-")
    photos = [photo(src, f"p{i}.jpg", (4032, 3024)) for i in range(3)]
    runs = []

    def fake(photo_dir, photos_, work_dir, name, cfg, px, log, run, error_cls, w):
        runs.append((name, cfg, px))
        return os.path.join(work_dir, f"scan_{name}", "m.obj")

    with mock.patch.object(pgw, "available", return_value=True), mock.patch.object(pgw, "_reconstruct", fake):
        work = tempfile.mkdtemp(prefix="berria-pgw-maxwork-")
        with mock.patch.object(pgw, "_free_memory", return_value=2 * 2 ** 30):
            out, info = pgw.reconstruct(src, photos, work, "max", lambda line: None, None, RuntimeError)
        assert runs[-1][0] == "detailed" and runs[-1][1] is pgw.RESOLUTIONS["high"] and info["res"] == "high", runs
        with mock.patch.object(pgw, "_free_memory", return_value=256 * 2 ** 30):
            out, info = pgw.reconstruct(src, photos, work, "max", lambda line: None, None, RuntimeError)
        assert runs[-1][0] == "max" and info == {"res": "max", "px": 4032}, (runs, info)
        mesh = os.path.join(work, "scan_max", "scene_texture.obj")
        os.makedirs(os.path.dirname(mesh))
        open(mesh, "w").close()
        with open(mesh + ".orient.json", "w", encoding="utf-8") as f:
            json.dump({"matrix": None, "raw_axes": True, "version": pgw.SCAN_VERSION, "px": 3265}, f)
        n = len(runs)
        with mock.patch.object(pgw, "_free_memory", return_value=2 * 2 ** 30):  # a Max scan made earlier serves as is
            out, info = pgw.reconstruct(src, photos, work, "max", lambda line: None, None, RuntimeError)
        assert len(runs) == n and out == mesh and info == {"res": "max", "px": 3265}, (runs, out, info)
    print("photogrammetry_win : Max ramené à Haute réutilise le scan Haute, un scan Max existant sert tel quel")


def test_sift_threads():
    src = tempfile.mkdtemp(prefix="berria-pgw-sift-")
    photos = [photo(src, "iphone.jpg", (4032, 3024)), {"name": "absente.jpg"}]
    with mock.patch.object(pgw, "_free_memory", return_value=8 * 2 ** 30), mock.patch.object(os, "cpu_count", return_value=8):
        counts = {res: pgw._sift_threads(src, photos, cfg["max_image"])[0] for res, cfg in pgw.RESOLUTIONS.items()}
    assert counts == {"low": 8, "mid": 5, "high": 2}, counts
    with mock.patch.object(pgw, "_free_memory", return_value=2 * 2 ** 30):
        assert pgw._sift_threads(src, photos, 3200)[0] == 1
    with mock.patch.object(pgw, "_free_memory", return_value=None):
        assert pgw._sift_threads(src, photos, 3200) == (None, None)
    if IS_WIN:  # the real reading, through GlobalMemoryStatusEx
        assert (pgw._free_memory() or 0) > 2 ** 28, pgw._free_memory()
    print("photogrammetry_win : extraction SIFT limitée à la mémoire libre (8 Go : 8, 5 et 2 photos à la fois)")


def fake_blender(root, version, app):
    if app:
        exe = os.path.join(root, "Blender.app", "Contents", "MacOS", "Blender")
        os.makedirs(os.path.join(root, "Blender.app", "Contents", "Resources", version))
    else:
        exe = os.path.join(root, "blender", "blender.exe")
        os.makedirs(os.path.join(root, "blender", version))
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    open(exe, "w").close()
    return exe


def test_blender_version():
    app = pl.IS_MAC
    old = fake_blender(tempfile.mkdtemp(prefix="berria-blender-old-"), "4.2", app)
    assert pl.blender_version(old) == (4, 2)
    if not (pl.IS_MAC or pl.IS_WIN):
        return
    tools = tempfile.mkdtemp(prefix="berria-tools-")
    with mock.patch.object(pl, "TOOLS", tools):
        mine = fake_blender(tools, "5.2", app)
        assert pl.blender_path() == mine, pl.blender_path()  # the installed copy comes first
    tools = tempfile.mkdtemp(prefix="berria-tools-")
    with mock.patch.object(pl, "TOOLS", tools):
        fake_blender(tools, "4.2", app)
        found = pl.blender_path()
        assert not (found or "").startswith(tools), found  # too old for the smoothing nodes: ignored
        assert found is None or pl.blender_version(found) >= pl.BLENDER_MIN, found
    print("pipeline : Blender 5 ou plus exigé, la copie installée par l'app passe en premier")


def test_vcredist_lock():
    calls, state = [], {"ok": False}

    def install(step):
        calls.append(1)
        time.sleep(0.3)
        state["ok"] = True

    with mock.patch.object(setup_tools.pl, "IS_WIN", True), \
            mock.patch.object(setup_tools, "vcredist_ok", side_effect=lambda: state["ok"]), \
            mock.patch.object(setup_tools, "_install_vcredist", side_effect=install):
        threads = [threading.Thread(target=setup_tools.ensure_vcredist, args=(lambda text: None,)) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert len(calls) == 1, calls
    print("setup_tools : un seul téléchargement Visual C++ pour deux installations simultanées")


BROAD = {"S-1-1-0": "Tout le monde", "S-1-5-32-545": "Utilisateurs", "S-1-5-11": "Utilisateurs authentifiés",
         "S-1-5-4": "Interactif"}
ALLOWED = {"S-1-5-18", "S-1-5-32-544", "S-1-3-4"}  # Windows itself, administrators, the folder's owner


def test_private_dir():
    assert pgw._ascii_workspace("C:\\Frédéric absent\\projet", "lowpoly") is None  # no short name: the fallback
    root = pgw._public_root()  # as reconstruct makes it when no ASCII path exists
    try:
        assert root.isascii() and root.startswith(os.environ["PUBLIC"]), root
        work = os.path.join(root, "colmap_lowpoly", "images")
        os.makedirs(work)
        with open(os.path.join(work, "img_0001.jpg"), "wb") as f:
            f.write(b"photo")
        script = ("(Get-Acl -LiteralPath $env:TARGET).Access | ForEach-Object { "
                  "$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }")
        me = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
        sid = me.strip().split(",")[-1].strip('"')
        for path in (root, work, os.path.join(work, "img_0001.jpg")):
            r = pl.powershell(script, env={**os.environ, "TARGET": path})
            sids = set(r.stdout.split())
            listing = subprocess.run(["icacls", path], capture_output=True, text=True, errors="replace").stdout
            assert sid in sids and sids <= ALLOWED | {sid} and not sids & set(BROAD), (path, r.stdout, r.stderr[-1500:], listing)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    assert not os.path.exists(root)
    print("photogrammetry_win : le dossier de repli dans Public et son contenu restent fermés aux autres comptes")


def wait_pid(path):
    for _ in range(200):
        if os.path.exists(path) and open(path).read().strip():
            return int(open(path).read())
        time.sleep(0.1)
    raise AssertionError("le programme lancé n'a pas démarré")


def alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return f'"{pid}"' in out


def survives_engine_stop(detached):
    folder = tempfile.mkdtemp(prefix="berria-detach-")
    pidfile = os.path.join(folder, "app.pid")
    app = [sys.executable, "-c", f"import os, time; open({pidfile!r}, 'w').write(str(os.getpid())); time.sleep(120)"]
    start = (f"import pipeline as pl; pl.launch_detached({app!r})" if detached
             else f"import subprocess; subprocess.Popen({app!r})")
    engine = subprocess.Popen([sys.executable, "-c", f"import sys; sys.path.insert(0, {os.path.join(ROOT, 'engine')!r}); "
                               f"{start}; import time; time.sleep(120)"])
    pid = wait_pid(pidfile)
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(engine.pid)], capture_output=True)  # as boot.py stops the engine
    time.sleep(1)
    survived = alive(pid)
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    return survived


def test_orca_survives():
    assert not survives_engine_stop(False), "témoin : un enfant direct devrait être arrêté avec le moteur"
    assert survives_engine_stop(True), "l'application ouverte par le moteur a été arrêtée avec lui"
    print("pipeline : OrcaSlicer, lancé à part, survit à l'arrêt du moteur")


def main():
    test_stage()
    test_largest_model()
    test_cache()
    test_texture_command()
    test_max_config()
    test_max_choice()
    test_sift_threads()
    test_blender_version()
    test_vcredist_lock()
    if IS_WIN:
        test_private_dir()
        test_orca_survives()


if __name__ == "__main__":
    main()
