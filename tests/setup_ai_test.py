"""Checks of the in-app AI installer that need no download: platform support, CUDA build choice, progress from uv output.

python tests/setup_ai_test.py
"""
import os
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["LOWPOLY_DATA"] = tempfile.mkdtemp(prefix="lowpoly3d-ai-data-")
sys.path.insert(0, os.path.join(ROOT, "engine"))
import pipeline as pl  # noqa: E402
import setup_ai  # noqa: E402

# what uv 0.9 prints when its output is not a terminal
UV_OK = """Using Python 3.11.14 environment at: venv
Resolved 49 packages in 702ms
Downloading torch (121.4MiB)
Downloading scipy (26.9MiB)
Downloading networkx (2.0MiB)
 Downloaded networkx
 Downloaded scipy
 Downloaded torch
Prepared 40 packages in 9.31s
Installed 40 packages in 253ms
 + torch==2.14.1
"""
UV_OFFLINE = """error: Failed to fetch: `https://pypi.org/simple/torch/`
  Caused by: Request failed after 3 retries
  Caused by: dns error: failed to lookup address information
"""


class FakeProc:
    def __init__(self, text, code=0):
        self.stdout = iter(text.splitlines(keepends=True))
        self.code = code

    def wait(self):
        return self.code


def run_libraries(output, code=0, backend=None):
    calls, seen = [], []
    real_advance = setup_ai._advance

    def popen(cmd, **kw):
        calls.append((cmd, kw["env"], kw["cwd"]))
        return FakeProc(output, code)

    def spy(n):
        real_advance(n)
        seen.append(setup_ai.STATE["done"])

    setup_ai.STATE.update(done=0)
    with mock.patch.object(pl, "IS_MAC", backend is None), mock.patch.object(pl, "IS_WIN", backend is not None), \
            mock.patch.object(setup_ai, "torch_backend", return_value=backend), mock.patch.dict(os.environ, {"LOWPOLY_UV": "uv"}), \
            mock.patch("subprocess.Popen", popen), mock.patch.object(setup_ai, "_advance", spy):
        setup_ai._libraries()
    return calls, seen


def check_unsupported():
    cases = [("darwin", "arm64", "26.2", None), ("darwin", "arm64", "14.0", None), ("darwin", "arm64", "13.6.1", "macOS 14"),
             ("darwin", "x86_64", "14.5", "puce Apple"), ("win32", "AMD64", "", None), ("win32", "ARM64", "", "64 bits")]
    for plat, machine, version, expect in cases:
        with mock.patch.object(pl, "IS_MAC", plat == "darwin"), mock.patch.object(pl, "IS_WIN", plat == "win32"), \
                mock.patch("platform.machine", return_value=machine), \
                mock.patch("platform.mac_ver", return_value=(version, ("", "", ""), "")):
            got = setup_ai.unsupported()
        assert (got is None) if expect is None else expect in (got or ""), (plat, machine, version, got)


def check_backend():
    def smi(version):
        return subprocess.CompletedProcess([], 0, stdout=f"| NVIDIA-SMI 580.88  Driver Version: 580.88  CUDA Version: {version} |\n")

    for version, expect in [("13.0", "cu130"), ("12.9", "cu126"), ("12.6", "cu126"), ("12.4", None)]:
        setup_ai.torch_backend.cache_clear()
        with mock.patch.object(pl, "IS_WIN", True), mock.patch("shutil.which", return_value="nvidia-smi"), \
                mock.patch("subprocess.run", return_value=smi(version)):
            got = setup_ai.torch_backend()
        assert got == expect, (version, got)
    setup_ai.torch_backend.cache_clear()
    with mock.patch.object(pl, "IS_WIN", True), mock.patch("shutil.which", return_value=None):
        assert setup_ai.torch_backend() is None
    setup_ai.torch_backend.cache_clear()


def check_progress():
    calls, seen = run_libraries(UV_OK)
    cmd, env, cwd = calls[0]
    # uv splits a -c value on spaces: file names must stay relative to ROOT, whatever folder the app lives in
    assert cmd[cmd.index("-c") + 1] == "requirements-core.txt" and cmd[cmd.index("-r") + 1] == "requirements-ai.txt", cmd
    assert cwd == pl.ROOT and os.path.exists(os.path.join(cwd, "requirements-core.txt")), cwd
    assert "UV_TORCH_BACKEND" not in env
    assert len(seen) == 4 and seen == sorted(seen) and seen[-1] == setup_ai.LIBS_BYTES["mac"], seen

    calls, seen = run_libraries(UV_OK, backend="cu130")
    assert calls[0][1]["UV_TORCH_BACKEND"] == "cu130" and seen[-1] == setup_ai.LIBS_BYTES["cu130"], (calls[0][1], seen)

    with mock.patch.dict(setup_ai.LIBS_BYTES, {"mac": 10_000_000}):
        _, seen = run_libraries(UV_OK)
    assert max(seen) == 10_000_000, seen

    try:
        run_libraries(UV_OFFLINE, code=2)
        raise AssertionError("an offline install must fail")
    except RuntimeError as e:
        assert str(e) == setup_ai.NET_ERROR, e


def check_verify():
    broken = subprocess.CompletedProcess([], 1, stdout="", stderr="Traceback (most recent call last):\n"
                                         "OSError: [WinError 126] Le module spécifié est introuvable : fbgemm.dll\n")
    with mock.patch("subprocess.run", return_value=broken):
        try:
            setup_ai._verify()
            raise AssertionError("a library that cannot load must stop the install")
        except RuntimeError as e:
            assert "ne démarre pas" in str(e) and "fbgemm.dll" in str(e), e


def check_not_ready_while_installing():
    # the libraries land before the models: no AI project may start until the installer has finished
    os.environ.setdefault("LOWPOLY_PROJECTS", tempfile.mkdtemp(prefix="lowpoly3d-ai-projects-"))
    sys.path.insert(0, ROOT)
    from app import server
    with mock.patch.object(pl, "tools_status", side_effect=lambda: {"ia": True, "photogrammetry": True}):
        for status, expect in [("running", False), ("done", True), ("error", True)]:
            setup_ai.STATE.update(status=status)
            assert server.tools_now()["ia"] is expect, (status, server.tools_now())


def check_disk_space():
    setup_ai.STATE.update(status="running", error=None)
    with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=10 ** 9)), \
            mock.patch.object(setup_ai, "unsupported", return_value=None), \
            mock.patch.object(setup_ai, "_libraries", side_effect=AssertionError("started without disk space")):
        setup_ai._install()
    assert setup_ai.STATE["status"] == "error" and "espace libre" in setup_ai.STATE["error"], setup_ai.STATE


def main():
    check_unsupported()
    check_backend()
    check_progress()
    check_verify()
    check_not_ready_while_installing()
    check_disk_space()
    print("setup_ai : compatibilité, index CUDA, progression, vérification, erreurs réseau et disque OK")


if __name__ == "__main__":
    main()
