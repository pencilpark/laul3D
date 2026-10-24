"""End-to-end smoke test: headless CLI on synthetic photos, inside a folder with accents and spaces.

python tests/smoke_test.py [--photogrammetry] [--ia] [--out results.json]
Photos: tests/fixtures/suzanne_48 (Blender renders, regenerate with tests/fixtures/render_views.py).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "suzanne_48")


def run_cli(photos, out, extra):
    cmd = [sys.executable, os.path.join(ROOT, "engine", "cli.py"), photos, "--sortie", out, *extra]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(p.stdout[-4000:])
    if p.returncode != 0:
        print(p.stderr[-4000:], file=sys.stderr)
        raise SystemExit(f"échec de la CLI (code {p.returncode})")
    summary = json.loads(p.stdout.strip().splitlines()[-1])
    assert summary["printable"], summary
    assert summary["triangles"] > 100, summary
    assert os.path.getsize(summary["stl"]) > 1000, summary
    summary["seconds"] = round(time.time() - t0, 1)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photogrammetry", action="store_true")
    ap.add_argument("--ia", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--root", default=None, help="parent folder to keep outputs (CI artifacts)")
    a = ap.parse_args()
    if not (a.photogrammetry or a.ia):
        a.photogrammetry = a.ia = True

    # Windows refuses trailing spaces in names, so the tricky part is the leading space and the accents.
    root = os.path.abspath(a.root) if a.root else tempfile.mkdtemp(prefix="lowpoly3d-")
    base = os.path.join(root, "Frédéric", " Mon -Chemin", "Été 2026")
    results = {"base": base}
    if a.photogrammetry:
        photos = os.path.join(base, "photos multi")
        shutil.copytree(FIXTURES, photos)
        results["photogrammetry"] = run_cli(photos, os.path.join(base, "sortie pg"),
                                            ["--niveau", "lowpoly", "--moteur", "photogrammetry", "--facettes", "500", "--hauteur", "60"])
    if a.ia:
        photo = os.path.join(base, "photo unique")
        os.makedirs(photo)
        shutil.copy(os.path.join(ROOT, "vendor", "TripoSR", "examples", "chair.png"), os.path.join(photo, "Chaise de Frédéric.png"))
        results["ia"] = run_cli(photo, os.path.join(base, "sortie ia"),
                                ["--moteur", "ia", "--facettes", "500", "--hauteur", "80"])
    print(json.dumps(results, ensure_ascii=False, indent=1))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
