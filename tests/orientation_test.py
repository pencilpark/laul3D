"""The Windows photogrammetry rotation stands the scan up and turns the first photo's side to the front.

python tests/orientation_test.py
Synthetic COLMAP poses: a ring of upright cameras around the subject, in an arbitrarily rotated frame.
"""
import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("LOWPOLY_DATA", tempfile.mkdtemp(prefix="berria-orient-"))
sys.path.insert(0, os.path.join(ROOT, "engine"))
import photogrammetry_win  # noqa: E402


def quaternion(r):
    w = np.sqrt(max(0.0, 1 + r[0, 0] + r[1, 1] + r[2, 2])) / 2
    x = np.copysign(np.sqrt(max(0.0, 1 + r[0, 0] - r[1, 1] - r[2, 2])) / 2, r[2, 1] - r[1, 2])
    y = np.copysign(np.sqrt(max(0.0, 1 - r[0, 0] + r[1, 1] - r[2, 2])) / 2, r[0, 2] - r[2, 0])
    z = np.copysign(np.sqrt(max(0.0, 1 - r[0, 0] - r[1, 1] + r[2, 2])) / 2, r[1, 0] - r[0, 1])
    return w, x, y, z


def ring(frame, n=24):
    """Cameras around the origin, upright in `frame` (whose columns give the world's right, front, up)."""
    lines = ["# Image list with two lines of data per image:"]
    for k in range(n):
        a = 2 * np.pi * k / n + 0.3
        c = frame @ np.array([3 * np.sin(a), -3 * np.cos(a), 0.4 * np.sin(3 * a)])
        forward = -c / np.linalg.norm(c)
        down = -frame[:, 2] - forward * forward.dot(-frame[:, 2])
        down /= np.linalg.norm(down)
        r = np.stack([np.cross(down, forward), down, forward])  # camera from world: x right, y down, z forward
        t = -r @ c
        # one folder per camera setting, the first photo not in the first folder by name
        lines.append(f"{k + 1} {' '.join(map(str, quaternion(r)))} {t[0]} {t[1]} {t[2]} 1 cam{2 - k % 2}/img_{k + 1:04d}.jpg")
        lines.append("")  # points line, empty here
    return "\n".join(lines) + "\n", frame @ np.array([np.sin(0.3), -np.cos(0.3), 0.0])


def main():
    rng = np.random.default_rng(7)
    for _ in range(5):
        q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
        frame = q * np.sign(np.linalg.det(q))  # a random proper rotation as the arbitrary COLMAP frame
        text, first_side = ring(frame)
        path = os.path.join(tempfile.mkdtemp(prefix="berria-poses-"), "images.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        m = np.array(photogrammetry_win.orientation(path))
        assert np.allclose(m @ m.T, np.eye(3), atol=1e-9) and np.isclose(np.linalg.det(m), 1.0), m
        assert np.allclose(m @ frame[:, 2], [0, 0, 1], atol=0.05), m @ frame[:, 2]
        side = m @ first_side
        assert side[1] < -0.999, side  # the next photo, 15° away, would give -0.966
    print("orientation : redressement et face avant OK sur 5 repères quelconques")


if __name__ == "__main__":
    main()
