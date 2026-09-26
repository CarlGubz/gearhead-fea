import React, { useState } from "react";

export default function BCLoadPanel({
  selectedNodes,
  boundaryConditions,
  loads,
  onAddBC,
  onDeleteBC,
  onAddLoad,
  onDeleteLoad,
  onClearSelection,
  pickMode,
  setPickMode,
}) {
  const [fx, setFx] = useState(0);
  const [fy, setFy] = useState(0);
  const [fz, setFz] = useState(-1000);
  const [fixX, setFixX] = useState(true);
  const [fixY, setFixY] = useState(true);
  const [fixZ, setFixZ] = useState(true);

  const dofs = [fixX, fixY, fixZ].reduce((acc, v, i) => (v ? [...acc, i] : acc), []);

  return (
    <div className="panel">
      <h3>Boundary Conditions &amp; Loads</h3>

      <div className="field-row">
        <label>Pick mode</label>
        <select value={pickMode} onChange={(e) => setPickMode(e.target.value)}>
          <option value="none">Off (rotate/zoom)</option>
          <option value="select">Select nodes (click faces on model)</option>
        </select>
      </div>

      <p className="hint">
        {selectedNodes.length} node(s) selected.{" "}
        {selectedNodes.length > 0 && (
          <button className="link" onClick={onClearSelection}>
            clear
          </button>
        )}
      </p>

      <fieldset>
        <legend>Fix selected nodes</legend>
        <label><input type="checkbox" checked={fixX} onChange={(e) => setFixX(e.target.checked)} /> X</label>
        <label><input type="checkbox" checked={fixY} onChange={(e) => setFixY(e.target.checked)} /> Y</label>
        <label><input type="checkbox" checked={fixZ} onChange={(e) => setFixZ(e.target.checked)} /> Z</label>
        <button
          disabled={selectedNodes.length === 0}
          onClick={() => onAddBC({ name: "Fixed", node_ids: selectedNodes, dofs })}
        >
          Add Fixed Support
        </button>
      </fieldset>

      <fieldset>
        <legend>Apply load to selected nodes</legend>
        <div className="field-row">
          <label>Fx (N)</label>
          <input type="number" value={fx} onChange={(e) => setFx(parseFloat(e.target.value))} />
        </div>
        <div className="field-row">
          <label>Fy (N)</label>
          <input type="number" value={fy} onChange={(e) => setFy(parseFloat(e.target.value))} />
        </div>
        <div className="field-row">
          <label>Fz (N)</label>
          <input type="number" value={fz} onChange={(e) => setFz(parseFloat(e.target.value))} />
        </div>
        <button
          disabled={selectedNodes.length === 0}
          onClick={() => onAddLoad({ name: "Force", node_ids: selectedNodes, vector: [fx, fy, fz] })}
        >
          Add Load
        </button>
      </fieldset>

      <div className="list-block">
        <h4>Fixed supports</h4>
        {(boundaryConditions || []).length === 0 && <p className="hint">None yet.</p>}
        <ul>
          {(boundaryConditions || []).map((bc) => (
            <li key={bc.id}>
              {bc.name} — {bc.node_ids.length} node(s), dofs {bc.dofs.join(",")}
              <button className="link" onClick={() => onDeleteBC(bc.id)}>✕</button>
            </li>
          ))}
        </ul>
      </div>

      <div className="list-block">
        <h4>Loads</h4>
        {(loads || []).length === 0 && <p className="hint">None yet.</p>}
        <ul>
          {(loads || []).map((ld) => (
            <li key={ld.id}>
              {ld.name} — {ld.node_ids.length} node(s), F=({ld.vector.map((v) => v.toFixed(1)).join(", ")}) N
              <button className="link" onClick={() => onDeleteLoad(ld.id)}>✕</button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
