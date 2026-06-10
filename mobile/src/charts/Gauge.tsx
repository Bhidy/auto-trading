import React from 'react';
import { View } from 'react-native';
import Svg, { Circle, Line, Path } from 'react-native-svg';
import { useTheme } from '@/theme/ThemeProvider';

interface Props {
  /** 0..1 — needle position (e.g. invested fraction of the book). */
  fraction: number;
  size?: number;
  stroke?: number;
}

const SEGMENTS: Array<{ from: number; to: number; color: string }> = [
  { from: 180, to: 124, color: '#FFD9BD' },
  { from: 116, to: 64, color: '#FF8A3D' },
  { from: 56, to: 0, color: '#E55A1F' },
];

/** Semicircular dial — three warm arc segments + needle (reference dashboard style). */
export function Gauge({ fraction, size = 190, stroke = 14 }: Props) {
  const { palette } = useTheme();
  const f = Math.max(0, Math.min(1, isFinite(fraction) ? fraction : 0));

  const r = (size - stroke) / 2 - 2;
  const cx = size / 2;
  const cy = r + stroke / 2 + 2;
  const h = cy + 12;

  const pt = (deg: number): [number, number] => {
    const rad = (deg * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy - r * Math.sin(rad)];
  };
  const arc = (from: number, to: number) => {
    const [x1, y1] = pt(from);
    const [x2, y2] = pt(to);
    return `M${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 0 1 ${x2.toFixed(2)},${y2.toFixed(2)}`;
  };

  const needleDeg = 180 - f * 180;
  const nr = r - stroke / 2 - 7;
  const nx = cx + nr * Math.cos((needleDeg * Math.PI) / 180);
  const ny = cy - nr * Math.sin((needleDeg * Math.PI) / 180);

  return (
    <View style={{ width: size, height: h }}>
      <Svg width={size} height={h}>
        <Path d={arc(180, 0)} stroke={palette.surfaceInset} strokeWidth={stroke} fill="none" strokeLinecap="round" />
        {SEGMENTS.map((s, i) => (
          <Path key={i} d={arc(s.from, s.to)} stroke={s.color} strokeWidth={stroke} fill="none" strokeLinecap="round" />
        ))}
        <Line x1={cx} y1={cy} x2={nx} y2={ny} stroke={palette.ink} strokeWidth={2.4} strokeLinecap="round" />
        <Circle cx={cx} cy={cy} r={7} fill={palette.ink} />
        <Circle cx={cx} cy={cy} r={2.6} fill={palette.surface} />
      </Svg>
    </View>
  );
}
