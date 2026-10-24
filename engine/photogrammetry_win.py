"""Windows/Linux photogrammetry backend (stand-in for Apple Object Capture). Filled in by the Windows port."""
import os


def available():
    return False


def reconstruct(photo_dir, photos, work_dir, level, log, run, stage_photos, error_cls):
    raise error_cls("La photogrammétrie Windows n'est pas encore installée : passe le moteur en IA.")
