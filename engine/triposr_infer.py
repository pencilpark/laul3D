"""Single image -> 3D mesh with TripoSR (MIT), running on Apple Silicon (MPS) or CPU.

Usage: python triposr_infer.py IMAGE OUT.obj [--mc-resolution 256] [--no-remove-bg] [--device auto]
"""
import argparse
import os
import sys
import time
import types

import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "vendor", "TripoSR"))


def _install_mcubes_shim():
    # torchmcubes only builds from source; skimage gives the same surface.
    # torchmcubes returns vertices in (x, y, z) = reversed index order, TripoSR flips them back.
    from skimage import measure

    def marching_cubes(vol, thresh):
        v, f, _, _ = measure.marching_cubes(vol.detach().cpu().numpy(), thresh)
        v = np.ascontiguousarray(v[:, ::-1])
        return torch.from_numpy(v).float(), torch.from_numpy(f.astype(np.int64))

    mod = types.ModuleType("torchmcubes")
    mod.marching_cubes = marching_cubes
    sys.modules["torchmcubes"] = mod


def _use_local_dino_config():
    # TripoSR fetches facebook/dino-vitb16/config.json at startup; the installer pre-downloads it.
    local = os.environ.get("LOWPOLY_DINO_CONFIG")
    if not local or not os.path.exists(local):
        return
    import tsr.models.tokenizers.image as tokenizer
    original = tokenizer.hf_hub_download

    def hf_hub_download(repo_id, filename, **kwargs):
        if repo_id == "facebook/dino-vitb16" and filename == "config.json":
            return local
        return original(repo_id=repo_id, filename=filename, **kwargs)

    tokenizer.hf_hub_download = hf_hub_download


def pick_device(requested):
    requested = os.environ.get("LOWPOLY_DEVICE", requested)
    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("out")
    ap.add_argument("--mc-resolution", type=int, default=256)
    ap.add_argument("--no-remove-bg", action="store_true")
    ap.add_argument("--foreground-ratio", type=float, default=0.85)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--preprocessed-out", default=None, help="save the image fed to the model")
    args = ap.parse_args()

    _install_mcubes_shim()
    _use_local_dino_config()
    from PIL import Image
    from tsr.system import TSR
    from tsr.utils import remove_background, resize_foreground

    t0 = time.time()
    device = pick_device(args.device)
    print(f"[triposr] device={device}", flush=True)

    weights = os.environ.get("LOWPOLY_TRIPOSR_WEIGHTS")
    source = weights if weights and os.path.exists(os.path.join(weights, "model.ckpt")) else "stabilityai/TripoSR"
    model = TSR.from_pretrained(source, config_name="config.yaml", weight_name="model.ckpt")
    model.renderer.set_chunk_size(8192)
    model.to(device)
    print(f"[triposr] model loaded in {time.time() - t0:.1f}s", flush=True)

    img = Image.open(args.image)
    if args.no_remove_bg:
        image = np.array(img.convert("RGB"))
    else:
        import rembg
        session = rembg.new_session()
        img = remove_background(img, session)
        img = resize_foreground(img, args.foreground_ratio)
        arr = np.array(img).astype(np.float32) / 255.0
        arr = arr[:, :, :3] * arr[:, :, 3:4] + (1 - arr[:, :, 3:4]) * 0.5
        image = (arr * 255.0).astype(np.uint8)
    if args.preprocessed_out:
        Image.fromarray(image).save(args.preprocessed_out)

    def run(dev):
        model.to(dev)
        with torch.no_grad():
            codes = model([Image.fromarray(image)], device=dev)
        return model.extract_mesh(codes, True, resolution=args.mc_resolution)[0]

    t1 = time.time()
    try:
        mesh = run(device)
    except Exception as e:  # some MPS kernels are missing on older torch builds
        if device == "cpu":
            raise
        print(f"[triposr] {device} failed ({e!r}), retrying on cpu", flush=True)
        mesh = run("cpu")
    print(f"[triposr] mesh {len(mesh.vertices)} verts / {len(mesh.faces)} faces in {time.time() - t1:.1f}s", flush=True)

    # Same rotation as tsr.utils.to_gradio_3d_orientation (Y-up, what Blender's OBJ importer expects),
    # done in numpy: trimesh 4.0.5 (pinned by TripoSR) calls ndarray.ptp, removed in NumPy 2.
    # The extra half turn about the vertical axis makes the subject face Blender's -Y (front view).
    rx = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64)
    ry = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], dtype=np.float64)
    half_turn = np.diag([-1.0, 1.0, -1.0])
    verts = np.asarray(mesh.vertices, dtype=np.float64) @ (half_turn @ ry @ rx).T
    faces = np.asarray(mesh.faces, dtype=np.int64) + 1
    # "v x y z r g b": Blender's OBJ importer turns the colors into a color attribute, used for the colored preview
    rgb = np.asarray(mesh.visual.vertex_colors, dtype=np.float64)[:, :3] / 255.0
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write("".join(f"v {x:.6f} {y:.6f} {z:.6f} {r:.4f} {g:.4f} {b:.4f}\n" for (x, y, z), (r, g, b) in zip(verts, rgb)))
        f.write("".join(f"f {a} {b} {c}\n" for a, b, c in faces))
    print(f"[triposr] saved {args.out} total {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
