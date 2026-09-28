# WebFEA — Browser-Based CAD/CAE Simulation Suite

WebFEA is a full-stack web application that reproduces the core workflow of
**PrePoMax**: a pre-processor for building a model (geometry → mesh →
material → boundary conditions/loads), a **finite element solver** covering
static structural, modal (natural frequency), and steady-state thermal
analysis, and a post-processor for visualizing displacement, stress, mode
shape, and temperature results — all in the browser, with no desktop
software required.

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
   ships a real, self-contained FEA solver (4-node tetrahedral elements,
   isotropic linear elasticity, sparse assembly) written in NumPy/SciPy
   covering three analysis types, so simulations work immediately with **no
   external binary required**:
   - **Static structural** — Dirichlet elimination, von Mises + principal
     stress recovery, concentrated forces, distributed surface pressure,
     and gravity/self-weight body loads.
   - **Modal (natural frequency)** — undamped free-vibration eigenproblem
     (lumped mass matrix + sparse shift-invert eigensolver), returning mode
     shapes you can animate in the viewport.
   - **Steady-state thermal** — heat-conduction FEA with fixed-temperature
     boundary conditions and concentrated heat sources.

   If you additionally install the real **CalculiX** solver (`ccx`) on the
   host/container, WebFEA automatically detects it and uses it for **static**
   analysis (writes a standard CalculiX `.inp` deck, runs it, parses the
   `.frd` results) — giving you the same industrial solver PrePoMax uses,
   with an automatic fallback to the internal solver either way. Modal and
   thermal analysis currently always run on the internal solver (see
   [Extending it](#extending-it)).
3. **Simulator (like in CAD tools)** — an interactive 3D viewport
   (`react-three-fiber`) lets you generate primitive geometry (box,
   cylinder, sphere), mesh it, click faces to select nodes or faces, pin
   supports, apply forces/pressure/gravity/heat, run the solve, and inspect
   color-mapped contour plots of displacement/stress/temperature or animate
   mode shapes, with an animated/scaled deformed shape — the same loop as
   PrePoMax's Pre-Processor → Solver → Post-Processor.
4. **Detailed documentation** — this file.

---

## Features

- Project manager (create/select/delete simulation projects; persisted in
  SQLite so your work survives restarts).
- Parametric primitive mesh generator (box / cylinder / sphere) with
  adjustable mesh density, producing real tetrahedral volume meshes
  (Delaunay tetrahedralization + automatic outward-oriented outer-surface
  extraction, used for both rendering and pressure-load direction).
- Three analysis types, switchable per project: **static structural**,
  **modal (natural frequency)**, and **steady-state thermal**. Switching
  type clears BCs/loads since their meaning changes (e.g. fixed support vs.
  fixed temperature).
- Material library (Steel, Aluminum, Titanium, Copper, Cast Iron, ABS
  plastic, Concrete, Glass presets) with editable Young's modulus,
  Poisson's ratio, density, thermal conductivity, and specific heat.
- Interactive boundary-condition and load assignment: click faces in the 3D
  viewport to select nodes or faces, then apply:
  - Fixed supports (per-axis) or concentrated nodal forces (static)
  - Distributed surface **pressure** loads (converted to statically
    equivalent nodal forces from outward face normals) and a project-wide
    **gravity/self-weight** toggle (static)
  - Node supports only, no loads needed (modal)
  - Fixed temperatures and concentrated heat sources (thermal)
- One-click solve with live progress polling; automatically uses CalculiX
  for static analysis if installed, otherwise the built-in Python solver
  (modal/thermal always use the built-in solver — see
  [Extending it](#extending-it)).
- Post-processing viewer:
  - Static: von Mises stress, max/min principal stress (S1/S3), or
    displacement-magnitude contour plots, with a deformation-scale slider.
  - Modal: a list of computed natural frequencies (Hz) with a normalized
    mode-shape animation slider per selected mode.
  - Thermal: a temperature contour plot.
  - A color legend for whichever field is active.
- Dockerized for one-command local run or cloud deployment.

## What's intentionally out of scope (v1)

This is a working, from-scratch engineering application, not a clone of
every PrePoMax menu. To keep it honest about capability:

- Only 4-node tetrahedral (Tet4/C3D4) solid elements are supported (no
  shells/beams yet).
- Static, modal, and steady-state thermal analysis are implemented; no
  transient/dynamic, nonlinear (large deformation, plasticity, contact), or
  coupled thermo-mechanical analysis yet — the architecture supports adding
  these as new analysis modules alongside `solve_linear_static` /
  `solve_modal` / `solve_thermal` in `solver.py`.
- CalculiX passthrough only covers static analysis; modal and thermal jobs
  always use the internal solver (see [Extending it](#extending-it)).
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
│   │   ├── main.py          API routes + startup schema migration
│   │   ├── models.py        SQLAlchemy models (Project, Job)
│   │   ├── schemas.py       Pydantic request/response schemas
│   │   ├── mesh.py          Primitive mesh generation + outward-oriented surface extraction
│   │   ├── solver.py        Internal FEM solver (static/modal/thermal, NumPy/SciPy)
│   │   ├── calculix.py      Optional real CalculiX (.inp/.frd) integration (static only)
│   │   ├── jobs.py          Job orchestration (analysis type, load combination, solver choice)
│   │   └── database.py      DB engine/session setup
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                 React + Vite + react-three-fiber
│   ├── src/
│   │   ├── App.jsx           Main application state/layout
│   │   ├── api.js            Backend REST client
│   │   ├── components/
│   │   │   ├── Viewport3D.jsx    3D mesh/contour viewport + node/face picking
│   │   │   ├── ProjectPanel.jsx  Project list/create/delete
│   │   │   ├── GeometryPanel.jsx Primitive geometry + mesh density
│   │   │   ├── AnalysisPanel.jsx Analysis type, mode count, gravity toggle
│   │   │   ├── MaterialPanel.jsx Material presets/properties (structural + thermal)
│   │   │   ├── BCLoadPanel.jsx   Boundary conditions & loads (per analysis type)
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

### 3. Try it — static structural

1. Create a project (left sidebar).
2. Generate a mesh: pick **Box**, keep defaults, click **Generate Mesh**.
3. Leave **Analysis type** at "Static structural" and set a material (Steel
   is the default).
4. In the right sidebar, set **Pick mode** to "Select nodes", then click a
   face at one end of the box in the 3D view — this selects that face's
   nodes.
5. With those nodes selected, click **Add Fixed Support** (fixes X/Y/Z).
6. Clear selection, pick a face at the other end, set Fz to something like
   `-500`, click **Add Force**.
7. (Optional) Set **Pick mode** to "Select faces", click a face, set a
   pressure, click **Add Pressure** — or just enable **Gravity** in the
   Analysis panel for a self-weight load.
8. Click **Run Solver**. When it completes, switch **Result field** between
   Von Mises Stress / Principal Stress / Displacement Magnitude and drag the
   deformation-scale slider to see the deflected shape.

### 4. Try it — modal analysis

1. In the **Analysis** panel, switch **Analysis type** to "Modal (natural
   frequency)" (this clears any existing BCs/loads) and set the number of
   modes.
2. Select nodes on a full face (not just one or two points — see
   [Troubleshooting](#troubleshooting)) and **Add Fixed Support**.
3. Click **Run Solver**. Click through the computed frequencies in the list
   and drag the mode-shape scale slider to animate the selected mode.

### 5. Try it — steady-state thermal

1. Switch **Analysis type** to "Steady-state thermal". The Material panel
   now shows thermal conductivity/specific heat instead of E/nu/density.
2. Select nodes at one end, set a temperature (e.g. `100`), **Add Fixed
   Temperature**. Select nodes at the other end, set a lower temperature
   (e.g. `0`), **Add Fixed Temperature** again.
3. (Optional) Add a concentrated **Heat Flux** (W) on any selected nodes.
4. Click **Run Solver** to see the temperature contour.

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

### Deploying to DigitalOcean App Platform

This repo is a monorepo with two separately buildable apps
(`backend/Dockerfile`, `frontend/Dockerfile`), so App Platform's
autodetection at the repo root won't find either one on its own — you need
to add **two components** by hand and wire their routes together.

1. **Backend — Service component**
   - Source Directory: `backend`
   - Build: autodetects `backend/Dockerfile`
   - HTTP Port: `8000`
   - HTTP Route: `/api`
   - Env var: `DATABASE_URL` (defaults to the SQLite file baked into the
     image; point this at a managed Postgres connection string for
     production use).

2. **Frontend — Static Site component**
   - Source Directory: `frontend`
   - Build: autodetects `frontend/Dockerfile`
   - Output Directory: `/app/dist` — this **must be an absolute path**
     when a static site is paired with `dockerfile_path`, since App
     Platform builds the Dockerfile as an image and extracts this path
     from inside it. It's `/app/dist` because the Dockerfile's build
     stage sets `WORKDIR /app` and `npm run build` writes Vite's output to
     `./dist`.
   - HTTP Route: `/` (catch-all)
   - Build-time env var: `VITE_API_URL=/api` — this makes the built
     frontend call same-origin `/api`, which App Platform's router then
     forwards to the backend component. Do **not** use
     `http://localhost:8000/api` here; that only works for local
     `docker compose`.

3. Both components must sit under the **same app** so they share one
   domain and the routes above can both take effect — creating them as two
   separate apps will not work.

Minimal app spec reflecting the above (`doctl apps create --spec app.yaml`,
or paste into the App Spec editor):

```yaml
name: webfea
services:
  - name: backend
    source_dir: backend
    dockerfile_path: backend/Dockerfile
    http_port: 8000
    routes:
      - path: /api
static_sites:
  - name: frontend
    source_dir: frontend
    dockerfile_path: frontend/Dockerfile
    output_dir: /app/dist
    routes:
      - path: /
    envs:
      - key: VITE_API_URL
        value: /api
        scope: BUILD_TIME
```

**Common pitfall:** if you only see one component in the dashboard after
deploying, the frontend was never added — App Platform's initial "create
app" wizard often only creates a component for the first Dockerfile it
finds. Use **Settings → Create Component** to add the second one instead of
relying on the wizard picking up both.

---

## API reference (summary)

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Backend status + whether CalculiX is installed |
| POST | `/api/projects` | Create a project |
| GET | `/api/projects` | List projects |
| GET | `/api/projects/{id}` | Get one project (nodes, elements, BCs, loads, material, analysis type, gravity) |
| DELETE | `/api/projects/{id}` | Delete a project |
| POST | `/api/projects/{id}/mesh/primitive` | Generate a tet mesh for a box/cylinder/sphere |
| POST | `/api/projects/{id}/mesh/custom` | Upload an externally generated tet mesh (`nodes`, `elements`) |
| PUT | `/api/projects/{id}/material` | Set material (`name`, `E`, `nu`, `density`, `conductivity`, `specific_heat`) |
| PUT | `/api/projects/{id}/analysis-type` | Set `analysis_type` (`static`\|`modal`\|`thermal`) and `n_modes`; clears BCs/loads on change |
| PUT | `/api/projects/{id}/gravity` | Set gravity body-force (`enabled`, `x`, `y`, `z` in m/s²), used by static analysis |
| POST | `/api/projects/{id}/bcs` | Add a boundary condition (fixed support for static/modal, fixed temperature for thermal) |
| DELETE | `/api/projects/{id}/bcs/{bc_id}` | Remove a boundary condition |
| POST | `/api/projects/{id}/loads` | Add a load: `load_type` `force` (nodal), `pressure` (on `faces`), or `heat_flux` (thermal) |
| DELETE | `/api/projects/{id}/loads/{load_id}` | Remove a load |
| POST | `/api/projects/{id}/solve` | Start a solve job (returns immediately; poll for status) |
| GET | `/api/jobs/{job_id}` | Job status/progress/results (shape depends on `results.analysis_type`) |
| GET | `/api/projects/{id}/jobs` | Job history for a project |

Full interactive docs (Swagger UI) are auto-generated by FastAPI at
`http://localhost:8000/docs`.

---

## Solver details (for the curious / for extending it)

`backend/app/solver.py` implements three analysis pipelines sharing the same
Tet4 element formulation:

1. **Element formulation**: 4-node tetrahedron, constant-strain (the
   simplest 3D solid element — the same one CalculiX calls `C3D4`).
   Shape-function gradients (`_tet4_shape_grads`) are computed via the
   cofactor/determinant method, giving the gradient matrix and element
   volume in closed form (no numerical integration needed for this
   element). Both the structural strain-displacement matrix `B` and the
   thermal conduction gradient matrix are built from these same gradients.
2. **Static structural** (`solve_linear_static`):
   - Constitutive law: isotropic linear elasticity in Voigt notation (`D`
     matrix from `E`, `nu`).
   - Assembly: element stiffness `k_e = V * Bᵀ D B` scattered into a global
     sparse (`scipy.sparse.lil_matrix` → `csr_matrix`) stiffness matrix.
   - Boundary conditions: Dirichlet conditions are applied by partitioning
     the system into free/fixed degrees of freedom and solving only the
     free-free block (`K_ff u_f = f_f - K_fp u_p`) — this satisfies
     prescribed displacements exactly, unlike a penalty method.
   - Loads: concentrated nodal forces, plus **pressure** and **gravity**
     loads converted to statically-equivalent nodal forces before assembly
     (`pressure_nodal_forces` integrates traction × area over the picked,
     outward-oriented triangles and splits it 3 ways per triangle;
     `gravity_nodal_forces` integrates `density * volume * g` per element
     and splits it 4 ways per tet).
   - Solve: `scipy.sparse.linalg.spsolve` (sparse direct solver).
   - Post-processing: element stress from `stress = D · (B · u_e)`, von
     Mises equivalent stress, and principal stresses `S1 ≥ S2 ≥ S3`
     (eigenvalues of the 3×3 stress tensor) per element, then averaged onto
     nodes for smooth contour plots; reaction forces recovered from
     `R = K u - f`.
3. **Modal / natural frequency** (`solve_modal`): the undamped free-vibration
   eigenproblem `K v = ω² M v`, using the same stiffness assembly as static
   analysis plus a **lumped (diagonal) element mass matrix**
   (`density * volume / 4` per node) — simple, always positive-definite, and
   adequate for the coarse tet meshes this application generates. Solved on
   the free DOFs (after the same Dirichlet elimination as static analysis)
   with `scipy.sparse.linalg.eigsh` in shift-invert mode (`sigma=0`) to get
   the lowest `n_modes` frequencies; mode shapes are normalized to unit max
   component for display.
4. **Steady-state thermal** (`solve_thermal`): heat conduction `K_t T = Q`,
   one scalar temperature DOF per node, element conductivity matrix
   `k_e = k * V * (∇N)ᵀ(∇N)` built from the same shape-function gradients as
   the structural `B` matrix, fixed-temperature Dirichlet BCs via the same
   free/fixed partitioning, and concentrated nodal heat sources as loads.

This is the same class of method professional codes like CalculiX use — this
implementation is simplified (single element type, linear/steady-state
analysis only, lumped mass) but numerically correct: the static solver was
validated against classical cantilever-beam bending theory (order-of-
magnitude agreement, with the expected extra stiffness from coarse linear
tetrahedra — a well-known property of constant-strain elements, not a bug),
and the modal solver's first bending frequency likewise lands in the correct
order of magnitude against the analytical cantilever formula for the same
coarse mesh.

`backend/app/calculix.py` is the alternate path for **static analysis
only**: it writes the exact same model out as a CalculiX `.inp` deck
(`*NODE`, `*ELEMENT TYPE=C3D4`, `*MATERIAL`, `*BOUNDARY`, `*CLOAD`,
`*STATIC` step — pressure and gravity are pre-converted to the same
equivalent `*CLOAD` nodal forces the internal solver uses, rather than
native `*DLOAD`/`*DFLUX` cards), shells out to `ccx`, and parses
displacements/stresses (including principal stresses) back out of the
`.frd` output file. This is used automatically whenever `ccx` is found on
`PATH` for a static job — you get to upgrade to the "real" solver just by
installing one package, with zero application code changes. Modal and
thermal jobs always use the internal solver regardless of whether `ccx` is
installed (see below).

### Extending it

- **CalculiX passthrough for modal/thermal**: `write_inp` would need a
  `*FREQUENCY` step (and `.frd` eigenmode parsing) for modal, and a
  `*HEAT TRANSFER` step with `*CONDUCTIVITY`/`*CFLUX` cards for thermal;
  `jobs.py`'s `_run_modal`/`_run_thermal` currently call the internal solver
  unconditionally, so wiring in a `calculix.solve_modal_with_calculix`/
  `solve_thermal_with_calculix` there is the natural next step.
- **More element types** (shells, beams, hex): add a new shape-function/
  gradient function in `solver.py` (parallel to `_tet4_shape_grads`) and
  branch on element connectivity length; CalculiX already supports these
  via different `*ELEMENT TYPE=` values in `calculix.py`.
- **Transient/nonlinear analysis** (dynamic time-history, large
  deformation, plasticity, contact): add a new function alongside
  `solve_linear_static` and extend `analysis_type` on the `Project` model;
  CalculiX already supports these via different `*STEP` cards in
  `calculix.py`.
- **Real CAD import** (STEP/IGES): pipe an uploaded file through a geometry
  kernel (e.g. `pythonocc`/OpenCascade) to get a boundary representation,
  then tetrahedralize with Gmsh/TetGen and POST the resulting arrays to
  `/api/projects/{id}/mesh/custom` — the rest of the pipeline (BCs, solve,
  post-processing) needs no changes.

---

## Troubleshooting

- **"No boundary conditions applied" error on solve (static)** — a model
  with no fixed supports is a rigid body with no unique static solution
  (division by a singular stiffness matrix); add at least one fixed
  support.
- **"Add at least one load..." error (static)** — a force, pressure, or
  enabled gravity is required; a static analysis with only supports and no
  load has nothing to solve for.
- **"Could not solve the eigenproblem..." error (modal)** — fixing only a
  single point (or a few collinear points) removes translational rigid-body
  motion but not rotation about that point/line, leaving the constrained
  stiffness matrix singular. Fix a full face (several non-collinear nodes)
  instead.
- **"No fixed-temperature boundary condition applied" error (thermal)** — a
  model with only heat-flux loads and no fixed temperature has no unique
  steady-state solution (same underlying issue as an unsupported static
  model); fix the temperature of at least one node.
- **"Project has no mesh yet"** — generate a primitive mesh (or upload one)
  before adding BCs/loads/solving.
- **CalculiX not detected on Docker** — some platforms (e.g. Apple Silicon
  hosts building `linux/arm64` images) may not have a `calculix-ccx`
  package available; the build continues and the app just uses the
  built-in solver, which requires no configuration change.
- **Modal/thermal jobs always show `solver_used: "internal"` even with
  CalculiX installed** — expected; CalculiX passthrough currently only
  covers static analysis (see [Extending it](#extending-it)).
- **Large/slow solves** — the internal solver is a direct sparse solve;
  meshes of a few thousand nodes solve in well under a second on a laptop,
  tens of thousands in a few seconds. Modal analysis additionally factors
  the constrained stiffness matrix for shift-invert eigensolving, which is
  comparable in cost to one static solve. For very large or repeated
  parametric studies, install real CalculiX for better performance and
  additional element types.

---

## License / attribution

This project is provided as-is for you to run locally and deploy. It uses:
FastAPI, SQLAlchemy, NumPy, SciPy (backend); React, Vite, Three.js,
`@react-three/fiber`/`drei` (frontend); optionally CalculiX (`ccx`, GPL) if
you choose to install it on the host/container.
