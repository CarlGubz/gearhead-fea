"""Job orchestration: picks CalculiX if available, else the internal solver."""
from __future__ import annotations

import datetime as dt
import traceback
from typing import Dict

import numpy as np
from sqlalchemy.orm import Session

from . import calculix
from .models import Job, Project
from .solver import BC, Material, NodalLoad, solve_linear_static


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

        bcs_raw = project.boundary_conditions or []
        loads_raw = project.loads or []

        if not bcs_raw:
            raise ValueError("Add at least one boundary condition before running a job.")
        if not loads_raw:
            raise ValueError("Add at least one load before running a job.")

        job.progress = 0.15
        db.commit()

        result_dict: Dict[str, np.ndarray]
        solver_used = "internal"

        ccx_result = None
        if calculix.is_available():
            ccx_result = calculix.solve_with_calculix(
                nodes, elements, E, nu, density, bcs_raw, loads_raw
            )

        if ccx_result is not None and "error" not in ccx_result:
            solver_used = "calculix"
            job.progress = 0.8
            db.commit()
            displacements = ccx_result["displacements"]
            von_mises_nodal = ccx_result["von_mises_nodal"]
            max_disp = float(np.linalg.norm(displacements, axis=1).max()) if len(displacements) else 0.0
            max_vm = float(von_mises_nodal.max()) if len(von_mises_nodal) else 0.0
            log = ccx_result.get("log", "")
            reactions = np.zeros_like(displacements)
            von_mises_element = []
        else:
            if ccx_result is not None and "error" in ccx_result:
                log_prefix = f"CalculiX run failed, falling back to internal solver.\n{ccx_result['error']}\n\n"
            else:
                log_prefix = "CalculiX (ccx) not found on PATH - using built-in Python solver.\n\n"

            bcs = [
                BC(node_ids=b["node_ids"], dofs=b["dofs"], values=b.get("values"))
                for b in bcs_raw
            ]
            loads = [NodalLoad(node_ids=l["node_ids"], vector=l["vector"]) for l in loads_raw]
            material = Material(E=E, nu=nu, density=density)

            job.progress = 0.4
            db.commit()

            res = solve_linear_static(nodes, elements, material, bcs, loads)

            job.progress = 0.85
            db.commit()

            displacements = res.displacements
            von_mises_nodal = res.von_mises_nodal
            von_mises_element = res.von_mises_element.tolist()
            max_disp = res.max_displacement
            max_vm = res.max_von_mises
            reactions = res.reaction_forces
            log = log_prefix + "Solve completed successfully."

        job.results = {
            "displacements": displacements.tolist(),
            "von_mises_nodal": von_mises_nodal.tolist(),
            "von_mises_element": von_mises_element,
            "reaction_forces": reactions.tolist(),
            "max_displacement": max_disp,
            "max_von_mises": max_vm,
        }
        job.solver_used = solver_used
        job.status = "completed"
        job.progress = 1.0
        job.log = log
        job.finished_at = dt.datetime.utcnow()
        db.commit()

    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.log = f"{exc}\n\n{traceback.format_exc()}"
        job.progress = 1.0
        job.finished_at = dt.datetime.utcnow()
        db.commit()
