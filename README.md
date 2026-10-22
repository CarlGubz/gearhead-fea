# Gearhead FEA (WebFEA) — Browser-Based CAD/CAE Simulation Suite

Gearhead FEA is a full-stack web application for finite element analysis, modelled on the **PrePoMax** workflow
(pre-processor → solver → post-processor) with its own **standalone solver** — no CalculiX or any other external
binary is needed. It also ships a product website, PostgreSQL-backed accounts and prepaid **GCash** subscriptions.

```
 Browser (React + Three.js)  ──REST/JSON──▶  FastAPI  ──▶  app/fea  (NumPy / SciPy engine)
  website · accounts · billing                │
  PrePoMax-style workspace                    └──▶  PostgreSQL (users, sessions, projects, jobs, payments)
```

## Documentation map
| Doc | What it covers |
|---|---|
| [`docs/SOLVER_REFERENCE.md`](docs/SOLVER_REFERENCE.md) | **The solver**: elements, formulations, analyses, constraints, verification tables, limits |
| [`docs/SOLVER_AND_PREPOMAX_PLAN.md`](docs/SOLVER_AND_PREPOMAX_PLAN.md) | Scope, CalculiX/PrePoMax capability matrices, roadmap |
| [`docs/SOLVER_AND_PREPOMAX_LOG.md`](docs/SOLVER_AND_PREPOMAX_LOG.md) | What was built, how it was verified, known limitations |
| [`docs/PARTS_AND_MATERIALS.md`](docs/PARTS_AND_MATERIALS.md) | Multiple parts and materials: design, API, verification, limits |
| [`docs/UNDO_ITERATIVE_CONTACT.md`](docs/UNDO_ITERATIVE_CONTACT.md) | Undo/redo, iterative solver for large models, frictionless contact between parts: design, results, limits |
| [`docs/NLGEOM_STRUCTURAL_CAD.md`](docs/NLGEOM_STRUCTURAL_CAD.md) | Large deformation (NLGEOM), truss / beam / shell / spring elements, STEP / IGES / STL import: design, verification numbers, limits |
| [`docs/AI_AGENT_AND_VIEWPORT.md`](docs/AI_AGENT_AND_VIEWPORT.md) | The AI engineering assistant (chat → model → simulation) and the 3-D support / load glyphs and pick cursor: design, tools, API, limits |
| [`docs/MESHING_GMSH_AND_SELECTION.md`](docs/MESHING_GMSH_AND_SELECTION.md) | **Bricks (Hex8 / Hex20) for every shape**, cone and torus, the **full Gmsh mesher** (primitives, CAD, `.msh`; algorithms, size fields, optimisers), the **mid-side pick cursor** on quadratic meshes and the redesigned **node / face selection highlight**: design, options, API, verification, limits |
| [`docs/AUTH_AND_BILLING.md`](docs/AUTH_AND_BILLING.md) | Login system, plans, GCash (PayMongo) flow, going live |
| [`docs/DESIGN_SYSTEM.md`](docs/DESIGN_SYSTEM.md) | Site visual identity and reusable components |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Env vars, Docker/PostgreSQL, production checklist |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) · [`IMPLEMENTATION_LOG.md`](docs/IMPLEMENTATION_LOG.md) | Website/accounts/billing change set |

## What it can do
**AI engineering assistant** — open **✦ AI Assistant** in the workspace toolbar, describe a problem in plain language
(*"1 m steel cantilever, 50 mm square, fixed at one end, 2 kN down at the tip"*) and the agent builds the model in your
project — geometry and mesh, material, analysis type, supports, loads — then **starts the simulation exactly as the Solve
button does**, so progress and results appear in the normal workspace. It fills in any missing value with a stated engineering
default (asking only when something essential is completely absent), reports tool errors back to itself and retries, and
every step is an ordinary undoable edit (Ctrl+Z). Powered by Google Gemini 2.5 Pro; needs `GEMINI_API_KEY` in the
server's `.env` (falls back to Anthropic, then OpenRouter via `OPENROUTER_API_KEY`, when the earlier keys are empty) ([details](docs/AI_AGENT_AND_VIEWPORT.md)).

**PrePoMax-style viewport symbols** — supports are blue **cones** that grip the node along each restrained axis, forces,
pressures and tractions are red **3-D arrows** pointing the way the load acts, temperatures and heat sources are spheres.
In the node / face selection tools a **3-D pick cursor** (hub with red X / green Y / blue Z arrows) snaps to the nearest
node under the pointer — on **quadratic meshes also to the mid-side node at the centre of each edge** — the mouse cursor
becomes a crosshair, and the toolbar uses pictograms instead of ◆ ▤ ◪ glyphs.

**Clear selection feedback** — one click in the node tool selects exactly the node the cursor shows (shift adds / removes) and
marks it with a **magenta 3-D sphere**; the face tool **previews the face under the cursor** (the whole quadrilateral on brick
meshes) and selects it with an exact tint and outline that never spills onto neighbouring faces. In node mode every pickable node
is drawn as a small dot so you can see what the cursor can snap to.

**Pre-processing** — box, cylinder, sphere, tube, plate-with-hole, L-bracket, **cone and torus** primitives, each meshable with
**every** element type: Tet4 / Tet10 / **Hex8 / Hex20 bricks for all shapes** (mapped structured grids, mid-side nodes on the true
curved surface); a built-in mesher **or Gmsh** with its algorithm, element-size, curvature, recombination, optimiser, refinement and
**local size-field** (ball / box) options — also for **CAD import** (STEP / IGES / BREP / STL → tets or bricks) and Gmsh `.msh`
files of any version; **multiple parts, each with its own material from a library** (rename, move, hide, delete; automatic tie between parts);
mesh import (`.inp` with parts and materials, Gmsh `.msh` ASCII / binary, v2 / v4, linear / quadratic); mesh statistics; materials with thermal and plastic
properties; reference points; rigid-body, tie and **frictionless contact** constraints; **beams, trusses, shells and springs** (6-DOF structural models); **CAD import** (STEP / IGES / STL, meshed with Gmsh); **undo/redo** (Ctrl+Z / Ctrl+Y); selection by click, coordinate range, face angle or id,
with named sets; supports (fixed, symmetry, prescribed displacement); loads (force, pressure, traction, remote
force/moment, gravity, centrifugal, thermal strain, heat source, flux, convection, radiation).

**Analyses (8)** — static · nonlinear (J2 plasticity) · frequency · linear buckling · dynamic (Newmark) ·
heat transfer steady · heat transfer transient · thermo-mechanical, plus **large deformation (NLGEOM)** for solids. Free plan: static; Pro: all.

**Post-processing** — contours of displacement, von Mises, Tresca, principal, stress/strain components, plastic
strain, temperature, heat flux; deformation scale/animation, undeformed ghost, mesh edges, section plane, min/max
markers, node probe, legend range, mode/buckling browser, time-frame playback, history charts; export CSV, VTK, PNG;
save/open project files; export a CalculiX/Abaqus-style `.inp` deck.

Accuracy is checked against closed-form solutions in an automated test suite (e.g. cantilever frequency +0.15 %,
Euler buckling load +0.16 %) — see the solver reference.

## Run it
### Docker (PostgreSQL + API + nginx)
```bash
cp .env.example .env        # set POSTGRES_PASSWORD
docker compose up --build   # http://localhost:5173
```
### Local development
```bash
# backend (SQLite by default; set DATABASE_URL=postgresql://... for PostgreSQL)
cd backend && python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend && npm install && npm run dev                      # http://localhost:5173

# optional: enable the AI assistant (key stays on the server)
export GEMINI_API_KEY=...                  # Windows PowerShell: $env:GEMINI_API_KEY = "..."  (or put it in backend/.env)

# create yourself an account (optionally with Pro) without the sign-up form
cd backend && python -m scripts.create_user you@example.com --pro-days 365
```
The Vite dev server proxies `/api` to the backend. Payments default to a mock GCash screen in development.

### Tests
```bash
cd backend && pytest tests                                         # 459 tests, SQLite (the AI agent tests use a scripted fake LLM: no key or network)
TEST_DATABASE_URL=postgresql://user:pass@host/db_test pytest tests  # same suite on PostgreSQL
```

## Repository layout
```
backend/app/
  fea/            standalone solver (elements, assembly, materials, constraints, analyses, recovery, meshgen, inp, runner)
                  + Gmsh meshing: gmsh_options.py (validation / catalogue), gmsh_worker.py (own process), cad.py (runner)
  agent.py        AI assistant: Gemini / Anthropic / OpenRouter tool loop + model-building tools
  routers/        auth + billing endpoints          payments/   PayMongo + mock provider
  main.py         project / mesh / model / job API  jobs.py     runs the engine, stores results
backend/tests/    fea/ benchmarks, API end-to-end, auth, billing
frontend/src/
  pages/          site pages + Workspace            components/ workspace panels, 3-D viewport, glyphs, AgentPanel, utils
  ui/ brand/ layout/ site/ auth/   reusable site components
docs/             plan, logs, solver reference, billing, design, deployment
```

## API (summary)
Interactive docs at `/docs` in development. All project routes require a signed-in session.

| Area | Endpoints |
|---|---|
| Account | `POST /api/auth/register · login · logout · change-password · forgot-password · reset-password`, `GET /api/auth/me` |
| Billing | `GET /api/billing/plans · subscription · payments`, `POST /api/billing/checkout`, `POST /api/webhooks/paymongo` |
| Projects | `GET/POST /api/projects`, `GET/DELETE /api/projects/{id}`, `POST /api/projects/import`, `GET …/export/project`, `GET …/export/inp` |
| Mesh | `POST …/mesh/primitive · append · import · cad · custom` (primitive / append take `mesher: "builtin" \| "gmsh"` + `gmsh` options; cad takes `family` and `options`), `GET …/mesh/quality` |
| Model | `PUT …/material · analysis-type · settings · gravity`, `POST/DELETE …/bcs · loads · reference-points · constraints · node-sets` |
| Parts & materials | `POST/PUT/DELETE …/materials[/{id}]`, `PUT/DELETE …/parts/{id}`, `POST …/parts/{id}/translate` |
| AI assistant | `GET /api/agent/status`, `POST /api/projects/{id}/agent/chat` |
| Solve | `POST …/solve`, `GET /api/jobs/{id}`, `GET …/jobs`, `GET …/jobs/latest` |
| Meta | `GET /api/health`, `GET /api/capabilities` (shapes and their default dimensions, element types, Gmsh availability / version / option catalogue) |

## Troubleshooting
- **"model is not fully constrained"** — add supports that stop all rigid-body motion (a full face, not a single node).
- **Buckling: "no buckling mode exists"** — the reference load must compress the part (e.g. a pressure pushing *into* the end face).
- **Nonlinear: "did not converge"** — reduce the load or raise the hardening modulus; increase the number of increments.
- **Bending looks too stiff** — use the quadratic element types (Tet10 / Hex20); Tet4 and Hex8 are intentionally simple.
- **Gmsh says it cannot sweep a shape / produced prisms** — bricks are swept only for box, cylinder, tube, plate with hole and L-bracket; pick *Subdivide* (or *Automatic*) for other shapes, and a full-quad recombination for swept bricks.
- **"Element size … is too small"** — more than 150 elements would fit across the part; raise the element size or lower the density.
- **Node tool selects one node, not a whole face** — use the face tool (or *By coordinate* in the Selection panel) to constrain or load a whole face.
- **Slow solves** — direct sparse solver: about 6–9 s at 30–40k DOFs. Lower the mesh density or use quadratic elements on a coarser mesh.

- **"The assistant is switched off on this server"** — set `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY`) in `backend/.env` (or the root `.env` for Docker) and restart.
- **The assistant says a Pro analysis is unavailable** — modal, buckling, dynamic, nonlinear and thermal analyses need the Pro plan; it will offer a static model instead.
- **The assistant built something different from what you meant** — say so in the chat (it can inspect and fix the model), or press Ctrl+Z to undo its steps one by one.

## License / attribution
Provided as-is. Uses FastAPI, SQLAlchemy, NumPy, SciPy, Argon2, psycopg, httpx and the Google Gemini API (or Anthropic / OpenRouter as fallbacks) for the optional assistant (backend); React, Vite, Three.js,
`@react-three/fiber`/`drei`, react-router (frontend). The `.inp` format is Abaqus/CalculiX-compatible text; no CalculiX code is used.
