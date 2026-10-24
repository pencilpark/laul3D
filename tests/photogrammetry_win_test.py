"""Checks of the Windows photogrammetry around COLMAP, and of the fixes from the October review.

python tests/photogrammetry_win_test.py
Staging (names, EXIF orientation, camera folders), model choice, atomic cache, Blender version, Visual C++ lock;
on Windows also the private fallback folder and OrcaSlicer surviving the engine's stop.
"""
import os
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
    os.remove(out + ".orient.json")  # an older cache, without its orientation
    assert pgw._cached(work, "lowpoly") is None
    print("photogrammetry_win : le cache n'apparaît que complet")


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


def test_private_dir():
    folder = os.path.join(tempfile.mkdtemp(prefix="berria-pgw-"), "Privé")
    pgw._private_dir(folder)
    script = ("(Get-Acl -LiteralPath $env:TARGET).Access | ForEach-Object { "
              "$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                         env={**os.environ, "TARGET": folder}).stdout.split()
    me = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
    sid = me.strip().split(",")[-1].strip('"')
    assert set(out) == {sid, "S-1-5-18"}, (out, sid)
    print("photogrammetry_win : le dossier de repli n'est lisible que par le compte et Windows")


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
    test_blender_version()
    test_vcredist_lock()
    if IS_WIN:
        test_private_dir()
        test_orca_survives()


if __name__ == "__main__":
    main()
