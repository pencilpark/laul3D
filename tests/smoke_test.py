"""End-to-end smoke test: headless CLI on synthetic photos, inside a folder with accents and spaces.

python tests/smoke_test.py [--photogrammetry] [--ia] [--out results.json]
Photos: tests/fixtures/suzanne_48, a Suzanne with colored cells (Blender renders, regenerate with
tests/fixtures/render_views.py -- OUT --couleurs). The photogrammetry run must give a colored preview.
"""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "suzanne_48")
# the lines that explain the colors, which the end of the output alone often misses
KEY_LINES = re.compile(r"points communs|TextureMesh|texture du scan|texture des photos|couleurs|photos placées|reconstruction|ERREUR")


def glb_colors(path):
    """Share of black corners and mean saturation of the colored preview (its COLOR_0), in sRGB."""
    import numpy as np
    with open(path, "rb") as f:
        data = f.read()
    size = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + size])
    acc = gltf["accessors"][gltf["meshes"][0]["primitives"][0]["attributes"]["COLOR_0"]]
    view = gltf["bufferViews"][acc["bufferView"]]
    dtype, scale = {5121: (np.uint8, 255), 5123: (np.uint16, 65535), 5126: (np.float32, 1)}[acc["componentType"]]
    n = {"VEC3": 3, "VEC4": 4}[acc["type"]]
    assert view.get("byteStride", n * np.dtype(dtype).itemsize) == n * np.dtype(dtype).itemsize, view
    start = 20 + size + 8 + view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    lin = np.frombuffer(data, dtype, acc["count"] * n, start).reshape(-1, n)[:, :3] / scale
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return {"black": round(float((srgb.max(1) < 20 / 255).mean()), 3),
            "saturation": round(float((srgb.max(1) - srgb.min(1)).mean()), 3)}


def run_cli(photos, out, extra):
    cmd = [sys.executable, os.path.join(ROOT, "engine", "cli.py"), photos, "--sortie", out, *extra]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "cli.log"), "w", encoding="utf-8") as f:  # whole run, kept in the CI artifact
        f.write(p.stdout + p.stderr)
    print("\n".join(line for line in p.stdout.splitlines() if KEY_LINES.search(line)))
    print(p.stdout[-1500:])
    if p.returncode != 0:
        print(p.stderr[-4000:], file=sys.stderr)
        raise SystemExit(f"échec de la CLI (code {p.returncode})")
    summary = json.loads(p.stdout.strip().splitlines()[-1])
    assert summary["printable"], summary
    assert summary["triangles"] > 100, summary
    assert os.path.getsize(summary["stl"]) > 1000, summary
    if summary.get("colors"):
        summary["colors_stats"] = glb_colors(summary["colors"])
    summary["seconds"] = round(time.time() - t0, 1)
    return summary


def check_color_files(summary):
    """The painted 3MF and colored OBJ for multi-filament printers, the textured OBJ zip for color print services."""
    assert summary.get("filaments") and 1 <= len(summary.get("palette") or []) <= 4, summary
    with zipfile.ZipFile(summary["filaments"]) as z:
        assert "3D/3dmodel.model" in z.namelist(), z.namelist()
    assert summary.get("obj_colors") and os.path.isfile(summary["obj_colors"][:-4] + ".mtl"), summary
    with open(summary["obj_colors"], encoding="utf-8") as f:
        assert sum(ln.startswith("usemtl ") for ln in f) == len(summary["palette"])
    assert summary.get("texture"), summary
    with zipfile.ZipFile(summary["texture"]) as z:
        names = z.namelist()
    assert sorted(os.path.splitext(n)[1] for n in names) == [".mtl", ".obj", ".png"] and not any("/" in n for n in names), names


def check_export_files(summary):
    """The three profiles outside printing: one zip each, real size in meters with Y up in the GLB."""
    expected = {"software": {".blend", ".fbx", ".obj", ".mtl", ".png"}, "game": {".glb", ".fbx", ".jpg", ".png"},
                "web": {".glb"}}
    for p, exts in expected.items():
        assert summary.get("export_" + p), (p, summary.get("profiles"))
        with zipfile.ZipFile(summary["export_" + p]) as z:
            names = z.namelist()
            assert {os.path.splitext(n)[1] for n in names} == exts and not any("/" in n for n in names), (p, names)
            glb = next((n for n in names if n.endswith(("_web.glb", "_LOD0.glb"))), None)
            if glb:
                data = z.read(glb)
                doc = json.loads(data[20:20 + int.from_bytes(data[12:16], "little")])
                top = doc["accessors"][doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]["max"][1]
                assert abs(top - 0.06) < 0.003, (p, top)  # 60 mm tall, Y up, in meters
    assert sum(n.endswith("_LOD1.glb") or n.endswith("_LOD2.glb")
               for n in zipfile.ZipFile(summary["export_game"]).namelist()) == 2
    assert summary["profiles"]["software"]["quads"], summary["profiles"]
    # Draco depends on the library shipped with Blender: reported, not required
    summary["draco"] = any(n.endswith("_draco.glb") for n in zipfile.ZipFile(summary["export_web"]).namelist())
    print(f"profils d'export : {summary['profiles']}, Draco {'oui' if summary['draco'] else 'non'}", flush=True)


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
        pg = run_cli(photos, os.path.join(base, "sortie pg"),
                     ["--niveau", "lowpoly", "--moteur", "photogrammetry", "--facettes", "500", "--hauteur", "60",
                      "--exports", "software,game,web"])
        results["photogrammetry"] = pg
        # black: OpenMVS 2.4.0 seam leveling; grey: faces without photos. The fixture's cells average to about 0.12
        assert pg.get("colors"), "photogrammétrie sans aperçu en couleurs"
        assert pg["colors_stats"]["black"] < 0.3 and pg["colors_stats"]["saturation"] > 0.06, pg["colors_stats"]
        check_color_files(pg)
        check_export_files(pg)
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
