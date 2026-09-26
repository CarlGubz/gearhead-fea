"""
Internal linear-static structural FEA solver.

This is a real, self-contained finite element implementation (no external
solver binary required) so the application works out of the box. It is used
automatically whenever the CalculiX (`ccx`) binary is not found on PATH; see
calculix.py for the alternative path that hands the exact same model off to
CalculiX when it is installed.

Formulation
-----------
- Element type: 4-node linear tetrahedron (Tet4), constant strain.
- Material: isotropic linear elastic (Young's modulus E, Poisson ratio nu).
- Analysis: small-deformation linear static equilibrium, K u = f.
- Boundary conditions: prescribed nodal displacements (Dirichlet), applied
  via row/column elimination so they are satisfied exactly.
- Loads: concentrated nodal forces (distributed loads are converted to
  equivalent nodal forces by the API layer before reaching the solver).
- Post-processing: element strain/stress (constant per element for Tet4),
  von Mises stress, then averaged onto nodes for smooth contour plots.

The stiffness assembly and solve use SciPy sparse matrices, so meshes of a
few thousand nodes solve in well under a second, and tens of thousands solve
in a few seconds - suitable for interactive use in the browser.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
from scipy.sparse import lil_matrix, csr_matrix
from scipy.sparse.linalg import spsolve


@dataclass
class Material:
    E: float = 210e9
    nu: float = 0.3
    density: float = 7850.0


@dataclass
class BC:
    node_ids: List[int]
    dofs: List[int]           # which of x,y,z (0,1,2) are constrained
    values: Optional[List[float]] = None  # prescribed value per dof, default 0


@dataclass
class NodalLoad:
    node_ids: List[int]
    vector: List[float]  # total [Fx,Fy,Fz], split evenly across node_ids


@dataclass
class SolveResult:
    displacements: np.ndarray   # (N,3)
    von_mises_nodal: np.ndarray  # (N,)
    von_mises_element: np.ndarray  # (M,)
    max_displacement: float
    max_von_mises: float
    reaction_forces: np.ndarray  # (N,3)


def _constitutive_matrix(E: float, nu: float) -> np.ndarray:
    """6x6 isotropic elasticity matrix in Voigt notation (stress = D * strain)."""
    lam = E * nu / ((1 + nu) * (1 - 2 * nu))
    mu = E / (2 * (1 + nu))
    D = np.zeros((6, 6))
    D[0, 0] = D[1, 1] = D[2, 2] = lam + 2 * mu
    D[0, 1] = D[1, 0] = D[0, 2] = D[2, 0] = D[1, 2] = D[2, 1] = lam
    D[3, 3] = D[4, 4] = D[5, 5] = mu
    return D


def _tet4_strain_displacement(coords: np.ndarray) -> tuple[np.ndarray, float]:
    """
    B matrix (6x12) and volume for a linear (constant-strain) tetrahedron.
    coords: (4,3) node coordinates in element order.
    """
    ones = np.ones((4, 1))
    C = np.hstack([ones, coords])  # 4x4
    volume = np.linalg.det(C) / 6.0

    # Cofactor expansion gives shape function gradients (constant over element)
    b = np.zeros(4)
    c = np.zeros(4)
    d = np.zeros(4)
    for i in range(4):
        rows = [r for r in range(4) if r != i]
        minor = C[np.ix_(rows, [0, 2, 3])]
        b[i] = ((-1) ** i) * np.linalg.det(minor)
        minor = C[np.ix_(rows, [0, 1, 3])]
        c[i] = ((-1) ** (i + 1)) * np.linalg.det(minor)
        minor = C[np.ix_(rows, [0, 1, 2])]
        d[i] = ((-1) ** i) * np.linalg.det(minor)

    V6 = 6.0 * volume
    B = np.zeros((6, 12))
    for i in range(4):
        bi, ci, di = b[i] / V6, c[i] / V6, d[i] / V6
        B[:, i * 3:i * 3 + 3] = np.array([
            [bi, 0, 0],
            [0, ci, 0],
            [0, 0, di],
            [ci, bi, 0],
            [0, di, ci],
            [di, 0, bi],
        ])
    return B, abs(volume)


def solve_linear_static(
    nodes: np.ndarray,
    elements: np.ndarray,
    material: Material,
    bcs: List[BC],
    loads: List[NodalLoad],
) -> SolveResult:
    n_nodes = nodes.shape[0]
    n_dof = n_nodes * 3
    D = _constitutive_matrix(material.E, material.nu)

    K = lil_matrix((n_dof, n_dof))
    f = np.zeros(n_dof)

    elem_B = []
    elem_V = []

    for tet in elements:
        coords = nodes[tet]
        B, V = _tet4_strain_displacement(coords)
        elem_B.append(B)
        elem_V.append(V)
        ke = V * (B.T @ D @ B)

        dof_map = np.empty(12, dtype=np.int64)
        for i, n in enumerate(tet):
            dof_map[i * 3:i * 3 + 3] = [n * 3, n * 3 + 1, n * 3 + 2]

        for a in range(12):
            K[dof_map[a], dof_map] += ke[a, :]

    # Assemble nodal loads
    for load in loads:
        n_targets = len(load.node_ids)
        if n_targets == 0:
            continue
        share = np.array(load.vector, dtype=np.float64) / n_targets
        for nid in load.node_ids:
            f[nid * 3:nid * 3 + 3] += share

    K = K.tocsr()

    # Apply Dirichlet BCs via penalty-free elimination:
    # Build the set of constrained dof -> prescribed value.
    constrained: Dict[int, float] = {}
    for bc in bcs:
        vals = bc.values if bc.values is not None else [0.0] * len(bc.dofs)
        for nid in bc.node_ids:
            for dof_local, val in zip(bc.dofs, vals):
                constrained[nid * 3 + dof_local] = val

    all_dofs = np.arange(n_dof)
    fixed_dofs = np.array(sorted(constrained.keys()), dtype=np.int64)
    free_dofs = np.setdiff1d(all_dofs, fixed_dofs)

    if len(fixed_dofs) == 0:
        raise ValueError(
            "No boundary conditions applied - the model is a rigid body and "
            "has no unique static solution. Fix at least one node."
        )

    u_p = np.array([constrained[d] for d in fixed_dofs])

    K_ff = K[np.ix_(free_dofs, free_dofs)]
    K_fp = K[np.ix_(free_dofs, fixed_dofs)]
    f_f = f[free_dofs] - K_fp @ u_p

    u = np.zeros(n_dof)
    if len(free_dofs) > 0:
        u_f = spsolve(csr_matrix(K_ff), f_f)
        u[free_dofs] = u_f
    u[fixed_dofs] = u_p

    # Reaction forces at all dofs: R = K u - f  (nonzero mainly at fixed dofs)
    reactions_flat = K @ u - f
    reactions = reactions_flat.reshape(n_nodes, 3)

    displacements = u.reshape(n_nodes, 3)

    # Element stresses (constant strain -> constant stress per Tet4)
    n_elem = len(elements)
    von_mises_element = np.zeros(n_elem)
    nodal_vm_sum = np.zeros(n_nodes)
    nodal_vm_count = np.zeros(n_nodes)

    for idx, tet in enumerate(elements):
        dof_map = np.empty(12, dtype=np.int64)
        for i, n in enumerate(tet):
            dof_map[i * 3:i * 3 + 3] = [n * 3, n * 3 + 1, n * 3 + 2]
        ue = u[dof_map]
        strain = elem_B[idx] @ ue
        stress = D @ strain  # [sxx,syy,szz,sxy,syz,szx]
        sxx, syy, szz, sxy, syz, szx = stress
        vm = np.sqrt(
            0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
            + 3 * (sxy ** 2 + syz ** 2 + szx ** 2)
        )
        von_mises_element[idx] = vm
        for n in tet:
            nodal_vm_sum[n] += vm
            nodal_vm_count[n] += 1

    nodal_vm_count[nodal_vm_count == 0] = 1
    von_mises_nodal = nodal_vm_sum / nodal_vm_count

    disp_mag = np.linalg.norm(displacements, axis=1)

    return SolveResult(
        displacements=displacements,
        von_mises_nodal=von_mises_nodal,
        von_mises_element=von_mises_element,
        max_displacement=float(disp_mag.max()) if len(disp_mag) else 0.0,
        max_von_mises=float(von_mises_nodal.max()) if len(von_mises_nodal) else 0.0,
        reaction_forces=reactions,
    )
