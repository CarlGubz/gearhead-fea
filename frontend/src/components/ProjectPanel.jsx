import React, { useRef, useState } from "react";

export default function ProjectPanel({ projects, activeId, onSelect, onCreate, onDelete, onSave, onOpen, onExportInp, history, onUndo, onRedo }) {
  const [name, setName] = useState("New Project");
  const fileRef = useRef(null);

  return (
    <>
      <div className="field-row">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" />
        <button onClick={() => onCreate(name)}>+ New</button>
      </div>
      <ul className="project-list">
        {projects.map((p) => (
          <li key={p.id} className={p.id === activeId ? "active" : ""}>
            <span onClick={() => onSelect(p.id)}>{p.name}</span>
            <button className="link" title="Delete project" onClick={() => window.confirm(`Delete “${p.name}”?`) && onDelete(p.id)}>✕</button>
          </li>
        ))}
      </ul>
      <div className="btn-row" style={{ marginTop: 8 }}>
        <button onClick={onUndo} disabled={!history?.canUndo}
          title={history?.canUndo ? `Undo: ${history.undoLabel} (Ctrl+Z)` : "Nothing to undo"}>↶ Undo</button>
        <button onClick={onRedo} disabled={!history?.canRedo}
          title={history?.canRedo ? `Redo: ${history.redoLabel} (Ctrl+Y)` : "Nothing to redo"}>↷ Redo</button>
      </div>
      <div className="btn-row">
        <button onClick={onSave} disabled={!activeId} title="Download the project as a .gfea.json file">Save…</button>
        <button onClick={() => fileRef.current?.click()} title="Open a saved .gfea.json project as a new project">Open…</button>
        <button onClick={onExportInp} disabled={!activeId} title="Export a CalculiX/Abaqus-style .inp deck">Export .inp</button>
      </div>
      <input ref={fileRef} type="file" accept=".json,application/json" style={{ display: "none" }}
        onChange={(e) => { if (e.target.files[0]) onOpen(e.target.files[0]); e.target.value = ""; }} />
    </>
  );
}
