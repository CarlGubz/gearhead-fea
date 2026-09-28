"""
Internal FEA solver: linear-static structural, modal (natural frequency),
and steady-state thermal analysis.

This is a real, self-contained finite element implementation (no external
solver binary required) so the application works out of the box. It is used
automatically whenever the CalculiX (`ccx`) binary is not found on PATH (for
static analysis only - see calculix.py); modal and thermal analyses always
run through this internal solver.

Formulation
-----------
- Element type: 4-node linear tetrahedron (Tet4), constant strain/gradient.
- Material: isotropic linear elastic (Young's modulus E, Poisson ratio nu),
  plus isotropic thermal conductivity for thermal analysis.
- Static analysis: small-deformation linear equilibrium, K u = f. Boundary
  conditions are prescribed nodal displacements (Dirichlet), applied via
  row/column elimination so they are satisfied exactly. Loads are
  concentrated nodal forces; distributed pressure and gravity body forces
  are converted to statically-equivalent nodal forces before assembly (see
  `pressure_nodal_forces` / `gravity_nodal_forces`).
- Modal analysis: undamped free-vibration eigenproblem K v = omega^2 M v,
  solved on the constrained (free) degrees of freedom with a lumped
  (diagonal) element mass matrix.
- Thermal analysis: steady-state heat conduction, K_t T = Q, one scalar
  temperature DOF per node, prescribed-temperature Dirichlet BCs, and
  concentrated nodal heat sources as loads.
- Post-processing: element strain/stress (constant per element for Tet4),
  von Mises stress and principal stresses, then averaged onto nodes for
  smooth contour plots.

The stiffness assembly and solves use SciPy sparse matrices, so meshes of a
few thousand nodes solve in well under a second, and tens of thousands solve
in a few seconds - suitable for interactive use in the browser.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.sparse import lil_matrix, csr_matrix, diags
from scipy.sparse.linalg import spsolve, eigsh


@dataclass
class Material:
    E: float = 210e9
    nu: float = 0.3
    density: float = 7850.0
    conductivity: float = 50.0      # W/(m*K), used by thermal analysis only
    specific_heat: float = 490.0    # J/(kg*K), reserved for transient thermal


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
    displacements: np.ndarray            # (N,3)
    von_mises_nodal: np.ndarray          # (N,)
    von_mises_element: np.ndarray        # (M,)
    principal_max_nodal: np.ndarray      # (N,) S1, most tensile
    principal_min_nodal: np.ndarray      # (N,) S3, most compressive
    max_displacement: float
    max_von_mises: float
    reaction_forces: np.ndarray          # (N,3)


@dataclass
class ModalResult:
    frequencies_hz: np.ndarray           # (n_modes,)
    mode_shapes: List[np.ndarray]        # each (N,3), normalized to unit max component


@dataclass
class ThermalResult:
    temperatures: np.ndarray             # (N,)
    max_temperature: float
    min_temperature: float


def _constitutive_matrix(E: float, nu: float) -> np.ndarray:
    """6x6 isotropic elasticity matrix in Voigt notation (stress = D * strain)."""
    lam = E * nu / ((1 + nu) * (1 - 2 * nu))
    mu = E / (2 * (1 + nu))
    D = np.zeros((6, 6))
    D[0, 0] = D[1, 1] = D[2, 2] = lam + 2 * mu
    D[0, 1] = D[1, 0] = D[0, 2] = D[2, 0] = D[1, 2] = D[2, 1] = lam
    D[3, 3] = D[4, 4] = D[5, 5] = mu
    return D


def _tet4_shape_grads(coords: np.ndarray) -> Tuple[np.ndarray, float]:
    """
    Shape function gradients (4,3) and volume for a linear (constant-strain)
    tetrahedron. coords: (4,3) node coordinates in element order.
    grads[i] = [dNi/dx, dNi/dy, dNi/dz], constant over the element.
    """
    ones = np.ones((4, 1))
    C = np.hstack([ones, coords])  # 4x4
    volume = np.linalg.det(C) / 6.0

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
    grads = np.stack([b / V6, c / V6, d / V6], axis=1)  # (4,3)
    return grads, abs(volume)


def _tet4_strain_displacement(coords: np.ndarray) -> Tuple[np.ndarray, float]:
    """B matrix (6x12) and volume for a linear tetrahedron."""
    grads, volume = _tet4_shape_grads(coords)
    B = np.zeros((6, 12))
    for i in range(4):
        bi, ci, di = grads[i]
        B[:, i * 3:i * 3 + 3] = np.array([
            [bi, 0, 0],
            [0, ci, 0],
            [0, 0, di],
            [ci, bi, 0],
            [0, di, ci],
            [di, 0, bi],
        ])
    return B, volume


def _dof_map(tet: np.ndarray) -> np.ndarray:
    dof_map = np.empty(12, dtype=np.int64)
    for i, n in enumerate(tet):
        dof_map[i * 3:i * 3 + 3] = [n * 3, n * 3 + 1, n * 3 + 2]
    return dof_map


def _principal_stresses(sxx, syy, szz, sxy, syz, szx) -> np.ndarray:
    """Sorted ascending [S3, S2, S1] eigenvalues of the 3x3 stress tensor."""
    tensor = np.array([
        [sxx, sxy, szx],
        [sxy, syy, syz],
        [szx, syz, szz],
    ])
    return np.linalg.eigvalsh(tensor)  # ascending


# --------------------------------------------------------------- Static FEA
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

    for tet in elements:
        coords = nodes[tet]
        B, V = _tet4_strain_displacement(coords)
        elem_B.append(B)
        ke = V * (B.T @ D @ B)

        dof_map = _dof_map(tet)
        for a in range(12):
            K[dof_map[a], dof_map] += ke[a, :]

    for load in loads:
        n_targets = len(load.node_ids)
        if n_targets == 0:
            continue
        share = np.array(load.vector, dtype=np.float64) / n_targets
        for nid in load.node_ids:
            f[nid * 3:nid * 3 + 3] += share

    K = K.tocsr()

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

    reactions_flat = K @ u - f
    reactions = reactions_flat.reshape(n_nodes, 3)
    displacements = u.reshape(n_nodes, 3)

    n_elem = len(elements)
    von_mises_element = np.zeros(n_elem)
    nodal_vm_sum = np.zeros(n_nodes)
    nodal_s1_sum = np.zeros(n_nodes)
    nodal_s3_sum = np.zeros(n_nodes)
    nodal_count = np.zeros(n_nodes)

    for idx, tet in enumerate(elements):
        dof_map = _dof_map(tet)
        ue = u[dof_map]
        strain = elem_B[idx] @ ue
        stress = D @ strain  # [sxx,syy,szz,sxy,syz,szx]
        sxx, syy, szz, sxy, syz, szx = stress
        vm = np.sqrt(
            0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
            + 3 * (sxy ** 2 + syz ** 2 + szx ** 2)
        )
        von_mises_element[idx] = vm
        s3, s2, s1 = _principal_stresses(sxx, syy, szz, sxy, syz, szx)
        for n in tet:
            nodal_vm_sum[n] += vm
            nodal_s1_sum[n] += s1
            nodal_s3_sum[n] += s3
            nodal_count[n] += 1

    nodal_count[nodal_count == 0] = 1
    von_mises_nodal = nodal_vm_sum / nodal_count
    principal_max_nodal = nodal_s1_sum / nodal_count
    principal_min_nodal = nodal_s3_sum / nodal_count

    disp_mag = np.linalg.norm(displacements, axis=1)

    return SolveResult(
        displacements=displacements,
        von_mises_nodal=von_mises_nodal,
        von_mises_element=von_mises_element,
        principal_max_nodal=principal_max_nodal,
        principal_min_nodal=principal_min_nodal,
        max_displacement=float(disp_mag.max()) if len(disp_mag) else 0.0,
        max_von_mises=float(von_mises_nodal.max()) if len(von_mises_nodal) else 0.0,
        reaction_forces=reactions,
    )


# --------------------------------------------------- Distributed load -> nodal
def gravity_nodal_forces(
    nodes: np.ndarray, elements: np.ndarray, density: float, gravity_vector: List[float]
) -> Dict[int, np.ndarray]:
    """
    Convert a uniform gravitational body force (self-weight) into
    statically-equivalent lumped nodal forces: each element's weight
    (density * volume * g) is split evenly across its 4 nodes.
    """
    g = np.array(gravity_vector, dtype=np.float64)
    forces: Dict[int, np.ndarray] = {}
    for tet in elements:
        coords = nodes[tet]
        _, volume = _tet4_shape_grads(coords)
        share = density * volume * g / 4.0
        for n in tet:
            n = int(n)
            forces[n] = forces.get(n, np.zeros(3)) + share
    return forces


def pressure_nodal_forces(
    nodes: np.ndarray, faces: np.ndarray, pressure: float
) -> Dict[int, np.ndarray]:
    """
    Convert a uniform normal pressure over a set of outward-oriented surface
    triangles into statically-equivalent lumped nodal forces (positive
    pressure acts inward/compressive, matching the CalculiX/PrePoMax sign
    convention). Each triangle's traction*area is split evenly across its 3
    nodes.
    """
    forces: Dict[int, np.ndarray] = {}
    for tri in faces:
        p0, p1, p2 = nodes[tri[0]], nodes[tri[1]], nodes[tri[2]]
        normal = np.cross(p1 - p0, p2 - p0)
        norm = np.linalg.norm(normal)
        if norm < 1e-14:
            continue
        unit_normal = normal / norm
        area = norm / 2.0
        f_total = -pressure * unit_normal * area
        share = f_total / 3.0
        for n in tri:
            n = int(n)
            forces[n] = forces.get(n, np.zeros(3)) + share
    return forces


# ------------------------------------------------------------- Modal analysis
def solve_modal(
    nodes: np.ndarray,
    elements: np.ndarray,
    material: Material,
    bcs: List[BC],
    n_modes: int = 6,
) -> ModalResult:
    """
    Undamped natural-frequency (eigenvalue) analysis: K v = omega^2 M v,
    solved on the free DOFs after applying the same Dirichlet supports used
    for static analysis. Uses a lumped (diagonal) element mass matrix, which
    is simple, always positive-definite, and adequate for the coarse tet
    meshes this application generates.
    """
    n_nodes = nodes.shape[0]
    n_dof = n_nodes * 3
    D = _constitutive_matrix(material.E, material.nu)

    K = lil_matrix((n_dof, n_dof))
    mass_diag = np.zeros(n_dof)

    for tet in elements:
        coords = nodes[tet]
        B, V = _tet4_strain_displacement(coords)
        ke = V * (B.T @ D @ B)
        dof_map = _dof_map(tet)
        for a in range(12):
            K[dof_map[a], dof_map] += ke[a, :]

        node_mass = material.density * V / 4.0
        for n in tet:
            mass_diag[n * 3:n * 3 + 3] += node_mass

    K = K.tocsr()

    constrained_dofs = set()
    for bc in bcs:
        for nid in bc.node_ids:
            for dof_local in bc.dofs:
                constrained_dofs.add(nid * 3 + dof_local)

    if not constrained_dofs:
        raise ValueError(
            "No boundary conditions applied - a completely free model has 6 "
            "rigid-body modes at 0 Hz and an unbounded eigenproblem. Fix at "
            "least one node before running a modal analysis."
        )

    all_dofs = np.arange(n_dof)
    fixed_dofs = np.array(sorted(constrained_dofs), dtype=np.int64)
    free_dofs = np.setdiff1d(all_dofs, fixed_dofs)

    if len(free_dofs) == 0:
        raise ValueError("The entire model is fixed - there are no free degrees of freedom left to vibrate.")

    K_ff = csr_matrix(K[np.ix_(free_dofs, free_dofs)])
    M_ff = diags(mass_diag[free_dofs]).tocsr()

    n_modes = max(1, min(n_modes, len(free_dofs) - 1))
    try:
        eigvals, eigvecs = eigsh(K_ff, k=n_modes, M=M_ff, sigma=0.0, which="LM")
    except RuntimeError as exc:
        raise ValueError(
            "Could not solve the eigenproblem - this usually means the "
            "current supports don't fully eliminate rigid-body motion (e.g. "
            "fixing a single point removes translation but not rotation "
            "about it). Fix a full face (several non-collinear nodes) "
            "instead of just one or two points."
        ) from exc

    order = np.argsort(eigvals)
    eigvals = np.clip(eigvals[order], a_min=0.0, a_max=None)
    eigvecs = eigvecs[:, order]

    frequencies_hz = np.sqrt(eigvals) / (2.0 * np.pi)

    mode_shapes = []
    for m in range(eigvecs.shape[1]):
        u = np.zeros(n_dof)
        u[free_dofs] = eigvecs[:, m]
        shape = u.reshape(n_nodes, 3)
        max_comp = np.max(np.abs(shape))
        if max_comp > 1e-14:
            shape = shape / max_comp
        mode_shapes.append(shape)

    return ModalResult(frequencies_hz=frequencies_hz, mode_shapes=mode_shapes)


# ----------------------------------------------------------- Thermal analysis
def solve_thermal(
    nodes: np.ndarray,
    elements: np.ndarray,
    conductivity: float,
    temp_bcs: Dict[int, float],
    heat_loads: Dict[int, float],
) -> ThermalResult:
    """
    Steady-state heat conduction: K_t T = Q, one scalar temperature DOF per
    node. `temp_bcs` maps node id -> prescribed temperature (Dirichlet).
    `heat_loads` maps node id -> concentrated heat source (W).
    """
    n_nodes = nodes.shape[0]
    K = lil_matrix((n_nodes, n_nodes))
    Q = np.zeros(n_nodes)

    for tet in elements:
        coords = nodes[tet]
        grads, V = _tet4_shape_grads(coords)  # (4,3)
        ke = conductivity * V * (grads @ grads.T)  # (4,4)
        for a in range(4):
            K[tet[a], tet] += ke[a, :]

    for nid, q in heat_loads.items():
        Q[nid] += q

    K = K.tocsr()

    if not temp_bcs:
        raise ValueError(
            "No fixed-temperature boundary condition applied - a model with "
            "only heat-flux loads has no unique steady-state solution. Fix "
            "the temperature of at least one node."
        )

    all_dofs = np.arange(n_nodes)
    fixed_dofs = np.array(sorted(temp_bcs.keys()), dtype=np.int64)
    free_dofs = np.setdiff1d(all_dofs, fixed_dofs)
    T_p = np.array([temp_bcs[d] for d in fixed_dofs])

    K_ff = K[np.ix_(free_dofs, free_dofs)]
    K_fp = K[np.ix_(free_dofs, fixed_dofs)]
    Q_f = Q[free_dofs] - K_fp @ T_p

    T = np.zeros(n_nodes)
    if len(free_dofs) > 0:
        T_f = spsolve(csr_matrix(K_ff), Q_f)
        T[free_dofs] = T_f
    T[fixed_dofs] = T_p

    return ThermalResult(
        temperatures=T,
        max_temperature=float(T.max()) if len(T) else 0.0,
        min_temperature=float(T.min()) if len(T) else 0.0,
    )
