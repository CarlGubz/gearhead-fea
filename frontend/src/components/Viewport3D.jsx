import React, { useMemo, useRef } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Grid } from "@react-three/drei";
import * as THREE from "three";

// Blue -> Cyan -> Green -> Yellow -> Red "jet-like" colormap, same convention
// PrePoMax/CalculiX viewers use for stress/displacement contour plots.
function colormap(t) {
  t = Math.min(1, Math.max(0, t));
  const stops = [
    [0.0, 0, 0, 0.6],
    [0.25, 0, 0.6, 1],
    [0.5, 0, 1, 0.2],
    [0.75, 1, 1, 0],
    [1.0, 1, 0, 0],
  ];
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, r0, g0, b0] = stops[i];
    const [t1, r1, g1, b1] = stops[i + 1];
    if (t >= t0 && t <= t1) {
      const f = (t - t0) / (t1 - t0 || 1);
      return [r0 + (r1 - r0) * f, g0 + (g1 - g0) * f, b0 + (b1 - b0) * f];
    }
  }
  return [1, 0, 0];
}

function Mesh({ nodes, faces, displacements, field, deformScale, selectedNodes, onPickFace }) {
  const geometry = useMemo(() => {
    if (!nodes?.length || !faces?.length) return null;

    const positions = new Float32Array(faces.length * 3 * 3);
    const colors = new Float32Array(faces.length * 3 * 3);

    let minV = 0;
    let maxV = 1;
    if (field && field.length) {
      minV = Math.min(...field);
      maxV = Math.max(...field);
      if (maxV - minV < 1e-12) maxV = minV + 1;
    }

    const nodeSelected = new Set(selectedNodes || []);

    faces.forEach((tri, fi) => {
      tri.forEach((nodeIdx, vi) => {
        const base = nodes[nodeIdx];
        let x = base[0];
        let y = base[1];
        let z = base[2];
        if (displacements && displacements.length) {
          const d = displacements[nodeIdx];
          x += d[0] * deformScale;
          y += d[1] * deformScale;
          z += d[2] * deformScale;
        }
        const pOff = (fi * 3 + vi) * 3;
        positions[pOff] = x;
        positions[pOff + 1] = y;
        positions[pOff + 2] = z;

        let r, g, b;
        if (nodeSelected.has(nodeIdx)) {
          r = 1;
          g = 0.1;
          b = 0.9;
        } else if (field && field.length) {
          const t = (field[nodeIdx] - minV) / (maxV - minV);
          [r, g, b] = colormap(t);
        } else {
          r = 0.55;
          g = 0.65;
          b = 0.85;
        }
        colors[pOff] = r;
        colors[pOff + 1] = g;
        colors[pOff + 2] = b;
      });
    });

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    return geo;
  }, [nodes, faces, displacements, field, deformScale, selectedNodes]);

  const meshRef = useRef();

  if (!geometry) return null;

  const handleClick = (e) => {
    e.stopPropagation();
    if (!onPickFace) return;
    const faceIndex = e.faceIndex;
    if (faceIndex === undefined || faceIndex === null) return;
    const tri = faces[faceIndex];
    onPickFace(tri, e.shiftKey);
  };

  return (
    <mesh ref={meshRef} geometry={geometry} onClick={handleClick}>
      <meshStandardMaterial vertexColors side={THREE.DoubleSide} flatShading />
    </mesh>
  );
}

function FitCamera({ nodes }) {
  const { camera } = useThree();
  useMemo(() => {
    if (!nodes || !nodes.length) return;
    const box = new THREE.Box3();
    nodes.forEach(([x, y, z]) => box.expandByPoint(new THREE.Vector3(x, y, z)));
    const size = new THREE.Vector3();
    box.getSize(size);
    const center = new THREE.Vector3();
    box.getCenter(center);
    const maxDim = Math.max(size.x, size.y, size.z, 0.1);
    camera.position.set(center.x + maxDim * 1.5, center.y + maxDim * 1.2, center.z + maxDim * 1.8);
    camera.lookAt(center);
    camera.near = maxDim / 100;
    camera.far = maxDim * 50;
    camera.updateProjectionMatrix();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes]);
  return null;
}

export default function Viewport3D({
  nodes,
  faces,
  displacements,
  field,
  deformScale = 0,
  selectedNodes = [],
  onPickFace,
}) {
  return (
    <Canvas camera={{ fov: 45 }} style={{ background: "#0e1117" }}>
      <ambientLight intensity={0.7} />
      <directionalLight position={[5, 8, 5]} intensity={0.8} />
      <directionalLight position={[-5, -3, -5]} intensity={0.3} />
      <FitCamera nodes={nodes} />
      <Mesh
        nodes={nodes}
        faces={faces}
        displacements={displacements}
        field={field}
        deformScale={deformScale}
        selectedNodes={selectedNodes}
        onPickFace={onPickFace}
      />
      <Grid args={[20, 20]} position={[0, 0, 0]} cellColor="#333" sectionColor="#555" infiniteGrid fadeDistance={30} />
      <OrbitControls makeDefault />
    </Canvas>
  );
}
