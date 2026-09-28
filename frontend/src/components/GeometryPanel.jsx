import React, { useState } from "react";

const PRESETS = {
  box: { length: 1, width: 1, height: 1 },
  cylinder: { radius: 0.5, height: 1 },
  sphere: { radius: 0.5 },
};

export default function GeometryPanel({ onGenerate }) {
  const [shape, setShape] = useState("box");
  const [dims, setDims] = useState(PRESETS.box);
  const [divisions, setDivisions] = useState(4);

  const changeShape = (s) => {
    setShape(s);
    setDims(PRESETS[s]);
  };

  return (
    <>
      <label>Primitive</label>
      <select value={shape} onChange={(e) => changeShape(e.target.value)}>
        <option value="box">Box</option>
        <option value="cylinder">Cylinder</option>
        <option value="sphere">Sphere</option>
      </select>

      {Object.keys(dims).map((k) => (
        <div key={k} className="field-row">
          <label>{k}</label>
          <input
            type="number"
            step="0.05"
            value={dims[k]}
            onChange={(e) => setDims({ ...dims, [k]: parseFloat(e.target.value) })}
          />
        </div>
      ))}

      <div className="field-row">
        <label>Mesh density</label>
        <input
          type="range"
          min="2"
          max="9"
          value={divisions}
          onChange={(e) => setDivisions(parseInt(e.target.value, 10))}
        />
        <span>{divisions}</span>
      </div>

      <button className="primary" onClick={() => onGenerate(shape, dims, divisions)}>
        Generate Mesh
      </button>
      <p className="hint">
        Tip: higher mesh density = smoother stress results but slower solves.
      </p>
    </>
  );
}
