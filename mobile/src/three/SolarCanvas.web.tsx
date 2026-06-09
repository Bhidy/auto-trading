/** Web canvas (DOM WebGL) — used by the dev preview and any web export. */
import React from 'react';
import { Canvas } from '@react-three/fiber';
import { SolarSceneContent, type Mood } from './SolarSceneContent';

export function SolarCanvas({ mood }: { mood: React.MutableRefObject<Mood> }) {
  return (
    <Canvas
      style={{ width: '100%', height: '100%' }}
      camera={{ position: [0, 0, 3.6], fov: 46 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
    >
      <SolarSceneContent mood={mood} />
    </Canvas>
  );
}
