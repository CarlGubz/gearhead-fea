"""
Mesh generation and geometry utilities.

Generates tetrahedral (4-node, Tet4) volume meshes for basic primitives
(box, cylinder, sphere) which is enough to cover most CAD-style "sketch and
extrude" style parts used to learn / prototype FEA, and also extracts the
outer triangulated surface of any tet mesh for 3D rendering + BC picking in
the browser.

For arbitrary CAD geometry, the same pipeline accepts an externally
generated tet mesh (e.g. produced by Gmsh or TetGen if the user has them
installed) via `mesh_from_arrays`.
"""
from __future__ import annotations

import itertools
from typing import Dict, List, Tuple

import numpy as np
from scipy.spatial import Delaunay


def _box_points(l: float, w: float, h: float, n: int) -> np.ndarray:
    xs = np.linspace(-l / 2, l / 2, n)
    ys = np.linspace(-w / 2, w / 2, n)
    zs = np.linspace(-h / 2, h / 2, n)
    grid = np.array(list(itertools.product(xs, ys, zs)))
    return grid


def _cylinder_points(r: float, h: float, n: int) -> np.ndarray:
    pts = []
    n_r = max(2, n // 2)
    n_theta = max(6, n * 2)
    n_z = max(2, n)
    for zi in np.linspace(-h / 2, h / 2, n_z):
        for ri in np.linspace(0, r, n_r):
            if ri == 0:
                pts.append([0.0, 0.0, zi])
                continue
            for ti in np.linspace(0, 2 * np.pi, n_theta, endpoint=False):
                pts.append([ri * np.cos(ti), ri * np.sin(ti), zi])
    return np.array(pts)


def _sphere_points(r: float, n: int) -> np.ndarray:
    pts = [[0.0, 0.0, 0.0]]
    n_r = max(2, n // 2)
    n_theta = max(6, n * 2)
    n_phi = max(3, n)
    for ri in np.linspace(r / n_r, r, n_r):
        for pi in np.linspace(0.15, np.pi - 0.15, n_phi):
            for ti in np.linspace(0, 2 * np.pi, n_theta, endpoint=False):
                pts.append([
                    ri * np.sin(pi) * np.cos(ti),
                    ri * np.sin(pi) * np.sin(ti),
                    ri * np.cos(pi),
                ])
    return np.array(pts)


def generate_primitive_mesh(shape: str, dims: Dict[str, float], divisions: int = 4) -> Tuple[np.ndarray, np.ndarray]:
    """Return (nodes[N,3], elements[M,4]) tetrahedral mesh for a primitive."""
    divisions = max(2, min(int(divisions), 10))

    if shape == "box":
        l = dims.get("length", 1.0)
        w = dims.get("width", 1.0)
        h = dims.get("height", 1.0)
        pts = _box_points(l, w, h, divisions)
    elif shape == "cylinder":
        r = dims.get("radius", 0.5)
        h = dims.get("height", 1.0)
        pts = _cylinder_points(r, h, divisions)
    elif shape == "sphere":
        r = dims.get("radius", 0.5)
        pts = _sphere_points(r, divisions)
    else:
        raise ValueError(f"Unknown primitive shape: {shape}")

    tri = Delaunay(pts)
    elements = tri.simplices  # (M,4) tetrahedra indices into pts

    # Drop degenerate (near-zero-volume) tets
    good = []
    for tet in elements:
        v = tet_volume(pts[tet])
        if v > 1e-12:
            good.append(tet)
    elements = np.array(good, dtype=np.int64)

    return pts.astype(np.float64), elements


def tet_volume(coords: np.ndarray) -> float:
    """Volume of a tetrahedron given its 4 (x,y,z) vertex coordinates."""
    a, b, c, d = coords
    return abs(np.dot(np.cross(b - a, c - a), d - a)) / 6.0


def extract_surface_faces(elements: np.ndarray) -> np.ndarray:
    """
    Extract the outer boundary triangles of a tet mesh: any triangular face
    that belongs to exactly one tetrahedron is a surface (boundary) face.
    Used for 3D rendering and for letting the user click faces to apply
    boundary conditions / loads without rendering every internal tet face.
    """
    face_count: Dict[Tuple[int, int, int], int] = {}
    face_orig: Dict[Tuple[int, int, int], List[int]] = {}

    for tet in elements:
        tet = list(tet)
        faces = [
            (tet[0], tet[1], tet[2]),
            (tet[0], tet[1], tet[3]),
            (tet[0], tet[2], tet[3]),
            (tet[1], tet[2], tet[3]),
        ]
        for f in faces:
            key = tuple(sorted(f))
            face_count[key] = face_count.get(key, 0) + 1
            if key not in face_orig:
                face_orig[key] = list(f)

    surface = [face_orig[k] for k, cnt in face_count.items() if cnt == 1]
    return np.array(surface, dtype=np.int64)


def mesh_from_arrays(nodes: List[List[float]], elements: List[List[int]]):
    """Pass-through validator for externally supplied tet meshes."""
    nodes_arr = np.array(nodes, dtype=np.float64)
    elements_arr = np.array(elements, dtype=np.int64)
    if elements_arr.shape[1] != 4:
        raise ValueError("Only 4-node tetrahedral (Tet4) elements are supported")
    return nodes_arr, elements_arr
