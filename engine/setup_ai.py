"""On-demand install of the one-photo AI module: Python libraries, then the model files, with progress.

Started from the app (POST /api/setup/ai); models land in DATA/models, where pipeline.local_model_env finds them.
"""
import functools
import glob
import hashlib
import importlib
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pipeline as pl

TRIPOSR_REV = "5b521936b01fbe1890f6f9baed0254ab6351c04a"
DINO_REV = "f205d5d8e640a89a2b8ef0369670dfc37cc07fc2"
# (folder, file, url, size, sha256, md5); revisions are pinned so the files never change under the app
MODELS = [
    ("triposr", "model.ckpt", f"https://huggingface.co/stabilityai/TripoSR/resolve/{TRIPOSR_REV}/model.ckpt", 1677246742,
     "429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee", None),
    ("triposr", "config.yaml", f"https://huggingface.co/stabilityai/TripoSR/resolve/{TRIPOSR_REV}/config.yaml", 987,
     "74ca708ce086bf68e97709ea6b3d91f14717921c04691e84043f0eb8fcc68e62", None),
    ("dino-vitb16", "config.json", f"https://huggingface.co/facebook/dino-vitb16/resolve/{DINO_REV}/config.json", 454,
     "b87c0270b97db085fd82cf114a761fd0f62ae7914fbd407c752a2260646b689c", None),
    ("u2net", "u2net.onnx", "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx", 175997641,
     None, "60024c5c889badc19c04ad937298a77b"),
]
MODELS_BYTES = sum(m[3] for m in MODELS)
# download size of requirements-ai.txt with torch 2.14.1, measured 2026-10-24; the CUDA builds of torch weigh 2 to 2.6 GB
LIBS_BYTES = {"mac": 326_000_000, "cpu": 321_000_000, "cu126": 2_800_000_000, "cu130": 2_188_000_000}
NET_ERROR = "connexion à Internet impossible ; vérifie la connexion puis clique « Réessayer »"

LOCK = threading.Lock()
STATE = {"status": "idle", "step": "", "done": 0, "total": 0, "error": None}


def unsupported():
    """Why this computer cannot run the module, or None. torch 2.14.1 ships for macOS 14+ on Apple silicon and 64-bit Windows."""
    if pl.IS_MAC:
        if platform.machine() != "arm64":
            return "il demande un Mac à puce Apple (M1 ou plus récent)"
        version = platform.mac_ver()[0]
        if version and int(version.split(".")[0]) < 14:
            return f"il demande macOS 14 Sonoma ou plus récent, ce Mac a macOS {version}"
    elif pl.IS_WIN and platform.machine().lower() not in ("amd64", "x86_64"):
        return "il demande un PC Windows 64 bits à processeur Intel ou AMD"
    return None


@functools.lru_cache(maxsize=None)
def torch_backend():
    """CUDA build of torch when the NVIDIA driver can run one that torch 2.14.1 ships (cu126, cu130); None means CPU."""
    if not pl.IS_WIN or not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=15, creationflags=pl.NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
    cuda = (int(m[1]), int(m[2])) if m else (0, 0)
    return "cu130" if cuda >= (13, 0) else "cu126" if cuda >= (12, 6) else None


def libs_bytes():
    return LIBS_BYTES[torch_backend() or ("mac" if pl.IS_MAC else "cpu")]


def snapshot():
    with LOCK:
        s = dict(STATE)
    if s["status"] == "idle":
        s["total"] = MODELS_BYTES + libs_bytes()
    return {**s, "unsupported": unsupported(), "gpu": torch_backend() is not None}


def running():
    with LOCK:
        return STATE["status"] == "running"


def _set(**kw):
    with LOCK:
        STATE.update(kw)


def _advance(n):
    with LOCK:
        STATE["done"] += n


def start():
    total = MODELS_BYTES + libs_bytes()
    with LOCK:
        if STATE["status"] == "running":
            return
        STATE.update(status="running", step="Préparation", done=0, total=total, error=None)
    threading.Thread(target=_install, daemon=True).start()


def _install():
    try:
        if reason := unsupported():
            raise RuntimeError(f"ce module ne peut pas fonctionner sur cet ordinateur : {reason}")
        # wheels are cached then unpacked, and the models are written once: about three times the libraries
        need = MODELS_BYTES + 3 * libs_bytes()
        os.makedirs(pl.DATA, exist_ok=True)
        if shutil.disk_usage(pl.DATA).free < need:
            raise RuntimeError(f"il faut environ {need / 1e9:.0f} Go d'espace libre sur le disque ; libère de la place puis réessaie")
        _libraries()
        for folder, name, url, size, sha256, md5 in MODELS:
            _model(folder, name, url, size, sha256, md5)
        _verify()
        importlib.invalidate_caches()
        if not pl.tools_status()["ia"]:
            raise RuntimeError("les bibliothèques sont installées mais le module reste introuvable ; redémarre l'app")
        _set(status="done", step="Module IA installé", done=STATE["total"])
    except urllib.error.HTTPError as e:
        _set(status="error", error=f"le serveur de téléchargement a répondu {e.code} ; réessaie plus tard")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        _set(status="error", error=NET_ERROR)
    except Exception as e:  # noqa: BLE001
        _set(status="error", error=str(e) or type(e).__name__)


def _libraries():
    uv = os.environ.get("LOWPOLY_UV") or shutil.which("uv")
    if not uv:
        raise RuntimeError("l'outil d'installation uv est introuvable ; réinstalle LowPoly3D")
    backend, budget = torch_backend(), libs_bytes()
    _set(step="Téléchargement des bibliothèques" + (", version pour carte NVIDIA" if backend else ""))
    # the core pins act as constraints, so nothing the running app has loaded gets replaced (Windows locks loaded DLLs);
    # relative names from ROOT because uv splits a -c value on spaces (it shares the space-separated UV_CONSTRAINT list)
    cmd = [uv, "pip", "install", "--compile-bytecode", "--python", sys.executable, "-r", "requirements-ai.txt",
           "-c", "requirements-core.txt"]
    env = {**os.environ, **({"UV_TORCH_BACKEND": backend} if backend else {})}
    proc = subprocess.Popen(cmd, cwd=pl.ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", env=env, creationflags=pl.NO_WINDOW)
    sizes, got, tail = {}, 0, []
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        tail = (tail + [line])[-20:]
        if m := re.match(r"Downloading (\S+) \(([\d.]+)([KMG])iB\)", line):
            sizes[m[1]] = int(float(m[2]) * 1024 ** " KMG".index(m[3]))
        elif m := re.match(r"Downloaded (\S+)", line):
            n = min(sizes.pop(m[1], 0), budget - got)
            got += n
            _advance(n)
        elif line.startswith(("Prepared", "Installed")):
            _set(step="Installation des bibliothèques")
    if proc.wait() != 0:
        if re.search(r"Failed to (fetch|download)|dns error|timed out|[Cc]onnection", "\n".join(tail)):
            raise RuntimeError(NET_ERROR)
        raise RuntimeError(f"installation des bibliothèques impossible : {tail[-1] if tail else proc.returncode}")
    _advance(budget - got)


def _verify():
    # the first import costs about a minute (macOS scans the new native libraries, numba fills its cache):
    # paid here, under the progress bar, rather than by the first creation; a library that cannot load shows up now
    _set(step="Dernière vérification du module, environ une minute")
    r = subprocess.run([sys.executable, "-c", "import torch, transformers, onnxruntime, rembg, skimage.measure"], cwd=pl.ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                       creationflags=pl.NO_WINDOW)
    if r.returncode != 0:
        lines = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(f"le module IA ne démarre pas : {lines[-1] if lines else r.returncode}")


def _model(folder, name, url, size, sha256, md5):
    dest_dir = os.path.join(pl.DATA, "models", folder)
    dest = os.path.join(dest_dir, name)
    os.makedirs(dest_dir, exist_ok=True)
    label = {"model.ckpt": "du modèle d'IA (TripoSR)", "u2net.onnx": "du modèle de détourage"}.get(name, "de la configuration du modèle")
    if os.path.exists(dest) and os.path.getsize(dest) == size and _digest_ok(dest, sha256, md5):
        _advance(size)
        return
    cached = _hf_cache(folder, name, size)
    if cached:
        _set(step=f"Copie {label}")
        shutil.copyfile(cached, dest + ".partial")
        _advance(size)
    else:
        _set(step=f"Téléchargement {label}")
        _download(url, dest + ".partial", size)
    if os.path.getsize(dest + ".partial") != size or not _digest_ok(dest + ".partial", sha256, md5):
        os.remove(dest + ".partial")
        raise RuntimeError(f"fichier {name} incomplet ou altéré ; réessaie")
    os.replace(dest + ".partial", dest)


def _hf_cache(folder, name, size):
    # a TripoSR or rembg run before this installer may already have downloaded the file; the digest check follows
    patterns = {"triposr": f"~/.cache/huggingface/hub/models--stabilityai--TripoSR/snapshots/*/{name}",
                "u2net": "~/.u2net/u2net.onnx"}
    for path in glob.glob(os.path.expanduser(patterns.get(folder, ""))) if folder in patterns else []:
        if os.path.getsize(path) == size:
            return path
    return None


def _download(url, tmp, size):
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    if have > size:
        os.remove(tmp)
        have = 0
    _advance(have)
    if have == size:
        return
    headers = {"User-Agent": "LowPoly3D", **({"Range": f"bytes={have}-"} if have else {})}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        resumed = have and r.status == 206
        if have and not resumed:  # server ignored the range: start over
            _advance(-have)
            have = 0
        with open(tmp, "ab" if resumed else "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
                _advance(len(chunk))


def _digest_ok(path, sha256, md5):
    if not (sha256 or md5):
        return True
    h = hashlib.sha256() if sha256 else hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest() == (sha256 or md5)
