"""Export profiles outside printing: what the GLB, FBX, textures and README carry, and the settings behind them.

python tests/exports_test.py   (needs Blender; LOWPOLY_BLENDER overrides its path)
A scan like Object Capture's at High (tests/fixtures/textured_scan.py: colors, roughness map, normal map, holes) goes
through the three profiles at a real height of 25 cm, with the scan's roughness and relief. Then the web profile again,
glossy, smooth relief, WebP, half the faces, on the free memory of a small computer, which must lower the 4096
textures asked.
"""
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import zipfile
from unittest import mock

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))
import pipeline as pl  # noqa: E402
from app import server  # noqa: E402


def glb(data):
    size = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20:20 + size]), data[20 + size + 8:]


def picture(doc, binary, index):
    view = doc["bufferViews"][doc["images"][index]["bufferView"]]
    start = view.get("byteOffset", 0)
    return Image.open(io.BytesIO(binary[start:start + view["byteLength"]]))


def texture_image(doc, texture_index):
    return doc["textures"][texture_index]["source"]


def test_settings():
    s = server.clean_settings({"bake_samples": 7, "export_density": 0.7, "texture_size": 3000, "relief": "fine",
                               "finish": "satin", "web_images": "webp", "real_height_cm": 0.01})
    assert (s["bake_samples"], s["export_density"], s["texture_size"]) == (4, 0.5, "auto"), s
    assert (s["relief"], s["finish"], s["web_images"], s["real_height_cm"]) == ("auto", "satin", "webp", 0.1), s
    assert server.clean_settings({})["real_height_cm"] == 0.0 and server.clean_settings({})["bake_samples"] == 4
    assert server.clean_settings({"real_height_cm": -5})["real_height_cm"] == 0.0

    def relief(settings, res):
        cmds = []

        def run(cmd, log, **kw):
            cmds.append(cmd)
            if "--profiles-only" in cmd:
                return 0, ["PROFILES {}"]
            return 0, ['REPORT {"stl": "x.stl"}', "PREVIEWS []"]
        with mock.patch.object(pl, "run", run), mock.patch.object(pl, "blender_path", return_value=sys.executable):
            pl.blender_prep("scan.usdz", "out", "x", "lowpoly", dict(server.DEFAULTS, export_web=True, **settings),
                            lambda line: None, res)
        cmd = cmds[-1]
        return cmd[cmd.index("--relief") + 1], cmd[cmd.index("--real-height-mm") + 1]
    # auto: the scan's relief from photogrammetry, the solid's for the AI and after a medium or strong smoothing
    assert relief({}, "high") == ("scan", "0.0")
    assert relief({"smooth": 2}, "high")[0] == "solid" and relief({}, None)[0] == "solid"
    assert relief({"relief": "scan", "real_height_cm": 30}, None) == ("scan", "300.0")
    print("réglages : valeurs ramenées aux choix proposés, relief Auto selon le moteur et le lissage")


def blender(scan, out, *args, env=None):
    cmd = [pl.blender_path(), "-b", "--factory-startup", "--python-exit-code", "1",
           "-P", os.path.join(ROOT, "engine", "blender_lowpoly.py"), "--", "--input", scan, "--outdir", out,
           "--name", "essai", "--level", "lowpoly", "--height-mm", "60", "--colors", *args]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "LOWPOLY_LANG": "en", **(env or {})})
    lines = p.stdout.splitlines()
    profiles = next((json.loads(line[9:]) for line in lines if line.startswith("PROFILES ")), None)
    assert p.returncode == 0 and profiles is not None, (p.returncode, p.stdout[-3000:], p.stderr[-2000:])
    return profiles, [line for line in lines if line.startswith("[blender]")]


def check_web(path, height):
    with zipfile.ZipFile(path) as z:
        names = sorted(z.namelist())
        doc, binary = glb(z.read("essai_web.glb"))
        readme = z.read("README.txt").decode("utf-8-sig")
        variants = {n: glb(z.read(n))[0] for n in names if n.endswith(("_draco.glb", "_meshopt.glb"))}
    prim = doc["meshes"][0]["primitives"][0]
    assert "TANGENT" in prim["attributes"], prim["attributes"]
    top = doc["accessors"][prim["attributes"]["POSITION"]]["max"][1]
    assert abs(top - height) < 0.03 * height, top
    mat = doc["materials"][0]
    assert not mat.get("doubleSided"), mat
    pbr = mat["pbrMetallicRoughness"]
    # roughness and metal read from one JPEG: the exporter kept the file instead of packing a PNG
    rough = texture_image(doc, pbr["metallicRoughnessTexture"]["index"])
    assert doc["images"][rough]["mimeType"] == "image/jpeg", doc["images"]
    metal = np.asarray(picture(doc, binary, rough).convert("RGB"), dtype=float)[..., 2]
    assert metal.mean() < 8 and np.percentile(metal, 99) < 24, (metal.mean(), np.percentile(metal, 99))
    color = np.asarray(picture(doc, binary, texture_image(doc, pbr["baseColorTexture"]["index"])).convert("RGB"))
    # the fixture has no black: a black texel would be a hole or a gap between islands left unfilled
    assert (color.max(2) < 10).mean() < 0.001, (color.max(2) < 10).mean()
    for name, variant in variants.items():
        ext = "KHR_draco_mesh_compression" if name.endswith("_draco.glb") else "EXT_meshopt_compression"
        assert ext in variant.get("extensionsRequired", []), (name, variant.get("extensionsUsed"))
        assert "TANGENT" in variant["meshes"][0]["primitives"][0]["attributes"], name
    assert "README.txt" in names and "MikkTSpace" in readme, (names, readme)
    return sorted(variants)


def check_game(path):
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        gl = np.asarray(Image.open(io.BytesIO(z.read("essai_game_normal.png"))).convert("RGB"), dtype=int)
        dx = np.asarray(Image.open(io.BytesIO(z.read("essai_game_normal_dx.png"))).convert("RGB"), dtype=int)
        rough = np.asarray(Image.open(io.BytesIO(z.read("essai_game_roughness.png"))).convert("RGB"), dtype=int)
        lod0, _ = glb(z.read("essai_game_LOD0.glb"))
        readme = z.read("README.txt").decode("utf-8-sig")
    expected = {f"essai_game_LOD{i}.{e}" for i in range(3) for e in ("glb", "fbx")} | {
        "essai_game_color.jpg", "essai_game_normal.png", "essai_game_normal_dx.png", "essai_game_roughness.png",
        "README.txt"}
    assert names == expected, sorted(names ^ expected)
    assert (gl[..., 0] == dx[..., 0]).all() and (gl[..., 1] + dx[..., 1] == 255).all() and (gl[..., 2] == dx[..., 2]).all()
    # the fixture's roughness runs from 0.2 to 0.8 across its texture
    assert rough[..., 0].min() < 90 and rough[..., 0].max() > 170 and (rough[..., 0] == rough[..., 1]).all()
    assert "TANGENT" in lod0["meshes"][0]["primitives"][0]["attributes"]
    assert "_normal_dx" in readme and "Unreal" in readme, readme


def check_software(path):
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
    expected = {"essai_software." + e for e in ("blend", "fbx", "obj", "mtl")} | {
        f"essai_software_{k}.png" for k in ("color", "normal", "roughness")} | {"README.txt"}
    assert names == expected, sorted(names ^ expected)


def test_profiles():
    if not pl.blender_path():
        print("exports : Blender absent, test sauté")
        return
    base = os.path.join(tempfile.mkdtemp(prefix="lowpoly3d-"), "Frédéric", " Mon -Chemin")
    os.makedirs(base)
    scan = os.path.join(base, "scan é.glb")
    p = subprocess.run([pl.blender_path(), "-b", "--factory-startup", "--python-exit-code", "1", "-P",
                        os.path.join(ROOT, "tests", "fixtures", "textured_scan.py"), "--", scan],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0 and os.path.isfile(scan), p.stdout[-2000:] + p.stderr[-2000:]

    out = os.path.join(base, "profils")
    profiles, log = blender(scan, out, "--profiles-only", "software,game,web", "--texture-size", "1024",
                            "--real-height-mm", "250")
    assert set(profiles) == {"software", "game", "web"}, (profiles, log)
    for k, v in profiles.items():
        assert v["size"] == 1024 and v["roughness_map"] and v["relief"] == "scan", (k, v)
        assert abs(v["height_m"] - 0.25) < 0.001, (k, v)
    compressed = check_web(profiles["web"]["path"], 0.25)
    check_game(profiles["game"]["path"])
    check_software(profiles["software"]["path"])
    print(f"exports : tangentes, rugosité du scan, 25 cm, normal map DirectX, textures comblées, README ; "
          f"compressions {compressed or 'aucune'}")

    out = os.path.join(base, "petite machine")
    profiles, log = blender(scan, out, "--profiles-only", "web", "--texture-size", "4096", "--finish", "gloss",
                            "--relief", "solid", "--web-images", "webp", "--density", "0.5",
                            env={"LOWPOLY_FREE_MEMORY_GB": "2.5"})
    web = profiles["web"]
    # 2.5 GB free: a 4096 bake needs about 5.3 with the reserve, a 2048 one 2.4
    assert web["size"] == 2048 and any("2048" in line and "4096" in line for line in log), (web, log)
    assert web["relief"] == "solid" and web["roughness"] == 0.3 and not web["roughness_map"], web
    assert 15000 <= web["faces"] <= 25000, web
    with zipfile.ZipFile(web["path"]) as z:
        doc, _ = glb(z.read("essai_web.glb"))
        readme = z.read("README.txt").decode("utf-8-sig")
    assert {im["mimeType"] for im in doc["images"]} == {"image/webp"}, doc["images"]
    assert "EXT_texture_webp" in doc.get("extensionsUsed", []), doc.get("extensionsUsed")
    pbr = doc["materials"][0]["pbrMetallicRoughness"]
    assert "metallicRoughnessTexture" not in pbr and abs(pbr["roughnessFactor"] - 0.3) < 1e-3, pbr
    assert "WebP" in readme and "0.3" in readme, readme
    print(f"petite machine : textures {web['size']} px au lieu de 4096, WebP, brillant, relief lissé, "
          f"{web['faces']} triangles")


def main():
    test_settings()
    test_profiles()


if __name__ == "__main__":
    main()
