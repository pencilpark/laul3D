"""Checks of the first-launch tools installer with a local archive: unpack, replace, corrupted download, disk space.

python tests/setup_tools_test.py
python tests/setup_tools_test.py --real photogrammetry   real downloads into LOWPOLY_DATA (CI)
"""
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = sys.argv[1:2] == ["--real"]
if not REAL:
    os.environ["LOWPOLY_DATA"] = tempfile.mkdtemp(prefix="berria-tools-data-")
sys.path.insert(0, os.path.join(ROOT, "engine"))
import i18n  # noqa: E402
import pipeline as pl  # noqa: E402
import setup_tools  # noqa: E402


def make_zip(content):
    folder = tempfile.mkdtemp(prefix="berria-tools-zip-")
    path = os.path.join(folder, "outil-1.0.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("outil-1.0/bin/outil.exe", content)
        z.writestr("outil-1.0/LISEZMOI.txt", "outil de test")
    data = open(path, "rb").read()
    return path, {"url": "https://example.invalid/outil-1.0.zip", "size": len(data),
                  "sha256": hashlib.sha256(data).hexdigest(), "kind": "zip", "inner": "outil-1.0", "dest": "outil"}


def install(part, local_zip, tamper=False):
    def download(url, tmp, size, advance):
        shutil.copyfile(local_zip, tmp)
        if tamper:
            with open(tmp, "r+b") as f:
                f.write(b"X")
        advance(size)

    spec = {**setup_tools.SPECS["orcaslicer"], setup_tools._platform(): [part]}
    with mock.patch.dict(setup_tools.SPECS, {"orcaslicer": spec}), \
            mock.patch.object(setup_tools, "installed", return_value={"blender": True, "photogrammetry": True, "orcaslicer": False}), \
            mock.patch("fetch.download", side_effect=download):
        setup_tools.STATE.update(status="running", done=0, total=part["size"], error=None)
        setup_tools._install(["orcaslicer"])
    return dict(setup_tools.STATE)


def real_install(ids):
    setup_tools.STATE.update(status="running", done=0, error=None,
                             total=sum(p["size"] for t in ids for p in setup_tools.parts(t)))
    setup_tools._install(ids)
    state, have = setup_tools.snapshot(), setup_tools.installed()
    assert state["status"] == "done" and all(have[t] for t in ids), (state, have)
    print(f"setup_tools : installation réelle de {', '.join(ids)} terminée dans {pl.TOOLS}")


def main():
    if REAL:
        return real_install(sys.argv[2:])
    exe = os.path.join(pl.TOOLS, "outil", "bin", "outil.exe")
    local, part = make_zip(b"version 1")
    state = install(part, local)
    assert state["status"] == "done" and open(exe, "rb").read() == b"version 1", state
    assert not os.listdir(os.path.join(pl.DATA, "downloads")), "the archive must be removed once unpacked"

    local, part = make_zip(b"version 2")
    state = install(part, local)
    assert state["status"] == "done" and open(exe, "rb").read() == b"version 2", state
    assert not os.path.exists(os.path.join(pl.TOOLS, "outil.old"))

    state = install(part, local, tamper=True)
    assert state["status"] == "error" and state["error"] == i18n.tr("srv.tools_download_corrupt", name="OrcaSlicer"), state
    assert open(exe, "rb").read() == b"version 2", "a bad download must leave the installed tool alone"

    with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=10)):
        state = install(part, local)
    need = f"{3 * part['size'] / 1e9:.0f}"
    assert state["status"] == "error" and state["error"] == i18n.tr("srv.setup_disk_space", gb=need), state
    print("setup_tools : installation, remplacement, téléchargement altéré et espace disque OK")


if __name__ == "__main__":
    main()
