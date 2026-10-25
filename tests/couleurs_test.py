"""Colors reduced to filaments, the painted 3MF and the colored OBJ.

python tests/couleurs_test.py
A grid of red, blue and green faces with 1 % stray white texels and, in one case, a small black patch:
speckles vanish, the patch keeps a filament, twin shades never take a spool.
"""
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))
import couleurs  # noqa: E402

N = 120
CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def linear(rgb):
    c = np.array(rgb) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def grid(patch):
    """Two triangles per square of 1 mm2 in total, the colors of a simple painted figure."""
    rng = np.random.default_rng(1)
    idx = np.arange((N + 1) ** 2).reshape(N + 1, N + 1)
    red, blue, green, white, black = (linear(c) for c in ((200, 40, 40), (40, 60, 200), (50, 170, 60),
                                                          (240, 240, 240), (15, 15, 15)))
    tris, cols = [], []
    for i in range(N):
        for j in range(N):
            base = green if i < 24 else red if j < N // 2 else blue
            if patch and 60 <= i < 64 and 30 <= j < 40:
                base = black
            for t in ((idx[i, j], idx[i + 1, j], idx[i, j + 1]), (idx[i + 1, j], idx[i + 1, j + 1], idx[i, j + 1])):
                tris.append(t)
                cols.append(white if rng.random() < 0.01 else np.clip(base + rng.normal(0, 0.01, 3), 0, 1))
    verts = [(j, i, 0.0) for i in range(N + 1) for j in range(N + 1)]
    return np.array(verts, dtype=float), np.array(tris), np.array(cols)


def main():
    verts, tris, cols = grid(patch=True)
    areas = np.full(len(tris), 0.5)
    labels, palette = couleurs.filaments(cols, areas, tris, 4, min_island_area=2.5)
    assert len(palette) == 4, palette
    assert min(sum(abs(a - b) for a, b in zip(p, (15, 15, 15))) for p in palette) < 30, palette  # the patch
    assert all(sum(abs(a - b) for a, b in zip(p, (240, 240, 240))) > 60 for p in palette), palette  # no speckle
    sizes = np.bincount(labels)
    assert list(sizes) == sorted(sizes, reverse=True), sizes  # filament 1 covers the most
    assert 75 <= sizes[-1] <= 90, sizes  # the 80 faces of the patch, give or take a speckle on its edge

    _, tris2, cols2 = grid(patch=False)
    _, palette2 = couleurs.filaments(cols2, areas, tris2, 4, min_island_area=2.5)
    assert len(palette2) == 3, palette2  # a 4th filament would only be a twin shade

    _, palette1 = couleurs.filaments(cols, areas, tris, 2, min_island_area=2.5)
    assert len(palette1) == 2, palette1

    path = os.path.join(tempfile.mkdtemp(prefix="berria-couleurs-é "), "modèle_filaments.3mf")
    couleurs.write_3mf(path, verts, tris, labels, palette)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= names, names
        model = ET.fromstring(z.read("3D/3dmodel.model"))
    assert model.get("unit") == "millimeter"
    triangles = model.findall(f".//{CORE}triangle")
    assert len(triangles) == len(tris) and len(model.findall(f".//{CORE}vertex")) == len(verts)
    colors = ["#%02X%02X%02X" % c for c in palette]
    assert [b.get("displaycolor") for b in model.findall(f".//{CORE}base")] == colors
    assert [int(t.get("p1")) for t in triangles] == list(labels)
    # OrcaSlicer's own table for filaments 1 to 8 (CONST_FILAMENTS, src/libslic3r/Model.cpp, v2.4.2)
    assert [couleurs.paint_code(k) for k in range(1, 9)] == ["4", "8", "0C", "1C", "2C", "3C", "4C", "5C"]
    assert [t.get("paint_color") for t in triangles] == [couleurs.paint_code(k + 1) for k in labels]

    obj = os.path.join(os.path.dirname(path), "modèle_colors_orca.obj")
    mtl = couleurs.write_obj(obj, verts, tris, labels, palette)
    with open(obj, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[0] == "mtllib " + os.path.basename(mtl), lines[0]
    assert sum(ln.startswith("v ") for ln in lines) == len(verts)
    current, faces = None, []
    for ln in lines:
        if ln.startswith("usemtl "):
            current = int(ln.split("_")[1]) - 1
        elif ln.startswith("f "):
            faces.append((tuple(int(v) - 1 for v in ln.split()[1:]), current))
    assert len(faces) == len(tris)
    by_face = {tuple(t): k for t, k in zip(tris.tolist(), labels)}
    assert all(by_face[t] == k for t, k in faces)  # same triangles, same shared vertices, same filament
    with open(mtl, encoding="utf-8") as f:
        materials = f.read()
    assert "map_Kd" not in materials and materials.count("Ka 0 0 0") == len(palette)
    # OrcaSlicer reads a channel as (int)(x * 255.f), src/libslic3r/ObjColorUtils.hpp:258 (v2.4.2)
    kd = [tuple(int(float(v) * 255) for v in ln.split()[1:]) for ln in materials.splitlines() if ln.startswith("Kd ")]
    assert kd == [tuple(c) for c in palette], (kd, palette)
    every = [(v, (v + 85) % 256, (v + 170) % 256) for v in range(256)]  # each byte value on each channel
    with open(couleurs.write_obj(obj, verts, tris, np.zeros(len(tris), dtype=int), every), encoding="utf-8") as f:
        kd = [tuple(int(float(v) * 255) for v in ln.split()[1:]) for ln in f if ln.startswith("Kd ")]
    assert kd == every
    print("couleurs : taches écartées, petit détail gardé, teintes jumelles fusionnées, 3MF et OBJ lisibles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
