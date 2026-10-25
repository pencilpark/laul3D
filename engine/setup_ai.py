"""On-demand install of the one-photo AI module: Python libraries, then the model files, with progress.

Started from the app (POST /api/setup/ai); models land in DATA/models, where pipeline.local_model_env finds them.
"""
import functools
import glob
import importlib
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import urllib.error

import fetch
import i18n
import pipeline as pl
import setup_tools

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

LOCK = threading.Lock()
STATE = {"status": "idle", "step": "", "done": 0, "total": 0, "error": None}


def unsupported():
    """Why this computer cannot run the module, or None. torch 2.14.1 ships for macOS 14+ on Apple silicon and 64-bit Windows."""
    if pl.IS_MAC:
        if platform.machine() != "arm64":
            return i18n.tr("srv.ai_setup_needs_apple_silicon")
        version = platform.mac_ver()[0]
        if version and int(version.split(".")[0]) < 14:
            return i18n.tr("srv.ai_setup_needs_macos14", version=version)
    elif pl.IS_WIN and platform.machine().lower() not in ("amd64", "x86_64"):
        return i18n.tr("srv.ai_setup_needs_win64")
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
        STATE.update(status="running", step=i18n.tr("srv.setup_preparing"), done=0, total=total, error=None)
    threading.Thread(target=_install, daemon=True).start()


def _install():
    try:
        if reason := unsupported():
            raise RuntimeError(i18n.tr("srv.ai_setup_unsupported", reason=reason))
        # wheels are cached then unpacked, and the models are written once: about three times the libraries
        need = MODELS_BYTES + 3 * libs_bytes()
        os.makedirs(pl.DATA, exist_ok=True)
        if shutil.disk_usage(pl.DATA).free < need:
            raise RuntimeError(i18n.tr("srv.setup_disk_space", gb=f"{need / 1e9:.0f}"))
        _libraries()
        for folder, name, url, size, sha256, md5 in MODELS:
            _model(folder, name, url, size, sha256, md5)
        setup_tools.ensure_vcredist(lambda text: _set(step=text))  # torch loads the Visual C++ runtime on Windows
        _verify()
        importlib.invalidate_caches()
        if not pl.tools_status()["ia"]:
            raise RuntimeError(i18n.tr("srv.ai_setup_not_found"))
        _set(status="done", step=i18n.tr("srv.ai_setup_done"), done=STATE["total"])
    except urllib.error.HTTPError as e:
        _set(status="error", error=i18n.tr("srv.setup_http_error", code=e.code))
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        _set(status="error", error=i18n.tr("srv.setup_net_error"))
    except Exception as e:  # noqa: BLE001
        _set(status="error", error=str(e) or type(e).__name__)


def _libraries():
    uv = os.environ.get("LOWPOLY_UV") or shutil.which("uv")
    if not uv:
        raise RuntimeError(i18n.tr("srv.ai_setup_no_uv"))
    backend, budget = torch_backend(), libs_bytes()
    _set(step=i18n.tr("srv.ai_setup_downloading_libs_nvidia") if backend else i18n.tr("srv.ai_setup_downloading_libs"))
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
            _set(step=i18n.tr("srv.ai_setup_installing_libs"))
    if proc.wait() != 0:
        if re.search(r"Failed to (fetch|download)|dns error|timed out|[Cc]onnection", "\n".join(tail)):
            raise RuntimeError(i18n.tr("srv.setup_net_error"))
        raise RuntimeError(i18n.tr("srv.ai_setup_libs_failed", detail=tail[-1] if tail else proc.returncode))
    _advance(budget - got)


def _verify():
    # the first import costs about a minute (macOS scans the new native libraries, numba fills its cache):
    # paid here, under the progress bar, rather than by the first creation; a library that cannot load shows up now
    _set(step=i18n.tr("srv.ai_setup_verifying"))
    r = subprocess.run([sys.executable, "-c", "import torch, transformers, onnxruntime, rembg, skimage.measure"], cwd=pl.ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                       creationflags=pl.NO_WINDOW)
    if r.returncode != 0:
        lines = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(i18n.tr("srv.ai_setup_start_failed", detail=lines[-1] if lines else r.returncode))


def _model_step(name, copy):
    # one whole sentence per file and action: the languages do not build it the same way
    if name == "model.ckpt":
        return i18n.tr("srv.ai_setup_copy_model") if copy else i18n.tr("srv.ai_setup_download_model")
    if name == "u2net.onnx":
        return i18n.tr("srv.ai_setup_copy_matting") if copy else i18n.tr("srv.ai_setup_download_matting")
    return i18n.tr("srv.ai_setup_copy_config") if copy else i18n.tr("srv.ai_setup_download_config")


def _model(folder, name, url, size, sha256, md5):
    dest_dir = os.path.join(pl.DATA, "models", folder)
    dest = os.path.join(dest_dir, name)
    os.makedirs(dest_dir, exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) == size and _digest_ok(dest, sha256, md5):
        _advance(size)
        return
    cached = _hf_cache(folder, name, size)
    if cached:
        _set(step=_model_step(name, copy=True))
        shutil.copyfile(cached, dest + ".partial")
        if _digest_ok(dest + ".partial", sha256, md5):
            _advance(size)
            os.replace(dest + ".partial", dest)
            return
        os.remove(dest + ".partial")  # same size, other revision: fetch the pinned file
    _set(step=_model_step(name, copy=False))
    _download(url, dest + ".partial", size)
    if os.path.getsize(dest + ".partial") != size or not _digest_ok(dest + ".partial", sha256, md5):
        os.remove(dest + ".partial")
        raise RuntimeError(i18n.tr("srv.ai_setup_file_corrupt", name=name))
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
    fetch.download(url, tmp, size, _advance)


_digest_ok = fetch.digest_ok
