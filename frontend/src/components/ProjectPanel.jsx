import React, { useState } from "react";

export default function ProjectPanel({ projects, activeId, onSelect, onCreate, onDelete }) {
  const [name, setName] = useState("New Project");

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
            <button className="link" onClick={() => onDelete(p.id)}>✕</button>
          </li>
        ))}
      </ul>
    </>
  );
}
