"""The desktop launcher leaves nothing running: closing the app during the first-launch setup stops the setup command,
and an engine that never answers is stopped before the error is shown.

python tests/boot_test.py
boot.py runs in a child process with its setup steps replaced by long sleeps, as the app runs it (stdin = pipe).
"""
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WIN = sys.platform == "win32"

DRIVER = r'''
import os, subprocess, sys, time
sys.path.insert(0, sys.argv[3])
import boot
mode, pidfile = sys.argv[1], sys.argv[2]
sleeper = [sys.executable, "-c", f"import os, time; open({pidfile!r}, 'w').write(str(os.getpid())); time.sleep(60)"]
boot.runtime = lambda: ("runtime", sys.executable)
boot.venv = lambda rt_dir, rt_python: sys.executable
if mode == "setup":
    boot.core = lambda python: boot.run(sleeper)
else:
    def serve(python, port):
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if boot.IS_WIN else {"start_new_session": True}
        with boot.LOCK:
            boot.CHILDREN["server"] = subprocess.Popen(sleeper, **group)
            return boot.CHILDREN["server"]
    def wait_ready(proc, port, timeout=180):
        while not os.path.exists(pidfile):
            time.sleep(0.1)
        raise RuntimeError("le moteur ne répond pas")
    boot.core, boot.serve, boot.wait_ready = (lambda python: None), serve, wait_ready
sys.argv = ["boot.py", "--port", "1"]
sys.exit(boot.main())
'''


def alive(pid):
    if IS_WIN:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def launch(mode):
    folder = tempfile.mkdtemp(prefix="berria-boot-Frédéric ")
    driver, pidfile = os.path.join(folder, "driver.py"), os.path.join(folder, "child.pid")
    with open(driver, "w", encoding="utf-8") as f:
        f.write(DRIVER)
    env = {**os.environ, "LOWPOLY_HOME": os.path.join(folder, "home")}
    p = subprocess.Popen([sys.executable, driver, mode, pidfile, os.path.join(ROOT, "desktop")], env=env,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    for _ in range(300):
        if os.path.exists(pidfile) and open(pidfile).read().strip():
            return p, int(open(pidfile).read())
        time.sleep(0.1)
    p.kill()
    raise AssertionError(f"{mode} : la commande simulée n'a pas démarré")


def gone(pid, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.2)
    return False


def main():
    p, child = launch("setup")
    p.stdin.close()  # the app quits during the first-launch setup
    p.wait(15)
    assert gone(child), "la commande d'installation tourne encore après la fermeture"
    print("boot : fermer pendant la préparation arrête la commande en cours")

    p, server = launch("timeout")
    out = p.stdout.read()  # stdin stays open: closing it would mean "the app quits"
    p.wait(20)
    p.stdin.close()
    assert p.returncode == 1 and "ERROR le moteur ne répond pas" in out, (p.returncode, out)
    assert gone(server), "le moteur tourne encore après l'échec du démarrage"
    print("boot : un moteur qui ne répond pas est arrêté avant l'affichage de l'erreur")


if __name__ == "__main__":
    main()
