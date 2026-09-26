# WebFEA — Browser-Based CAD/CAE Simulation Suite

WebFEA is a full-stack web application that reproduces the core workflow of
**PrePoMax**: a pre-processor for building a model (geometry → mesh →
material → boundary conditions/loads), a **finite element solver**, and a
post-processor for visualizing displacement and stress results — all in the
browser, with no desktop software required.

```
┌─────────────┐      REST API       ┌──────────────────┐      subprocess       ┌────────────┐
│  React/Three │ <-----------------> │ FastAPI backend  │ <-------------------> │  CalculiX  │
│  (Pre/Post   │   JSON mesh,        │  - mesh gen       │   .inp / .frd files   │  (ccx)     │
│  processor)  │   BCs, results      │  - job queue      │   (if installed)      │  optional  │
└─────────────┘                     │  - internal FEM   │                       └────────────┘
                                     │    solver (numpy/ │
                                     │    scipy, always  │
                                     │    available)      │
                                     └──────────────────┘
```

## What it does

1. **Full-stack web application** — a FastAPI backend + a React/Three.js
   frontend. Everything runs over HTTP; there's nothing to install on the
   client beyond a browser.
2. **Solver + pre/post-processor (like CalculiX / PrePoMax)** — the backend
   ships a real, self-contained **linear-static structural FEA solver**
   (4-node tetrahedral elements, isotropic linear elasticity, sparse
   stiffness assembly, Dirichlet elimination, von Mises stress recovery)
   written in NumPy/SciPy, so simulations work immediately with **no
   external binary required**. If you additionally install the real
   **CalculiX** solver (`ccx`) on the host/container, WebFEA automatically
   detects it, writes a standard CalculiX `.inp` deck, runs it, and parses
   the `.frd` results instead — giving you the same industrial solver
   PrePoMax uses, with an automatic fallback either way.
3. **Simulator (like in CAD tools)** — an interactive 3D viewport
   (`react-three-fiber`) lets you generate primitive geometry (box,
   cylinder, sphere), mesh it, click faces to select nodes, pin supports,
   apply forces, run the solve, and inspect color-mapped contour plots of
   displacement/von Mises stress with an animated/scaled deformed shape —
   the same loop as PrePoMax's Pre-Processor → Solver → Post-Processor.
4. **Detailed documentation** — this file.

---

## Features

- Project manager (create/select/delete simulation projects; persisted in
  SQLite so your work survives restarts).
- Parametric primitive mesh generator (box / cylinder / sphere) with
  adjustable mesh density, producing real tetrahedral volume meshes
  (Delaunay tetrahedralization + automatic outer-surface extraction).
- Material library (Steel, Aluminum, Titanium, ABS plastic presets) with
  editable Young's modulus, Poisson's ratio, and density.
- Interactive boundary-condition and load assignment: click faces in the 3D
  viewport to select nodes, then apply fixed supports (per-axis) or
  concentrated nodal forces.
- One-click solve with live progress polling; automatically uses CalculiX
  if installed, otherwise the built-in Python solver.
- Post-processing viewer: von Mises stress or displacement-magnitude
  contour plots, a color legend, and a deformation-scale slider to see the
  deformed shape exaggerated for clarity.
- Dockerized for one-command local run or cloud deployment.

## What's intentionally out of scope (v1)

This is a working, from-scratch engineering application, not a clone of
every PrePoMax menu. To keep it honest about capability:

- Only 4-node tetrahedral (Tet4/C3D4) solid elements are supported (no
  shells/beams yet).
- Only linear static structural analysis (no modal/dynamic/nonlinear/
  thermal analysis yet — the architecture supports adding these as new
  analysis modules).
- Geometry input is parametric primitives + a JSON mesh-upload endpoint
  (`/api/projects/{id}/mesh/custom`) for meshes generated elsewhere (e.g.
  Gmsh/TetGen output converted to node/element arrays). Native STEP/IGES
  import is not implemented.

---

## Project layout

```
webfea/
├── backend/                 FastAPI application
│   ├── app/
│   │   ├── main.py          API routes
│   │   ├── models.py        SQLAlchemy models (Project, Job)
│   │   ├── schemas.py       Pydantic request/response schemas
│   │   ├── mesh.py          Primitive mesh generation + surface extraction
│   │   ├── solver.py        Internal FEM solver (NumPy/SciPy)
│   │   ├── calculix.py      Optional real CalculiX (.inp/.frd) integration
│   │   ├── jobs.py          Job orchestration (chooses solver, stores results)
│   │   └── database.py      DB engine/session setup
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                 React + Vite + react-three-fiber
│   ├── src/
│   │   ├── App.jsx           Main application state/layout
│   │   ├── api.js            Backend REST client
│   │   ├── components/
│   │   │   ├── Viewport3D.jsx    3D mesh/contour viewport + face picking
│   │   │   ├── ProjectPanel.jsx  Project list/create/delete
│   │   │   ├── GeometryPanel.jsx Primitive geometry + mesh density
│   │   │   ├── MaterialPanel.jsx Material presets/properties
│   │   │   ├── BCLoadPanel.jsx   Boundary conditions & loads
│   │   │   ├── JobPanel.jsx      Solve button, progress, result field toggle
│   │   │   └── Legend.jsx        Contour color legend
│   │   └── styles.css
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Quick start (local, no Docker)

### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is now at `http://localhost:8000`. Check `http://localhost:8000/api/health`
— it reports whether it found a real CalculiX (`ccx`) install.

### 2. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/api/*` to the
backend on port 8000 automatically (see `frontend/vite.config.js`).

### 3. Try it

1. Create a project (left sidebar).
2. Generate a mesh: pick **Box**, keep defaults, click **Generate Mesh**.
3. Set a material (Steel is the default).
4. In the right sidebar, set **Pick mode** to "Select nodes", then click a
   face at one end of the box in the 3D view — this selects that face's
   nodes.
5. With those nodes selected, click **Add Fixed Support** (fixes X/Y/Z).
6. Clear selection, pick a face at the other end, set Fz to something like
   `-500`, click **Add Load**.
7. Click **Run Solver**. When it completes, switch **Result field** between
   Von Mises Stress / Displacement Magnitude and drag the deformation-scale
   slider to see the deflected shape.

---

## Running with Docker (recommended for a clean environment or cloud deploy)

```bash
docker compose up --build
```

- Backend → `http://localhost:8000`
- Frontend → `http://localhost:5173`

The backend `Dockerfile` attempts to `apt-get install calculix-ccx` so the
container uses the real CalculiX solver out of the box; if that package is
unavailable on your platform/architecture, the build step simply continues
(`|| true`) and the app transparently uses the built-in Python solver
instead — no functionality is lost.

Data persists in a named Docker volume (`webfea_data`) mounted at
`/app/data` in the backend container, so projects survive
`docker compose down` / `up` cycles.

### Deploying to the cloud

This app has no exotic infrastructure requirements — it's two standard
containers (a Python API, a static frontend) plus a SQLite file (swappable
for Postgres). It runs as-is on:

- **A single VM** (EC2, a DigitalOcean droplet, a GCE instance, etc.): install
  Docker, copy this folder up, run `docker compose up -d`.
- **Render / Railway / Fly.io**: point one service at `backend/Dockerfile`
  and one at `frontend/Dockerfile`; set the frontend's `VITE_API_URL` build
  arg to the backend's public URL.
- **Kubernetes**: the two Dockerfiles build directly into Deployments;
  add a Service + Ingress per component, and switch `DATABASE_URL` to a
  managed Postgres instance for multi-replica durability (SQLite is
  single-writer and fine for a single backend replica).
- **A managed Postgres database** (recommended beyond local/dev use): set
  `DATABASE_URL=postgresql://user:pass@host:5432/dbname` as an environment
  variable on the backend service — no code changes needed, SQLAlchemy
  handles both.

---

## API reference (summary)

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Backend status + whether CalculiX is installed |
| POST | `/api/projects` | Create a project |
| GET | `/api/projects` | List projects |
| GET | `/api/projects/{id}` | Get one project (nodes, elements, BCs, loads, material) |
| DELETE | `/api/projects/{id}` | Delete a project |
| POST | `/api/projects/{id}/mesh/primitive` | Generate a tet mesh for a box/cylinder/sphere |
| POST | `/api/projects/{id}/mesh/custom` | Upload an externally generated tet mesh (`nodes`, `elements`) |
| PUT | `/api/projects/{id}/material` | Set material (`name`, `E`, `nu`, `density`) |
| POST | `/api/projects/{id}/bcs` | Add a fixed/prescribed boundary condition |
| DELETE | `/api/projects/{id}/bcs/{bc_id}` | Remove a boundary condition |
| POST | `/api/projects/{id}/loads` | Add a nodal force load |
| DELETE | `/api/projects/{id}/loads/{load_id}` | Remove a load |
| POST | `/api/projects/{id}/solve` | Start a solve job (returns immediately; poll for status) |
| GET | `/api/jobs/{job_id}` | Job status/progress/results |
| GET | `/api/projects/{id}/jobs` | Job history for a project |

Full interactive docs (Swagger UI) are auto-generated by FastAPI at
`http://localhost:8000/docs`.

---

## Solver details (for the curious / for extending it)

`backend/app/solver.py` implements the standard linear FEA pipeline:

1. **Element formulation**: 4-node tetrahedron, constant-strain (the
   simplest 3D solid element — the same one CalculiX calls `C3D4`).
   Shape-function gradients are computed via the cofactor/determinant
   method, giving the strain-displacement matrix `B` and element volume in
   closed form (no numerical integration needed for this element).
2. **Constitutive law**: isotropic linear elasticity in Voigt notation
   (`D` matrix from `E`, `nu`).
3. **Assembly**: element stiffness `k_e = V * Bᵀ D B` scattered into a
   global sparse (`scipy.sparse.lil_matrix` → `csr_matrix`) stiffness
   matrix.
4. **Boundary conditions**: Dirichlet conditions are applied by
   partitioning the system into free/fixed degrees of freedom and solving
   only the free-free block (`K_ff u_f = f_f - K_fp u_p`) — this satisfies
   prescribed displacements exactly, unlike a penalty method.
5. **Solve**: `scipy.sparse.linalg.spsolve` (sparse direct solver).
6. **Post-processing**: element stress from `stress = D · (B · u_e)`, von
   Mises equivalent stress per element, then averaged onto nodes for smooth
   contour plots; reaction forces recovered from `R = K u - f`.

This is the same class of method professional codes like CalculiX use for
linear statics — this implementation is simplified (single element type,
linear analysis only) but numerically correct, and was validated against
classical cantilever-beam bending theory during development (order-of-
magnitude agreement, with the expected extra stiffness from coarse linear
tetrahedra — a well-known property of constant-strain elements, not a bug).

`backend/app/calculix.py` is the alternate path: it writes the exact same
model out as a CalculiX `.inp` deck (`*NODE`, `*ELEMENT TYPE=C3D4`,
`*MATERIAL`, `*BOUNDARY`, `*CLOAD`, `*STATIC` step), shells out to `ccx`,
and parses displacements/stresses back out of the `.frd` output file. This
is used automatically whenever `ccx` is found on `PATH` — you get to
upgrade to the "real" solver just by installing one package, with zero
application code changes.

### Extending it

- **More element types** (shells, beams, hex): add a new `_elemtype_B_matrix`
  function in `solver.py` and branch on element connectivity length.
- **New analysis types** (modal, thermal, nonlinear): add a new function
  alongside `solve_linear_static` and a `analysis_type` field on the job;
  CalculiX already supports these via different `*STEP` cards in
  `calculix.py`.
- **Real CAD import** (STEP/IGES): pipe an uploaded file through a geometry
  kernel (e.g. `pythonocc`/OpenCascade) to get a boundary representation,
  then tetrahedralize with Gmsh/TetGen and POST the resulting arrays to
  `/api/projects/{id}/mesh/custom` — the rest of the pipeline (BCs, solve,
  post-processing) needs no changes.

---

## Troubleshooting

- **"No boundary conditions applied" error on solve** — a model with no
  fixed supports is a rigid body with no unique static solution (division
  by a singular stiffness matrix); add at least one fixed support.
- **"Project has no mesh yet"** — generate a primitive mesh (or upload one)
  before adding BCs/loads/solving.
- **CalculiX not detected on Docker** — some platforms (e.g. Apple Silicon
  hosts building `linux/arm64` images) may not have a `calculix-ccx`
  package available; the build continues and the app just uses the
  built-in solver, which requires no configuration change.
- **Large/slow solves** — the internal solver is a direct sparse solve;
  meshes of a few thousand nodes solve in well under a second on a laptop,
  tens of thousands in a few seconds. For very large or repeated
  parametric studies, install real CalculiX for better performance and
  additional element types.

---

## License / attribution

This project is provided as-is for you to run locally and deploy. It uses:
FastAPI, SQLAlchemy, NumPy, SciPy (backend); React, Vite, Three.js,
`@react-three/fiber`/`drei` (frontend); optionally CalculiX (`ccx`, GPL) if
you choose to install it on the host/container.
