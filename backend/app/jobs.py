"""Job orchestration: picks the analysis type, then CalculiX if available
(static analysis only), else the internal solver."""
from __future__ import annotations

import datetime as dt
import traceback
from typing import Dict, List

import numpy as np
from sqlalchemy.orm import Session

from . import calculix, solver
from .models import Job, Project
from .solver import BC, Material, NodalLoad, solve_linear_static, solve_modal, solve_thermal


def _build_static_loads(nodes: np.ndarray, elements: np.ndarray, density: float, loads_raw: List[dict], gravity_cfg: dict) -> List[dict]:
    """Merge concentrated forces, pressure loads, and gravity into a single
    list of per-node equivalent nodal loads, consumable by both the internal
    solver and the CalculiX .inp writer (both accept {node_ids, vector})."""
    combined: Dict[int, np.ndarray] = {}

    def _add(nid: int, vec: np.ndarray):
        nid = int(nid)
        combined[nid] = combined.get(nid, np.zeros(3)) + vec

    for ld in loads_raw:
        load_type = ld.get("load_type", "force")
        if load_type == "force":
            vec = np.array(ld.get("vector", [0.0, 0.0, 0.0]), dtype=np.float64)
            node_ids = ld.get("node_ids", [])
            if not node_ids:
                continue
            share = vec / len(node_ids)
            for nid in node_ids:
                _add(nid, share)
        elif load_type == "pressure":
            faces = np.array(ld.get("faces") or [], dtype=np.int64)
            if faces.size == 0:
                continue
            pressure = float(ld.get("magnitude") or 0.0)
            for nid, vec in solver.pressure_nodal_forces(nodes, faces, pressure).items():
                _add(nid, vec)
        # "heat_flux" loads are not meaningful for static analysis; ignored.

    if gravity_cfg and gravity_cfg.get("enabled"):
        gvec = [gravity_cfg.get("x", 0.0), gravity_cfg.get("y", 0.0), gravity_cfg.get("z", -9.81)]
        for nid, vec in solver.gravity_nodal_forces(nodes, elements, density, gvec).items():
            _add(nid, vec)

    return [{"node_ids": [nid], "vector": vec.tolist()} for nid, vec in combined.items()]


def run_job(db: Session, job: Job, project: Project) -> None:
    job.status = "running"
    job.progress = 0.05
    db.commit()

    try:
        nodes = np.array(project.nodes, dtype=np.float64)
        elements = np.array(project.elements, dtype=np.int64)
        mat = project.material or {}
        E = float(mat.get("E", 210e9))
        nu = float(mat.get("nu", 0.3))
        density = float(mat.get("density", 7850.0))
        conductivity = float(mat.get("conductivity", 50.0))

        bcs_raw = project.boundary_conditions or []
        loads_raw = project.loads or []
        analysis_type = project.analysis_type or "static"

        job.progress = 0.15
        db.commit()

        if analysis_type == "modal":
            _run_modal(db, job, project, nodes, elements, E, nu, density, bcs_raw)
        elif analysis_type == "thermal":
            _run_thermal(db, job, project, nodes, elements, conductivity, bcs_raw, loads_raw)
        else:
            _run_static(db, job, project, nodes, elements, E, nu, density, bcs_raw, loads_raw)

        job.status = "completed"
        job.progress = 1.0
        job.finished_at = dt.datetime.utcnow()
        db.commit()

    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.log = f"{exc}\n\n{traceback.format_exc()}"
        job.progress = 1.0
        job.finished_at = dt.datetime.utcnow()
        db.commit()


def _run_static(db, job, project, nodes, elements, E, nu, density, bcs_raw, loads_raw):
    if not bcs_raw:
        raise ValueError("Add at least one boundary condition before running a job.")

    effective_loads = _build_static_loads(nodes, elements, density, loads_raw, project.gravity)
    if not effective_loads:
        raise ValueError("Add at least one load (force, pressure, or enable gravity) before running a job.")

    result_used = "internal"
    ccx_result = None
    if calculix.is_available():
        ccx_result = calculix.solve_with_calculix(nodes, elements, E, nu, density, bcs_raw, effective_loads)

    if ccx_result is not None and "error" not in ccx_result:
        result_used = "calculix"
        job.progress = 0.8
        db.commit()
        displacements = ccx_result["displacements"]
        von_mises_nodal = ccx_result["von_mises_nodal"]
        max_disp = float(np.linalg.norm(displacements, axis=1).max()) if len(displacements) else 0.0
        max_vm = float(von_mises_nodal.max()) if len(von_mises_nodal) else 0.0
        log = ccx_result.get("log", "")
        reactions = np.zeros_like(displacements)
        von_mises_element = []
        principal_max_nodal = ccx_result["principal_stress_max_nodal"].tolist()
        principal_min_nodal = ccx_result["principal_stress_min_nodal"].tolist()
    else:
        if ccx_result is not None and "error" in ccx_result:
            log_prefix = f"CalculiX run failed, falling back to internal solver.\n{ccx_result['error']}\n\n"
        else:
            log_prefix = "CalculiX (ccx) not found on PATH - using built-in Python solver.\n\n"

        bcs = [BC(node_ids=b["node_ids"], dofs=b["dofs"], values=b.get("values")) for b in bcs_raw]
        loads = [NodalLoad(node_ids=l["node_ids"], vector=l["vector"]) for l in effective_loads]
        material = Material(E=E, nu=nu, density=density)

        job.progress = 0.4
        db.commit()

        res = solve_linear_static(nodes, elements, material, bcs, loads)

        job.progress = 0.85
        db.commit()

        displacements = res.displacements
        von_mises_nodal = res.von_mises_nodal
        von_mises_element = res.von_mises_element.tolist()
        principal_max_nodal = res.principal_max_nodal.tolist()
        principal_min_nodal = res.principal_min_nodal.tolist()
        max_disp = res.max_displacement
        max_vm = res.max_von_mises
        reactions = res.reaction_forces
        log = log_prefix + "Solve completed successfully."

    job.results = {
        "analysis_type": "static",
        "displacements": displacements.tolist() if hasattr(displacements, "tolist") else displacements,
        "von_mises_nodal": von_mises_nodal.tolist() if hasattr(von_mises_nodal, "tolist") else von_mises_nodal,
        "von_mises_element": von_mises_element,
        "principal_stress_max_nodal": principal_max_nodal,
        "principal_stress_min_nodal": principal_min_nodal,
        "reaction_forces": reactions.tolist() if hasattr(reactions, "tolist") else reactions,
        "max_displacement": max_disp,
        "max_von_mises": max_vm,
    }
    job.solver_used = result_used
    job.log = log


def _run_modal(db, job, project, nodes, elements, E, nu, density, bcs_raw):
    if not bcs_raw:
        raise ValueError("Add at least one boundary condition (support) before running a modal analysis.")

    bcs = [BC(node_ids=b["node_ids"], dofs=b["dofs"], values=b.get("values")) for b in bcs_raw]
    material = Material(E=E, nu=nu, density=density)
    n_modes = int(project.n_modes or 6)

    job.progress = 0.4
    db.commit()

    res = solve_modal(nodes, elements, material, bcs, n_modes=n_modes)

    job.progress = 0.9
    db.commit()

    job.results = {
        "analysis_type": "modal",
        "frequencies_hz": res.frequencies_hz.tolist(),
        "mode_shapes": [m.tolist() for m in res.mode_shapes],
    }
    job.solver_used = "internal"
    job.log = (
        "Modal (natural frequency) analysis completed using the built-in "
        "solver. CalculiX passthrough for *FREQUENCY steps is not "
        "implemented yet, so this analysis type always uses the internal "
        "eigensolver."
    )


def _run_thermal(db, job, project, nodes, elements, conductivity, bcs_raw, loads_raw):
    temp_bcs = {}
    for bc in bcs_raw:
        vals = bc.get("values") or [0.0] * len(bc.get("node_ids", []))
        val = vals[0] if vals else 0.0
        for nid in bc.get("node_ids", []):
            temp_bcs[int(nid)] = float(val)

    if not temp_bcs:
        raise ValueError("Add at least one fixed-temperature boundary condition before running a thermal analysis.")

    heat_loads: Dict[int, float] = {}
    for ld in loads_raw:
        if ld.get("load_type") != "heat_flux":
            continue
        node_ids = ld.get("node_ids", [])
        if not node_ids:
            continue
        magnitude = float(ld.get("magnitude") or 0.0)
        share = magnitude / len(node_ids)
        for nid in node_ids:
            heat_loads[int(nid)] = heat_loads.get(int(nid), 0.0) + share

    job.progress = 0.4
    db.commit()

    res = solve_thermal(nodes, elements, conductivity, temp_bcs, heat_loads)

    job.progress = 0.9
    db.commit()

    job.results = {
        "analysis_type": "thermal",
        "temperatures": res.temperatures.tolist(),
        "max_temperature": res.max_temperature,
        "min_temperature": res.min_temperature,
    }
    job.solver_used = "internal"
    job.log = (
        "Steady-state thermal analysis completed using the built-in solver. "
        "CalculiX passthrough for *HEAT TRANSFER steps is not implemented "
        "yet, so this analysis type always uses the internal solver."
    )
