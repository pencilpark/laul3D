"""Headless command line: photo folder -> printable STL, without window or server.

lowpoly3d PHOTOS [--niveau lowpoly|medium|detailed] [--resolution auto|low|mid|high|max] [--hauteur 80]
          [--moteur auto|photogrammetry|ia] [--facettes 1000] [--socle 3] [--buse 0.4] [--rotation zx]
          [--photo-principale NAME] [--sortie FOLDER]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i18n  # noqa: E402
import pipeline as pl  # noqa: E402


def helptext(key):
    return i18n.tr(key).replace("%", "%%")  # argparse %-formats help strings


def main(argv=None):
    if os.environ.get("LOWPOLY_LANG") not in i18n.LANGUAGES:  # else the app's saved language or the system's
        i18n.startup_language(pl.DATA)
    ap = argparse.ArgumentParser(prog="lowpoly3d", description=i18n.tr("srv.cli_description"))
    ap.add_argument("photos", help=helptext("srv.cli_help_photos"))
    ap.add_argument("--niveau", choices=["lowpoly", "medium", "detailed"], default="lowpoly")
    ap.add_argument("--resolution", choices=pl.PHOTO_RES, default="auto", help=helptext("srv.cli_help_resolution"))
    ap.add_argument("--hauteur", type=float, default=80.0, metavar="MM", help=helptext("srv.cli_help_height"))
    ap.add_argument("--moteur", choices=["auto", "photogrammetry", "ia"], default="auto")
    ap.add_argument("--facettes", type=int, default=1000, metavar="N", help=helptext("srv.cli_help_faces"))
    ap.add_argument("--socle", type=float, default=3.0, metavar="PERCENT", help=helptext("srv.cli_help_base"))
    ap.add_argument("--buse", type=float, default=0.4, metavar="MM")
    ap.add_argument("--rotation", default="", metavar="AXES", help=helptext("srv.cli_help_rotation"))
    ap.add_argument("--photo-principale", default=None, metavar="NAME", help=helptext("srv.cli_help_main_photo"))
    ap.add_argument("--sortie", default=None, metavar="FOLDER", help=helptext("srv.cli_help_output"))
    ap.add_argument("--exports", default="", metavar="PROFILES", help=helptext("srv.cli_help_exports"))
    a = ap.parse_args(argv)

    photos_dir = os.path.abspath(a.photos)
    if not os.path.isdir(photos_dir):
        print(i18n.tr("srv.cli_folder_missing", path=photos_dir), file=sys.stderr)
        return 2
    out_dir = os.path.abspath(a.sortie or os.path.join(photos_dir, "lowpoly3d"))
    work = os.path.join(out_dir, "work")
    os.makedirs(work, exist_ok=True)

    def log(msg):
        print(msg, flush=True)

    try:
        photos = pl.scan_photos(photos_dir, os.path.join(work, "thumbs"))
        n_ok = sum(1 for p in photos if "error" not in p)
        if not n_ok:
            raise pl.PipelineError(i18n.tr("srv.cli_no_readable_photo"))
        engine = pl.choose_engine(a.moteur, n_ok, pl.tools_status())
        log(i18n.tr("srv.cli_photos_engine", n=n_ok, engine=engine))
        scan = None
        if engine == "photogrammetry":
            raw, scan = pl.photogrammetry(photos_dir, photos, work, pl.photo_res(a.niveau, a.resolution), log)
        else:
            raw, _ = pl.triposr(photos_dir, photos, a.photo_principale, work, log)
        settings = {"height_mm": a.hauteur, "base_cut": a.socle, "rot_seq": a.rotation, "nozzle": a.buse,
                    "faces": a.facettes, "keep_parts": False,
                    **{"export_" + k: True for k in a.exports.split(",") if k in ("software", "game", "web")}}
        name = f"{pl.slug(os.path.basename(photos_dir))}_{a.niveau}_{int(round(a.hauteur))}mm"
        report = pl.blender_prep(raw, out_dir, name, a.niveau, settings, log, scan and scan["res"])
    except pl.PipelineError as e:
        print(i18n.tr("srv.error_line", error=e), file=sys.stderr)
        return 1
    print(json.dumps({**{k: report[k] for k in ("stl", "dimensions_mm", "triangles", "printable", "volume_cm3")},
                      **{k: report.get(k) for k in ("colors", "filaments", "obj_colors", "palette", "texture", "export_software",
                                                    "export_game", "export_web", "profiles")}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
