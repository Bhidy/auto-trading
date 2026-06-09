import React, { useId, useMemo, useState } from 'react';
import { type GestureResponderEvent, View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Line, Path, Stop } from 'react-native-svg';
import { useTheme } from '@/theme/ThemeProvider';
import { clampIndex, extent, smoothPath, type Pt } from './util';

export interface EquityPoint {
  date: string;
  equity: number;
  profit_loss?: number;
  profit_loss_pct?: number;
}

interface Props {
  data: EquityPoint[];
  width: number;
  height: number;
  baseValue?: number;
  onScrub?: (p: EquityPoint | null, index: number) => void;
}

/** Interactive equity curve — gradient area, dashed cost basis, scrub crosshair. */
export function EquityChart({ data, width, height, baseValue, onScrub }: Props) {
  const { palette } = useTheme();
  const gid = useId().replace(/:/g, '');
  const [active, setActive] = useState<number | null>(null);

  const padTop = 12;
  const padBottom = 10;
  const padX = 3;
  const innerW = width - padX * 2;
  const innerH = height - padTop - padBottom;

  const model = useMemo(() => {
    const vals = data.map((d) => d.equity).filter((v) => isFinite(v));
    if (vals.length < 2) return null;
    const domain = baseValue != null ? [...vals, baseValue] : vals;
    const [mn, mx] = extent(domain);
    const range = mx - mn || 1;
    const stepX = innerW / (vals.length - 1);
    const pts: Pt[] = vals.map((v, i) => [padX + i * stepX, padTop + innerH * (1 - (v - mn) / range)]);
    const line = smoothPath(pts);
    const area = `${line} L${(padX + innerW).toFixed(2)},${padTop + innerH} L${padX},${padTop + innerH} Z`;
    const net = vals[vals.length - 1] - (baseValue ?? vals[0]);
    const color = net >= 0 ? palette.up : palette.down;
    const baseY = baseValue != null ? padTop + innerH * (1 - (baseValue - mn) / range) : null;
    return { pts, line, area, color, baseY };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, width, height, baseValue, palette.up, palette.down]);

  if (!model) return <View style={{ width, height }} />;
  const { pts, line, area, color, baseY } = model;

  const handleTouch = (e: GestureResponderEvent) => {
    const x = e.nativeEvent.locationX - padX;
    const idx = clampIndex(Math.round((x / innerW) * (pts.length - 1)), pts.length);
    setActive(idx);
    onScrub?.(data[idx], idx);
  };
  const clear = () => {
    setActive(null);
    onScrub?.(null, -1);
  };

  const last = pts[pts.length - 1];

  return (
    <View
      style={{ width, height }}
      onStartShouldSetResponder={() => true}
      onMoveShouldSetResponder={() => true}
      onResponderGrant={handleTouch}
      onResponderMove={handleTouch}
      onResponderRelease={clear}
      onResponderTerminate={clear}
    >
      <Svg width={width} height={height}>
        <Defs>
          <LinearGradient id={`eq${gid}`} x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={color} stopOpacity={0.3} />
            <Stop offset="0.85" stopColor={color} stopOpacity={0.02} />
            <Stop offset="1" stopColor={color} stopOpacity={0} />
          </LinearGradient>
        </Defs>
        {baseY != null && (
          <Line x1={padX} y1={baseY} x2={padX + innerW} y2={baseY} stroke={palette.hairline} strokeWidth={1} strokeDasharray="3 5" />
        )}
        <Path d={area} fill={`url(#eq${gid})`} />
        {/* Glow underlay */}
        <Path d={line} stroke={color} strokeOpacity={0.3} strokeWidth={7} fill="none" strokeLinejoin="round" strokeLinecap="round" />
        <Path d={line} stroke={color} strokeWidth={2.4} fill="none" strokeLinejoin="round" strokeLinecap="round" />
        {active == null ? (
          <Circle cx={last[0]} cy={last[1]} r={4} fill={color} stroke={palette.page} strokeWidth={2} />
        ) : (
          <>
            <Line x1={pts[active][0]} y1={padTop} x2={pts[active][0]} y2={padTop + innerH} stroke={palette.muted} strokeWidth={1} strokeDasharray="3 3" />
            <Circle cx={pts[active][0]} cy={pts[active][1]} r={5.5} fill={color} stroke={palette.page} strokeWidth={2.5} />
          </>
        )}
      </Svg>
    </View>
  );
}
