"""Desktop launcher, run by the Python bundled in the app.

Prepares a private environment in the user's application data (once), starts the local server, prints
STEP / ERROR / READY lines for the window, and stops the server when the app closes its stdin.

python boot.py --port 8642
"""
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request

RES = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # Resources/app/desktop/boot.py
APP = os.path.join(RES, "app")
IS_WIN = sys.platform == "win32"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
# Tauri's app data folder (named after the identifier), not the install folder: uninstalling keeps the projects
HOME = os.environ.get("LOWPOLY_HOME") or (
    os.path.join(os.environ["LOCALAPPDATA"], "com.pencilpark.berriacraft") if IS_WIN
    else os.path.expanduser("~/Library/Application Support/com.pencilpark.berriacraft"))
UV = os.path.join(RES, "bin", "uv.exe" if IS_WIN else "uv")
# own process group, so stopping a child also stops what it started (uv's Python, the server's Blender)
GROUP = {"creationflags": NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WIN else {"start_new_session": True}
# what runs right now, for the stdin watcher: a setup command, then the server
CHILDREN = {"setup": None, "server": None}
LOCK = threading.Lock()


def say(kind, text=""):
    print(f"{kind} {text}".rstrip(), flush=True)


def run(cmd, **kw):
    with LOCK:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", **GROUP, **kw)
        CHILDREN["setup"] = proc
    out, _ = proc.communicate()
    with LOCK:
        CHILDREN["setup"] = None
    if proc.returncode != 0:
        lines = (out or "").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else f"code {proc.returncode}")


def watch_stdin():
    """The app closed our stdin (quitting, or killed): stop whatever runs, at any stage, then leave."""
    sys.stdin.read()
    LOCK.acquire()  # kept until the exit: nothing new starts while we stop what runs
    for proc in (CHILDREN["setup"], CHILDREN["server"]):
        if proc:
            stop(proc)
    os._exit(0)


def runtime():
    """Copy of the bundled Python in HOME, so the environment survives moving or updating the app."""
    dest = os.path.join(HOME, "runtime", sys.version.split()[0])
    python = os.path.join(dest, "python.exe") if IS_WIN else os.path.join(dest, "bin", "python3.11")
    if not os.path.exists(python):
        say("STEP", "Première ouverture : copie de Python")
        shutil.rmtree(dest + ".partial", ignore_errors=True)
        shutil.copytree(os.path.join(RES, "python"), dest + ".partial", symlinks=True)
        os.replace(dest + ".partial", dest)
    return dest, python


def venv(rt_dir, rt_python):
    v = os.path.join(HOME, "venv")
    python = os.path.join(v, "Scripts", "python.exe") if IS_WIN else os.path.join(v, "bin", "python")
    try:
        with open(os.path.join(v, "pyvenv.cfg"), encoding="utf-8") as f:
            current = rt_dir in f.read()
    except OSError:
        current = False
    if not (current and os.path.exists(python)):
        say("STEP", "Première ouverture : création de l'environnement")
        shutil.rmtree(v, ignore_errors=True)
        run([UV, "venv", "--python", rt_python, v])
    return python


def core(python):
    # relative names from RES: uv splits some list options on spaces, and the app may live in a folder with spaces
    req = os.path.join(APP, "requirements-core.txt")
    with open(req, "rb") as f:
        want = hashlib.sha256(f.read()).hexdigest()
    stamp = os.path.join(HOME, "venv", "lowpoly-core.txt")
    if os.path.exists(stamp) and open(stamp, encoding="utf-8").read() == want:
        return
    say("STEP", "Première ouverture : installation du moteur de calcul")
    run([UV, "pip", "install", "--python", python, "--offline", "--no-index", "--find-links", "wheels",
         "-r", os.path.join("app", "requirements-core.txt")], cwd=RES)
    with open(stamp, "w", encoding="utf-8") as f:
        f.write(want)


def serve(python, port):
    env = {**os.environ, "LOWPOLY_DATA": os.path.join(HOME, "data"), "LOWPOLY_PROJECTS": os.path.join(HOME, "Projets"),
           "LOWPOLY_UV": UV, "PYTHONPYCACHEPREFIX": os.path.join(HOME, "cache", "pyc"), "PYTHONUTF8": "1"}
    helper = os.path.join(RES, "bin", "HelloPhotogrammetry")
    if os.path.exists(helper):
        env["LOWPOLY_PHOTOGRAMMETRY"] = helper
    os.makedirs(os.path.join(HOME, "logs"), exist_ok=True)
    log = open(os.path.join(HOME, "logs", "serveur.log"), "a", encoding="utf-8")
    log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} port {port}\n")
    log.flush()
    with LOCK:
        CHILDREN["server"] = subprocess.Popen(
            [python, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=APP, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **GROUP)
        return CHILDREN["server"]


def wait_ready(proc, port, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            raise RuntimeError(f"le moteur s'est arrêté au démarrage (journal : {os.path.join(HOME, 'logs', 'serveur.log')})")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError("le moteur ne répond pas")


def stop(proc):
    if proc.poll() is not None:
        return
    if IS_WIN:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)
        return
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the app reads UTF-8 whatever the Windows code page
    port = int(sys.argv[sys.argv.index("--port") + 1])
    threading.Thread(target=watch_stdin, daemon=True).start()
    proc = None
    try:
        os.makedirs(HOME, exist_ok=True)
        rt_dir, rt_python = runtime()
        python = venv(rt_dir, rt_python)
        core(python)
        say("STEP", "Démarrage du moteur de calcul")
        proc = serve(python, port)
        wait_ready(proc, port)
    except Exception as e:  # noqa: BLE001
        if proc:
            stop(proc)
        say("ERROR", str(e) or type(e).__name__)
        return 1
    say("READY", str(port))
    threading.Event().wait()  # watch_stdin ends the process when the app quits
    return 0


if __name__ == "__main__":
    sys.exit(main())
