import React from 'react';
import { View } from 'react-native';
import Svg, { Circle, G, Path } from 'react-native-svg';
import { Text } from '@/components/Text';
import { useTheme } from '@/theme/ThemeProvider';

export interface DonutSlice {
  label: string;
  value: number;
  color: string;
}

function arcPath(cx: number, cy: number, r: number, a0: number, a1: number): string {
  const x0 = cx + r * Math.cos(a0);
  const y0 = cy + r * Math.sin(a0);
  const x1 = cx + r * Math.cos(a1);
  const y1 = cy + r * Math.sin(a1);
  const large = a1 - a0 > Math.PI ? 1 : 0;
  return `M${x0.toFixed(3)},${y0.toFixed(3)} A${r},${r} 0 ${large} 1 ${x1.toFixed(3)},${y1.toFixed(3)}`;
}

/** Allocation donut — stroked arcs with a center summary. */
export function Donut({
  slices,
  size = 168,
  thickness = 22,
  centerTitle,
  centerValue,
}: {
  slices: DonutSlice[];
  size?: number;
  thickness?: number;
  centerTitle?: string;
  centerValue?: string;
}) {
  const { palette } = useTheme();
  const total = slices.reduce((s, x) => s + Math.max(0, x.value), 0);
  const r = (size - thickness) / 2;
  const c = size / 2;
  const GAP = 0.035; // radians between segments

  let angle = -Math.PI / 2;
  const arcs = total
    ? slices
        .filter((s) => s.value > 0)
        .map((s, i) => {
          const sweep = (s.value / total) * Math.PI * 2;
          const a0 = angle + GAP / 2;
          const a1 = angle + sweep - GAP / 2;
          angle += sweep;
          return a1 > a0 ? <Path key={i} d={arcPath(c, c, r, a0, a1)} stroke={s.color} strokeWidth={thickness} strokeLinecap="round" fill="none" /> : null;
        })
    : null;

  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      <Svg width={size} height={size}>
        <Circle cx={c} cy={c} r={r} stroke={palette.surfaceInset} strokeWidth={thickness} fill="none" />
        <G>{arcs}</G>
      </Svg>
      <View style={{ position: 'absolute', alignItems: 'center', gap: 2 }}>
        {centerTitle ? (
          <Text variant="overline" dim>
            {centerTitle}
          </Text>
        ) : null}
        {centerValue ? <Text variant="monoL">{centerValue}</Text> : null}
      </View>
    </View>
  );
}
