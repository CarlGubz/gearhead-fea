import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import workspaceCss from "../styles.css?inline";
import { useAuth } from "../auth/AuthContext.jsx";
import { Logo } from "../brand/Logo.jsx";
import Viewport3D from "../components/Viewport3D.jsx";
import GeometryPanel from "../components/GeometryPanel.jsx";
import MaterialPanel from "../components/MaterialPanel.jsx";
import PartsPanel from "../components/PartsPanel.jsx";
import StructuralPanel from "../components/StructuralPanel.jsx";
import AnalysisPanel from "../components/AnalysisPanel.jsx";
import BCLoadPanel from "../components/BCLoadPanel.jsx";
import ConstraintPanel from "../components/ConstraintPanel.jsx";
import SelectionPanel from "../components/SelectionPanel.jsx";
import JobPanel from "../components/JobPanel.jsx";
import ProjectPanel from "../components/ProjectPanel.jsx";
import MessagesPanel from "../components/MessagesPanel.jsx";
import AgentPanel from "../components/AgentPanel.jsx";
import Legend from "../components/Legend.jsx";
import TreeSection from "../components/TreeSection.jsx";
import {
  autoScale, boundingBox, buildDisplay, buildTubeView, defaultField, download, facesByAngle, fmt, isLineElement, isStructural,
  minMax, resultsToCSV, resultsToVTK, surfaceNodeIds,
} from "../components/utils.js";
import { buildGlyphs } from "../components/glyphs.js";
import * as api from "../api.js";

function getInitialTheme() {
  try {
    return document.documentElement.getAttribute("data-theme") || "light";
  } catch (e) {
    return "light";
  }
}

/**
 * The simulation workspace. Its stylesheet is global (element selectors such as `button` and `label`),
 * so it is injected only while this route is mounted instead of leaking into the marketing pages.
 */
function useWorkspaceStyles() {
  useLayoutEffect(() => {
    const el = document.createElement("style");
    el.setAttribute("data-workspace", "");
    el.textContent = workspaceCss;
    document.head.appendChild(el);
    return () => el.remove();
  }, []);
}

const navBtn = { textDecoration: "none", whiteSpace: "nowrap", flex: "none", width: "auto", padding: "0 10px", fontSize: 13 };

const DEFAULT_VIEW = {
  deformScale: 1, scaleMax: 10, animate: false, showUndeformed: false, showEdges: false, showMinMax: false,
  rangeAuto: true, rangeMin: 0, rangeMax: 1, probeMode: false,
  clip: { enabled: false, axis: 0, pos: 0.5, flip: false },
};

let msgSeq = 0;

export default function Workspace() {
  useWorkspaceStyles();
  const { user, isPro, logout } = useAuth();
  const navigate = useNavigate();
  const [theme, setTheme] = useState(getInitialTheme);
  const [health, setHealth] = useState(null);
  const [projects, setProjects] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [project, setProject] = useState(null);
  const [quality, setQuality] = useState(null);

  const [pickMode, setPickMode] = useState("none");
  const [selectedNodes, setSelectedNodes] = useState([]);
  const [selectedFaces, setSelectedFaces] = useState([]);
  const [angle, setAngle] = useState(30);
  const [hiddenParts, setHiddenParts] = useState(() => new Set());

  const [job, setJob] = useState(null);
  const [solving, setSolving] = useState(false);
  const [sel, setSelState] = useState({ field: "von_mises", frame: 0 });
  const [view, setViewState] = useState(DEFAULT_VIEW);
  const [probeNode, setProbeNode] = useState(null);
  const [viewCommand, setViewCommand] = useState({ name: "iso", n: 0 });
  const [messages, setMessages] = useState([]);
  const [msgOpen, setMsgOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const viewApi = useRef(null);
  const pollRef = useRef(null);

  const setSel = useCallback((patch) => setSelState((s) => ({ ...s, ...patch })), []);
  const setView = useCallback((patch) => setViewState((v) => ({ ...v, ...patch })), []);
  const setViewName = useCallback((name) => setViewCommand((c) => ({ name, n: c.n + 1 })), []);

  const notify = useCallback((text, level = "info") => {
    setMessages((m) => [...m.slice(-199), { id: ++msgSeq, level, text, time: new Date().toLocaleTimeString() }]);
    if (level === "error" || level === "warn") setMsgOpen(true);
  }, []);

  /** Run an API call; failures become messages instead of unhandled rejections. */
  const guard = useCallback(async (promise, fallback) => {
    try {
      return await promise;
    } catch (err) {
      if (err?.response?.status !== 402) notify(api.errorMessage(err, fallback), "error");
      return undefined;
    }
  }, [notify]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("webfea-theme", theme); } catch (e) { /* storage unavailable */ }
  }, [theme]);

  useEffect(() => () => pollRef.current && clearInterval(pollRef.current), []);

  /* ------------------------------------------------------ results display */
  const clearResults = useCallback(() => {
    setJob(null);
    setProbeNode(null);
    setViewState((v) => ({ ...DEFAULT_VIEW, showEdges: v.showEdges, clip: v.clip }));
  }, []);

  const showResults = useCallback((j, p) => {
    setJob(j);
    if (j?.status !== "completed") return;
    const r = j.results;
    const field = defaultField(r);
    // open dynamics at the peak response and transient heat at the final state
    const frame = r.analysis_type === "dynamic" ? r.peak_frame || 0 : r.analysis_type === "thermal_transient" ? (r.frames?.length || 1) - 1 : 0;
    setSelState({ field, frame });
    const d = buildDisplay(r, { field, frame }, p.nodes.length);
    const scale = autoScale(d.disp, boundingBox(p.nodes).size);
    setViewState((v) => ({
      ...v, deformScale: scale, scaleMax: Math.max(scale * 10, 10), rangeAuto: true, probeMode: false,
      animate: r.analysis_type === "modal" || r.analysis_type === "buckling",
    }));
    setProbeNode(null);
  }, []);

  const results = job?.status === "completed" ? job.results : null;
  const nNodes = project?.nodes?.length || 0;
  const display = useMemo(() => buildDisplay(results, sel, nNodes), [results, sel, nNodes]);
  const fieldRange = useMemo(() => (display.field && display.field.length ? minMax(display.field) : [0, 1]), [display.field]);
  const range = view.rangeAuto ? null : [view.rangeMin, view.rangeMax];
  const legendRange = range || fieldRange;

  const probe = useMemo(() => {
    if (probeNode === null || !results) return null;
    const rows = [];
    const d = display.disp?.[probeNode];
    if (d) rows.push(["u (x,y,z)", d.map((v) => fmt(v, 3)).join(", ")]);
    if (display.field) rows.push([(display.label || "value").split("·")[0].trim(), `${fmt(display.field[probeNode], 5)} ${display.unit || ""}`]);
    Object.entries(results.fields || {}).forEach(([k, arr]) => {
      if (["von_mises", "temperature", "plastic_strain", "tresca"].includes(k)) rows.push([k.replace(/_/g, " "), fmt(arr[probeNode], 5)]);
    });
    return { node: probeNode, rows };
  }, [probeNode, results, display]);

  /* ---------------------------------------------------------- project load */
  const loadQuality = useCallback((id) => {
    api.meshQuality(id).then(setQuality).catch(() => setQuality(null));
  }, []);

  const selectProject = useCallback(async (id) => {
    setActiveId(id);
    setHiddenParts(new Set());
    setSelectedNodes([]);
    setSelectedFaces([]);
    setQuality(null);
    clearResults();
    const p = await guard(api.getProject(id));
    if (!p) return;
    setProject(p);
    if (p.elements?.length) {
      loadQuality(id);
      api.latestJob(id).then((j) => showResults(j, p)).catch(() => {});
    }
  }, [guard, clearResults, loadQuality, showResults]);

  const refreshProjects = useCallback(async () => {
    const ps = await guard(api.listProjects());
    if (ps) setProjects(ps);
    return ps || [];
  }, [guard]);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: "unreachable" }));
    (async () => {
      const ps = await refreshProjects();
      if (ps.length) selectProject(ps[0].id);
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /* ------------------------------------------------------- project actions */
  /** Apply a model edit: replace the project and drop now-stale results. */
  const mutate = useCallback(async (promise, { reload = false } = {}) => {
    const p = await guard(promise);
    if (!p) return undefined;
    setProject(p);
    clearResults();
    if (reload) loadQuality(p.id);
    return p;
  }, [guard, clearResults, loadQuality]);

  const clearSel = () => { setSelectedNodes([]); setSelectedFaces([]); };

  const handleCreate = async (name) => {
    const p = await guard(api.createProject(name));
    if (!p) return;
    await refreshProjects();
    selectProject(p.id);
    notify(`Created project “${p.name}”.`);
  };

  const handleDelete = async (id) => {
    if (!(await guard(api.deleteProject(id)))) return;
    if (id === activeId) { setActiveId(null); setProject(null); clearResults(); }
    const ps = await refreshProjects();
    if (id === activeId && ps.length) selectProject(ps[0].id);
  };

  const handleSave = async () => {
    const text = await guard(api.exportProjectText(activeId));
    if (text) { download(`${project.name.replace(/[^\w-]+/g, "_")}.gfea.json`, text, "application/json"); notify("Project saved."); }
  };
  const handleOpen = async (file) => {
    let data;
    try {
      data = JSON.parse(await file.text());
    } catch (e) {
      notify("That file is not valid JSON.", "error");
      return;
    }
    const p = await guard(api.importProject(data), "That file is not a valid project.");
    if (!p) return;
    await refreshProjects();
    selectProject(p.id);
    notify(`Opened “${p.name}” as a new project.`);
  };
  const handleExportInp = async () => {
    const text = await guard(api.exportInpText(activeId));
    if (text) { download(`${project.name.replace(/[^\w-]+/g, "_")}.inp`, text); notify("Exported a CalculiX/Abaqus-style .inp deck."); }
  };

  const handleGenerate = async (shape, dims, divisions, etype) => {
    const p = await mutate(api.generatePrimitive(activeId, shape, dims, divisions, etype), { reload: true });
    if (p) { clearSel(); setViewName("iso"); notify(`Meshed: ${p.nodes.length} nodes, ${p.elements.length} ${p.element_type} elements.`); }
  };
  const handleAppend = async (shape, dims, divisions, offset, name, materialId) => {
    const p = await mutate(
      api.appendPart(activeId, shape, dims, divisions, offset, project.element_type, name, materialId), { reload: true });
    if (p) { clearSel(); notify(`Added part “${p.parts[p.parts.length - 1].name}”. The mesh now has ${p.nodes.length} nodes.`); }
  };

  const handleImportCad = async (file, opts) => {
    notify(`Meshing ${file.name}… this can take up to a minute.`);
    const p = await mutate(api.importCad(activeId, file, opts), { reload: true });
    if (p) { clearSel(); setViewName("iso"); notify(`Imported ${file.name}: ${p.parts.length} part(s), ${p.nodes.length} nodes, ${p.elements.length} ${p.element_type} elements.`); }
  };
  const handleGenerateStructural = async (body) => {
    const p = await mutate(api.generateStructural(activeId, body), { reload: true });
    if (p) { clearSel(); setViewName("iso"); notify(`Created ${p.nodes.length} nodes, ${p.elements.length} ${p.element_type} elements.`); }
  };
  const handleAppendStructural = async (body) => {
    const p = await mutate(api.appendStructural(activeId, body), { reload: true });
    if (p) { clearSel(); notify(`Added part “${p.parts[p.parts.length - 1].name}” (${p.elements.length} elements in total).`); }
  };
  const handleCustomStructural = async (body) => {
    const p = await mutate(api.customStructural(activeId, body), { reload: true });
    if (p) { clearSel(); setViewName("iso"); notify(`Created ${p.nodes.length} nodes, ${p.elements.length} ${p.element_type} elements.`); }
  };

  /* ------------------------------------------------------ materials & parts */
  const handleMaterialUpdate = (id, m) => mutate(id === "default" ? api.setMaterial(activeId, m) : api.updateMaterial(activeId, id, m));
  const handleMaterialAdd = (m) => mutate(api.addMaterial(activeId, m));
  const handleMaterialDelete = (id) => mutate(api.deleteMaterial(activeId, id));
  const handlePartUpdate = (pid, patch) => mutate(api.updatePart(activeId, pid, patch));
  const handlePartMove = async (pid, offset) => {
    const p = await mutate(api.translatePart(activeId, pid, offset));
    if (p) notify("Part moved. Re-check ties and supports that depend on its position.");
  };
  const handlePartDelete = async (pid) => {
    const p = await mutate(api.deletePart(activeId, pid), { reload: true });
    if (p) { clearSel(); notify("Part deleted. Supports, loads and sets that only used it were removed."); }
  };
  const togglePart = (pid) => setHiddenParts((h) => {
    const n = new Set(h);
    if (n.has(pid)) n.delete(pid); else n.add(pid);
    return n;
  });
  const handleImportMesh = async (file) => {
    const p = await mutate(api.importMesh(activeId, file), { reload: true });
    if (p) { clearSel(); setViewName("iso"); notify(`Imported ${file.name}: ${p.nodes.length} nodes, ${p.elements.length} ${p.element_type} elements.`); }
  };

  /* --------------------------------------------------------------- undo / redo */
  const labels = project?.history_labels || [];
  const pos = project?.history_pos ?? -1;
  const history = {
    canUndo: pos > 0, canRedo: pos >= 0 && pos < labels.length - 1,
    undoLabel: pos > 0 ? labels[pos] : null, redoLabel: pos >= 0 && pos < labels.length - 1 ? labels[pos + 1] : null,
  };
  const handleUndo = async () => {
    if (!history.canUndo) return;
    const label = history.undoLabel;
    const p = await mutate(api.undoEdit(activeId), { reload: true });
    if (p) { clearSel(); notify(`Undid: ${label}`); }
  };
  const handleRedo = async () => {
    if (!history.canRedo) return;
    const label = history.redoLabel;
    const p = await mutate(api.redoEdit(activeId), { reload: true });
    if (p) { clearSel(); notify(`Redid: ${label}`); }
  };
  const undoRef = useRef({});
  undoRef.current = { handleUndo, handleRedo };
  useEffect(() => {
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      const t = e.target;
      if (t && (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || t.isContentEditable)) return;
      const k = e.key.toLowerCase();
      if (k === "z" && !e.shiftKey) { e.preventDefault(); undoRef.current.handleUndo(); }
      else if (k === "y" || (k === "z" && e.shiftKey)) { e.preventDefault(); undoRef.current.handleRedo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /* --------------------------------------------------------------- picking */
  const handlePickFace = (rawTri, additive, faceIdx) => {
    const tri = tube ? Array.from(new Set(rawTri.map((v) => tube.baseOf[v]))) : rawTri;
    if (pickMode === "select") {
      setSelectedFaces([]);
      setSelectedNodes((prev) => {
        const set = new Set(additive ? prev : []);
        const all = tri.every((n) => set.has(n));
        tri.forEach((n) => (all ? set.delete(n) : set.add(n)));
        return Array.from(set);
      });
    } else if (pickMode === "select-faces") {
      setSelectedNodes([]);
      setSelectedFaces((prev) => {
        const key = [...tri].sort().join(",");
        const exists = prev.some((f) => [...f].sort().join(",") === key);
        if (exists) return prev.filter((f) => [...f].sort().join(",") !== key);
        return additive ? [...prev, tri] : [tri];
      });
    } else if (pickMode === "select-angle" && project) {
      setSelectedNodes([]);
      setSelectedFaces(facesByAngle(project.surface_faces, project.nodes, visIdx[faceIdx] ?? faceIdx, angle));
    }
  };

  /* ------------------------------------------------------------ model edits */
  const afterEdit = (msg) => (p) => { if (p) { clearSel(); if (msg) notify(msg); } };
  const handleAddBC = async (bc) => afterEdit("Added.")(await mutate(api.addBC(activeId, bc)));
  const handleAddLoad = async (ld) => afterEdit("Added.")(await mutate(api.addLoad(activeId, ld)));
  const handleSettings = (patch) => mutate(api.setSettings(activeId, patch));
  const handleType = async (type) => {
    const p = await mutate(api.setAnalysisType(activeId, type, project.settings?.n_modes || project.n_modes || 6));
    if (p) { clearSel(); setPickMode("none"); }
  };

  /* ----------------------------------------------------------------- solve */
  const startPolling = (jobId, p) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      const j = await api.getJob(jobId).catch(() => null);
      if (!j) return;
      setJob(j);
      if (j.status === "completed" || j.status === "failed") {
        clearInterval(pollRef.current);
        setSolving(false);
        if (j.status === "failed") notify(j.log, "error");
        else { notify(j.log || "Analysis completed."); showResults(j, p); }
      }
    }, 700);
  };

  /** Start the analysis of `proj` (the manual Solve button and the AI agent both come through here). */
  const runSolve = async (proj) => {
    setSolving(true);
    clearResults();
    const j = await guard(api.solve(proj.id));
    if (!j) { setSolving(false); return; }
    setJob(j);
    notify("Analysis started.");
    startPolling(j.id, proj);
  };
  const handleSolve = () => runSolve(project);

  /** The AI agent edited the project on the server: adopt its version and drop stale results/selection. */
  const handleAgentProject = (p) => {
    setProject(p);
    clearResults();
    clearSel();
    setHiddenParts(new Set());
    if (p.elements?.length) loadQuality(p.id);
    setViewName("iso");
    notify("The AI assistant updated the model.");
  };
  const handleAgentRun = (p) => {
    notify("The AI assistant started the simulation.");
    runSolve(p);
  };

  /* ---------------------------------------------------------------- exports */
  const handleExport = (kind) => {
    if (!results) return;
    const base = (project.name || "results").replace(/[^\w-]+/g, "_");
    if (kind === "csv") download(`${base}_results.csv`, resultsToCSV(project, results, display.disp), "text/csv");
    else if (kind === "vtk") download(`${base}_results.vtk`, resultsToVTK(project, results, display.disp));
    else if (kind === "png" && viewApi.current) {
      const a = document.createElement("a");
      a.href = viewApi.current.capture();
      a.download = `${base}.png`;
      a.click();
    }
  };

  /* ------------------------------------------------------- viewport helpers */
  const structuralType = isStructural(project?.element_type) ? project.element_type : null;
  const lineModel = isLineElement(project?.element_type);
  const tube = useMemo(() => {
    if (!lineModel || !project?.elements?.length) return null;
    const partOf = new Int32Array(project.elements.length);
    (project.parts || []).forEach((p, k) => partOf.fill(k, p.elem_start, p.elem_end));
    const diag = Math.max(Math.hypot(...boundingBox(project.nodes).size), 1e-6);
    const thin = project.element_type === "SPRING2" ? 0.5 : 1;
    return buildTubeView(project.nodes, project.elements, partOf, 0.012 * diag * thin);
  }, [lineModel, project?.nodes, project?.elements, project?.parts, project?.element_type]);
  const viewNodes = tube ? tube.nodes : project?.nodes;
  const toView = useCallback((arr) => {
    if (!tube || !arr) return arr;
    const out = new Array(tube.baseOf.length);
    for (let v = 0; v < out.length; v++) out[v] = arr[tube.baseOf[v]];
    return out;
  }, [tube]);
  const viewDisp = useMemo(() => toView(display.disp), [toView, display.disp]);
  const viewField = useMemo(() => toView(display.field), [toView, display.field]);
  const selNodesView = useMemo(
    () => (tube ? selectedNodes.flatMap((n) => [n, ...(tube.ringsOf[n] || [])]) : selectedNodes), [tube, selectedNodes]);
  const selectionFaces = useMemo(
    () => (lineModel ? (project?.elements || []).map(([a, b]) => [a, b, b]) : project?.surface_faces || []),
    [lineModel, project?.elements, project?.surface_faces]);

  const { visibleFaces, visIdx, faceParts } = useMemo(() => {
    const faces = tube ? tube.faces : project?.surface_faces || [];
    const owner = tube ? tube.faceParts : project?.surface_parts || [];
    const plist = project?.parts || [];
    if (!hiddenParts.size) return { visibleFaces: faces, visIdx: faces.map((_, i) => i), faceParts: owner };
    const vf = [], vi = [], fp = [];
    faces.forEach((t, i) => {
      const pid = plist[owner[i] ?? 0]?.id;
      if (!hiddenParts.has(pid)) { vf.push(t); vi.push(i); fp.push(owner[i] ?? 0); }
    });
    return { visibleFaces: vf, visIdx: vi, faceParts: fp };
  }, [tube, project?.surface_faces, project?.surface_parts, project?.parts, hiddenParts]);
  const surfaceSet = useMemo(
    () => new Set(lineModel ? (project?.elements || []).flat() : surfaceNodeIds(visibleFaces)), [lineModel, project?.elements, visibleFaces]);
  const glyphs = useMemo(() => (project ? buildGlyphs(project, surfaceSet) : []), [project, surfaceSet]);

  const analysisType = project?.analysis_type || "static";
  const oscillate = results?.analysis_type === "modal" || results?.analysis_type === "buckling";
  const statusText = !health ? "Connecting…" : health.status !== "ok" ? "Backend unreachable" : "Standalone solver ready";
  const loadsCount = (project?.boundary_conditions?.length || 0) + (project?.loads?.length || 0);
  const hasMesh = !!project?.elements?.length;

  return (
    <div className="app">
      <div className="toolbar">
        <div className="brand">
          <Logo />
          <span className="brand-sheet">Workspace</span>
        </div>
        <div className="divider" />
        {health && <span className={`badge ${health.status === "ok" ? "ok" : "warn"}`}>{statusText}</span>}
        <div className="spacer" />
        <button className={`toolbar-btn ${agentOpen ? "active" : ""}`} style={navBtn} onClick={() => setAgentOpen((o) => !o)}
          title="Describe a problem in plain language and let the AI build and run the simulation">✦ AI Assistant</button>
        <Link className="toolbar-btn" to="/account" title="Account & billing" style={{ ...navBtn, maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis" }}>
          {isPro ? "Pro" : "Free"} · {user?.email}
        </Link>
        {!isPro && <Link className="toolbar-btn active" to="/pricing" style={navBtn}>Upgrade</Link>}
        <button className="toolbar-btn" style={navBtn} onClick={() => logout().finally(() => navigate("/"))}>Sign out</button>
        <button className="toolbar-btn" title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>
          {theme === "dark" ? "☀" : "☾"}
        </button>
      </div>

      <div className="body">
        <aside className="sidebar left">
          <div className="tree-root">
            <TreeSection icon="01" title="Project" defaultOpen>
              <ProjectPanel projects={projects} activeId={activeId} onSelect={selectProject} onCreate={handleCreate}
                onDelete={handleDelete} onSave={handleSave} onOpen={handleOpen} onExportInp={handleExportInp}
                history={history} onUndo={handleUndo} onRedo={handleRedo} />
            </TreeSection>
            {project && (
              <TreeSection icon="02" title="Geometry & Mesh" defaultOpen={!hasMesh}>
                <GeometryPanel elementType={project.element_type} quality={quality} hasMesh={hasMesh}
                  materials={project.materials} defaultMaterial={project.material}
                  onGenerate={handleGenerate} onAppend={handleAppend} onImport={handleImportMesh} onImportCad={handleImportCad} />
              </TreeSection>
            )}
            {project && (
              <TreeSection icon="02" title="Beams, trusses, shells, springs" badge={structuralType} defaultOpen={!!structuralType}>
                <StructuralPanel project={project} hasMesh={hasMesh} onGenerate={handleGenerateStructural}
                  onAppend={handleAppendStructural} onCustom={handleCustomStructural} onMessage={notify} />
              </TreeSection>
            )}
            {hasMesh && (
              <TreeSection icon="03" title="Parts" badge={project.parts?.length || null} defaultOpen={(project.parts?.length || 0) > 1}>
                <PartsPanel parts={project.parts} defaultMaterial={project.material} materials={project.materials}
                  hidden={hiddenParts} onToggle={togglePart} onUpdate={handlePartUpdate}
                  onMove={handlePartMove} onDelete={handlePartDelete} structuralType={structuralType} />
              </TreeSection>
            )}
            {project && (
              <TreeSection icon="04" title="Materials" badge={1 + (project.materials?.length || 0)} defaultOpen={false}>
                <MaterialPanel material={project.material} materials={project.materials} parts={project.parts}
                  onUpdate={handleMaterialUpdate} onAdd={handleMaterialAdd} onDelete={handleMaterialDelete} />
              </TreeSection>
            )}
            {project && (
              <TreeSection icon="04" title="Analysis" badge={analysisType} defaultOpen>
                <AnalysisPanel analysisType={analysisType} settings={project.settings} gravity={project.gravity} isPro={isPro}
                  onChangeType={handleType} onSettings={handleSettings} onGravity={(g) => mutate(api.setGravity(activeId, g))}
                  structural={!!structuralType} />
              </TreeSection>
            )}
            {hasMesh && (
              <TreeSection icon="05" title="Selection & sets" badge={selectedNodes.length + selectedFaces.length || null} defaultOpen={false}>
                <SelectionPanel nodes={project.nodes} faces={selectionFaces} selectedNodes={selectedNodes}
                  selectedFaces={selectedFaces} setSelectedNodes={setSelectedNodes} setSelectedFaces={setSelectedFaces}
                  angle={angle} setAngle={setAngle} sets={project.node_sets}
                  onSaveSet={(name, kind, ids) => mutate(api.addNodeSet(activeId, { name, kind, ids }))}
                  onDeleteSet={(id) => mutate(api.deleteNodeSet(activeId, id))} />
              </TreeSection>
            )}
          </div>
        </aside>

        <main className="viewport">
          {hasMesh ? (
            <Viewport3D
              nodes={viewNodes} faces={visibleFaces} faceParts={faceParts} displacements={viewDisp} field={viewField}
              range={range} deformScale={view.deformScale} animate={view.animate} oscillate={oscillate}
              showEdges={view.showEdges} showUndeformed={view.showUndeformed} showMinMax={view.showMinMax}
              clip={view.clip} selectedNodes={selNodesView} selectedFaces={selectedFaces} onPickFace={handlePickFace}
              probeMode={view.probeMode && !!display.field} onProbe={(v) => setProbeNode(tube ? tube.baseOf[v] : v)} probeNode={probeNode}
              pickNearest={lineModel} allowFacePick={!lineModel}
              glyphs={results ? [] : glyphs} refPoints={project.reference_points || []} theme={theme} pickMode={pickMode}
              setPickMode={(m) => { setPickMode(m); setView({ probeMode: false }); }}
              viewCommand={viewCommand} setView={setViewName} onApi={(a) => { viewApi.current = a; }}
            />
          ) : (
            <div className="empty-state"><p>Select or create a project, then generate or import a mesh, or open the ✦ AI Assistant and describe your problem.</p></div>
          )}
          {agentOpen && (
            <AgentPanel projectId={activeId} solving={solving} onClose={() => setAgentOpen(false)}
              onProject={handleAgentProject} onRun={handleAgentRun} />
          )}
          {display.field && <Legend label={display.label} min={fmt(legendRange[0])} max={fmt(legendRange[1])} unit={display.unit} />}
        </main>

        <aside className="sidebar right">
          <div className="tree-root">
            {hasMesh && (
              <TreeSection icon="06" title="Supports & loads" badge={loadsCount || null} defaultOpen>
                <BCLoadPanel analysisType={analysisType} selectedNodes={selectedNodes} selectedFaces={selectedFaces}
                  boundaryConditions={project.boundary_conditions} loads={project.loads} refPoints={project.reference_points}
                  structuralType={structuralType} parts={project.parts} onAddBC={handleAddBC} onDeleteBC={(id) => mutate(api.deleteBC(activeId, id))}
                  onAddLoad={handleAddLoad} onDeleteLoad={(id) => mutate(api.deleteLoad(activeId, id))} onMessage={notify} />
              </TreeSection>
            )}
            {hasMesh && !structuralType && (
              <TreeSection icon="07" title="Constraints" badge={(project.constraints?.length || 0) + (project.reference_points?.length || 0) || null} defaultOpen={false}>
                <ConstraintPanel nodes={project.nodes} selectedNodes={selectedNodes} selectedFaces={selectedFaces} parts={project.parts}
                  refPoints={project.reference_points} constraints={project.constraints} sets={project.node_sets}
                  onAddRef={(rp) => mutate(api.addReferencePoint(activeId, rp))} onDeleteRef={(id) => mutate(api.deleteReferencePoint(activeId, id))}
                  onAddConstraint={async (c) => afterEdit("Constraint added.")(await mutate(api.addConstraint(activeId, c)))}
                  onDeleteConstraint={(id) => mutate(api.deleteConstraint(activeId, id))} onMessage={notify} />
              </TreeSection>
            )}
            {project && (
              <TreeSection icon="08" title="Solve & results" defaultOpen>
                <JobPanel onSolve={handleSolve} solving={solving} job={job} project={project} sel={sel} setSel={setSel}
                  view={view} setView={setView} display={display} fieldRange={fieldRange} probe={probe}
                  onExport={handleExport} onClearResults={clearResults}
                  onAutoScale={() => setView({ deformScale: autoScale(display.disp, boundingBox(project.nodes).size) })} />
              </TreeSection>
            )}
          </div>
        </aside>
      </div>

      <MessagesPanel messages={messages} open={msgOpen} setOpen={setMsgOpen} onClear={() => setMessages([])} />

      <div className="status-bar">
        <span className="status-item">{statusText}</span>
        {job && (
          <>
            <span className="status-item">Job: {job.status}</span>
            {(job.status === "running" || job.status === "pending") && (
              <div className="status-progress"><div className="status-progress-fill" style={{ width: `${(job.progress || 0) * 100}%` }} /></div>
            )}
          </>
        )}
        {hasMesh && <span className="status-item">{project.nodes.length.toLocaleString()} nodes · {project.elements.length.toLocaleString()} {project.element_type}</span>}
        <div className="spacer" />
        <span className="status-item">{project ? project.name : "No project selected"}</span>
      </div>
    </div>
  );
}
