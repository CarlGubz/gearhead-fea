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
| [`docs/AUTH_AND_BILLING.md`](docs/AUTH_AND_BILLING.md) | Login system, plans, GCash (PayMongo) flow, going live |
| [`docs/DESIGN_SYSTEM.md`](docs/DESIGN_SYSTEM.md) | Site visual identity and reusable components |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Env vars, Docker/PostgreSQL, production checklist |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) · [`IMPLEMENTATION_LOG.md`](docs/IMPLEMENTATION_LOG.md) | Website/accounts/billing change set |

## What it can do
**Pre-processing** — box, cylinder, sphere, tube, plate-with-hole and L-bracket primitives; Tet4 / Tet10 / Hex8 / Hex20
elements; **multiple parts, each with its own material from a library** (rename, move, hide, delete; automatic tie between parts);
mesh import (`.inp` with parts and materials, Gmsh `.msh`); mesh statistics; materials with thermal and plastic
properties; reference points; rigid-body, tie and **frictionless contact** constraints; **undo/redo** (Ctrl+Z / Ctrl+Y); selection by click, coordinate range, face angle or id,
with named sets; supports (fixed, symmetry, prescribed displacement); loads (force, pressure, traction, remote
force/moment, gravity, centrifugal, thermal strain, heat source, flux, convection, radiation).

**Analyses (8)** — static · nonlinear (J2 plasticity) · frequency · linear buckling · dynamic (Newmark) ·
heat transfer steady · heat transfer transient · thermo-mechanical. Free plan: static; Pro: all.

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

# create yourself an account (optionally with Pro) without the sign-up form
cd backend && python -m scripts.create_user you@example.com --pro-days 365
```
The Vite dev server proxies `/api` to the backend. Payments default to a mock GCash screen in development.

### Tests
```bash
cd backend && pytest tests                                         # 150 tests, SQLite
TEST_DATABASE_URL=postgresql://user:pass@host/db_test pytest tests  # same suite on PostgreSQL
```

## Repository layout
```
backend/app/
  fea/            standalone solver (elements, assembly, materials, constraints, analyses, recovery, meshgen, inp, runner)
  routers/        auth + billing endpoints          payments/   PayMongo + mock provider
  main.py         project / mesh / model / job API  jobs.py     runs the engine, stores results
backend/tests/    fea/ benchmarks, API end-to-end, auth, billing
frontend/src/
  pages/          site pages + Workspace            components/ workspace panels, 3-D viewport, utils
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
| Mesh | `POST …/mesh/primitive · append · import · custom`, `GET …/mesh/quality` |
| Model | `PUT …/material · analysis-type · settings · gravity`, `POST/DELETE …/bcs · loads · reference-points · constraints · node-sets` |
| Parts & materials | `POST/PUT/DELETE …/materials[/{id}]`, `PUT/DELETE …/parts/{id}`, `POST …/parts/{id}/translate` |
| Solve | `POST …/solve`, `GET /api/jobs/{id}`, `GET …/jobs`, `GET …/jobs/latest` |
| Meta | `GET /api/health`, `GET /api/capabilities` |

## Troubleshooting
- **"model is not fully constrained"** — add supports that stop all rigid-body motion (a full face, not a single node).
- **Buckling: "no buckling mode exists"** — the reference load must compress the part (e.g. a pressure pushing *into* the end face).
- **Nonlinear: "did not converge"** — reduce the load or raise the hardening modulus; increase the number of increments.
- **Bending looks too stiff** — use the quadratic element types (Tet10 / Hex20); Tet4 and Hex8 are intentionally simple.
- **Slow solves** — direct sparse solver: about 6–9 s at 30–40k DOFs. Lower the mesh density or use quadratic elements on a coarser mesh.

## License / attribution
Provided as-is. Uses FastAPI, SQLAlchemy, NumPy, SciPy, Argon2, psycopg (backend); React, Vite, Three.js,
`@react-three/fiber`/`drei`, react-router (frontend). The `.inp` format is Abaqus/CalculiX-compatible text; no CalculiX code is used.
