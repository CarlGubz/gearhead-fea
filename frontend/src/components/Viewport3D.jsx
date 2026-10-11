import React, { useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Grid, GizmoHelper, GizmoViewport } from "@react-three/drei";
import * as THREE from "three";
import { boundingBox, minMax } from "./utils.js";

// FEA models are Z-up (gravity is -Z), so the whole scene is Z-up as well.
THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

// Blue -> cyan -> green -> yellow -> red contour map (same convention as PrePoMax/CalculiX viewers).
const STOPS = [
  [0.0, 0, 0, 0.8],
  [0.25, 0, 0.6, 1],
  [0.5, 0, 0.8, 0.27],
  [0.75, 1, 0.93, 0],
  [1.0, 0.93, 0, 0],
];
// Distinct, calm tints for parts (shown when no result contour is displayed).
export const PART_COLORS = [
  [0.56, 0.64, 0.80], [0.80, 0.62, 0.45], [0.50, 0.72, 0.58], [0.76, 0.55, 0.72],
  [0.82, 0.76, 0.46], [0.46, 0.70, 0.78], [0.78, 0.50, 0.50], [0.62, 0.62, 0.66],
];

export function colormap(t) {
  t = Math.min(1, Math.max(0, t));
  for (let i = 0; i < STOPS.length - 1; i++) {
    const [t0, r0, g0, b0] = STOPS[i];
    const [t1, r1, g1, b1] = STOPS[i + 1];
    if (t >= t0 && t <= t1) {
      const f = (t - t0) / (t1 - t0 || 1);
      return [r0 + (r1 - r0) * f, g0 + (g1 - g0) * f, b0 + (b1 - b0) * f];
    }
  }
  return [0.93, 0, 0];
}

/* ---------------------------------------------------------------- the mesh */
function SurfaceMesh({
  nodes, faces, displacements, field, range, deformScale, animate, oscillate,
  showEdges, showUndeformed, planes, selectedNodes, selectedFaces, onClickFace, scaleRef, faceParts,
}) {
  const base = useMemo(() => {
    const nv = faces.length * 3;
    const idx = new Int32Array(nv);
    const pos0 = new Float32Array(nv * 3);
    faces.forEach((tri, fi) =>
      tri.forEach((n, vi) => {
        const k = fi * 3 + vi;
        idx[k] = n;
        pos0.set(nodes[n], k * 3);
      })
    );
    return { idx, pos0, nv };
  }, [nodes, faces]);

  const dispVerts = useMemo(() => {
    if (!displacements || !displacements.length) return null;
    const a = new Float32Array(base.nv * 3);
    for (let k = 0; k < base.nv; k++) {
      const d = displacements[base.idx[k]];
      if (d) a.set(d, k * 3);
    }
    return a;
  }, [displacements, base]);

  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const pos = new THREE.BufferAttribute(base.pos0.slice(), 3);
    pos.setUsage(THREE.DynamicDrawUsage);
    g.setAttribute("position", pos);
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(base.nv * 3), 3));
    return g;
  }, [base]);

  const ghost = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(base.pos0, 3));
    return g;
  }, [base]);

  // vertex colours: contour, or plain shading; selection overrides
  useEffect(() => {
    const col = geometry.getAttribute("color");
    const sel = new Set(selectedNodes || []);
    (selectedFaces || []).forEach((t) => t.forEach((n) => sel.add(n)));
    let lo = 0;
    let hi = 1;
    if (field && field.length) {
      [lo, hi] = range || minMax(field);
      if (hi - lo < 1e-30) hi = lo + 1e-30;
    }
    for (let k = 0; k < base.nv; k++) {
      const n = base.idx[k];
      let c;
      if (sel.has(n)) c = [1, 0.1, 0.9];
      else if (field && field.length) c = colormap((field[n] - lo) / (hi - lo));
      else c = PART_COLORS[(faceParts ? faceParts[Math.floor(k / 3)] : 0) % PART_COLORS.length];
      col.setXYZ(k, c[0], c[1], c[2]);
    }
    col.needsUpdate = true;
  }, [geometry, base, field, range, selectedNodes, selectedFaces, faceParts]);

  const lastScale = useRef(null);
  useFrame(({ clock }) => {
    let s = deformScale;
    if (animate) {
      const w = clock.getElapsedTime() * Math.PI * 1.2;
      s = deformScale * (oscillate ? Math.sin(w) : 0.5 - 0.5 * Math.cos(w));
    }
    scaleRef.current = dispVerts ? s : 0;
    const p = geometry.getAttribute("position");
    if (!dispVerts) {
      if (lastScale.current !== 0) {
        p.array.set(base.pos0);
        p.needsUpdate = true;
        lastScale.current = 0;
      }
      return;
    }
    if (lastScale.current === s && !animate) return;
    const arr = p.array;
    for (let i = 0; i < arr.length; i++) arr[i] = base.pos0[i] + dispVerts[i] * s;
    p.needsUpdate = true;
    geometry.computeBoundingSphere();
    lastScale.current = s;
  });

  // geometry/data changed -> force a refresh on the next frame
  useEffect(() => {
    lastScale.current = null;
  }, [dispVerts, base]);

  return (
    <>
      <mesh geometry={geometry} onClick={onClickFace}>
        <meshStandardMaterial vertexColors side={THREE.DoubleSide} flatShading clippingPlanes={planes}
          polygonOffset polygonOffsetFactor={1} polygonOffsetUnits={1} />
      </mesh>
      {showEdges && (
        <mesh geometry={geometry}>
          <meshBasicMaterial color="#10141c" wireframe transparent opacity={0.35} clippingPlanes={planes} />
        </mesh>
      )}
      {showUndeformed && dispVerts && (
        <mesh geometry={ghost}>
          <meshBasicMaterial color="#6b7280" wireframe transparent opacity={0.5} clippingPlanes={planes} />
        </mesh>
      )}
    </>
  );
}

/** Points that follow the (animated) deformation: supports, loads, probe, min/max. */
function PointLayer({ nodes, ids, displacements, color, size = 7, scaleRef }) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(ids.length * 3), 3));
    return g;
  }, [ids]);
  useFrame(() => {
    const attr = geometry.getAttribute("position");
    const arr = attr.array;
    const s = scaleRef.current || 0;
    ids.forEach((id, k) => {
      const p = nodes[id];
      const d = displacements && displacements[id] ? displacements[id] : [0, 0, 0];
      arr[k * 3] = p[0] + d[0] * s;
      arr[k * 3 + 1] = p[1] + d[1] * s;
      arr[k * 3 + 2] = p[2] + d[2] * s;
    });
    attr.needsUpdate = true;
    geometry.computeBoundingSphere();
  });
  if (!ids.length) return null;
  return (
    <points geometry={geometry} renderOrder={10} frustumCulled={false}>
      <pointsMaterial color={color} size={size} sizeAttenuation={false} depthTest={false} />
    </points>
  );
}

function ReferencePoints({ refs, size }) {
  return refs.map((r) => (
    <mesh key={r.id} position={r.coords} renderOrder={11}>
      <sphereGeometry args={[size, 16, 12]} />
      <meshBasicMaterial color="#f59e0b" depthTest={false} />
    </mesh>
  ));
}

/* ----------------------------------------------------- camera & utilities */
function Rig({ bbox, viewCommand, onApi }) {
  const { camera, gl, scene, controls } = useThree();
  const center = useMemo(() => bbox.lo.map((v, i) => v + bbox.size[i] / 2), [bbox]);
  const diag = Math.max(Math.hypot(...bbox.size), 0.1);

  useEffect(() => {
    camera.near = diag / 500;
    camera.far = diag * 100;
    camera.updateProjectionMatrix();
  }, [camera, diag]);

  useEffect(() => {
    const d = diag * 1.1;
    const [cx, cy, cz] = center;
    const views = {
      iso: [cx + d * 0.7, cy - d * 0.9, cz + d * 0.65],
      front: [cx, cy - d * 1.4, cz],
      back: [cx, cy + d * 1.4, cz],
      right: [cx + d * 1.4, cy, cz],
      left: [cx - d * 1.4, cy, cz],
      top: [cx + d * 0.0001, cy - d * 0.0001, cz + d * 1.4],
      bottom: [cx + d * 0.0001, cy + d * 0.0001, cz - d * 1.4],
    };
    const p = views[viewCommand?.name || "iso"] || views.iso;
    camera.position.set(p[0], p[1], p[2]);
    camera.up.set(0, 0, 1);
    camera.lookAt(cx, cy, cz);
    if (controls) {
      controls.target.set(cx, cy, cz);
      controls.update();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewCommand, center, diag, controls]);

  useEffect(() => {
    if (!onApi) return;
    onApi({
      capture: () => {
        gl.render(scene, camera);
        return gl.domElement.toDataURL("image/png");
      },
    });
  }, [gl, scene, camera, onApi]);
  return null;
}

const GRID_COLORS = {
  light: { cell: "#aab4c4", section: "#7f8a9c", bg: "linear-gradient(#f7f9fc, #b9c3d3)" },
  dark: { cell: "#3a4150", section: "#566075", bg: "linear-gradient(#2a303a, #12151a)" },
};

const niceStep = (x) => {
  const p = 10 ** Math.floor(Math.log10(Math.max(x, 1e-12)));
  const m = x / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
};

export default function Viewport3D({
  nodes, faces, displacements, field, range = null, deformScale = 0, animate = false, oscillate = false,
  showEdges = false, showUndeformed = false, clip = null, showMinMax = false,
  selectedNodes = [], selectedFaces = [], onPickFace, probeMode = false, onProbe, probeNode = null,
  markers = [], refPoints = [], theme = "dark", pickMode = "none", setPickMode, allowFacePick = false,
  viewCommand, setView, onApi, toolbarExtra, faceParts = null, pickNearest = false,
}) {
  const colors = GRID_COLORS[theme] || GRID_COLORS.dark;
  const bbox = useMemo(() => boundingBox(nodes), [nodes]);
  const scaleRef = useRef(0);
  const diag = Math.max(Math.hypot(...bbox.size), 0.1);

  const planes = useMemo(() => {
    if (!clip?.enabled) return [];
    const k = clip.axis ?? 0;
    const pos = bbox.lo[k] + (clip.pos ?? 0.5) * bbox.size[k];
    const n = [0, 0, 0];
    n[k] = clip.flip ? 1 : -1;
    return [new THREE.Plane(new THREE.Vector3(...n), clip.flip ? -pos : pos)];
  }, [clip, bbox]);

  const minMaxIds = useMemo(() => {
    if (!showMinMax || !field || !field.length) return { lo: [], hi: [] };
    let lo = -1;
    let hi = -1;
    let vlo = Infinity;
    let vhi = -Infinity;
    const seen = new Set();
    faces.forEach((t) => t.forEach((n) => {
      if (seen.has(n)) return;
      seen.add(n);
      if (field[n] < vlo) { vlo = field[n]; lo = n; }
      if (field[n] > vhi) { vhi = field[n]; hi = n; }
    }));
    return { lo: lo >= 0 ? [lo] : [], hi: hi >= 0 ? [hi] : [] };
  }, [showMinMax, field, faces]);

  const handleClick = (e) => {
    e.stopPropagation();
    const fi = e.faceIndex;
    if (fi === undefined || fi === null) return;
    const tri = faces[fi];
    const nearest = () => {
      const pos = e.object.geometry.getAttribute("position");
      let best = tri[0];
      let bd = Infinity;
      tri.forEach((n, vi) => {
        const k = fi * 3 + vi;
        const dx = pos.getX(k) - e.point.x;
        const dy = pos.getY(k) - e.point.y;
        const dz = pos.getZ(k) - e.point.z;
        const dd = dx * dx + dy * dy + dz * dz;
        if (dd < bd) { bd = dd; best = n; }
      });
      return best;
    };
    if (probeMode && onProbe) {
      onProbe(nearest());
      return;
    }
    // beams / bars have no faces: picking selects the end node nearest to the click
    if (pickNearest && pickMode === "select" && onPickFace) {
      onPickFace([nearest()], e.shiftKey, fi);
      return;
    }
    if (onPickFace && pickMode !== "none") onPickFace(tri, e.shiftKey, fi);
  };

  return (
    <>
      {setPickMode && (
        <div className="viewport-toolbar">
          <button className={`toolbar-btn ${pickMode === "none" && !probeMode ? "active" : ""}`}
            title="Orbit / pan / zoom (no selection)" onClick={() => setPickMode("none")}>⟲</button>
          <button className={`toolbar-btn ${pickMode === "select" ? "active" : ""}`}
            title="Select nodes: click a face to select its nodes (shift = add)" onClick={() => setPickMode("select")}>◆</button>
          <button className={`toolbar-btn ${pickMode === "select-faces" ? "active" : ""}`}
            title="Select faces (shift = add)" disabled={!allowFacePick} onClick={() => setPickMode("select-faces")}>▤</button>
          <button className={`toolbar-btn ${pickMode === "select-angle" ? "active" : ""}`}
            title="Select connected faces by angle (set the angle in the Selection panel)" disabled={!allowFacePick}
            onClick={() => setPickMode("select-angle")}>◪</button>
          <span className="vt-sep" />
          {[["iso", "ISO"], ["front", "Front"], ["right", "Right"], ["top", "Top"]].map(([n, l]) => (
            <button key={n} className="toolbar-btn" style={{ fontSize: 11 }} title={`${l} view`}
              onClick={() => setView?.(n)}>{l}</button>
          ))}
          <button className="toolbar-btn" style={{ fontSize: 11 }} title="Fit all" onClick={() => setView?.("iso")}>Fit</button>
          <span className="vt-sep" />
          {toolbarExtra}
        </div>
      )}
      <Canvas camera={{ fov: 45, up: [0, 0, 1] }} style={{ background: colors.bg }}
        gl={{ preserveDrawingBuffer: true, localClippingEnabled: true }}>
        <ambientLight intensity={0.75} />
        <directionalLight position={[5, -8, 9]} intensity={0.8} />
        <directionalLight position={[-5, 6, -4]} intensity={0.3} />
        <Rig bbox={bbox} viewCommand={viewCommand} onApi={onApi} />
        <SurfaceMesh
          nodes={nodes} faces={faces} displacements={displacements} field={field} range={range}
          deformScale={deformScale} animate={animate} oscillate={oscillate} showEdges={showEdges}
          showUndeformed={showUndeformed} planes={planes} selectedNodes={selectedNodes}
          selectedFaces={selectedFaces} onClickFace={handleClick} scaleRef={scaleRef} faceParts={faceParts}
        />
        {markers.map((m, i) => (
          <PointLayer key={i} nodes={nodes} ids={m.ids} displacements={displacements} color={m.color}
            size={m.size || 7} scaleRef={scaleRef} />
        ))}
        <PointLayer nodes={nodes} ids={minMaxIds.lo} displacements={displacements} color="#2563eb" size={13} scaleRef={scaleRef} />
        <PointLayer nodes={nodes} ids={minMaxIds.hi} displacements={displacements} color="#dc2626" size={13} scaleRef={scaleRef} />
        <PointLayer nodes={nodes} ids={probeNode !== null && probeNode !== undefined ? [probeNode] : []}
          displacements={displacements} color="#facc15" size={14} scaleRef={scaleRef} />
        <ReferencePoints refs={refPoints} size={diag * 0.012} />
        <Grid args={[20, 20]} rotation={[Math.PI / 2, 0, 0]}
          position={[bbox.lo[0] + bbox.size[0] / 2, bbox.lo[1] + bbox.size[1] / 2, bbox.lo[2] - diag * 0.002]}
          cellSize={niceStep(diag / 20)} sectionSize={niceStep(diag / 20) * 5}
          cellColor={colors.cell} sectionColor={colors.section} infiniteGrid fadeDistance={diag * 8} />
        <GizmoHelper alignment="top-right" margin={[64, 100]}>
          <GizmoViewport axisColors={["#e05a5a", "#5ac25a", "#4d8fe0"]} labelColor="white" />
        </GizmoHelper>
        <OrbitControls makeDefault />
      </Canvas>
    </>
  );
}
