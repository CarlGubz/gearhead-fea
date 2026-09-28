import React, { useState } from "react";

export default function BCLoadPanel({
  analysisType,
  selectedNodes,
  selectedFaces,
  boundaryConditions,
  loads,
  onAddBC,
  onDeleteBC,
  onAddLoad,
  onDeleteLoad,
  onClearSelection,
}) {
  const [fx, setFx] = useState(0);
  const [fy, setFy] = useState(0);
  const [fz, setFz] = useState(-1000);
  const [fixX, setFixX] = useState(true);
  const [fixY, setFixY] = useState(true);
  const [fixZ, setFixZ] = useState(true);
  const [pressure, setPressure] = useState(1000);
  const [temperature, setTemperature] = useState(20);
  const [heatFlux, setHeatFlux] = useState(10);

  const dofs = [fixX, fixY, fixZ].reduce((acc, v, i) => (v ? [...acc, i] : acc), []);
  const faceNodeCount = new Set((selectedFaces || []).flat()).size;

  return (
    <>
      <p className="hint">
        {selectedNodes.length} node(s) / {(selectedFaces || []).length} face(s) selected.{" "}
        {(selectedNodes.length > 0 || (selectedFaces || []).length > 0) && (
          <button className="link" onClick={onClearSelection}>
            clear
          </button>
        )}
      </p>

      {analysisType === "thermal" ? (
        <>
          <fieldset>
            <legend>Fix temperature of selected nodes</legend>
            <div className="field-row">
              <label>Temperature</label>
              <input type="number" value={temperature} onChange={(e) => setTemperature(parseFloat(e.target.value))} />
            </div>
            <button
              disabled={selectedNodes.length === 0}
              onClick={() => onAddBC({ name: "Fixed Temperature", node_ids: selectedNodes, dofs: [0], values: [temperature] })}
            >
              Add Fixed Temperature
            </button>
          </fieldset>

          <fieldset>
            <legend>Heat source on selected nodes</legend>
            <div className="field-row">
              <label>Heat rate Q (W)</label>
              <input type="number" value={heatFlux} onChange={(e) => setHeatFlux(parseFloat(e.target.value))} />
            </div>
            <button
              disabled={selectedNodes.length === 0}
              onClick={() =>
                onAddLoad({ name: "Heat Flux", load_type: "heat_flux", node_ids: selectedNodes, magnitude: heatFlux })
              }
            >
              Add Heat Flux
            </button>
          </fieldset>
        </>
      ) : (
        <fieldset>
          <legend>{analysisType === "modal" ? "Support selected nodes" : "Fix selected nodes"}</legend>
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
      )}

      {analysisType === "static" && (
        <>
          <fieldset>
            <legend>Apply force to selected nodes</legend>
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
              onClick={() => onAddLoad({ name: "Force", load_type: "force", node_ids: selectedNodes, vector: [fx, fy, fz] })}
            >
              Add Force
            </button>
          </fieldset>

          <fieldset>
            <legend>Apply pressure to selected faces</legend>
            <div className="field-row">
              <label>Pressure (Pa, + = inward)</label>
              <input type="number" value={pressure} onChange={(e) => setPressure(parseFloat(e.target.value))} />
            </div>
            <button
              disabled={(selectedFaces || []).length === 0}
              onClick={() =>
                onAddLoad({
                  name: "Pressure",
                  load_type: "pressure",
                  node_ids: Array.from(new Set((selectedFaces || []).flat())),
                  faces: selectedFaces,
                  magnitude: pressure,
                })
              }
            >
              Add Pressure ({faceNodeCount} node(s) on {(selectedFaces || []).length} face(s))
            </button>
          </fieldset>
        </>
      )}

      <div className="list-block">
        <h4>{analysisType === "thermal" ? "Fixed temperatures" : "Fixed supports"}</h4>
        {(boundaryConditions || []).length === 0 && <p className="hint">None yet.</p>}
        <ul>
          {(boundaryConditions || []).map((bc) => (
            <li key={bc.id}>
              {bc.name} — {bc.node_ids.length} node(s)
              {analysisType === "thermal" ? `, T=${bc.values?.[0]}` : `, dofs ${bc.dofs.join(",")}`}
              <button className="link" onClick={() => onDeleteBC(bc.id)}>✕</button>
            </li>
          ))}
        </ul>
      </div>

      {analysisType !== "modal" && (
        <div className="list-block">
          <h4>Loads</h4>
          {(loads || []).length === 0 && <p className="hint">None yet.</p>}
          <ul>
            {(loads || []).map((ld) => (
              <li key={ld.id}>
                {ld.name} —{" "}
                {ld.load_type === "force" && `${ld.node_ids.length} node(s), F=(${ld.vector.map((v) => v.toFixed(1)).join(", ")}) N`}
                {ld.load_type === "pressure" && `${(ld.faces || []).length} face(s), P=${ld.magnitude} Pa`}
                {ld.load_type === "heat_flux" && `${ld.node_ids.length} node(s), Q=${ld.magnitude} W`}
                <button className="link" onClick={() => onDeleteLoad(ld.id)}>✕</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
