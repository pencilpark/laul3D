"""First-launch install of the tools the app drives: Blender (required), OrcaSlicer, and on Windows COLMAP + OpenMVS.

The window lists them from GET /api/status ("tools_setup"); POST /api/setup/tools installs the chosen ones under
DATA/tools (OrcaSlicer goes to ~/Applications on a Mac, where the user can open it too).
"""
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile

import fetch
import pipeline as pl

# pinned downloads from the official release pages; each part: url, size, sha256, kind (dmg-app, zip),
# inner = folder or app inside the archive ("" for its root), dest = where it goes (relative to DATA/tools, or ~/...)
BLENDER = "https://download.blender.org/release/Blender5.2"
GITHUB = "https://github.com"
SPECS = {
    "blender": {
        "label": "Blender", "role": "Calcul 3D", "required": True,
        "mac": [{"url": f"{BLENDER}/blender-5.2.3-macos-arm64.dmg", "size": 346295881, "kind": "dmg-app",
                 "sha256": "acc05374485a272342d4b323c15ac01953e7f697da2f1bad8af9c3bf087267a4",
                 "inner": "Blender.app", "dest": "Blender.app"}],
        "win": [{"url": f"{BLENDER}/blender-5.2.3-windows-x64.zip", "size": 405839452, "kind": "zip",
                 "sha256": "723f08a4401502561eb763cdeacf8745b31e5f3f154d287d3830d97cf75dc2fb",
                 "inner": "blender-5.2.3-windows-x64", "dest": "blender"}],
    },
    "photogrammetry": {
        "label": "COLMAP + OpenMVS", "role": "Plusieurs photos", "required": False,
        "mac": None,  # Object Capture comes with the app
        "win": [{"url": f"{GITHUB}/colmap/colmap/releases/download/4.2.1/colmap-x64-windows-nocuda.zip", "size": 127731595,
                 "kind": "zip", "sha256": "c493d88cb4a43f21afba42cb55bf786e5434a0420e73db0ba1454c5d8b3686ae",
                 "inner": "", "dest": "colmap"},
                {"url": f"{GITHUB}/cdcseacave/openMVS/releases/download/v2.4.0/OpenMVS_Windows_x64.zip", "size": 22363227,
                 "kind": "zip", "sha256": "0c31660c15c9ebc4c106873cf67564d9570d404aef7a6403451da1b6178b2167",
                 "inner": "vc17/x64/Release", "dest": "openmvs"}],
    },
    "orcaslicer": {
        "label": "OrcaSlicer", "role": "Impression", "required": False,
        "mac": [{"url": f"{GITHUB}/OrcaSlicer/OrcaSlicer/releases/download/v2.4.2/OrcaSlicer_Mac_universal_V2.4.2.dmg",
                 "size": 246088803, "kind": "dmg-app",
                 "sha256": "e15e7bb1b66214ec6e96b169b388004179c4f5f705effcdaf8c80d4992ee0366",
                 "inner": "OrcaSlicer.app", "dest": "~/Applications/OrcaSlicer.app"}],
        "win": [{"url": f"{GITHUB}/OrcaSlicer/OrcaSlicer/releases/download/v2.4.2/OrcaSlicer_Windows_V2.4.2_x64_portable.zip",
                 "size": 171367668, "kind": "zip",
                 "sha256": "feba3009dfb9d268779cca5758a1a5bc3b7d0722bf8fa48d5c57340de975d6be",
                 "inner": "", "dest": "OrcaSlicer"}],
    },
}
# COLMAP's test programs and debug symbols: about 200 MB nobody runs
SKIP_IN_ZIP = ("_test.exe", ".pdb")
# COLMAP 4.2.1 is linked with MSVC 14.51, and so needs at least that runtime; OpenMVS and torch use it too
VCREDIST_URL = "https://aka.ms/vc14/vc_redist.x64.exe"
VCREDIST_MIN = (14, 51)
NET_ERROR = "connexion à Internet impossible ; vérifie la connexion puis clique « Réessayer »"

LOCK = threading.Lock()
STATE = {"status": "idle", "current": None, "step": "", "done": 0, "total": 0, "error": None}


def _platform():
    return "mac" if pl.IS_MAC else "win" if pl.IS_WIN else None


def installed():
    t = pl.tools_status()
    return {"blender": t["blender"], "photogrammetry": t["photogrammetry"], "orcaslicer": t["orcaslicer"]}


def parts(tool):
    return SPECS[tool].get(_platform()) or []


def snapshot():
    with LOCK:
        s = dict(STATE)
    have = installed()
    s["tools"] = [{"id": k, "label": v["label"], "role": v["role"], "required": v["required"], "installed": have[k],
                   "size": sum(p["size"] for p in parts(k)), "available": bool(parts(k))} for k, v in SPECS.items()]
    return s


def running():
    with LOCK:
        return STATE["status"] == "running"


def _set(**kw):
    with LOCK:
        STATE.update(kw)


def _advance(n):
    with LOCK:
        STATE["done"] += n


def start(ids):
    todo = [t for t in ids if t in SPECS and parts(t) and not installed()[t]]
    with LOCK:
        if STATE["status"] == "running" or not todo:
            return
        STATE.update(status="running", current=None, step="Préparation", done=0,
                     total=sum(p["size"] for t in todo for p in parts(t)), error=None)
    threading.Thread(target=_install, args=(todo,), daemon=True).start()


def _install(todo):
    try:
        os.makedirs(pl.TOOLS, exist_ok=True)
        need = 3 * STATE["total"]  # archive, unpacked copy, margin
        if shutil.disk_usage(pl.TOOLS).free < need:
            raise RuntimeError(f"il faut environ {need / 1e9:.0f} Go d'espace libre sur le disque ; libère de la place puis réessaie")
        for tool in todo:
            _set(current=tool)
            if tool == "photogrammetry":
                ensure_vcredist(lambda text: _set(step=text))
            for part in parts(tool):
                archive = _fetch(tool, part["url"], part["size"], part["sha256"])
                _set(step=f"Installation de {SPECS[tool]['label']}")
                dest = os.path.join(pl.TOOLS, os.path.expanduser(part["dest"]))
                {"dmg-app": _from_dmg, "zip": _from_zip}[part["kind"]](archive, part["inner"], dest)
                os.remove(archive)
        _set(status="done", current=None, step="Outils installés", done=STATE["total"])
    except urllib.error.HTTPError as e:
        _set(status="error", error=f"le serveur de téléchargement a répondu {e.code} ; réessaie plus tard")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        _set(status="error", error=NET_ERROR)
    except Exception as e:  # noqa: BLE001
        _set(status="error", error=str(e) or type(e).__name__)


def _fetch(tool, url, size, sha256):
    folder = os.path.join(pl.DATA, "downloads")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, url.rsplit("/", 1)[-1])
    _set(step=f"Téléchargement de {SPECS[tool]['label']}")
    fetch.download(url, path + ".partial", size, _advance)
    if os.path.getsize(path + ".partial") != size or not fetch.digest_ok(path + ".partial", sha256):
        os.remove(path + ".partial")
        raise RuntimeError(f"téléchargement de {SPECS[tool]['label']} incomplet ou altéré ; réessaie")
    os.replace(path + ".partial", path)
    return path


def _replace(src, dest):
    # the previous copy goes only once the new one is complete
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    old = dest + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(dest):
        os.replace(dest, old)
    shutil.move(src, dest)
    shutil.rmtree(old, ignore_errors=True)


def _from_dmg(dmg, inner, dest):
    mount = tempfile.mkdtemp(prefix="berria-dmg-")
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", mount, dmg],
                   check=True, capture_output=True)
    try:
        staged = dest + ".partial"
        shutil.rmtree(staged, ignore_errors=True)
        subprocess.run(["ditto", os.path.join(mount, inner), staged], check=True, capture_output=True)
    finally:
        subprocess.run(["hdiutil", "detach", "-force", mount], capture_output=True)
        shutil.rmtree(mount, ignore_errors=True)
    _replace(staged, dest)


def _from_zip(archive, inner, dest):
    work = tempfile.mkdtemp(prefix="berria-zip-", dir=pl.TOOLS)
    try:
        with zipfile.ZipFile(archive) as z:
            z.extractall(work, [m for m in z.namelist() if not m.endswith(SKIP_IN_ZIP)])
        _replace(os.path.join(work, *inner.split("/")) if inner else work, dest)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def vcredist_ok():
    """Visual C++ runtime at least VCREDIST_MIN, read where Microsoft documents it, in both registry views."""
    import winreg
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                                0, winreg.KEY_READ | view) as key:
                if (winreg.QueryValueEx(key, "Major")[0], winreg.QueryValueEx(key, "Minor")[0]) >= VCREDIST_MIN:
                    return True
        except OSError:
            pass
    return False


def ensure_vcredist(step):
    """Installs Microsoft's Visual C++ runtime when missing; Windows asks the user's consent (UAC)."""
    if not pl.IS_WIN or vcredist_ok():
        return
    step("Composants Microsoft Visual C++ : Windows va demander ton accord")
    exe = os.path.join(pl.DATA, "downloads", "vc_redist.x64.exe")
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    request = urllib.request.Request(VCREDIST_URL, headers={"User-Agent": "BerriaCraft"})
    with urllib.request.urlopen(request, timeout=60) as r, open(exe, "wb") as f:
        shutil.copyfileobj(r, f)
    quoted = exe.replace("'", "''")
    # the link moves with each release, so the file is checked by its Microsoft signature rather than a pinned hash
    sig = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"$s = Get-AuthenticodeSignature -LiteralPath '{quoted}'; $s.Status.ToString() + '|' + $s.SignerCertificate.Subject"],
                         capture_output=True, text=True, creationflags=pl.NO_WINDOW).stdout.strip()
    if not sig.startswith("Valid|") or "O=Microsoft Corporation" not in sig:
        os.remove(exe)
        raise RuntimeError("le programme d'installation Microsoft n'a pas une signature valide ; réessaie plus tard")
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"try {{ $p = Start-Process -FilePath '{quoted}' -ArgumentList '/install','/quiet','/norestart' "
                        f"-Verb RunAs -Wait -PassThru; exit $p.ExitCode }} catch {{ exit 1223 }}"],
                       capture_output=True, creationflags=pl.NO_WINDOW)
    os.remove(exe)
    if r.returncode == 1223:
        raise RuntimeError("Windows n'a pas reçu ton accord pour les composants Microsoft ; clique « Réessayer » et réponds Oui")
    if r.returncode not in (0, 1638, 3010):  # 1638: a newer version is there, 3010: restart advised
        raise RuntimeError(f"installation des composants Microsoft impossible (code {r.returncode})")
