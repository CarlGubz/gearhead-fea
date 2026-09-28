import React, { useState, useEffect } from "react";

const PRESETS = {
  Steel: { E: 210e9, nu: 0.3, density: 7850, conductivity: 50, specific_heat: 490 },
  Aluminum: { E: 69e9, nu: 0.33, density: 2700, conductivity: 205, specific_heat: 900 },
  Titanium: { E: 114e9, nu: 0.34, density: 4500, conductivity: 21.9, specific_heat: 520 },
  Copper: { E: 110e9, nu: 0.34, density: 8960, conductivity: 401, specific_heat: 385 },
  Cast_Iron: { E: 110e9, nu: 0.28, density: 7200, conductivity: 55, specific_heat: 460 },
  ABS_Plastic: { E: 2.3e9, nu: 0.35, density: 1040, conductivity: 0.25, specific_heat: 1300 },
  Concrete: { E: 30e9, nu: 0.2, density: 2400, conductivity: 1.7, specific_heat: 880 },
  Glass: { E: 70e9, nu: 0.22, density: 2500, conductivity: 1.05, specific_heat: 840 },
};

export default function MaterialPanel({ material, onChange, analysisType }) {
  const [local, setLocal] = useState(material || PRESETS.Steel);

  useEffect(() => {
    if (material) setLocal(material);
  }, [material]);

  const applyPreset = (name) => {
    const m = { name, ...PRESETS[name] };
    setLocal(m);
    onChange(m);
  };

  const showThermal = analysisType === "thermal";

  return (
    <>
      <label>Preset</label>
      <select value={local.name || "Steel"} onChange={(e) => applyPreset(e.target.value)}>
        {Object.keys(PRESETS).map((k) => (
          <option key={k} value={k}>
            {k.replace(/_/g, " ")}
          </option>
        ))}
      </select>

      {!showThermal && (
        <>
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
        </>
      )}

      {showThermal && (
        <>
          <div className="field-row">
            <label>Thermal conductivity (W/m*K)</label>
            <input
              type="number"
              value={local.conductivity}
              onChange={(e) => setLocal({ ...local, conductivity: parseFloat(e.target.value) })}
              onBlur={() => onChange(local)}
            />
          </div>
          <div className="field-row">
            <label>Specific heat (J/kg*K)</label>
            <input
              type="number"
              value={local.specific_heat}
              onChange={(e) => setLocal({ ...local, specific_heat: parseFloat(e.target.value) })}
              onBlur={() => onChange(local)}
            />
          </div>
          <p className="hint">Only used by steady-state thermal analysis (density/E/nu are ignored).</p>
        </>
      )}
    </>
  );
}
