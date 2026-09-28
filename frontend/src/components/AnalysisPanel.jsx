import React, { useState, useEffect } from "react";

export default function AnalysisPanel({ analysisType, nModes, gravity, onChangeAnalysisType, onChangeGravity }) {
  const [modes, setModes] = useState(nModes || 6);
  const [g, setG] = useState(gravity || { enabled: false, x: 0, y: 0, z: -9.81 });

  useEffect(() => setModes(nModes || 6), [nModes]);
  useEffect(() => setG(gravity || { enabled: false, x: 0, y: 0, z: -9.81 }), [gravity]);

  return (
    <>
      <label>Analysis type</label>
      <select
        value={analysisType || "static"}
        onChange={(e) => onChangeAnalysisType(e.target.value, modes)}
      >
        <option value="static">Static structural</option>
        <option value="modal">Modal (natural frequency)</option>
        <option value="thermal">Steady-state thermal</option>
      </select>
      <p className="hint">
        Switching analysis type clears existing boundary conditions and
        loads, since their meaning changes (e.g. fixed support vs. fixed
        temperature).
      </p>

      {analysisType === "modal" && (
        <div className="field-row">
          <label>Number of modes</label>
          <input
            type="number"
            min="1"
            max="50"
            value={modes}
            onChange={(e) => setModes(parseInt(e.target.value, 10) || 1)}
            onBlur={() => onChangeAnalysisType("modal", modes)}
          />
        </div>
      )}

      {analysisType === "static" && (
        <fieldset>
          <legend>Gravity (self-weight)</legend>
          <label>
            <input
              type="checkbox"
              checked={g.enabled}
              onChange={(e) => {
                const next = { ...g, enabled: e.target.checked };
                setG(next);
                onChangeGravity(next);
              }}
            />{" "}
            Enabled
          </label>
          <div className="field-row">
            <label>Gx (m/s2)</label>
            <input
              type="number"
              step="0.1"
              value={g.x}
              onChange={(e) => setG({ ...g, x: parseFloat(e.target.value) })}
              onBlur={() => onChangeGravity(g)}
            />
          </div>
          <div className="field-row">
            <label>Gy (m/s2)</label>
            <input
              type="number"
              step="0.1"
              value={g.y}
              onChange={(e) => setG({ ...g, y: parseFloat(e.target.value) })}
              onBlur={() => onChangeGravity(g)}
            />
          </div>
          <div className="field-row">
            <label>Gz (m/s2)</label>
            <input
              type="number"
              step="0.1"
              value={g.z}
              onChange={(e) => setG({ ...g, z: parseFloat(e.target.value) })}
              onBlur={() => onChangeGravity(g)}
            />
          </div>
        </fieldset>
      )}
    </>
  );
}
