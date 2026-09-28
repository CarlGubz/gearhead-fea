import React, { useEffect, useState, useCallback, useRef } from "react";
import Viewport3D from "./components/Viewport3D.jsx";
import GeometryPanel from "./components/GeometryPanel.jsx";
import MaterialPanel from "./components/MaterialPanel.jsx";
import AnalysisPanel from "./components/AnalysisPanel.jsx";
import BCLoadPanel from "./components/BCLoadPanel.jsx";
import JobPanel from "./components/JobPanel.jsx";
import ProjectPanel from "./components/ProjectPanel.jsx";
import Legend from "./components/Legend.jsx";
import TreeSection from "./components/TreeSection.jsx";
import * as api from "./api.js";

function getInitialTheme() {
  try {
    return document.documentElement.getAttribute("data-theme") || "light";
  } catch (e) {
    return "light";
  }
}

export default function App() {
  const [theme, setTheme] = useState(getInitialTheme);
  const [health, setHealth] = useState(null);
  const [projects, setProjects] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [project, setProject] = useState(null);

  const [pickMode, setPickMode] = useState("none");
  const [selectedNodes, setSelectedNodes] = useState([]);
  const [selectedFaces, setSelectedFaces] = useState([]);

  const [job, setJob] = useState(null);
  const [solving, setSolving] = useState(false);
  const [resultField, setResultField] = useState("von_mises");
  const [deformScale, setDeformScale] = useState(10);
  const [selectedMode, setSelectedMode] = useState(0);

  const pollRef = useRef(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("webfea-theme", theme);
    } catch (e) {
      /* private browsing / storage disabled - theme just won't persist */
    }
  }, [theme]);

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
    setSelectedFaces([]);
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
      setSelectedFaces([]);
    });
  };

  const handleMaterialChange = (material) => {
    api.setMaterial(activeId, material).then(setProject);
  };

  const handleAnalysisTypeChange = (analysisType, nModes) => {
    api.setAnalysisType(activeId, analysisType, nModes).then((p) => {
      setProject(p);
      setJob(null);
      setSelectedNodes([]);
      setSelectedFaces([]);
      setPickMode("none");
      setResultField(analysisType === "thermal" ? "temperature" : "von_mises");
    });
  };

  const handleGravityChange = (gravity) => {
    api.setGravity(activeId, gravity).then(setProject);
  };

  const handlePickFace = (tri, additive) => {
    if (pickMode === "select") {
      setSelectedNodes((prev) => {
        const set = new Set(additive ? prev : []);
        const allSelected = tri.every((n) => set.has(n));
        tri.forEach((n) => {
          if (allSelected) set.delete(n);
          else set.add(n);
        });
        return Array.from(set);
      });
    } else if (pickMode === "select-faces") {
      setSelectedFaces((prev) => {
        const key = [...tri].sort().join(",");
        const exists = prev.some((f) => [...f].sort().join(",") === key);
        if (exists) return prev.filter((f) => [...f].sort().join(",") !== key);
        return additive ? [...prev, tri] : [tri];
      });
    }
  };

  const handleAddBC = (bc) => {
    api.addBC(activeId, bc).then((p) => {
      setProject(p);
      setSelectedNodes([]);
      setSelectedFaces([]);
    });
  };
  const handleDeleteBC = (bcId) => api.deleteBC(activeId, bcId).then(setProject);

  const handleAddLoad = (load) => {
    api.addLoad(activeId, load).then((p) => {
      setProject(p);
      setSelectedNodes([]);
      setSelectedFaces([]);
    });
  };
  const handleDeleteLoad = (loadId) => api.deleteLoad(activeId, loadId).then(setProject);

  const handleSolve = () => {
    setSolving(true);
    setSelectedMode(0);
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

  const analysisType = project?.analysis_type || "static";

  const arrayMin = (arr) => arr.reduce((m, v) => (v < m ? v : m), arr[0]);
  const arrayMax = (arr) => arr.reduce((m, v) => (v > m ? v : m), arr[0]);

  // Derive the field array shown as contour colors, and the displacement
  // field used to deform the mesh, based on analysis type and result job.
  let field = null;
  let displacements = null;
  let legendMin, legendMax, legendLabel, legendUnit;

  if (job?.status === "completed") {
    const results = job.results;
    if (results.analysis_type === "static") {
      displacements = results.displacements;
      if (resultField === "von_mises") {
        field = results.von_mises_nodal;
        legendLabel = "Von Mises Stress";
        legendUnit = "Pa";
        legendMin = 0;
        legendMax = results.max_von_mises?.toExponential(2);
      } else if (resultField === "displacement") {
        field = results.displacements.map((d) => Math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2));
        legendLabel = "Displacement Magnitude";
        legendUnit = "m";
        legendMin = 0;
        legendMax = results.max_displacement?.toExponential(2);
      } else if (resultField === "principal_max") {
        field = results.principal_stress_max_nodal;
        legendLabel = "Max Principal Stress (S1)";
        legendUnit = "Pa";
        legendMin = arrayMin(field).toExponential(2);
        legendMax = arrayMax(field).toExponential(2);
      } else if (resultField === "principal_min") {
        field = results.principal_stress_min_nodal;
        legendLabel = "Min Principal Stress (S3)";
        legendUnit = "Pa";
        legendMin = arrayMin(field).toExponential(2);
        legendMax = arrayMax(field).toExponential(2);
      }
    } else if (results.analysis_type === "modal") {
      const shape = results.mode_shapes[selectedMode] || results.mode_shapes[0];
      displacements = shape;
      field = shape ? shape.map((d) => Math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)) : null;
      legendLabel = `Mode ${selectedMode + 1} shape (normalized)`;
      legendUnit = "";
      legendMin = 0;
      legendMax = 1;
    } else if (results.analysis_type === "thermal") {
      field = results.temperatures;
      legendLabel = "Temperature";
      legendUnit = "";
      legendMin = results.min_temperature?.toFixed(2);
      legendMax = results.max_temperature?.toFixed(2);
    }
  }

  const deformActive = displacements ? deformScale / 10 : 0;

  const statusText = !health
    ? "Connecting..."
    : health.status !== "ok"
    ? "Backend unreachable"
    : health.calculix_available
    ? "CalculiX solver ready"
    : "Built-in solver (CalculiX not installed)";

  return (
    <div className="app">
      <div className="toolbar">
        <div className="brand">
          <span className="brand-icon">FE</span>
          <h1>Gearhead FEA Suite</h1>
        </div>
        <div className="divider" />
        {health && (
          <span className={`badge ${health.status === "ok" ? "ok" : "warn"}`}>{statusText}</span>
        )}
        <div className="spacer" />
        <button
          className="toolbar-btn"
          title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
        >
          {theme === "dark" ? "☀" : "☾"}
        </button>
      </div>

      <div className="body">
        <aside className="sidebar left">
          <div className="tree-root">
            <TreeSection icon="📁" title="Project" defaultOpen>
              <ProjectPanel
                projects={projects}
                activeId={activeId}
                onSelect={selectProject}
                onCreate={handleCreate}
                onDelete={handleDelete}
              />
            </TreeSection>
            {project && (
              <TreeSection icon="📐" title="Geometry & Mesh" defaultOpen>
                <GeometryPanel onGenerate={handleGenerateMesh} />
              </TreeSection>
            )}
            {project && (
              <TreeSection icon="⚙️" title="Analysis" badge={analysisType} defaultOpen>
                <AnalysisPanel
                  analysisType={analysisType}
                  nModes={project.n_modes}
                  gravity={project.gravity}
                  onChangeAnalysisType={handleAnalysisTypeChange}
                  onChangeGravity={handleGravityChange}
                />
              </TreeSection>
            )}
            {project && (
              <TreeSection icon="🧱" title="Material" defaultOpen={false}>
                <MaterialPanel material={project.material} onChange={handleMaterialChange} analysisType={analysisType} />
              </TreeSection>
            )}
          </div>
        </aside>

        <main className="viewport">
          {project?.nodes?.length ? (
            <Viewport3D
              nodes={project.nodes}
              faces={project.surface_faces}
              displacements={displacements}
              field={field}
              deformScale={deformActive}
              selectedNodes={selectedNodes}
              selectedFaces={selectedFaces}
              onPickFace={handlePickFace}
              theme={theme}
              pickMode={pickMode}
              setPickMode={setPickMode}
              allowFacePick={analysisType === "static"}
            />
          ) : (
            <div className="empty-state">
              <p>Select or create a project, then generate a mesh to get started.</p>
            </div>
          )}
          <Legend label={legendLabel} min={legendMin} max={legendMax} unit={legendUnit} />
        </main>

        <aside className="sidebar right">
          <div className="tree-root">
            {project && (
              <TreeSection
                icon="📌"
                title="Boundary Conditions & Loads"
                badge={(project.boundary_conditions?.length || 0) + (project.loads?.length || 0) || null}
                defaultOpen
              >
                <BCLoadPanel
                  analysisType={analysisType}
                  selectedNodes={selectedNodes}
                  selectedFaces={selectedFaces}
                  boundaryConditions={project.boundary_conditions}
                  loads={project.loads}
                  onAddBC={handleAddBC}
                  onDeleteBC={handleDeleteBC}
                  onAddLoad={handleAddLoad}
                  onDeleteLoad={handleDeleteLoad}
                  onClearSelection={() => {
                    setSelectedNodes([]);
                    setSelectedFaces([]);
                  }}
                />
              </TreeSection>
            )}
            {project && (
              <TreeSection icon="🚀" title="Solve" defaultOpen>
                <JobPanel
                  onSolve={handleSolve}
                  job={job}
                  resultField={resultField}
                  setResultField={setResultField}
                  deformScale={deformScale}
                  setDeformScale={setDeformScale}
                  solving={solving}
                  selectedMode={selectedMode}
                  setSelectedMode={setSelectedMode}
                />
              </TreeSection>
            )}
          </div>
        </aside>
      </div>

      <div className="status-bar">
        <span className="status-item">{statusText}</span>
        {job && (
          <>
            <span className="status-item">
              Job: {job.status}
              {job.solver_used ? ` (${job.solver_used})` : ""}
            </span>
            {(job.status === "running" || job.status === "pending") && (
              <div className="status-progress">
                <div className="status-progress-fill" style={{ width: `${(job.progress || 0) * 100}%` }} />
              </div>
            )}
          </>
        )}
        <div className="spacer" />
        <span className="status-item">{project ? project.name : "No project selected"}</span>
      </div>
    </div>
  );
}
