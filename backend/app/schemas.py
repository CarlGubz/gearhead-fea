"""Pydantic request/response schemas for projects, meshes, models and jobs."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default="", max_length=2000)


class PrimitiveMeshRequest(BaseModel):
    """Generate a mesh for a primitive (box, cylinder, sphere, tube, plate_hole, lbracket)."""
    shape: str
    dims: Dict[str, float] = {}
    divisions: int = Field(default=4, ge=1, le=24)
    element_type: str = "C3D4"   # C3D4 | C3D10 | C3D8 | C3D20


class AppendPartRequest(PrimitiveMeshRequest):
    offset: List[float] = [0.0, 0.0, 0.0]
    name: Optional[str] = Field(default=None, max_length=60)
    material_id: Optional[str] = None


class MaterialUpdate(BaseModel):
    name: str = "Steel"
    E: float = Field(default=210e9, gt=0)               # Young's modulus, Pa
    nu: float = Field(default=0.3, gt=-1, lt=0.5)       # Poisson's ratio
    density: float = Field(default=7850.0, ge=0)        # kg/m^3
    conductivity: float = Field(default=50.0, ge=0)     # W/(m K)
    specific_heat: float = Field(default=490.0, ge=0)   # J/(kg K)
    alpha: float = 0.0                                  # thermal expansion, 1/K
    yield_stress: float = Field(default=0.0, ge=0)      # Pa, 0 = elastic
    hardening: float = Field(default=0.0, ge=0)         # Pa, linear isotropic hardening modulus


class MaterialItem(MaterialUpdate):
    """A material library entry (name + properties)."""
    name: str = Field(default="Material", min_length=1, max_length=60)


class PartUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    material_id: Optional[str] = None


class TranslateRequest(BaseModel):
    offset: List[float] = Field(min_length=3, max_length=3)


class BoundaryCondition(BaseModel):
    """
    bc_type: "displacement" (fixed/pinned/symmetry/prescribed; `dofs` subset of 0..2, or 0..5 on a
    reference point) or "temperature" (fixed temperature in values[0]). If omitted, thermal analyses
    treat every BC as a temperature BC and mechanical analyses as a displacement BC.
    """
    id: Optional[str] = None
    name: str = "Fixed"
    bc_type: Optional[str] = None
    node_ids: List[int] = []
    ref_id: Optional[str] = None
    dofs: List[int] = []
    values: Optional[List[float]] = None


class Load(BaseModel):
    """
    load_type:
      force         total `vector` [N] split across node_ids
      pressure      `faces` + `magnitude` (Pa, positive = into the surface)
      traction      `faces` + `vector` (Pa)
      ref_force     `ref_id` + `vector` [N] + `moment` [N m] on a reference point
      heat_flux     concentrated nodal heat `magnitude` [W] split across node_ids
      surface_flux  `faces` + `magnitude` [W/m^2], positive = heat into the body
      body_heat     `magnitude` [W/m^3] in the whole volume
      convection    `faces` + `h` [W/m^2K] + `T_inf`
      radiation     `faces` + `emissivity` + `T_inf`
    """
    id: Optional[str] = None
    name: str = "Force"
    load_type: str = "force"
    node_ids: List[int] = []
    vector: List[float] = [0.0, 0.0, 0.0]
    moment: List[float] = [0.0, 0.0, 0.0]
    faces: Optional[List[List[int]]] = None
    magnitude: Optional[float] = None
    h: Optional[float] = None
    T_inf: Optional[float] = None
    emissivity: Optional[float] = None
    ref_id: Optional[str] = None


class GravityUpdate(BaseModel):
    enabled: bool = False
    x: float = 0.0
    y: float = 0.0
    z: float = -9.81


class AnalysisTypeUpdate(BaseModel):
    analysis_type: str
    n_modes: int = Field(default=6, ge=1, le=50)


class SettingsUpdate(BaseModel):
    """Merged into project.settings. Unknown keys are rejected so typos surface early."""
    model_config = ConfigDict(extra="forbid")
    n_modes: Optional[int] = Field(default=None, ge=1, le=50)
    increments: Optional[int] = Field(default=None, ge=1, le=200)
    t_end: Optional[float] = Field(default=None, gt=0)
    n_steps: Optional[int] = Field(default=None, ge=1, le=20000)
    theta: Optional[float] = Field(default=None, ge=0.5, le=1.0)
    initial_temperature: Optional[float] = None
    reference_temperature: Optional[float] = None
    uniform_temperature: Optional[float] = None
    absolute_zero: Optional[float] = None
    thermal_mode: Optional[str] = None
    linear_solver: Optional[str] = None
    auto_threshold: Optional[int] = Field(default=None, ge=1000)
    solver_tolerance: Optional[float] = Field(default=None, gt=0, le=1e-2)
    rayleigh_alpha: Optional[float] = Field(default=None, ge=0)
    rayleigh_beta: Optional[float] = Field(default=None, ge=0)
    history_nodes: Optional[List[int]] = None
    amplitude: Optional[Dict[str, Any]] = None
    centrifugal: Optional[Dict[str, Any]] = None
    clear: Optional[List[str]] = None  # keys to remove (e.g. uniform_temperature)

    @field_validator("linear_solver")
    @classmethod
    def _solver(cls, v):
        if v not in (None, "auto", "direct", "iterative"):
            raise ValueError("linear_solver must be 'auto', 'direct' or 'iterative'")
        return v

    @field_validator("thermal_mode")
    @classmethod
    def _mode(cls, v):
        if v not in (None, "steady", "transient"):
            raise ValueError("thermal_mode must be 'steady' or 'transient'")
        return v


class ReferencePoint(BaseModel):
    id: Optional[str] = None
    name: str = "RP"
    coords: List[float] = Field(min_length=3, max_length=3)


class Constraint(BaseModel):
    """rigid: ref_id + (faces | node_ids).  tie: slave_faces|slave_node_ids + master_faces (+ tolerance)."""
    id: Optional[str] = None
    name: str = "Constraint"
    type: str
    ref_id: Optional[str] = None
    faces: Optional[List[List[int]]] = None
    node_ids: List[int] = []
    slave_faces: Optional[List[List[int]]] = None
    slave_node_ids: List[int] = []
    master_faces: Optional[List[List[int]]] = None
    tolerance: Optional[float] = None
    master_part: Optional[str] = None   # tie/contact: the two parts involved
    slave_part: Optional[str] = None
    penalty_factor: Optional[float] = Field(default=None, gt=0, le=1e6)   # contact stiffness multiplier (default 10)


class NodeSet(BaseModel):
    id: Optional[str] = None
    name: str = Field(min_length=1, max_length=60)
    kind: str = "nodes"  # "nodes" | "faces"
    ids: List[Any] = []


_DEFAULTS = {
    "element_type": "C3D4", "settings": {}, "reference_points": [], "constraints": [], "node_sets": [],
    "materials": [], "parts": [], "surface_parts": [], "history_pos": -1, "history_labels": [],
    "gravity": {"enabled": False, "x": 0.0, "y": 0.0, "z": -9.81},
}


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str
    nodes: List[List[float]]
    elements: List[List[int]]
    surface_faces: List[List[int]]
    element_type: str = "C3D4"
    material: Dict[str, Any]
    boundary_conditions: List[Dict[str, Any]]
    loads: List[Dict[str, Any]]
    analysis_type: str
    n_modes: int
    gravity: Dict[str, Any]
    settings: Dict[str, Any] = {}
    reference_points: List[Dict[str, Any]] = []
    constraints: List[Dict[str, Any]] = []
    node_sets: List[Dict[str, Any]] = []
    materials: List[Dict[str, Any]] = []
    parts: List[Dict[str, Any]] = []
    surface_parts: List[int] = []
    history_pos: int = -1
    history_labels: List[str] = []

    @model_validator(mode="wrap")
    @classmethod
    def _fill_nulls(cls, data, handler):
        # Rows created before v3 hold NULL in the new columns: serve defaults instead of failing validation.
        if not isinstance(data, dict):
            values = {k: getattr(data, k, None) for k in cls.model_fields}
            data = {k: (_DEFAULTS[k] if v is None and k in _DEFAULTS else v) for k, v in values.items()}
        if isinstance(data, dict) and data.get("elements"):
            # projects created before parts existed: serve one implicit part
            if not data.get("parts"):
                data["parts"] = [{"id": "p0", "name": "Body", "elem_start": 0, "elem_end": len(data["elements"]),
                                  "material_id": "default"}]
            if not data.get("surface_parts"):
                data["surface_parts"] = [0] * len(data.get("surface_faces") or [])
        return handler(data)


class ProjectSummary(BaseModel):
    """Light listing row (no mesh or result arrays)."""
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str = ""
    analysis_type: str = "static"


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    status: str
    solver_used: str
    log: str
    progress: float
    results: Dict[str, Any]
