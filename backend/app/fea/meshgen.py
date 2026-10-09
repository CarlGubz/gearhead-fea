"""
Mesh generators for the built-in primitives: structured hexahedra (C3D8/C3D20) where the geometry
allows it, Delaunay tetrahedra (C3D4/C3D10) for curved shapes, plus linear -> quadratic conversion.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
from scipy.spatial import Delaunay

from .elements import element_type
from .model import FEMesh

MAX_ELEMENTS = 60_000

SHAPES = {
    "box": "Box",
    "cylinder": "Cylinder",
    "sphere": "Sphere",
    "tube": "Tube (hollow cylinder)",
    "plate_hole": "Plate with hole",
    "lbracket": "L-bracket",
}

# Freudenthal split of a unit cube into 6 tets (conforming across neighbouring cubes)
_PERMS = [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]
_CORNER_IDX = {(0, 0, 0): 0, (1, 0, 0): 1, (1, 1, 0): 2, (0, 1, 0): 3,
               (0, 0, 1): 4, (1, 0, 1): 5, (1, 1, 1): 6, (0, 1, 1): 7}
_HEX_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
_TET_EDGES = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]


def _tets_of_hex_pattern() -> np.ndarray:
    tets = []
    for perm in _PERMS:
        p = [0, 0, 0]
        path = [tuple(p)]
        for ax in perm:
            p[ax] = 1
            path.append(tuple(p))
        tets.append([_CORNER_IDX[c] for c in path])
    return np.array(tets)


_TET_PATTERN = _tets_of_hex_pattern()


def hex8_to_tet4(nodes: np.ndarray, hexes: np.ndarray) -> np.ndarray:
    tets = hexes[:, _TET_PATTERN].reshape(-1, 4)
    return tets


def _add_midside(nodes: np.ndarray, elems: np.ndarray, edges) -> Tuple[np.ndarray, np.ndarray]:
    edges = np.array(edges)
    a = elems[:, edges[:, 0]]
    b = elems[:, edges[:, 1]]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    keys = np.stack([lo.ravel(), hi.ravel()], axis=1)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    mid = 0.5 * (nodes[uniq[:, 0]] + nodes[uniq[:, 1]])
    new_nodes = np.vstack([nodes, mid])
    mid_ids = (len(nodes) + inv.reshape(-1)).reshape(a.shape)
    return new_nodes, np.hstack([elems, mid_ids])


def to_quadratic(mesh: FEMesh) -> FEMesh:
    """C3D4 -> C3D10, C3D8 -> C3D20 (mid-side nodes on straight edges)."""
    if mesh.et.name == "C3D4":
        n, e = _add_midside(mesh.nodes, mesh.elems, _TET_EDGES)
        return FEMesh(n, e, "C3D10")
    if mesh.et.name == "C3D8":
        n, e = _add_midside(mesh.nodes, mesh.elems, _HEX_EDGES)
        return FEMesh(n, e, "C3D20")
    return mesh


def _compress(nodes: np.ndarray, elems: np.ndarray):
    used = np.unique(elems)
    remap = -np.ones(len(nodes), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return nodes[used], remap[elems]


def _grid_hex(xs, ys, zs, keep=None) -> Tuple[np.ndarray, np.ndarray]:
    nx, ny, nz = len(xs), len(ys), len(zs)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    nodes = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    idx = np.arange(nx * ny * nz).reshape(nx, ny, nz)
    i, j, k = np.meshgrid(np.arange(nx - 1), np.arange(ny - 1), np.arange(nz - 1), indexing="ij")
    i, j, k = i.ravel(), j.ravel(), k.ravel()
    elems = np.stack([
        idx[i, j, k], idx[i + 1, j, k], idx[i + 1, j + 1, k], idx[i, j + 1, k],
        idx[i, j, k + 1], idx[i + 1, j, k + 1], idx[i + 1, j + 1, k + 1], idx[i, j + 1, k + 1],
    ], axis=1)
    if keep is not None:
        c = nodes[elems].mean(axis=1)
        elems = elems[keep(c)]
        nodes, elems = _compress(nodes, elems)
    return nodes, elems


def _delaunay_tets(pts: np.ndarray, keep=None) -> np.ndarray:
    tets = Delaunay(pts).simplices.astype(np.int64)
    vol = _tet_signed_volume(pts, tets)
    good = np.abs(vol) > 1e-12 * max(np.abs(vol).max(), 1e-300)
    tets = tets[good]
    if keep is not None:
        tets = tets[keep(pts[tets].mean(axis=1))]
    return tets


def _tet_signed_volume(pts, tets):
    a, b, c, d = (pts[tets[:, i]] for i in range(4))
    return np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a) / 6.0


def _count(div: int, length: float, ref: float) -> int:
    return max(1, int(round(div * length / ref)))


def generate(shape: str, dims: Dict[str, float], divisions: int = 4,
             element_type_name: str = "C3D4") -> FEMesh:
    """
    Build a mesh for a primitive. `divisions` ~ elements along the shortest edge (box/L-bracket)
    or around-the-section density (curved shapes). `element_type_name` picks linear/quadratic and
    tet/hex; hex is available for box and L-bracket.
    """
    et = element_type(element_type_name)
    div = max(1, min(int(divisions), 24))
    get = lambda k, d: float(dims.get(k, d))  # noqa: E731
    for k, v in dims.items():
        if float(v) <= 0:
            raise ValueError(f"Dimension '{k}' must be positive")

    if shape == "box":
        L, W, H = get("length", 1.0), get("width", 1.0), get("height", 1.0)
        ref = min(L, W, H)
        nx, ny, nz = _count(div, L, ref), _count(div, W, ref), _count(div, H, ref)
        xs = np.linspace(-L / 2, L / 2, nx + 1)
        ys = np.linspace(-W / 2, W / 2, ny + 1)
        zs = np.linspace(-H / 2, H / 2, nz + 1)
        nodes, hexes = _grid_hex(xs, ys, zs)
        base = _finish_structured(nodes, hexes, et.name)
    elif shape == "lbracket":
        a, b, t, d = get("length", 1.0), get("height", 1.0), get("thickness", 0.25), get("depth", 0.25)
        if t >= min(a, b):
            raise ValueError("L-bracket leg thickness must be smaller than its length and height")
        h = t / max(1, div)
        seg = lambda lo, hi: np.linspace(lo, hi, max(1, int(round((hi - lo) / h))) + 1)  # noqa: E731
        xs = np.unique(np.concatenate([seg(0, t), seg(t, a)]))
        ys = np.unique(np.concatenate([seg(0, t), seg(t, b)]))
        zs = seg(0, d)
        nodes, hexes = _grid_hex(xs, ys, zs, keep=lambda c: ~((c[:, 0] > t) & (c[:, 1] > t)))
        base = _finish_structured(nodes, hexes, et.name)
    elif shape in ("cylinder", "sphere", "tube", "plate_hole"):
        pts, keep = _curved_points(shape, dims, div)
        tets = _delaunay_tets(pts, keep)
        nodes, tets = _compress(pts, tets)
        mesh = FEMesh(nodes, tets, "C3D4")
        mesh.ensure_positive_orientation()
        if et.kind == "hex":
            raise ValueError(f"{shape} cannot be meshed with hexahedra; choose a tetrahedral element type")
        base = to_quadratic(mesh) if et.name == "C3D10" else mesh
        _project_midside(base, shape, dims, div)
    else:
        raise ValueError(f"Unknown primitive shape '{shape}'. Available: {', '.join(SHAPES)}")

    if base.n_elems > MAX_ELEMENTS:
        raise ValueError(f"Mesh would have {base.n_elems} elements (limit {MAX_ELEMENTS}). Lower the mesh density.")
    base.ensure_positive_orientation()
    return base


def _finish_structured(nodes, hexes, name: str) -> FEMesh:
    if name in ("C3D8", "C3D20"):
        m = FEMesh(nodes, hexes, "C3D8")
        return to_quadratic(m) if name == "C3D20" else m
    m = FEMesh(nodes, hex8_to_tet4(nodes, hexes), "C3D4")
    return to_quadratic(m) if name == "C3D10" else m


def _curved_points(shape: str, dims: Dict[str, float], n: int):
    get = lambda k, d: float(dims.get(k, d))  # noqa: E731
    n = max(2, n)
    if shape == "cylinder":
        r, h = get("radius", 0.5), get("height", 1.0)
        return _ring_points(0.0, r, h, n), None
    if shape == "tube":
        ro, ri, h = get("outer_radius", 0.5), get("inner_radius", 0.3), get("height", 1.0)
        if ri >= ro:
            raise ValueError("Tube inner radius must be smaller than the outer radius")
        pts = _ring_points(ri, ro, h, n)
        return pts, (lambda c: np.hypot(c[:, 0], c[:, 1]) > ri * 1.0001)
    if shape == "sphere":
        r = get("radius", 0.5)
        return _sphere_points(r, n), None
    # plate with a central hole (axis z)
    L, W, T, rh = get("length", 1.0), get("width", 0.5), get("thickness", 0.1), get("hole_radius", 0.1)
    if 2 * rh >= min(L, W):
        raise ValueError("Hole diameter must be smaller than the plate width")
    h = min(L, W) / (2 * n)
    xs = np.linspace(-L / 2, L / 2, max(2, int(round(L / h))) + 1)
    ys = np.linspace(-W / 2, W / 2, max(2, int(round(W / h))) + 1)
    zs = np.linspace(-T / 2, T / 2, max(1, int(round(T / h))) + 1)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    grid = np.stack([X.ravel(), Y.ravel()], axis=1)
    grid = grid[np.hypot(grid[:, 0], grid[:, 1]) > rh * 1.15]
    m = max(12, int(2 * np.pi * rh / h))
    ang = np.linspace(0, 2 * np.pi, m, endpoint=False)
    ring = np.stack([rh * np.cos(ang), rh * np.sin(ang)], axis=1)
    ring2 = np.stack([rh * 1.35 * np.cos(ang + np.pi / m), rh * 1.35 * np.sin(ang + np.pi / m)], axis=1)
    xy = np.vstack([grid, ring, ring2])
    pts = np.array([[x, y, z] for z in zs for x, y in xy])
    return pts, (lambda c: np.hypot(c[:, 0], c[:, 1]) > rh * 1.0001)


def _sphere_points(r: float, n: int) -> np.ndarray:
    pts = [[0.0, 0.0, 0.0]]
    n_r = max(2, n // 2)
    n_theta = max(6, n * 2)
    n_phi = max(3, n)
    for ri in np.linspace(r / n_r, r, n_r):
        for ph in np.linspace(0.15, np.pi - 0.15, n_phi):
            for th in np.linspace(0, 2 * np.pi, n_theta, endpoint=False):
                pts.append([ri * np.sin(ph) * np.cos(th), ri * np.sin(ph) * np.sin(th), ri * np.cos(ph)])
    return np.array(pts)


def _ring_points(r_in: float, r_out: float, h: float, n: int) -> np.ndarray:
    n_r = max(2, n // 2 + (1 if r_in > 0 else 0))
    n_t = max(8, n * 3)
    n_z = max(2, n + 1)
    rs = np.linspace(r_in, r_out, n_r) if r_in > 0 else np.linspace(0, r_out, n_r)
    pts = []
    for z in np.linspace(-h / 2, h / 2, n_z):
        for ri in rs:
            if ri == 0:
                pts.append([0.0, 0.0, z])
                continue
            for k, ti in enumerate(np.linspace(0, 2 * np.pi, n_t, endpoint=False)):
                pts.append([ri * np.cos(ti), ri * np.sin(ti), z])
    return np.array(pts)


def _project_midside(mesh: FEMesh, shape: str, dims: Dict[str, float], div: int = 4) -> None:
    """
    Put boundary mid-side nodes of curved shapes back onto the true surface.
    A mid-node is moved only if it lies on the boundary and both end nodes of its edge are on the
    curved surface and close together (so interior chords are never touched).
    """
    if mesh.et.name != "C3D10" or shape not in ("cylinder", "sphere", "tube"):
        return
    surf = np.zeros(mesh.n_nodes, dtype=bool)
    surf[mesh.surface_nodes()] = True
    p = mesh.nodes
    n_t = max(8, 3 * max(2, div))
    max_ang = 1.6 * 2 * np.pi / n_t
    if shape == "sphere":
        radii = [float(dims.get("radius", 0.5))]
    else:
        radii = [float(dims.get("outer_radius", dims.get("radius", 0.5)))]
        if shape == "tube":
            radii.append(float(dims.get("inner_radius", 0.3)))
    for m_idx, (i, j) in enumerate(_TET_EDGES):
        mid = mesh.elems[:, 4 + m_idx]
        a, b = mesh.elems[:, i], mesh.elems[:, j]
        for r in radii:
            if shape == "sphere":
                ra, rb = np.linalg.norm(p[a], axis=1), np.linalg.norm(p[b], axis=1)
                sel = surf[mid] & (np.abs(ra - r) < 1e-6 * r) & (np.abs(rb - r) < 1e-6 * r)
                tgt = p[mid[sel]]
                nrm = np.linalg.norm(tgt, axis=1)
                p[mid[sel]] = tgt * (r / np.maximum(nrm, 1e-300))[:, None]
            else:
                ra, rb = np.hypot(p[a, 0], p[a, 1]), np.hypot(p[b, 0], p[b, 1])
                dot = (p[a, 0] * p[b, 0] + p[a, 1] * p[b, 1]) / np.maximum(ra * rb, 1e-300)
                ang = np.arccos(np.clip(dot, -1, 1))
                sel = (surf[mid] & (np.abs(ra - r) < 1e-6 * r) & (np.abs(rb - r) < 1e-6 * r) & (ang <= max_ang))
                rho = np.hypot(p[mid[sel], 0], p[mid[sel], 1])
                ok = rho > 0
                ids = mid[sel][ok]
                p[ids, 0] *= r / rho[ok]
                p[ids, 1] *= r / rho[ok]
