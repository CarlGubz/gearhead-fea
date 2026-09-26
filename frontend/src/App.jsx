import React, { useEffect, useState, useCallback, useRef } from "react";
import Viewport3D from "./components/Viewport3D.jsx";
import GeometryPanel from "./components/GeometryPanel.jsx";
import MaterialPanel from "./components/MaterialPanel.jsx";
import BCLoadPanel from "./components/BCLoadPanel.jsx";
import JobPanel from "./components/JobPanel.jsx";
import ProjectPanel from "./components/ProjectPanel.jsx";
import Legend from "./components/Legend.jsx";
import * as api from "./api.js";

export default function App() {
  const [health, setHealth] = useState(null);
  const [projects, setProjects] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [project, setProject] = useState(null);

  const [pickMode, setPickMode] = useState("none");
  const [selectedNodes, setSelectedNodes] = useState([]);

  const [job, setJob] = useState(null);
  const [solving, setSolving] = useState(false);
  const [resultField, setResultField] = useState("von_mises");
  const [deformScale, setDeformScale] = useState(10);

  const pollRef = useRef(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: "unreachable" }));
    refreshProjects();
  }, []);

  const refreshProjects = () => {
    api.listProjects().then((ps) => {
      setProjects(ps);
      if (!activeId && ps.length) selectProject(ps[0].id);
    });
  };

  const selectProject = (id) => {
    setActiveId(id);
    setJob(null);
    setSelectedNodes([]);
    api.getProject(id).then(setProject);
  };

  const handleCreate = (name) => {
    api.createProject(name).then((p) => {
      refreshProjects();
      selectProject(p.id);
    });
  };

  const handleDelete = (id) => {
    api.deleteProject(id).then(() => {
      if (id === activeId) {
        setActiveId(null);
        setProject(null);
      }
      refreshProjects();
    });
  };

  const handleGenerateMesh = (shape, dims, divisions) => {
    api.generatePrimitive(activeId, shape, dims, divisions).then((p) => {
      setProject(p);
      setJob(null);
      setSelectedNodes([]);
    });
  };

  const handleMaterialChange = (material) => {
    api.setMaterial(activeId, material).then(setProject);
  };

  const handlePickFace = (tri, additive) => {
    if (pickMode !== "select") return;
    setSelectedNodes((prev) => {
      const set = new Set(additive ? prev : []);
      const allSelected = tri.every((n) => set.has(n));
      tri.forEach((n) => {
        if (allSelected) set.delete(n);
        else set.add(n);
      });
      return Array.from(set);
    });
  };

  const handleAddBC = (bc) => {
    api.addBC(activeId, bc).then((p) => {
      setProject(p);
      setSelectedNodes([]);
    });
  };
  const handleDeleteBC = (bcId) => api.deleteBC(activeId, bcId).then(setProject);

  const handleAddLoad = (load) => {
    api.addLoad(activeId, load).then((p) => {
      setProject(p);
      setSelectedNodes([]);
    });
  };
  const handleDeleteLoad = (loadId) => api.deleteLoad(activeId, loadId).then(setProject);

  const handleSolve = () => {
    setSolving(true);
    api.solve(activeId).then((j) => {
      setJob(j);
      startPolling(j.id);
    }).catch((err) => {
      setSolving(false);
      alert(err?.response?.data?.detail || "Failed to start solve");
    });
  };

  const startPolling = (jobId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => {
      api.getJob(jobId).then((j) => {
        setJob(j);
        if (j.status === "completed" || j.status === "failed") {
          clearInterval(pollRef.current);
          setSolving(false);
        }
      });
    }, 800);
  };

  useEffect(() => () => pollRef.current && clearInterval(pollRef.current), []);

  // Derive the field array shown as contour colors
  let field = null;
  let legendMin, legendMax, legendLabel, legendUnit;
  if (job?.status === "completed") {
    if (resultField === "von_mises") {
      field = job.results.von_mises_nodal;
      legendLabel = "Von Mises Stress";
      legendUnit = "Pa";
      legendMin = 0;
      legendMax = job.results.max_von_mises?.toExponential(2);
    } else if (resultField === "displacement") {
      field = job.results.displacements.map((d) => Math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2));
      legendLabel = "Displacement Magnitude";
      legendUnit = "m";
      legendMin = 0;
      legendMax = job.results.max_displacement?.toExponential(2);
    }
  }

  const displacements = job?.status === "completed" ? job.results.displacements : null;

  return (
    <div className="app">
      <header>
        <h1>Gearhead FEA Suite - POC</h1>
        {/* <span className="subtitle">Browser CAD / CAE Suite</span> */}
        {health && (
          <span className={`badge ${health.status === "ok" ? "ok" : "warn"}`}>
            {health.status === "ok"
              ? health.calculix_available
                ? "CalculiX solver ready"
                : "Built-in solver (CalculiX not installed)"
              : "Backend unreachable"}
          </span>
        )}
      </header>

      <div className="body">
        <aside className="sidebar left">
          <ProjectPanel
            projects={projects}
            activeId={activeId}
            onSelect={selectProject}
            onCreate={handleCreate}
            onDelete={handleDelete}
          />
          {project && <GeometryPanel onGenerate={handleGenerateMesh} />}
          {project && <MaterialPanel material={project.material} onChange={handleMaterialChange} />}
        </aside>

        <main className="viewport">
          {project?.nodes?.length ? (
            <Viewport3D
              nodes={project.nodes}
              faces={project.surface_faces}
              displacements={displacements}
              field={field}
              deformScale={displacements ? deformScale / 10 : 0}
              selectedNodes={selectedNodes}
              onPickFace={handlePickFace}
            />
          ) : (
            <div className="empty-state">
              <p>Select or create a project, then generate a mesh to get started.</p>
            </div>
          )}
          <Legend label={legendLabel} min={legendMin} max={legendMax} unit={legendUnit} />
        </main>

        <aside className="sidebar right">
          {project && (
            <BCLoadPanel
              selectedNodes={selectedNodes}
              boundaryConditions={project.boundary_conditions}
              loads={project.loads}
              onAddBC={handleAddBC}
              onDeleteBC={handleDeleteBC}
              onAddLoad={handleAddLoad}
              onDeleteLoad={handleDeleteLoad}
              onClearSelection={() => setSelectedNodes([])}
              pickMode={pickMode}
              setPickMode={setPickMode}
            />
          )}
          {project && (
            <JobPanel
              onSolve={handleSolve}
              job={job}
              resultField={resultField}
              setResultField={setResultField}
              deformScale={deformScale}
              setDeformScale={setDeformScale}
              solving={solving}
            />
          )}
        </aside>
      </div>
    </div>
  );
}
