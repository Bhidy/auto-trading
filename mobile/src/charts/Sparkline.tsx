import React, { useId } from 'react';
import Svg, { Defs, LinearGradient, Path, Stop } from 'react-native-svg';
import { useTheme } from '@/theme/ThemeProvider';
import { extent, smoothPath, type Pt } from './util';

interface Props {
  data: number[];
  width: number;
  height: number;
  color?: string;
  fill?: boolean;
  strokeWidth?: number;
}

/** Compact trend line for cards and rows. */
export function Sparkline({ data, width, height, color, fill = true, strokeWidth = 2 }: Props) {
  const { palette } = useTheme();
  const raw = useId();
  const gid = raw.replace(/:/g, '');
  const stroke = color ?? palette.teal;

  if (!data || data.length < 2) return <Svg width={width} height={height} />;

  const [mn, mx] = extent(data);
  const range = mx - mn || 1;
  const pad = strokeWidth + 1;
  const stepX = width / (data.length - 1);
  const pts: Pt[] = data.map((v, i) => [i * stepX, pad + (height - 2 * pad) * (1 - (v - mn) / range)]);
  const line = smoothPath(pts);
  const area = `${line} L${width.toFixed(2)},${height} L0,${height} Z`;

  return (
    <Svg width={width} height={height}>
      <Defs>
        <LinearGradient id={`sp${gid}`} x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={stroke} stopOpacity={0.26} />
          <Stop offset="1" stopColor={stroke} stopOpacity={0.0} />
        </LinearGradient>
      </Defs>
      {fill && <Path d={area} fill={`url(#sp${gid})`} />}
      {/* Glow underlay */}
      <Path
        d={line}
        stroke={stroke}
        strokeOpacity={0.35}
        strokeWidth={strokeWidth + 4}
        fill="none"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <Path d={line} stroke={stroke} strokeWidth={strokeWidth} fill="none" strokeLinejoin="round" strokeLinecap="round" />
    </Svg>
  );
}
