"""Pydantic request/response schemas."""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""


class PrimitiveMeshRequest(BaseModel):
    """Generate a tetrahedral mesh for a basic primitive shape."""
    shape: str  # "box", "cylinder", "sphere"
    dims: Dict[str, float] = {}
    divisions: int = 4


class MaterialUpdate(BaseModel):
    name: str = "Steel"
    E: float = 210e9          # Young's modulus, Pa
    nu: float = 0.3           # Poisson's ratio
    density: float = 7850.0   # kg/m^3
    conductivity: float = 50.0     # W/(m*K) - used by thermal analysis
    specific_heat: float = 490.0   # J/(kg*K) - reserved for transient thermal


class BoundaryCondition(BaseModel):
    """
    A Dirichlet constraint. For static/modal analysis, `dofs` is a subset of
    [0,1,2] meaning x/y/z displacement is fixed (to `values`, default 0).
    For thermal analysis, `dofs` is conventionally [0] and `values` is the
    prescribed temperature.
    """
    id: Optional[str] = None
    name: str = "Fixed"
    node_ids: List[int]
    dofs: List[int]
    values: Optional[List[float]] = None


class Load(BaseModel):
    """
    A load applied to a set of nodes/faces.
    - load_type="force": `vector` [Fx,Fy,Fz] (N) split evenly across node_ids.
    - load_type="pressure": `faces` (triangles of node ids) + `magnitude`
      (Pa, positive = compressive/inward), converted to equivalent nodal
      forces from the outward face normals.
    - load_type="heat_flux": `magnitude` (W) split evenly across node_ids,
      used by thermal analysis as a concentrated heat source.
    """
    id: Optional[str] = None
    name: str = "Force"
    load_type: str = "force"  # "force" | "pressure" | "heat_flux"
    node_ids: List[int] = []
    vector: List[float] = [0.0, 0.0, 0.0]
    faces: Optional[List[List[int]]] = None
    magnitude: Optional[float] = None


class GravityUpdate(BaseModel):
    enabled: bool = False
    x: float = 0.0
    y: float = 0.0
    z: float = -9.81


class AnalysisTypeUpdate(BaseModel):
    analysis_type: str  # "static" | "modal" | "thermal"
    n_modes: int = 6


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    nodes: List[List[float]]
    elements: List[List[int]]
    surface_faces: List[List[int]]
    material: Dict[str, Any]
    boundary_conditions: List[Dict[str, Any]]
    loads: List[Dict[str, Any]]
    analysis_type: str
    n_modes: int
    gravity: Dict[str, Any]

    class Config:
        from_attributes = True


class JobOut(BaseModel):
    id: str
    project_id: str
    status: str
    solver_used: str
    log: str
    progress: float
    results: Dict[str, Any]

    class Config:
        from_attributes = True
