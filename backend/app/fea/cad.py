"""CAD import (STEP / IGES / STL) -> tetrahedral mesh, by running app.fea.cad_worker (Gmsh) in a subprocess with a timeout."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Tuple

import numpy as np

FORMATS = (".step", ".stp", ".iges", ".igs", ".stl")
UNITS = {"m": 1.0, "mm": 1e-3, "cm": 1e-2, "in": 0.0254}
TIMEOUT_S = 180
BACKEND_DIR = Path(__file__).resolve().parents[2]


class CadError(ValueError):
    """A problem with the uploaded CAD file or the requested meshing parameters (user-facing)."""


def available() -> bool:
    return importlib.util.find_spec("gmsh") is not None


def mesh_cad(raw: bytes, filename: str, size: float, order: int, unit: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (nodes in metres, elements (Abaqus node order), cumulative element count per solid)."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in FORMATS:
        raise CadError("Unsupported CAD format. Use .step/.stp, .iges/.igs or .stl.")
    if order not in (1, 2):
        raise CadError("order must be 1 (Tet4) or 2 (Tet10)")
    if unit not in UNITS:
        raise CadError(f"unit must be one of: {', '.join(UNITS)}")
    if size < 0 or not np.isfinite(size):
        raise CadError("The element size must be positive (or 0 for automatic).")
    if not raw:
        raise CadError("The file is empty.")
    if not available():
        raise RuntimeError("Gmsh is not installed on the server, so CAD files cannot be meshed. Install it with: pip install gmsh")
    with tempfile.TemporaryDirectory(prefix="gfea_cad_") as tmp:
        src = os.path.join(tmp, "model" + ext)
        out = os.path.join(tmp, "mesh.npz")
        with open(src, "wb") as f:
            f.write(raw)
        cmd = [sys.executable, "-m", "app.fea.cad_worker", src, out, repr(float(size)), str(order), repr(UNITS[unit])]
        try:
            res = subprocess.run(cmd, cwd=str(BACKEND_DIR), capture_output=True, text=True, timeout=TIMEOUT_S,
                                 env={**os.environ, "PYTHONPATH": str(BACKEND_DIR)})
        except subprocess.TimeoutExpired:
            raise CadError(f"Meshing took longer than {TIMEOUT_S} s. Use a larger element size or a simpler model.") from None
        if res.returncode == 2:
            msg = (res.stderr.strip().splitlines() or ["CAD import failed."])[-1]
            raise CadError(msg)
        if res.returncode != 0 or not os.path.exists(out):
            raise CadError("The CAD kernel stopped unexpectedly while reading this file. It may be corrupt or too complex.")
        with np.load(out) as data:                      # close the file before the temp directory is removed (Windows)
            return data["nodes"].copy(), data["elems"].copy(), data["part_ends"].copy()
