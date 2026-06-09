/* eslint-disable react/no-unknown-property -- react-three-fiber JSX uses three.js props */
/**
 * The molten solar core — shared R3F scene used by both native (expo-gl) and web canvases.
 * A Perlin-displaced icosahedron with an inner ember light, halo sprite, and particle galaxy.
 * `mood.progress` (0..2, slide index) drives turbulence, tempo and tone. No post-processing —
 * glow is faked with an additive radial sprite (mobile-safe, no bloom pass).
 */
import React, { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { SimplexNoise } from '@/lib/noise';

export interface Mood {
  progress: number; // 0..2 across the three slides
}

const CORE_DETAIL = 14; // ~1.5k vertices — silky on phone GPUs
const PARTICLES = 850;

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Per-slide personalities: calm genesis → armored discipline → compounding energy. */
const MOODS = [
  { amp: 0.2, speed: 0.28, spin: 0.05, emissive: 1.25, scale: 1.0 },
  { amp: 0.09, speed: 0.16, spin: 0.12, emissive: 0.85, scale: 0.88 },
  { amp: 0.3, speed: 0.5, spin: 0.09, emissive: 1.6, scale: 1.08 },
];

function moodAt(p: number) {
  const c = Math.max(0, Math.min(2, p));
  const i = Math.min(1, Math.floor(c));
  const t = c - i;
  const a = MOODS[i];
  const b = MOODS[Math.min(2, i + 1)];
  return {
    amp: lerp(a.amp, b.amp, t),
    speed: lerp(a.speed, b.speed, t),
    spin: lerp(a.spin, b.spin, t),
    emissive: lerp(a.emissive, b.emissive, t),
    scale: lerp(a.scale, b.scale, t),
  };
}

/** Procedural radial-gradient texture (no DOM canvas — works on native GL). */
function makeHaloTexture(): THREE.DataTexture {
  const size = 128;
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = (x - size / 2) / (size / 2);
      const dy = (y - size / 2) / (size / 2);
      const d = Math.sqrt(dx * dx + dy * dy);
      const fall = Math.max(0, 1 - d);
      const a = Math.pow(fall, 2.6) * 255;
      const idx = (y * size + x) * 4;
      data[idx] = 255;
      data[idx + 1] = 138;
      data[idx + 2] = 61; // #FF8A3D
      data[idx + 3] = a;
    }
  }
  const tex = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
  tex.needsUpdate = true;
  return tex;
}

export function SolarSceneContent({ mood }: { mood: React.MutableRefObject<Mood> }) {
  const coreRef = useRef<THREE.Mesh>(null);
  const particlesRef = useRef<THREE.Points>(null);
  const haloRef = useRef<THREE.Sprite>(null);

  const noise = useMemo(() => new SimplexNoise(20260609), []);
  const haloTexture = useMemo(() => makeHaloTexture(), []);

  const { geometry, basePositions } = useMemo(() => {
    const geo = new THREE.IcosahedronGeometry(1.12, CORE_DETAIL);
    const base = Float32Array.from(geo.attributes.position.array as Float32Array);
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(base.length), 3));
    return { geometry: geo, basePositions: base };
  }, []);

  const particleGeo = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(PARTICLES * 3);
    const seeds = new Float32Array(PARTICLES);
    const rng = new SimplexNoise(7);
    for (let i = 0; i < PARTICLES; i++) {
      // Shell distribution 1.7..3.1 with slight equatorial bias (galaxy feel)
      const u = (rng.noise3(i * 0.91, 0.5, 0.13) + 1) / 2;
      const v = (rng.noise3(0.31, i * 0.77, 0.57) + 1) / 2;
      const r = 1.7 + 1.4 * ((rng.noise3(i * 0.13, i * 0.29, 0.7) + 1) / 2);
      const theta = u * Math.PI * 2;
      const phi = Math.acos(2 * v - 1) * 0.82 + Math.PI * 0.09;
      pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      pos[i * 3 + 1] = r * Math.cos(phi) * 0.72;
      pos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
      seeds[i] = u * 10;
    }
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    return geo;
  }, []);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    const m = moodAt(mood.current.progress);

    const core = coreRef.current;
    if (core) {
      const posAttr = core.geometry.attributes.position as THREE.BufferAttribute;
      const colAttr = core.geometry.attributes.color as THREE.BufferAttribute;
      const arr = posAttr.array as Float32Array;
      const col = colAttr.array as Float32Array;
      const time = t * m.speed;
      for (let i = 0; i < arr.length; i += 3) {
        const ox = basePositions[i];
        const oy = basePositions[i + 1];
        const oz = basePositions[i + 2];
        const n = noise.noise3(ox * 1.35 + time, oy * 1.35 + time * 0.85, oz * 1.35 - time * 0.6);
        const d = 1 + n * m.amp;
        arr[i] = ox * d;
        arr[i + 1] = oy * d;
        arr[i + 2] = oz * d;

        // Magma ramp: raised plates are dark crust; the valleys between them glow.
        const heat = Math.pow(Math.min(1, Math.max(0, (0.25 - n) / 1.25)), 1.35);
        if (heat < 0.5) {
          const k = heat / 0.5;
          col[i] = 0.16 + (0.62 - 0.16) * k;
          col[i + 1] = 0.05 + (0.16 - 0.05) * k;
          col[i + 2] = 0.025 + (0.05 - 0.025) * k;
        } else {
          const k = (heat - 0.5) / 0.5;
          col[i] = 0.62 + (1.0 - 0.62) * k;
          col[i + 1] = 0.16 + (0.6 - 0.16) * k;
          col[i + 2] = 0.05 + (0.22 - 0.05) * k;
        }
      }
      posAttr.needsUpdate = true;
      colAttr.needsUpdate = true;
      core.geometry.computeVertexNormals();
      core.rotation.y = t * m.spin;
      core.rotation.x = Math.sin(t * 0.12) * 0.16;
      const pulse = 1 + Math.sin(t * 1.7) * 0.012;
      core.scale.setScalar(m.scale * pulse);

      const mat = core.material as THREE.MeshStandardMaterial;
      mat.emissiveIntensity = 0.1 + 0.16 * m.emissive + Math.sin(t * 2.3) * 0.03;
    }

    if (haloRef.current) {
      const s = 3.1 * m.scale * (1 + Math.sin(t * 1.7) * 0.02);
      haloRef.current.scale.set(s, s, 1);
      (haloRef.current.material as THREE.SpriteMaterial).opacity = 0.34 + 0.16 * (m.emissive - 0.85);
    }

    if (particlesRef.current) {
      particlesRef.current.rotation.y = -t * (m.spin * 0.7 + 0.012);
      particlesRef.current.rotation.z = Math.sin(t * 0.07) * 0.05;
    }
  });

  return (
    <group position={[0, 0.78, 0]} scale={0.4}>
      <ambientLight intensity={0.16} color="#FFD9BD" />
      <directionalLight position={[3.5, 2.6, 4.5]} intensity={0.95} color="#FFC396" />
      <directionalLight position={[-4.5, -1.5, -2.5]} intensity={0.4} color="#C9461A" />

      {/* Halo glow (bloom substitute) */}
      <sprite ref={haloRef} position={[0, 0, -0.6]}>
        <spriteMaterial
          map={haloTexture}
          transparent
          opacity={0.36}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </sprite>

      {/* Molten core — vertex-color heat map */}
      <mesh ref={coreRef} geometry={geometry}>
        <meshStandardMaterial
          vertexColors
          color="#FFFFFF"
          emissive="#C9461A"
          emissiveIntensity={0.3}
          roughness={0.5}
          metalness={0.08}
          flatShading={false}
        />
      </mesh>

      {/* Particle embers (soft round sprites) */}
      <points ref={particlesRef} geometry={particleGeo}>
        <pointsMaterial
          color="#FFA86A"
          size={0.05}
          map={haloTexture}
          alphaMap={haloTexture}
          sizeAttenuation
          transparent
          opacity={0.6}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </points>
    </group>
  );
}
