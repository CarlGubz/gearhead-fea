"""
WebFEA backend - FastAPI application.

Endpoints cover the full PrePoMax-like workflow:
  1. Project CRUD
  2. Pre-processing: primitive mesh generation / custom mesh upload,
     material assignment, boundary conditions, loads
  3. Solve: run a job (CalculiX if installed, else the built-in solver)
  4. Post-processing: fetch displacement / stress fields for 3D contour
     plots in the browser
"""
from __future__ import annotations

import threading
from typing import List

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import models, schemas, mesh, calculix, jobs
from .database import Base, engine, get_db

Base.metadata.create_all(bind=engine)

app = FastAPI(title="WebFEA", description="Browser-based CAD/CAE FEA suite", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "calculix_available": calculix.is_available(),
    }


# ---------------------------------------------------------------- Projects
@app.post("/api/projects", response_model=schemas.ProjectOut)
def create_project(payload: schemas.ProjectCreate, db: Session = Depends(get_db)):
    project = models.Project(
        name=payload.name,
        description=payload.description or "",
        nodes=[],
        elements=[],
        surface_faces=[],
        material={"name": "Steel", "E": 210e9, "nu": 0.3, "density": 7850.0},
        boundary_conditions=[],
        loads=[],
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.get("/api/projects", response_model=List[schemas.ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(models.Project).order_by(models.Project.updated_at.desc()).all()


@app.get("/api/projects/{project_id}", response_model=schemas.ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    db.delete(project)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ Mesh
@app.post("/api/projects/{project_id}/mesh/primitive", response_model=schemas.ProjectOut)
def generate_primitive(project_id: str, payload: schemas.PrimitiveMeshRequest, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    try:
        nodes, elements = mesh.generate_primitive_mesh(payload.shape, payload.dims, payload.divisions)
        faces = mesh.extract_surface_faces(elements)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Mesh generation failed: {exc}")

    project.nodes = nodes.tolist()
    project.elements = elements.tolist()
    project.surface_faces = faces.tolist()
    project.boundary_conditions = []
    project.loads = []
    db.commit()
    db.refresh(project)
    return project


@app.post("/api/projects/{project_id}/mesh/custom", response_model=schemas.ProjectOut)
def upload_custom_mesh(
    project_id: str,
    nodes: List[List[float]],
    elements: List[List[int]],
    db: Session = Depends(get_db),
):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    try:
        n, e = mesh.mesh_from_arrays(nodes, elements)
        faces = mesh.extract_surface_faces(e)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Invalid mesh: {exc}")

    project.nodes = n.tolist()
    project.elements = e.tolist()
    project.surface_faces = faces.tolist()
    project.boundary_conditions = []
    project.loads = []
    db.commit()
    db.refresh(project)
    return project


# -------------------------------------------------------------- Material
@app.put("/api/projects/{project_id}/material", response_model=schemas.ProjectOut)
def set_material(project_id: str, payload: schemas.MaterialUpdate, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    project.material = payload.model_dump()
    db.commit()
    db.refresh(project)
    return project


# ------------------------------------------------------ Boundary conditions
@app.post("/api/projects/{project_id}/bcs", response_model=schemas.ProjectOut)
def add_bc(project_id: str, payload: schemas.BoundaryCondition, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    bc = payload.model_dump()
    bc["id"] = bc.get("id") or models.gen_id()
    bcs = list(project.boundary_conditions or [])
    bcs.append(bc)
    project.boundary_conditions = bcs
    db.commit()
    db.refresh(project)
    return project


@app.delete("/api/projects/{project_id}/bcs/{bc_id}", response_model=schemas.ProjectOut)
def delete_bc(project_id: str, bc_id: str, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    project.boundary_conditions = [b for b in (project.boundary_conditions or []) if b.get("id") != bc_id]
    db.commit()
    db.refresh(project)
    return project


# -------------------------------------------------------------------- Loads
@app.post("/api/projects/{project_id}/loads", response_model=schemas.ProjectOut)
def add_load(project_id: str, payload: schemas.Load, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    ld = payload.model_dump()
    ld["id"] = ld.get("id") or models.gen_id()
    loads = list(project.loads or [])
    loads.append(ld)
    project.loads = loads
    db.commit()
    db.refresh(project)
    return project


@app.delete("/api/projects/{project_id}/loads/{load_id}", response_model=schemas.ProjectOut)
def delete_load(project_id: str, load_id: str, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    project.loads = [l for l in (project.loads or []) if l.get("id") != load_id]
    db.commit()
    db.refresh(project)
    return project


# --------------------------------------------------------------------- Jobs
@app.post("/api/projects/{project_id}/solve", response_model=schemas.JobOut)
def solve(project_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.elements:
        raise HTTPException(400, "Project has no mesh yet")

    job = models.Job(project_id=project.id, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    def _run():
        from .database import SessionLocal
        session = SessionLocal()
        try:
            j = session.get(models.Job, job.id)
            p = session.get(models.Project, project.id)
            jobs.run_job(session, j, p)
        finally:
            session.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return job


@app.get("/api/jobs/{job_id}", response_model=schemas.JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/projects/{project_id}/jobs", response_model=List[schemas.JobOut])
def list_jobs(project_id: str, db: Session = Depends(get_db)):
    return (
        db.query(models.Job)
        .filter(models.Job.project_id == project_id)
        .order_by(models.Job.created_at.desc())
        .all()
    )
