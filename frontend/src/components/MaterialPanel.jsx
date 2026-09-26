import React, { useState, useEffect } from "react";

const PRESETS = {
  Steel: { E: 210e9, nu: 0.3, density: 7850 },
  Aluminum: { E: 69e9, nu: 0.33, density: 2700 },
  Titanium: { E: 114e9, nu: 0.34, density: 4500 },
  ABS_Plastic: { E: 2.3e9, nu: 0.35, density: 1040 },
};

export default function MaterialPanel({ material, onChange }) {
  const [local, setLocal] = useState(material || PRESETS.Steel);

  useEffect(() => {
    if (material) setLocal(material);
  }, [material]);

  const applyPreset = (name) => {
    const m = { name, ...PRESETS[name] };
    setLocal(m);
    onChange(m);
  };

  return (
    <div className="panel">
      <h3>Material</h3>
      <label>Preset</label>
      <select value={local.name || "Steel"} onChange={(e) => applyPreset(e.target.value)}>
        {Object.keys(PRESETS).map((k) => (
          <option key={k} value={k}>
            {k.replace("_", " ")}
          </option>
        ))}
      </select>

      <div className="field-row">
        <label>Young's modulus E (Pa)</label>
        <input
          type="number"
          value={local.E}
          onChange={(e) => setLocal({ ...local, E: parseFloat(e.target.value) })}
          onBlur={() => onChange(local)}
        />
      </div>
      <div className="field-row">
        <label>Poisson's ratio</label>
        <input
          type="number"
          step="0.01"
          value={local.nu}
          onChange={(e) => setLocal({ ...local, nu: parseFloat(e.target.value) })}
          onBlur={() => onChange(local)}
        />
      </div>
      <div className="field-row">
        <label>Density (kg/m3)</label>
        <input
          type="number"
          value={local.density}
          onChange={(e) => setLocal({ ...local, density: parseFloat(e.target.value) })}
          onBlur={() => onChange(local)}
        />
      </div>
    </div>
  );
}
