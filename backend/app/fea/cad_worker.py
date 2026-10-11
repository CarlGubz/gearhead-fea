"""
CAD -> tetrahedral mesh worker (runs in its own process: `python -m app.fea.cad_worker <in> <out.npz> <size> <order> <scale>`).

A separate process isolates the API server from the geometry kernel (crashes, hangs, memory) and lets the caller enforce a
timeout. Gmsh (OpenCASCADE) reads STEP / IGES / STL and meshes every solid with Tet4 or Tet10 elements.

Exit code 0 and the .npz written: nodes (n,3) in metres, elems (m, 4|10) in Abaqus node order, part_ends (k,) cumulative
element counts per solid. Any failure prints one readable line to stderr and exits with code 2.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

STEP_EXT = (".step", ".stp")
IGES_EXT = (".iges", ".igs")
STL_EXT = (".stl",)


class CadError(Exception):
    pass


def _fail(msg: str):
    print(msg, file=sys.stderr)
    sys.exit(2)


def _read_stl_header(path: str) -> int:
    """Number of facets in a binary or ASCII STL (cheap sanity check before meshing)."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(84)
    if len(head) >= 84:
        n = int.from_bytes(head[80:84], "little")
        if 84 + 50 * n == size:
            return n
    with open(path, "rb") as f:
        return f.read().count(b"endfacet")


def build(path: str, size_m: float, order: int, scale: float, straight: bool = False):
    import gmsh

    ext = os.path.splitext(path)[1].lower()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add("cad")
        size_file = size_m / scale                               # gmsh works in the file's own length unit
        if ext in STEP_EXT + IGES_EXT:
            try:
                gmsh.model.occ.importShapes(path)
                gmsh.model.occ.synchronize()
            except Exception as exc:  # noqa: BLE001
                raise CadError(f"Could not read the CAD file ({str(exc).splitlines()[0][:120]}).") from exc
            vols = [t for d, t in gmsh.model.getEntities(3)]
            if not vols:
                # surface-only files (typical for IGES): sew the faces into one closed shell and make a solid of it
                surfs = [t for d, t in gmsh.model.getEntities(2)]
                if not surfs:
                    raise CadError("The file contains no solid bodies or surfaces. Export solids from your CAD program.")
                try:
                    loop = gmsh.model.occ.addSurfaceLoop(surfs, sewing=True)
                    gmsh.model.occ.addVolume([loop])
                    gmsh.model.occ.synchronize()
                except Exception as exc:  # noqa: BLE001
                    raise CadError("The file holds surfaces that do not form one closed shell, so no solid could be built. "
                                   "Export a solid body from your CAD program.") from exc
                vols = [t for d, t in gmsh.model.getEntities(3)]
                if not vols:
                    raise CadError("The surfaces in the file do not enclose a volume. Export a solid body.")
        elif ext in STL_EXT:
            n_facets = _read_stl_header(path)
            if n_facets == 0:
                raise CadError("The STL file contains no triangles.")
            if n_facets > 120_000:
                raise CadError(f"The STL has {n_facets:,} facets (limit 120,000). Decimate it first.")
            try:
                gmsh.merge(path)
                gmsh.model.mesh.classifySurfaces(math.radians(40.0), True, True, math.pi)
                gmsh.model.mesh.createGeometry()
                surfaces = [t for d, t in gmsh.model.getEntities(2)]
                if not surfaces:
                    raise CadError("No surface was found in the STL file.")
                loop = gmsh.model.geo.addSurfaceLoop(surfaces)
                gmsh.model.geo.addVolume([loop])
                gmsh.model.geo.synchronize()
            except CadError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise CadError(f"Could not build a solid from the STL surface ({str(exc).splitlines()[0][:120]}).") from exc
            vols = [t for d, t in gmsh.model.getEntities(3)]
        else:
            raise CadError("Unsupported CAD format. Use .step/.stp, .iges/.igs or .stl.")

        # bounding box -> sanity checks on the requested element size
        xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
        diag_file = math.sqrt((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2)
        if diag_file <= 0:
            raise CadError("The geometry has zero size.")
        if size_file <= 0:
            size_file = diag_file / 12.0
        if diag_file / size_file > 150:
            raise CadError(f"Element size {size_m:g} m is too small for a part this large (more than 150 elements across). Use a larger size.")
        if size_file > diag_file:
            size_file = diag_file / 2.0
        gmsh.option.setNumber("Mesh.MeshSizeMax", size_file)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size_file * 0.15)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        try:
            gmsh.model.mesh.generate(3)
        except Exception as exc:  # noqa: BLE001
            raise CadError("Volume meshing failed. For STL files the surface must be closed (watertight) without self-intersections; "
                           "for STEP/IGES try a slightly larger element size.") from exc
        if order == 2:
            # STL geometry is faceted already, so mid-side nodes stay on the straight edges there (curving them onto
            # the facets can fold thin elements); STEP/IGES curve the mid-side nodes onto the exact surface.
            gmsh.option.setNumber("Mesh.SecondOrderLinear", 1 if (straight or ext in STL_EXT) else 0)
            gmsh.model.mesh.setOrder(2)

        etype = 4 if order == 1 else 11
        tags, coords, _ = gmsh.model.mesh.getNodes()
        tags = np.asarray(tags, dtype=np.int64)
        tag_order = np.argsort(tags)
        tags_sorted = tags[tag_order]
        nodes = np.asarray(coords, dtype=float).reshape(-1, 3) * scale
        used_elems, ends = [], []
        total = 0
        for vol in sorted(vols):
            types, _, enodes = gmsh.model.mesh.getElements(3, vol)
            for t, en in zip(types, enodes):
                if int(t) != etype:
                    continue
                nn = 4 if etype == 4 else 10
                arr = np.asarray(en, dtype=np.int64).reshape(-1, nn)
                arr = tag_order[np.searchsorted(tags_sorted, arr)]                  # gmsh node tags -> 0-based rows
                if etype == 11:
                    arr = arr[:, [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]]           # gmsh edge order -> Abaqus order
                # discrete (STL) geometry can yield flat sliver tetrahedra with zero volume: they carry no volume, drop them
                p = nodes[arr[:, :4]]
                vol = np.abs(np.einsum("ei,ei->e", np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), p[:, 3] - p[:, 0])) / 6.0
                arr = arr[vol > 1e-6 * np.median(vol)]
                used_elems.append(arr)
                total += len(arr)
            if total and (not ends or ends[-1] != total):
                ends.append(total)
        if not used_elems:
            raise CadError("Meshing produced no tetrahedra.")
        elems = np.vstack(used_elems)
        # drop nodes that no element uses (e.g. geometry vertices of non-meshed entities)
        keep = np.unique(elems)
        remap = -np.ones(len(nodes), dtype=np.int64)
        remap[keep] = np.arange(len(keep))
        return nodes[keep], remap[elems], np.array(ends, dtype=np.int64)
    finally:
        gmsh.finalize()


def _has_inverted(nodes: np.ndarray, elems: np.ndarray) -> bool:
    """True if a quadratic tetrahedron is folded: its Jacobian changes sign inside the element (checked with the solver's own element)."""
    from app.fea.model import FEMesh
    mesh = FEMesh(nodes, elems, "C3D10")
    for sl in mesh.chunks():
        _, _, _, detJ, _ = mesh.jacobian(sl)
        if ((detJ.min(axis=1) <= 0) & (detJ.max(axis=1) >= 0)).any():
            return True
    return False


def main(argv) -> int:
    if len(argv) != 6:
        _fail("usage: cad_worker <in> <out.npz> <size_m> <order> <scale>")
    path, out, size_m, order, scale = argv[1], argv[2], float(argv[3]), int(argv[4]), float(argv[5])
    try:
        nodes, elems, ends = build(path, size_m, order, scale)
        if order == 2 and _has_inverted(nodes, elems):
            nodes, elems, ends = build(path, size_m, order, scale, straight=True)     # curved elements folded: use straight edges
    except CadError as exc:
        _fail(str(exc))
    except ImportError:
        _fail("Gmsh is not installed on the server (pip install gmsh).")
    except Exception as exc:  # noqa: BLE001
        _fail(f"CAD import failed: {str(exc).splitlines()[0][:200]}")
    np.savez(out, nodes=nodes, elems=elems, part_ends=ends)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
