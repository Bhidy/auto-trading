/** Native canvas (expo-gl). Metro picks SolarCanvas.web.tsx on web. */
import React from 'react';
import { Canvas } from '@react-three/fiber/native';
import { SolarSceneContent, type Mood } from './SolarSceneContent';

export function SolarCanvas({ mood }: { mood: React.MutableRefObject<Mood> }) {
  return (
    <Canvas style={{ flex: 1 }} camera={{ position: [0, 0, 3.6], fov: 46 }} gl={{ antialias: true, alpha: true }}>
      <SolarSceneContent mood={mood} />
    </Canvas>
  );
}
