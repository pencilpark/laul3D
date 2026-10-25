"""Colors of the printable mesh reduced to a few filaments, for multi-filament FDM printers.

numpy only: imported by blender_lowpoly.py inside Blender and by the tests outside it.
"""
import numpy as np


def srgb_from_linear(lin):
    lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)


def lab_from_linear(lin):
    """CIE Lab (D65) of linear sRGB colors: distances there follow what the eye sees."""
    xyz = lin @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def kmeans(points, weights, k, iterations=40):
    """Weighted k-means, seeded deterministically (k-means++ with a fixed generator): same model, same palette."""
    rng = np.random.default_rng(0)
    centers = [points[np.argmax(weights)]]
    for _ in range(1, k):
        d = np.min(((points[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1) * weights
        if d.sum() <= 0:
            break
        centers.append(points[rng.choice(len(points), p=d / d.sum())])
    centers = np.array(centers)
    for _ in range(iterations):
        labels = np.argmin(((points[:, None, :] - centers[None]) ** 2).sum(-1), axis=1)
        moved = np.array([np.average(points[labels == i], axis=0, weights=weights[labels == i])
                          if weights[labels == i].sum() > 0 else centers[i] for i in range(len(centers))])
        if np.allclose(moved, centers):
            break
        centers = moved
    return np.argmin(((points[:, None, :] - centers[None]) ** 2).sum(-1), axis=1)


def face_neighbors(triangles):
    edges = {}
    for f, (a, b, c) in enumerate(triangles):
        for e in ((a, b), (b, c), (c, a)):
            edges.setdefault((min(e), max(e)), []).append(f)
    neighbors = [[] for _ in triangles]
    for faces in edges.values():
        for f in faces:
            neighbors[f].extend(g for g in faces if g != f)
    return neighbors


def remove_islands(neighbors, labels, areas, min_area, lab, rounds=3):
    """Regions of one filament smaller than min_area take the closest color among the filaments around them.

    Such an island is too small to print as a color (a few nozzle widths) and costs a filament change per layer.
    The closest color, not the most frequent: a stray shade of red next to a black patch stays red.
    """
    labels = labels.copy()
    for _ in range(rounds):
        centers = {i: np.average(lab[labels == i], axis=0, weights=areas[labels == i]) for i in np.unique(labels)}
        seen = np.zeros(len(labels), dtype=bool)
        changed = False
        for start in range(len(labels)):
            if seen[start]:
                continue
            region, stack, area = [], [start], 0.0
            seen[start] = True
            while stack:
                f = stack.pop()
                region.append(f)
                area += areas[f]
                for g in neighbors[f]:
                    if not seen[g] and labels[g] == labels[start]:
                        seen[g] = True
                        stack.append(g)
            if area >= min_area:
                continue
            border = {labels[g] for f in region for g in neighbors[f] if labels[g] != labels[start]}
            if border:
                own = np.average(lab[region], axis=0, weights=areas[region])
                labels[region] = min(border, key=lambda i: ((centers[i] - own) ** 2).sum())
                changed = True
        if not changed:
            break
    return labels


def merge_closest(lab, areas, labels, count, min_delta=12.0):
    """Merges the clusters whose union adds the least color error (Ward) until count remain.

    Near shades of one color merge first; a small but distinct patch (an eye) stays a filament of its own. Two
    filaments closer than min_delta (CIE Lab distance) are merged too: no spool spent on a twin shade.
    """
    ids = [i for i in range(labels.max() + 1) if (labels == i).any()]
    weight = {i: areas[labels == i].sum() for i in ids}
    center = {i: np.average(lab[labels == i], axis=0, weights=areas[labels == i]) for i in ids}
    while len(ids) > 1:
        pairs = [(a, b) for n, a in enumerate(ids) for b in ids[n + 1:]]
        dist = {p: ((center[p[0]] - center[p[1]]) ** 2).sum() for p in pairs}
        if len(ids) <= count:
            a, b = min(pairs, key=dist.get)
            if dist[(a, b)] >= min_delta ** 2:
                break
        else:
            a, b = min(pairs, key=lambda p: weight[p[0]] * weight[p[1]] / (weight[p[0]] + weight[p[1]]) * dist[p])
        center[a] = (center[a] * weight[a] + center[b] * weight[b]) / (weight[a] + weight[b])
        weight[a] += weight[b]
        labels[labels == b] = a
        ids.remove(b)
    return labels


def filaments(face_colors, face_areas, triangles, count, min_island_area=2.5):
    """Filament per face and palette: face_colors linear RGB, palette in sRGB 0-255, filament 0 the largest area.

    Over-segments the colors, drops islands under min_island_area (mm2, about (4 nozzles)^2), then merges the
    closest colors down to count: stray texels vanish while small coherent details keep their filament.
    """
    face_colors = np.asarray(face_colors, dtype=np.float64)
    face_areas = np.maximum(np.asarray(face_areas, dtype=np.float64), 1e-12)
    neighbors = face_neighbors(np.asarray(triangles))
    lab = lab_from_linear(face_colors)
    labels = kmeans(lab, face_areas, max(1, min(2 * count + 2, len(face_colors))))
    labels = remove_islands(neighbors, labels, face_areas, min_island_area, lab)
    labels = merge_closest(lab, face_areas, labels, count)
    labels = remove_islands(neighbors, labels, face_areas, min_island_area, lab)
    used = [i for i in np.argsort([-face_areas[labels == i].sum() for i in range(labels.max() + 1)])
            if (labels == i).any()]
    remap = np.zeros(labels.max() + 1, dtype=int)
    remap[used] = np.arange(len(used))
    labels = remap[labels]
    # the median color: a few faces drawn into a filament (speckles at its edge) do not tint it
    palette = [tuple(int(round(v * 255)) for v in srgb_from_linear(np.median(face_colors[labels == i], axis=0)))
               for i in range(len(used))]
    return labels, palette


def paint_code(k):
    """OrcaSlicer's paint_color of a whole triangle on filament k (1-based), as TriangleSelector::serialize writes it."""
    return "%X" % (k << 2) if k <= 2 else "%XC" % (k - 3)


def write_3mf(path, vertices, triangles, labels, palette):
    """3MF core in mm, the filament of each triangle as OrcaSlicer paints it (paint_color, read unprefixed)
    and as base materials for other viewers. Orca does not take the filament colors from the file."""
    import zipfile
    hexes = ["#%02X%02X%02X" % c for c in palette]
    codes = [paint_code(i + 1) for i in range(len(palette))]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n<resources>\n<basematerials id="1">\n']
    parts += [f'<base name="Filament {i + 1}" displaycolor="{h}"/>\n' for i, h in enumerate(hexes)]
    parts.append('</basematerials>\n<object id="2" type="model" pid="1" pindex="0">\n<mesh>\n<vertices>\n')
    parts += [f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>\n' for x, y, z in vertices]
    parts.append('</vertices>\n<triangles>\n')
    parts += [f'<triangle v1="{a}" v2="{b}" v3="{c}" pid="1" p1="{k}" paint_color="{codes[k]}"/>\n'
              for (a, b, c), k in zip(triangles, labels)]
    parts.append('</triangles>\n</mesh>\n</object>\n</resources>\n<build>\n<item objectid="2"/>\n</build>\n</model>\n')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns='
                   '"http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" '
                   'ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default '
                   'Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns='
                   '"http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target='
                   '"/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"'
                   '/></Relationships>')
        z.writestr("3D/3dmodel.model", "".join(parts))
