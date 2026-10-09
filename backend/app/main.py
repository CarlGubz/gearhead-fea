"""
Gearhead FEA backend - FastAPI application.

  1. Accounts (PostgreSQL-backed) and GCash subscriptions - see routers/
  2. Project CRUD (per user), project file export/import
  3. Pre-processing: primitive meshes (tet/hex, linear/quadratic), mesh import (.inp/.msh), materials,
     steps/settings, boundary conditions, loads, reference points, constraints, named sets
  4. Solve on the built-in FE engine (app/fea) - no external solver is used
  5. Post-processing data for the browser (contours, mode shapes, time histories)
"""
from __future__ import annotations

import datetime as dt
import threading
from typing import Any, Dict, List

from fastapi import Body, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from . import history, jobs, models, parts as parts_mod, plans, schemas
from .config import settings
from .database import Base, engine, get_db
from .deps import current_user, owned_project, require_pro_for, tier_of, verify_origin
from .fea import inp, meshgen
from .fea.elements import ELEMENT_TYPES
from .fea.model import FEMesh
from .fea.runner import ANALYSIS_TYPES
from .routers import auth as auth_router, billing as billing_router

Base.metadata.create_all(bind=engine)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_NODES = 120_000
STALE_JOB_MINUTES = 30
MAX_ACTIVE_JOBS = 2


def _migrate_schema():
    """
    Minimal, idempotent migration: `create_all` only creates missing tables, so columns added to an
    existing `projects` table later are backfilled here. Safe to run on every startup.
    """
    inspector = inspect(engine)
    if "projects" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("projects")}
    additions = {
        "analysis_type": "VARCHAR", "n_modes": "INTEGER", "gravity": "JSON",
        "element_type": "VARCHAR", "settings": "JSON", "reference_points": "JSON",
        "constraints": "JSON", "node_sets": "JSON", "materials": "JSON", "parts": "JSON", "surface_parts": "JSON",
        "history_pos": "INTEGER", "history_labels": "JSON",
    }
    with engine.begin() as conn:
        for col, typ in additions.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE projects ADD COLUMN {col} {typ}"))
        if "analysis_type" not in existing:
            conn.execute(text("UPDATE projects SET analysis_type = 'static' WHERE analysis_type IS NULL"))
        if "n_modes" not in existing:
            conn.execute(text("UPDATE projects SET n_modes = 6 WHERE n_modes IS NULL"))
        if "gravity" not in existing:
            conn.execute(text(
                "UPDATE projects SET gravity = '{\"enabled\": false, \"x\": 0.0, \"y\": 0.0, \"z\": -9.81}' "
                "WHERE gravity IS NULL"))
        if "element_type" not in existing:
            conn.execute(text("UPDATE projects SET element_type = 'C3D4' WHERE element_type IS NULL"))
        if "owner_id" not in existing:
            # Projects created before accounts existed stay ownerless (hidden).
            conn.execute(text("ALTER TABLE projects ADD COLUMN owner_id VARCHAR(32)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id)"))
            if settings.is_postgres:
                conn.execute(text(
                    "ALTER TABLE projects ADD CONSTRAINT fk_projects_owner "
                    "FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE"))


_migrate_schema()

app = FastAPI(
    title="Gearhead FEA",
    description="Browser-based CAD/CAE FEA suite with a standalone solver",
    version="3.0.0",
    dependencies=[Depends(verify_origin)],
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

if settings.extra_allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.extra_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


app.include_router(auth_router.router)
app.include_router(billing_router.router)
app.include_router(billing_router.webhooks)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "Database unavailable")
    return {"status": "ok", "solver": "gearhead-fea", "external_solver_required": False}


@app.get("/api/capabilities")
def capabilities():
    """What the engine can do - the UI builds its pickers from this."""
    return {
        "analysis_types": ANALYSIS_TYPES,
        "free_analysis_types": ["static"],
        "element_types": [{"id": k, "nodes": v.n_nodes, "kind": v.kind} for k, v in ELEMENT_TYPES.items()],
        "shapes": meshgen.SHAPES,
    }


# ------------------------------------------------------------------ helpers
def _commit(db: Session, project: models.Project, label: str = None) -> models.Project:
    """Commit an edit. With a label the edit also becomes an undo step (see history.py)."""
    if label:
        before = history.capture(project, before=True) if (project.history_pos is None or project.history_pos < 0) else None
        history.record(db, project, label, before)
    db.commit()
    db.refresh(project)
    return project


def _new_id() -> str:
    return models.gen_id()


def _fem_mesh(project: models.Project) -> FEMesh:
    if not project.elements:
        raise HTTPException(400, "Project has no mesh yet")
    return FEMesh(project.nodes, project.elements, project.element_type or "C3D4")


def _set_mesh(project: models.Project, mesh: FEMesh, part_name: str = "Body", parts=None) -> None:
    """Install a mesh (as one part, or the given parts) and clear everything that referenced the old one."""
    if mesh.n_nodes > MAX_NODES:
        raise HTTPException(413, f"Mesh too large ({mesh.n_nodes} nodes, limit {MAX_NODES}). Lower the mesh density.")
    mesh.ensure_positive_orientation()
    project.nodes = mesh.nodes.tolist()
    project.elements = mesh.elems.tolist()
    project.element_type = mesh.et.name
    project.surface_faces = mesh.boundary().tris.tolist()
    project.parts = parts if parts else parts_mod.default_parts(mesh.n_elems, part_name)
    project.surface_parts = parts_mod.surface_parts(mesh, project.parts)
    project.boundary_conditions = []
    project.loads = []
    project.constraints = []
    project.reference_points = []
    project.node_sets = []


def _check_node_ids(project: models.Project, ids) -> None:
    n = len(project.nodes or [])
    if any((not isinstance(i, int)) or i < 0 or i >= n for i in ids):
        raise HTTPException(422, "A node id is outside the mesh")


def _ref_ids(project: models.Project) -> set:
    return {r["id"] for r in (project.reference_points or [])}


def _ensure_parts(project: models.Project) -> list:
    """Persist the implicit single part of a pre-parts project and return the parts list."""
    if not project.parts:
        project.parts = parts_mod.effective_parts(None, len(project.elements or []))
        project.surface_parts = [0] * len(project.surface_faces or [])
    return [dict(p) for p in project.parts]


def _material_ids(project: models.Project) -> set:
    return {"default"} | {m["id"] for m in (project.materials or [])}


def _apply_inp_parts(project: models.Project, mesh: FEMesh, model) -> None:
    """Turn the parts / materials found in an .inp file into project parts and library entries."""
    ids = {}  # file material name -> project material id
    order = []
    for p in model.parts:
        if p.get("material") and p["material"] in model.materials and p["material"] not in order:
            order.append(p["material"])
    if not order and model.materials:
        order = list(model.materials)[:1]
    library = []
    for i, nm in enumerate(order):
        try:
            item = schemas.MaterialItem(name=nm[:60], **model.materials[nm]).model_dump()
        except ValueError:
            continue
        if i == 0:
            project.material = {**item}
            ids[nm] = "default"
        else:
            item["id"] = parts_mod.new_id(library, "m")
            library.append(item)
            ids[nm] = item["id"]
    project.materials = library
    plist = []
    for q in model.parts:
        plist.append({"id": parts_mod.new_id(plist, "p"), "name": str(q["name"])[:60], "elem_start": q["elem_start"],
                      "elem_end": q["elem_end"], "material_id": ids.get(q.get("material"), "default")})
    if plist:
        parts_mod.check_tiling(plist, mesh.n_elems)
        project.parts = plist
        project.surface_parts = parts_mod.surface_parts(mesh, plist)


# ---------------------------------------------------------------- Projects
def _limit_check(user: models.User, db: Session) -> None:
    limit = plans.limits_for(tier_of(user)).max_projects
    if limit is not None:
        used = db.query(models.Project).filter(models.Project.owner_id == user.id).count()
        if used >= limit:
            raise HTTPException(
                402, f"The Free plan includes {limit} projects. Upgrade to Pro for unlimited projects.")


def _blank_project(user: models.User, name: str, description: str = "") -> models.Project:
    return models.Project(
        owner_id=user.id, name=name.strip(), description=description or "",
        nodes=[], elements=[], surface_faces=[], element_type="C3D4",
        material={"name": "Steel", "E": 210e9, "nu": 0.3, "density": 7850.0, "conductivity": 50.0,
                  "specific_heat": 490.0, "alpha": 12e-6, "yield_stress": 0.0, "hardening": 0.0},
        boundary_conditions=[], loads=[], constraints=[], reference_points=[], node_sets=[],
        materials=[], parts=[], surface_parts=[],
        analysis_type="static", n_modes=6, settings={},
        gravity={"enabled": False, "x": 0.0, "y": 0.0, "z": -9.81},
    )


@app.post("/api/projects", response_model=schemas.ProjectOut)
def create_project(payload: schemas.ProjectCreate, user: models.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    _limit_check(user, db)
    project = _blank_project(user, payload.name, payload.description or "")
    db.add(project)
    return _commit(db, project)


@app.get("/api/projects", response_model=List[schemas.ProjectSummary])
def list_projects(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    return (db.query(models.Project).filter(models.Project.owner_id == user.id)
            .order_by(models.Project.updated_at.desc()).all())


PROJECT_FILE_KEYS = ["name", "description", "nodes", "elements", "element_type", "material", "materials", "parts",
                     "boundary_conditions", "loads", "analysis_type", "n_modes", "gravity", "settings",
                     "reference_points", "constraints", "node_sets"]


@app.post("/api/projects/import", response_model=schemas.ProjectOut)
def import_project(data: Dict[str, Any] = Body(...), user: models.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Create a project from a file previously saved with 'Save project'."""
    if data.get("format") != "gearhead-fea-project":
        raise HTTPException(422, "This is not a Gearhead FEA project file")
    _limit_check(user, db)
    project = _blank_project(user, str(data.get("name") or "Imported project")[:120], str(data.get("description") or "")[:2000])
    try:
        if data.get("elements"):
            mesh = FEMesh(data["nodes"], data["elements"], data.get("element_type") or "C3D4")
            _set_mesh(project, mesh)
        for key in ("material", "boundary_conditions", "loads", "gravity", "settings",
                    "reference_points", "constraints", "node_sets"):
            if key in data and data[key] is not None:
                setattr(project, key, data[key])
        project.material = schemas.MaterialUpdate(**{**(project.material or {}), **(data.get("material") or {})}).model_dump()
        lib = []
        for m in data.get("materials") or []:
            item = schemas.MaterialItem(**{k: v for k, v in m.items() if k != "id"}).model_dump()
            item["id"] = str(m.get("id") or parts_mod.new_id(lib, "m"))
            lib.append(item)
        project.materials = lib
        if project.elements and data.get("parts"):
            ids = {"default"} | {m["id"] for m in lib}
            plist = []
            for q in data["parts"]:
                q = dict(q)
                q["id"] = str(q.get("id") or parts_mod.new_id(plist, "p"))
                q["material_id"] = q.get("material_id") if q.get("material_id") in ids else "default"
                q["name"] = str(q.get("name") or q["id"])[:60]
                plist.append(q)
            parts_mod.check_tiling(plist, len(project.elements))
            project.parts = plist
            project.surface_parts = parts_mod.surface_parts(FEMesh(project.nodes, project.elements, project.element_type), plist)
        atype = data.get("analysis_type") or "static"
        project.analysis_type = atype if atype in plans.limits_for(tier_of(user)).analysis_types else "static"
        project.n_modes = max(1, min(int(data.get("n_modes") or 6), 50))
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, f"Invalid project file: {exc}")
    db.add(project)
    return _commit(db, project)


@app.get("/api/projects/{project_id}/history")
def project_history(project: models.Project = Depends(owned_project)):
    return history.info(project)


@app.post("/api/projects/{project_id}/undo", response_model=schemas.ProjectOut)
def undo_edit(project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    try:
        history.undo(db, project)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return _commit(db, project)


@app.post("/api/projects/{project_id}/redo", response_model=schemas.ProjectOut)
def redo_edit(project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    try:
        history.redo(db, project)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return _commit(db, project)


@app.get("/api/projects/{project_id}", response_model=schemas.ProjectOut)
def get_project(project: models.Project = Depends(owned_project)):
    return project


@app.delete("/api/projects/{project_id}")
def delete_project(project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    db.delete(project)
    db.commit()
    return {"ok": True}


@app.get("/api/projects/{project_id}/export/project")
def export_project(project: models.Project = Depends(owned_project)):
    data = {"format": "gearhead-fea-project", "version": 1}
    data.update({k: getattr(project, k) for k in PROJECT_FILE_KEYS})
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project.name)[:60] or "project"
    return Response(content=__import__("json").dumps(data), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.gfea.json"'})


@app.get("/api/projects/{project_id}/export/inp")
def export_inp(project: models.Project = Depends(owned_project)):
    _fem_mesh(project)
    from .jobs import project_to_dict
    try:
        body = inp.export_inp(project_to_dict(project))
    except (ValueError, inp.InpError) as exc:
        raise HTTPException(400, str(exc))
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project.name)[:60] or "model"
    return Response(content=body, media_type="text/plain",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.inp"'})


# ------------------------------------------------------------------- Mesh
@app.post("/api/projects/{project_id}/mesh/primitive", response_model=schemas.ProjectOut)
def generate_primitive(payload: schemas.PrimitiveMeshRequest, project: models.Project = Depends(owned_project),
                       db: Session = Depends(get_db)):
    try:
        mesh = meshgen.generate(payload.shape, payload.dims, payload.divisions, payload.element_type)
    except ValueError as exc:
        raise HTTPException(400, f"Mesh generation failed: {exc}")
    _set_mesh(project, mesh, meshgen.SHAPES.get(payload.shape, "Body"))
    return _commit(db, project, "Generate mesh")


@app.post("/api/projects/{project_id}/mesh/append", response_model=schemas.ProjectOut)
def append_part(payload: schemas.AppendPartRequest, project: models.Project = Depends(owned_project),
                db: Session = Depends(get_db)):
    """Add another primitive as a separate body (use ties/rigid constraints to join bodies)."""
    base = _fem_mesh(project)
    try:
        part = meshgen.generate(payload.shape, payload.dims, payload.divisions, base.et.name)
    except ValueError as exc:
        raise HTTPException(400, f"Mesh generation failed: {exc}")
    if len(payload.offset) != 3:
        raise HTTPException(422, "offset needs 3 numbers")
    import numpy as np
    old_parts = _ensure_parts(project)
    mid = payload.material_id or "default"
    if mid not in _material_ids(project):
        raise HTTPException(422, "Unknown material")
    part.nodes += np.array(payload.offset, dtype=float)
    merged = FEMesh(np.vstack([base.nodes, part.nodes]), np.vstack([base.elems, part.elems + base.n_nodes]), base.et.name)
    label = (payload.name or meshgen.SHAPES.get(payload.shape, "Body")).strip()
    taken = {p["name"] for p in old_parts}
    name, n = label, 2
    while name in taken:
        name, n = f"{label} {n}", n + 1
    new_part = {"id": parts_mod.new_id(old_parts, "p"), "name": name, "elem_start": base.n_elems,
                "elem_end": merged.n_elems, "material_id": mid}
    keep = (project.boundary_conditions, project.loads, project.reference_points, project.constraints, project.node_sets)
    _set_mesh(project, merged, parts=[*old_parts, new_part])
    # node ids of the original bodies are unchanged, so the existing setup stays valid
    (project.boundary_conditions, project.loads, project.reference_points,
     project.constraints, project.node_sets) = keep
    return _commit(db, project, "Add body")


@app.post("/api/projects/{project_id}/mesh/import", response_model=schemas.ProjectOut)
async def import_mesh(file: UploadFile = File(...), project: models.Project = Depends(owned_project),
                      db: Session = Depends(get_db)):
    """Load a mesh from a CalculiX/Abaqus .inp or a Gmsh 2.2 ASCII .msh file."""
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (limit 25 MB)")
    name = (file.filename or "").lower()
    try:
        body = raw.decode("utf-8", errors="replace")
        model = None
        if name.endswith(".msh"):
            mesh = inp.import_msh(body)
        elif name.endswith(".inp"):
            model = inp.import_inp_model(body)
            mesh = model.mesh
        else:
            raise HTTPException(415, "Unsupported file type. Use .inp (Abaqus/CalculiX) or .msh (Gmsh 2.2 ASCII).")
    except (inp.InpError, ValueError) as exc:
        raise HTTPException(400, f"Could not read mesh: {exc}")
    _set_mesh(project, mesh)
    if model is not None:
        _apply_inp_parts(project, mesh, model)
    return _commit(db, project, "Import mesh")


@app.post("/api/projects/{project_id}/mesh/custom", response_model=schemas.ProjectOut)
def upload_custom_mesh(nodes: List[List[float]], elements: List[List[int]], element_type: str = "C3D4",
                       project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    try:
        mesh = FEMesh(nodes, elements, element_type)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid mesh: {exc}")
    _set_mesh(project, mesh)
    return _commit(db, project, "Upload mesh")


@app.get("/api/projects/{project_id}/mesh/quality")
def mesh_quality(project: models.Project = Depends(owned_project)):
    return _fem_mesh(project).quality()


# ------------------------------------------------------- Model definition
@app.put("/api/projects/{project_id}/material", response_model=schemas.ProjectOut)
def set_material(payload: schemas.MaterialUpdate, project: models.Project = Depends(owned_project),
                 db: Session = Depends(get_db)):
    project.material = payload.model_dump()
    return _commit(db, project, "Edit default material")


# ------------------------------------------------------ materials & parts
def _library_item(payload: schemas.MaterialItem, mid: str) -> dict:
    item = payload.model_dump()
    item["id"] = mid
    return item


@app.post("/api/projects/{project_id}/materials", response_model=schemas.ProjectOut)
def add_material(payload: schemas.MaterialItem, project: models.Project = Depends(owned_project),
                 db: Session = Depends(get_db)):
    lib = list(project.materials or [])
    if len(lib) >= 30:
        raise HTTPException(422, "At most 30 extra materials per project")
    lib.append(_library_item(payload, parts_mod.new_id(lib, "m")))
    project.materials = lib
    return _commit(db, project, "Add material")


@app.put("/api/projects/{project_id}/materials/{material_id}", response_model=schemas.ProjectOut)
def update_material(material_id: str, payload: schemas.MaterialItem, project: models.Project = Depends(owned_project),
                    db: Session = Depends(get_db)):
    if material_id == "default":
        project.material = payload.model_dump()
        return _commit(db, project, "Edit material")
    lib = list(project.materials or [])
    for i, m in enumerate(lib):
        if m["id"] == material_id:
            lib[i] = _library_item(payload, material_id)
            project.materials = lib
            return _commit(db, project, "Edit material")
    raise HTTPException(404, "Material not found")


@app.delete("/api/projects/{project_id}/materials/{material_id}", response_model=schemas.ProjectOut)
def delete_material(material_id: str, project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    if material_id == "default":
        raise HTTPException(400, "The default material cannot be deleted")
    if material_id not in _material_ids(project):
        raise HTTPException(404, "Material not found")
    project.materials = [m for m in (project.materials or []) if m["id"] != material_id]
    project.parts = [{**p, "material_id": "default" if p.get("material_id") == material_id else p.get("material_id")}
                     for p in (project.parts or [])]
    return _commit(db, project, "Delete material")


@app.put("/api/projects/{project_id}/parts/{part_id}", response_model=schemas.ProjectOut)
def update_part(part_id: str, payload: schemas.PartUpdate, project: models.Project = Depends(owned_project),
                db: Session = Depends(get_db)):
    plist = _ensure_parts(project)
    part = next((p for p in plist if p["id"] == part_id), None)
    if part is None:
        raise HTTPException(404, "Part not found")
    if payload.name is not None:
        part["name"] = payload.name.strip()
    if payload.material_id is not None:
        if payload.material_id not in _material_ids(project):
            raise HTTPException(422, "Unknown material")
        part["material_id"] = payload.material_id
    project.parts = plist
    return _commit(db, project, "Edit part")


@app.post("/api/projects/{project_id}/parts/{part_id}/translate", response_model=schemas.ProjectOut)
def translate_part(part_id: str, payload: schemas.TranslateRequest, project: models.Project = Depends(owned_project),
                   db: Session = Depends(get_db)):
    import numpy as np
    plist = _ensure_parts(project)
    try:
        nodes = parts_mod.translate(np.array(project.nodes, dtype=float), np.array(project.elements, dtype=np.int64),
                                    plist, part_id, payload.offset)
    except KeyError:
        raise HTTPException(404, "Part not found")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    project.nodes = nodes.tolist()
    project.parts = plist
    return _commit(db, project, "Move part")


@app.delete("/api/projects/{project_id}/parts/{part_id}", response_model=schemas.ProjectOut)
def delete_part(part_id: str, project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    """Remove a body. Mesh is compressed; BCs, loads, constraints and sets are remapped (or dropped if emptied)."""
    import numpy as np
    plist = _ensure_parts(project)
    try:
        nodes, elems, new_parts, remap, _ = parts_mod.remove_part(
            np.array(project.nodes, dtype=float), np.array(project.elements, dtype=np.int64), plist, part_id)
    except KeyError:
        raise HTTPException(404, "Part not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    setup = parts_mod.remap_setup({
        "boundary_conditions": project.boundary_conditions, "loads": project.loads, "constraints": project.constraints,
        "node_sets": project.node_sets, "settings": project.settings}, remap, part_id)
    mesh = FEMesh(nodes, elems, project.element_type or "C3D4")
    project.nodes = mesh.nodes.tolist()
    project.elements = mesh.elems.tolist()
    project.parts = new_parts
    project.surface_faces = mesh.boundary().tris.tolist()
    project.surface_parts = parts_mod.surface_parts(mesh, new_parts)
    for key, value in setup.items():
        setattr(project, key, value)
    return _commit(db, project, "Delete part")


@app.put("/api/projects/{project_id}/analysis-type", response_model=schemas.ProjectOut)
def set_analysis_type(payload: schemas.AnalysisTypeUpdate, project: models.Project = Depends(owned_project),
                      user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    if payload.analysis_type not in ANALYSIS_TYPES:
        raise HTTPException(400, f"analysis_type must be one of: {', '.join(ANALYSIS_TYPES)}")
    require_pro_for(payload.analysis_type, user)
    thermal = {"thermal", "thermal_transient"}
    if (payload.analysis_type in thermal) != ((project.analysis_type or "static") in thermal):
        # Untyped legacy BCs change meaning (displacement vs temperature) between these families;
        # BCs with an explicit bc_type are unambiguous and are kept (thermo-mechanical needs both).
        project.boundary_conditions = [b for b in (project.boundary_conditions or []) if b.get("bc_type")]
    project.analysis_type = payload.analysis_type
    project.n_modes = payload.n_modes
    return _commit(db, project, "Change analysis type")


@app.put("/api/projects/{project_id}/settings", response_model=schemas.ProjectOut)
def set_settings(payload: schemas.SettingsUpdate, project: models.Project = Depends(owned_project),
                 db: Session = Depends(get_db)):
    cur = dict(project.settings or {})
    for k, v in payload.model_dump(exclude_none=True).items():
        if k == "clear":
            continue
        cur[k] = v
    for k in payload.clear or []:
        cur.pop(k, None)
    project.settings = cur
    if "n_modes" in cur:
        project.n_modes = int(cur["n_modes"])
    return _commit(db, project, "Change analysis settings")


@app.put("/api/projects/{project_id}/gravity", response_model=schemas.ProjectOut)
def set_gravity(payload: schemas.GravityUpdate, project: models.Project = Depends(owned_project),
                db: Session = Depends(get_db)):
    project.gravity = payload.model_dump()
    return _commit(db, project, "Change gravity")


@app.post("/api/projects/{project_id}/bcs", response_model=schemas.ProjectOut)
def add_bc(payload: schemas.BoundaryCondition, project: models.Project = Depends(owned_project),
           db: Session = Depends(get_db)):
    bc = payload.model_dump()
    if bc.get("ref_id"):
        if bc["ref_id"] not in _ref_ids(project):
            raise HTTPException(422, "Unknown reference point")
        if any(d not in range(6) for d in bc["dofs"]):
            raise HTTPException(422, "Reference-point DOFs must be 0..5")
    else:
        _check_node_ids(project, bc["node_ids"])
        if not bc["node_ids"]:
            raise HTTPException(422, "Select at least one node first")
        limit = 1 if bc.get("bc_type") == "temperature" else 3
        if any(d < 0 or d >= max(limit, 1) for d in bc["dofs"]) and bc.get("bc_type") != "temperature":
            raise HTTPException(422, "DOFs must be 0 (x), 1 (y) or 2 (z)")
    bc["id"] = bc.get("id") or _new_id()
    project.boundary_conditions = [*(project.boundary_conditions or []), bc]
    return _commit(db, project, "Add support")


@app.delete("/api/projects/{project_id}/bcs/{bc_id}", response_model=schemas.ProjectOut)
def delete_bc(bc_id: str, project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    project.boundary_conditions = [b for b in (project.boundary_conditions or []) if b.get("id") != bc_id]
    return _commit(db, project, "Delete support")


@app.post("/api/projects/{project_id}/loads", response_model=schemas.ProjectOut)
def add_load(payload: schemas.Load, project: models.Project = Depends(owned_project),
             db: Session = Depends(get_db)):
    ld = payload.model_dump()
    kind = ld["load_type"]
    valid = {"force", "pressure", "traction", "ref_force", "heat_flux", "surface_flux", "body_heat",
             "convection", "radiation"}
    if kind not in valid:
        raise HTTPException(422, f"load_type must be one of: {', '.join(sorted(valid))}")
    _check_node_ids(project, ld["node_ids"])
    if kind in ("pressure", "traction", "surface_flux", "convection", "radiation") and not ld.get("faces"):
        raise HTTPException(422, "Select at least one face first")
    if kind in ("force", "heat_flux") and not ld["node_ids"]:
        raise HTTPException(422, "Select at least one node first")
    if kind == "ref_force" and ld.get("ref_id") not in _ref_ids(project):
        raise HTTPException(422, "Unknown reference point")
    if kind == "convection" and (ld.get("h") is None or ld.get("T_inf") is None):
        raise HTTPException(422, "Convection needs h and T_inf")
    if kind == "radiation" and (ld.get("emissivity") is None or ld.get("T_inf") is None):
        raise HTTPException(422, "Radiation needs emissivity and T_inf")
    ld["id"] = ld.get("id") or _new_id()
    project.loads = [*(project.loads or []), ld]
    return _commit(db, project, "Add load")


@app.delete("/api/projects/{project_id}/loads/{load_id}", response_model=schemas.ProjectOut)
def delete_load(load_id: str, project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    project.loads = [l for l in (project.loads or []) if l.get("id") != load_id]
    return _commit(db, project, "Delete load")


@app.post("/api/projects/{project_id}/reference-points", response_model=schemas.ProjectOut)
def add_reference_point(payload: schemas.ReferencePoint, project: models.Project = Depends(owned_project),
                        db: Session = Depends(get_db)):
    rp = payload.model_dump()
    rp["id"] = rp.get("id") or _new_id()
    project.reference_points = [*(project.reference_points or []), rp]
    return _commit(db, project, "Add reference point")


@app.delete("/api/projects/{project_id}/reference-points/{rp_id}", response_model=schemas.ProjectOut)
def delete_reference_point(rp_id: str, project: models.Project = Depends(owned_project),
                           db: Session = Depends(get_db)):
    project.reference_points = [r for r in (project.reference_points or []) if r.get("id") != rp_id]
    project.constraints = [c for c in (project.constraints or []) if c.get("ref_id") != rp_id]
    project.boundary_conditions = [b for b in (project.boundary_conditions or []) if b.get("ref_id") != rp_id]
    project.loads = [l for l in (project.loads or []) if l.get("ref_id") != rp_id]
    return _commit(db, project, "Delete reference point")


@app.post("/api/projects/{project_id}/constraints", response_model=schemas.ProjectOut)
def add_constraint(payload: schemas.Constraint, project: models.Project = Depends(owned_project),
                   db: Session = Depends(get_db)):
    c = payload.model_dump()
    if c["type"] == "rigid":
        if c.get("ref_id") not in _ref_ids(project):
            raise HTTPException(422, "A rigid body needs a reference point")
        if not c.get("faces") and not c["node_ids"]:
            raise HTTPException(422, "Select the surface that moves with the reference point")
    elif c["type"] == "contact":
        pids = {p["id"] for p in _ensure_parts(project)}
        if c.get("master_part") not in pids or c.get("slave_part") not in pids:
            raise HTTPException(422, "Contact needs two existing parts")
        if c["master_part"] == c["slave_part"]:
            raise HTTPException(422, "Contact needs two different parts")
    elif c["type"] == "tie" and (c.get("master_part") or c.get("slave_part")):
        pids = {p["id"] for p in _ensure_parts(project)}
        if c.get("master_part") not in pids or c.get("slave_part") not in pids:
            raise HTTPException(422, "Choose two existing parts")
        if c["master_part"] == c["slave_part"]:
            raise HTTPException(422, "A tie needs two different parts")
    elif c["type"] == "tie":
        if not (c.get("slave_faces") or c["slave_node_ids"]) or not c.get("master_faces"):
            raise HTTPException(422, "A tie needs a slave selection and a master surface")
    else:
        raise HTTPException(422, "Constraint type must be 'rigid', 'tie' or 'contact'")
    c["id"] = c.get("id") or _new_id()
    project.constraints = [*(project.constraints or []), c]
    return _commit(db, project, "Add constraint")


@app.delete("/api/projects/{project_id}/constraints/{c_id}", response_model=schemas.ProjectOut)
def delete_constraint(c_id: str, project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    project.constraints = [c for c in (project.constraints or []) if c.get("id") != c_id]
    return _commit(db, project, "Delete constraint")


@app.post("/api/projects/{project_id}/node-sets", response_model=schemas.ProjectOut)
def add_node_set(payload: schemas.NodeSet, project: models.Project = Depends(owned_project),
                 db: Session = Depends(get_db)):
    s = payload.model_dump()
    if s["kind"] not in ("nodes", "faces") or not s["ids"]:
        raise HTTPException(422, "A set needs a kind ('nodes' or 'faces') and at least one item")
    if len(project.node_sets or []) >= 50:
        raise HTTPException(422, "At most 50 named sets per project")
    s["id"] = s.get("id") or _new_id()
    project.node_sets = [*(project.node_sets or []), s]
    return _commit(db, project, "Save set")


@app.delete("/api/projects/{project_id}/node-sets/{set_id}", response_model=schemas.ProjectOut)
def delete_node_set(set_id: str, project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    project.node_sets = [s for s in (project.node_sets or []) if s.get("id") != set_id]
    return _commit(db, project, "Delete set")


# --------------------------------------------------------------------- Jobs
def _expire_stale_jobs(db: Session, user: models.User) -> int:
    """Jobs left 'running' by a crashed worker must not block the user forever."""
    cutoff = dt.datetime.utcnow() - dt.timedelta(minutes=STALE_JOB_MINUTES)
    rows = (db.query(models.Job).join(models.Project, models.Job.project_id == models.Project.id)
            .filter(models.Project.owner_id == user.id, models.Job.status.in_(("pending", "running"))).all())
    active = 0
    for j in rows:
        if j.created_at and j.created_at < cutoff:
            j.status, j.log, j.progress = "failed", "Timed out (the solver stopped responding).", 1.0
        else:
            active += 1
    db.commit()
    return active


@app.post("/api/projects/{project_id}/solve", response_model=schemas.JobOut)
def solve(project: models.Project = Depends(owned_project), user: models.User = Depends(current_user),
          db: Session = Depends(get_db)):
    if not project.elements:
        raise HTTPException(400, "Project has no mesh yet")
    require_pro_for(project.analysis_type or "static", user)  # a lapsed Pro user may hold a Pro-only project
    if _expire_stale_jobs(db, user) >= MAX_ACTIVE_JOBS:
        raise HTTPException(429, "You already have analyses running. Wait for them to finish.")

    job = models.Job(project_id=project.id, status="pending", solver_used=jobs.SOLVER_NAME)
    db.add(job)
    db.commit()
    db.refresh(job)
    project_id, job_id = project.id, job.id

    def _run():
        from .database import SessionLocal
        session = SessionLocal()
        try:
            j = session.get(models.Job, job_id)
            p = session.get(models.Project, project_id)
            jobs.run_job(session, j, p)
        finally:
            session.close()

    threading.Thread(target=_run, daemon=True).start()
    return job


@app.get("/api/jobs/{job_id}", response_model=schemas.JobOut)
def get_job(job_id: str, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(models.Job, job_id)
    if not job or job.project is None or job.project.owner_id != user.id:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/projects/{project_id}/jobs/latest", response_model=schemas.JobOut)
def latest_job(project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    """Most recent completed job, so results survive a page reload."""
    job = (db.query(models.Job).filter(models.Job.project_id == project.id, models.Job.status == "completed")
           .order_by(models.Job.created_at.desc()).first())
    if not job:
        raise HTTPException(404, "No completed job yet")
    return job


@app.get("/api/projects/{project_id}/jobs", response_model=List[schemas.JobOut])
def list_jobs(project: models.Project = Depends(owned_project), db: Session = Depends(get_db)):
    return (db.query(models.Job).filter(models.Job.project_id == project.id)
            .order_by(models.Job.created_at.desc()).limit(20).all())
