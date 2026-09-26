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
    E: float = 210e9      # Young's modulus, Pa
    nu: float = 0.3       # Poisson's ratio
    density: float = 7850.0  # kg/m^3


class BoundaryCondition(BaseModel):
    id: Optional[str] = None
    name: str = "Fixed"
    node_ids: List[int]
    dofs: List[int]  # subset of [0,1,2] meaning x,y,z fixed
    values: Optional[List[float]] = None  # prescribed displacement, default 0


class Load(BaseModel):
    id: Optional[str] = None
    name: str = "Force"
    node_ids: List[int]
    vector: List[float]  # [Fx, Fy, Fz] total, distributed across node_ids evenly


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
