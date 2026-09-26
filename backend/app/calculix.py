"""
Optional CalculiX (ccx) integration.

If the `ccx` binary is available on PATH (install it via the OS package
manager, e.g. `apt install calculix-ccx`, or build from
http://www.calculix.de), WebFEA will write a standard CalculiX `.inp` deck,
shell out to the real CalculiX solver, and parse the resulting `.frd` file
for displacements and stresses - giving you the same industrial-grade
solver PrePoMax uses.

If `ccx` is not installed, `is_available()` returns False and the caller
(jobs.py) transparently falls back to the pure-Python solver in solver.py,
so the application is fully functional either way.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

import numpy as np


def is_available() -> bool:
    return shutil.which("ccx") is not None


def write_inp(
    path: str,
    nodes: np.ndarray,
    elements: np.ndarray,
    E: float,
    nu: float,
    density: float,
    bcs: List[dict],
    loads: List[dict],
) -> None:
    """Write a minimal static linear-elastic CalculiX input deck (C3D4 tets)."""
    lines = ["*HEADING", "WebFEA generated model", "*NODE"]
    for i, (x, y, z) in enumerate(nodes, start=1):
        lines.append(f"{i}, {x:.8f}, {y:.8f}, {z:.8f}")

    lines.append("*ELEMENT, TYPE=C3D4, ELSET=EALL")
    for i, tet in enumerate(elements, start=1):
        n = [t + 1 for t in tet]
        lines.append(f"{i}, {n[0]}, {n[1]}, {n[2]}, {n[3]}")

    lines.append("*SOLID SECTION, ELSET=EALL, MATERIAL=MAT1")
    lines.append("*MATERIAL, NAME=MAT1")
    lines.append("*ELASTIC")
    lines.append(f"{E:.6e}, {nu:.4f}")
    lines.append("*DENSITY")
    lines.append(f"{density:.4f}")

    # Node sets for BCs / loads
    for idx, bc in enumerate(bcs):
        name = f"NFIX{idx}"
        lines.append(f"*NSET, NSET={name}")
        ids = [str(n + 1) for n in bc["node_ids"]]
        for chunk_start in range(0, len(ids), 8):
            lines.append(", ".join(ids[chunk_start:chunk_start + 8]))

    for idx, ld in enumerate(loads):
        name = f"NLOAD{idx}"
        lines.append(f"*NSET, NSET={name}")
        ids = [str(n + 1) for n in ld["node_ids"]]
        for chunk_start in range(0, len(ids), 8):
            lines.append(", ".join(ids[chunk_start:chunk_start + 8]))

    lines.append("*STEP")
    lines.append("*STATIC")

    lines.append("*BOUNDARY")
    for idx, bc in enumerate(bcs):
        name = f"NFIX{idx}"
        vals = bc.get("values") or [0.0] * len(bc["dofs"])
        for dof, val in zip(bc["dofs"], vals):
            lines.append(f"{name}, {dof + 1}, {dof + 1}, {val:.6f}")

    lines.append("*CLOAD")
    for idx, ld in enumerate(loads):
        name = f"NLOAD{idx}"
        n_targets = max(1, len(ld["node_ids"]))
        fx, fy, fz = [v / n_targets for v in ld["vector"]]
        for comp, val in zip((1, 2, 3), (fx, fy, fz)):
            if abs(val) > 0:
                lines.append(f"{name}, {comp}, {val:.6f}")

    lines.append("*NODE FILE")
    lines.append("U")
    lines.append("*EL FILE")
    lines.append("S")
    lines.append("*END STEP")

    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def run_ccx(job_dir: str, job_name: str = "model", timeout: int = 300) -> Tuple[bool, str]:
    """Run ccx on model.inp inside job_dir. Returns (success, combined_log)."""
    cmd = ["ccx", job_name]
    try:
        proc = subprocess.run(
            cmd, cwd=job_dir, capture_output=True, text=True, timeout=timeout
        )
        log = proc.stdout + "\n" + proc.stderr
        success = proc.returncode == 0 and os.path.exists(os.path.join(job_dir, f"{job_name}.frd"))
        return success, log
    except subprocess.TimeoutExpired as e:
        return False, f"ccx timed out after {timeout}s: {e}"
    except Exception as e:  # noqa: BLE001
        return False, f"Failed to run ccx: {e}"


def parse_frd(path: str, n_nodes: int) -> Dict[str, np.ndarray]:
    """
    Parse displacements (and von Mises stress, if present) out of a
    CalculiX .frd results file. This is a minimal parser covering the
    standard ASCII .frd output blocks (1PSTEP / -4 DISP / -4 STRESS).
    """
    displacements = np.zeros((n_nodes, 3))
    stresses = {}  # node_id(0-based) -> [sxx,syy,szz,sxy,syz,szx]

    with open(path, "r") as fh:
        content = fh.readlines()

    mode = None
    for line in content:
        if " DISP" in line and line.strip().startswith("-4"):
            mode = "disp"
            continue
        if " STRESS" in line and line.strip().startswith("-4"):
            mode = "stress"
            continue
        if line.strip().startswith("-3"):
            mode = None
            continue
        if line.strip().startswith("-1") and mode == "disp":
            parts = line.split()
            try:
                nid = int(parts[1]) - 1
                vals = [float(v) for v in parts[2:5]]
                if 0 <= nid < n_nodes:
                    displacements[nid] = vals
            except (ValueError, IndexError):
                continue
        elif line.strip().startswith("-1") and mode == "stress":
            parts = line.split()
            try:
                nid = int(parts[1]) - 1
                vals = [float(v) for v in parts[2:8]]
                stresses[nid] = vals
            except (ValueError, IndexError):
                continue

    von_mises_nodal = np.zeros(n_nodes)
    for nid, s in stresses.items():
        sxx, syy, szz, sxy, syz, szx = s
        vm = np.sqrt(
            0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
            + 3 * (sxy ** 2 + syz ** 2 + szx ** 2)
        )
        von_mises_nodal[nid] = vm

    return {"displacements": displacements, "von_mises_nodal": von_mises_nodal}


def solve_with_calculix(
    nodes: np.ndarray,
    elements: np.ndarray,
    E: float,
    nu: float,
    density: float,
    bcs: List[dict],
    loads: List[dict],
) -> Optional[Dict[str, np.ndarray]]:
    """High-level helper: write deck, run ccx, parse results. None on failure."""
    if not is_available():
        return None

    with tempfile.TemporaryDirectory(prefix="webfea_ccx_") as job_dir:
        inp_path = os.path.join(job_dir, "model.inp")
        write_inp(inp_path, nodes, elements, E, nu, density, bcs, loads)
        success, log = run_ccx(job_dir, "model")
        if not success:
            return {"error": log}
        frd_path = os.path.join(job_dir, "model.frd")
        parsed = parse_frd(frd_path, nodes.shape[0])
        parsed["log"] = log
        return parsed
