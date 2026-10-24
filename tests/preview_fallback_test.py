"""Regression test: Blender dying while rendering the views must not lose the model.

python tests/preview_fallback_test.py   (needs Blender; LOWPOLY_BLENDER overrides its path)
Seen on the Windows CI runner: no OpenGL, EXCEPTION_ACCESS_VIOLATION in the Workbench render,
after the STL was written. The views are retried with Cycles on the CPU.
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))
import pipeline as pl  # noqa: E402

CUBE = "\n".join(["v -1 -1 -1", "v 1 -1 -1", "v 1 1 -1", "v -1 1 -1", "v -1 -1 1", "v 1 -1 1", "v 1 1 1", "v -1 1 1",
                  "f 1 3 2", "f 1 4 3", "f 5 6 7", "f 5 7 8", "f 1 2 6", "f 1 6 5",
                  "f 2 3 7", "f 2 7 6", "f 3 4 8", "f 3 8 7", "f 4 1 5", "f 4 5 8"]) + "\n"
SETTINGS = {"height_mm": 40, "base_cut": 0, "rot_seq": "", "nozzle": 0.4, "faces": 300, "keep_parts": False}


def main():
    base = os.path.join(tempfile.mkdtemp(prefix="lowpoly3d-"), "Frédéric", " Mon -Chemin")
    os.makedirs(base)
    raw = os.path.join(base, "cube é.obj")
    with open(raw, "w", encoding="utf-8") as f:
        f.write(CUBE)
    real_run, calls = pl.run, []

    def normal(cmd, log, cwd=None, env=None):
        calls.append(cmd)
        return real_run(cmd, log, cwd, env)

    def crash_after_report(cmd, log, cwd=None, env=None):
        calls.append(cmd)
        code, lines = real_run(cmd, log, cwd, env)
        if "--previews-only" not in cmd:
            return 11, [line for line in lines if not line.startswith("PREVIEWS ")]
        return code, lines

    results = {}
    for label, runner in (("normal", normal), ("crash", crash_after_report)):
        calls.clear()
        pl.run = runner
        report = pl.blender_prep(raw, os.path.join(base, f"sortie {label}"), "cube", "lowpoly", SETTINGS, lambda m: None)
        results[label] = {"calls": len(calls), "previews": len(report["previews"]),
                          "files": all(os.path.exists(p) for p in report["previews"]),
                          "stl": os.path.exists(report["stl"]), "printable": report["printable"]}
    pl.run = real_run
    print(json.dumps(results))
    ok = (results["normal"] == {"calls": 1, "previews": 4, "files": True, "stl": True, "printable": True}
          and results["crash"] == {"calls": 2, "previews": 4, "files": True, "stl": True, "printable": True})
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
