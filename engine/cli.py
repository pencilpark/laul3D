"""Headless command line: photo folder -> printable STL, without window or server.

lowpoly3d DOSSIER_PHOTOS [--niveau lowpoly|medium|detailed] [--hauteur 80] [--moteur auto|photogrammetry|ia]
          [--facettes 1000] [--socle 3] [--buse 0.4] [--rotation zx] [--photo-principale NOM] [--sortie DOSSIER]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as pl  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lowpoly3d", description="Photos vers STL imprimable (Creality Ender-3 V3), sans interface.")
    ap.add_argument("photos", help="dossier de photos")
    ap.add_argument("--niveau", choices=["lowpoly", "medium", "detailed"], default="lowpoly")
    ap.add_argument("--hauteur", type=float, default=80.0, help="hauteur finale en mm")
    ap.add_argument("--moteur", choices=["auto", "photogrammetry", "ia"], default="auto")
    ap.add_argument("--facettes", type=int, default=1000, help="triangles visés en LowPoly")
    ap.add_argument("--socle", type=float, default=3.0, help="pourcentage de hauteur coupé à plat")
    ap.add_argument("--buse", type=float, default=0.4)
    ap.add_argument("--rotation", default="", help="quarts de tour autour des axes, dans l'ordre, ex. zx")
    ap.add_argument("--photo-principale", default=None, help="photo utilisée par l'IA")
    ap.add_argument("--sortie", default=None, help="dossier de sortie (défaut : <photos>/lowpoly3d)")
    a = ap.parse_args(argv)

    photos_dir = os.path.abspath(a.photos)
    if not os.path.isdir(photos_dir):
        print(f"dossier introuvable : {photos_dir}", file=sys.stderr)
        return 2
    out_dir = os.path.abspath(a.sortie or os.path.join(photos_dir, "lowpoly3d"))
    work = os.path.join(out_dir, "travail")
    os.makedirs(work, exist_ok=True)

    def log(msg):
        print(msg, flush=True)

    try:
        photos = pl.scan_photos(photos_dir, os.path.join(work, "miniatures"))
        n_ok = sum(1 for p in photos if "error" not in p)
        if not n_ok:
            raise pl.PipelineError("aucune photo lisible dans ce dossier")
        engine = pl.choose_engine(a.moteur, n_ok, pl.tools_status())
        log(f"{n_ok} photo(s), moteur : {engine}")
        if engine == "photogrammetry":
            raw = pl.photogrammetry(photos_dir, photos, work, a.niveau, log)
        else:
            raw, _ = pl.triposr(photos_dir, photos, a.photo_principale, work, log)
        settings = {"height_mm": a.hauteur, "base_cut": a.socle, "rot_seq": a.rotation, "nozzle": a.buse,
                    "faces": a.facettes, "keep_parts": False}
        name = f"{pl.slug(os.path.basename(photos_dir))}_{a.niveau}_{int(round(a.hauteur))}mm"
        report = pl.blender_prep(raw, out_dir, name, a.niveau, settings, log)
    except pl.PipelineError as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        return 1
    print(json.dumps({k: report[k] for k in ("stl", "dimensions_mm", "triangles", "printable", "volume_cm3")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
