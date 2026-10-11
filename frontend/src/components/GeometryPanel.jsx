import React, { useRef, useState } from "react";
import { Num, Select } from "./fields.jsx";
import { ELEMENTS, fmt } from "./utils.js";

const PRESETS = {
  box: { label: "Box", dims: { length: 1, width: 0.2, height: 0.2 }, hex: true },
  cylinder: { label: "Cylinder", dims: { radius: 0.5, height: 1 }, hex: false },
  sphere: { label: "Sphere", dims: { radius: 0.5 }, hex: false },
  tube: { label: "Tube (hollow cylinder)", dims: { outer_radius: 0.5, inner_radius: 0.3, height: 1 }, hex: false },
  plate_hole: { label: "Plate with hole", dims: { length: 1, width: 0.5, thickness: 0.1, hole_radius: 0.1 }, hex: false },
  lbracket: { label: "L-bracket", dims: { length: 1, height: 1, thickness: 0.25, depth: 0.25 }, hex: true },
};

export default function GeometryPanel({ elementType, quality, onGenerate, onAppend, onImport, onImportCad, hasMesh, materials, defaultMaterial }) {
  const [shape, setShape] = useState("box");
  const [dims, setDims] = useState(PRESETS.box.dims);
  const [divisions, setDivisions] = useState(4);
  const [etype, setEtype] = useState(elementType || "C3D4");
  const [offset, setOffset] = useState([0, 0, 0]);
  const [bodyMaterial, setBodyMaterial] = useState("default");
  const [bodyName, setBodyName] = useState("");
  const fileRef = useRef(null);
  const cadRef = useRef(null);
  const [cadSize, setCadSize] = useState(0);
  const [cadOrder, setCadOrder] = useState("2");
  const [cadUnit, setCadUnit] = useState("mm");
  const [cadBusy, setCadBusy] = useState(false);

  const preset = PRESETS[shape];
  const changeShape = (s) => {
    setShape(s);
    setDims(PRESETS[s].dims);
    if (!PRESETS[s].hex && ELEMENTS[etype].corners === 8) setEtype("C3D10");
  };

  return (
    <>
      <Select label="Primitive" value={shape} onChange={changeShape}
        options={Object.entries(PRESETS).map(([k, v]) => ({ value: k, label: v.label }))} />
      {Object.keys(dims).map((k) => (
        <Num key={k} label={k.replace(/_/g, " ")} unit="m" value={dims[k]} min={1e-6} onCommit={(v) => setDims({ ...dims, [k]: v })} />
      ))}

      <Select label="Element type" value={etype} onChange={setEtype}
        options={Object.entries(ELEMENTS).map(([k, v]) => ({
          value: k, label: v.label, disabled: v.corners === 8 && !preset.hex,
        }))} />
      <p className="hint">
        Quadratic elements (Tet10, Hex20) are far more accurate in bending than linear ones. Bricks are available for
        box and L-bracket.
      </p>

      <div className="field-row">
        <label>Mesh density: {divisions}</label>
        <input type="range" min="1" max="12" value={divisions} onChange={(e) => setDivisions(parseInt(e.target.value, 10))} />
      </div>

      <button className="primary" onClick={() => onGenerate(shape, dims, divisions, etype)}>Generate mesh</button>

      <h4>Assembly &amp; import</h4>
      <input type="text" value={bodyName} placeholder={`Part name (default “${preset.label}”)`} onChange={(e) => setBodyName(e.target.value)} />
      <Select label="Material of the new body" value={bodyMaterial} onChange={setBodyMaterial}
        options={[{ value: "default", label: `${defaultMaterial?.name || "Default"} (default)` },
          ...(materials || []).map((m) => ({ value: m.id, label: m.name }))]} />
      <button onClick={() => onAppend(shape, dims, divisions, offset, bodyName.trim() || undefined, bodyMaterial)} disabled={!hasMesh}
        title="Mesh this primitive as a new part, placed at the offset below. Join parts with a Tie between parts.">
        + Add as separate body
      </button>
      <div className="vec3">
        {["x", "y", "z"].map((a, i) => (
          <Num key={a} value={offset[i]} onCommit={(v) => setOffset(offset.map((x, k) => (k === i ? v : x)))} />
        ))}
      </div>
      <p className="hint">Offset (x, y, z) in metres for the added body.</p>

      <input ref={fileRef} type="file" accept=".inp,.msh" style={{ display: "none" }}
        onChange={(e) => { if (e.target.files[0]) onImport(e.target.files[0]); e.target.value = ""; }} />
      <button onClick={() => fileRef.current?.click()}>Import mesh (.inp / .msh)…</button>
      <p className="hint">CalculiX/Abaqus .inp or Gmsh 2.2 ASCII; tet4/tet10/hex8/hex20.</p>

      <h4>CAD import</h4>
      <input ref={cadRef} type="file" accept=".step,.stp,.iges,.igs,.stl" style={{ display: "none" }}
        onChange={async (e) => {
          const f = e.target.files[0];
          e.target.value = "";
          if (!f) return;
          setCadBusy(true);
          try { await onImportCad(f, { size: cadSize, order: +cadOrder, unit: cadUnit }); } finally { setCadBusy(false); }
        }} />
      <Select label="Length unit of the file" value={cadUnit} onChange={setCadUnit}
        options={[{ value: "mm", label: "Millimetres" }, { value: "cm", label: "Centimetres" }, { value: "m", label: "Metres" }, { value: "in", label: "Inches" }]} />
      <Num label="Element size (0 = automatic)" unit="m" value={cadSize} min={0} onCommit={setCadSize}
        hint="Target edge length of the tetrahedra, in metres. Smaller = more accurate and slower." />
      <Select label="Elements" value={cadOrder} onChange={setCadOrder}
        options={[{ value: "2", label: "Tet10 (quadratic, recommended)" }, { value: "1", label: "Tet4 (linear)" }]} />
      <button onClick={() => cadRef.current?.click()} disabled={cadBusy}>{cadBusy ? "Meshing the CAD file…" : "Import CAD (STEP / IGES / STL)…"}</button>
      <p className="hint">Each solid becomes a part. STL must be a closed (watertight) surface. The CAD kernel runs on the server with a time limit.</p>

      {quality && (
        <>
          <h4>Mesh statistics</h4>
          <table className="kv">
            <tbody>
              <tr><td>Element type</td><td>{quality.element_type}</td></tr>
              <tr><td>Nodes</td><td>{quality.n_nodes.toLocaleString()}</td></tr>
              <tr><td>Elements</td><td>{quality.n_elements.toLocaleString()}</td></tr>
              {quality.total_volume !== undefined && <tr><td>Volume</td><td>{fmt(quality.total_volume)} m³</td></tr>}
              {quality.total_length !== undefined && <tr><td>Total length</td><td>{fmt(quality.total_length)} m</td></tr>}
              {quality.total_area !== undefined && <tr><td>Total area</td><td>{fmt(quality.total_area)} m²</td></tr>}
              {quality.min_jacobian_ratio !== undefined && <tr><td>Min Jacobian ratio</td><td>{fmt(quality.min_jacobian_ratio)}</td></tr>}
              {quality.max_edge_ratio !== undefined && <tr><td>Max edge ratio</td><td>{fmt(quality.max_edge_ratio)}</td></tr>}
              {quality.inverted_elements !== undefined && <tr><td>Inverted</td><td>{quality.inverted_elements}</td></tr>}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
