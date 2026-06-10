import React, { useId } from 'react';
import { View } from 'react-native';
import Svg, {
  Circle,
  Defs,
  Line,
  LinearGradient,
  Path,
  Rect,
  Stop,
  Text as SvgText,
} from 'react-native-svg';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';
import { extent, smoothPath, type Pt } from './util';
import { compact } from '@/lib/format';

interface Props {
  data: number[];
  width: number;
  height: number;
  /** Show dashed gridlines + $ labels (reference style). */
  grid?: boolean;
  /** Show the live dot + value tooltip on the last point. */
  tooltip?: boolean;
}

/**
 * Hero equity chart — smooth gradient line, soft area fill, dashed gridlines
 * with compact $ labels, and a dark tooltip pill pinned to the latest value.
 */
export function LineChart({ data, width, height, grid = true, tooltip = true }: Props) {
  const { palette, scheme } = useTheme();
  const raw = useId();
  const gid = raw.replace(/:/g, '');

  if (!data || data.length < 2 || width <= 0) return <View style={{ width, height }} />;

  const padTop = tooltip ? 30 : 12;
  const padBottom = 6;
  const padLeft = 8;
  const padRight = 14;
  const innerH = height - padTop - padBottom;
  const innerW = width - padLeft - padRight;

  const [mn, mx] = extent(data);
  const range = mx - mn || 1;
  const y = (v: number) => padTop + innerH * (1 - (v - mn) / range);
  const x = (i: number) => padLeft + (innerW * i) / (data.length - 1);

  const pts: Pt[] = data.map((v, i) => [x(i), y(v)]);
  const line = smoothPath(pts);
  const area = `${line} L${x(data.length - 1).toFixed(2)},${height} L${padLeft},${height} Z`;

  const levels = [mx, (mn + mx) / 2, mn];
  const last = data[data.length - 1];
  const lx = x(data.length - 1);
  const ly = y(last);

  const tipText = `$${compact(last)}`;
  const tipW = tipText.length * 7 + 18;
  const tipX = Math.max(4, Math.min(width - tipW - 4, lx - tipW / 2));
  const tipY = Math.max(2, ly - 34);

  const strokeStops = scheme === 'dark' ? ['#FFC396', '#FF8A3D'] : ['#FFB27D', '#E55A1F'];

  return (
    <Svg width={width} height={height}>
      <Defs>
        <LinearGradient id={`lcs${gid}`} x1="0" y1="0" x2="1" y2="0">
          <Stop offset="0" stopColor={strokeStops[0]} />
          <Stop offset="1" stopColor={strokeStops[1]} />
        </LinearGradient>
        <LinearGradient id={`lcf${gid}`} x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={palette.teal} stopOpacity={scheme === 'dark' ? 0.18 : 0.12} />
          <Stop offset="1" stopColor={palette.teal} stopOpacity={0} />
        </LinearGradient>
      </Defs>

      {grid &&
        levels.map((v, i) => (
          <React.Fragment key={i}>
            <Line
              x1={padLeft}
              y1={y(v)}
              x2={width - padRight}
              y2={y(v)}
              stroke={palette.line}
              strokeWidth={1}
              strokeDasharray="3 5"
            />
            <SvgText
              x={padLeft}
              y={y(v) - 5}
              fontSize={10}
              fontFamily={fonts.uiSemibold}
              fill={palette.muted}
            >
              {`$${compact(v)}`}
            </SvgText>
          </React.Fragment>
        ))}

      <Path d={area} fill={`url(#lcf${gid})`} />
      <Path
        d={line}
        stroke={`url(#lcs${gid})`}
        strokeWidth={2.6}
        fill="none"
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {tooltip && (
        <>
          <Circle cx={lx} cy={ly} r={4.5} fill={palette.teal} stroke={palette.page} strokeWidth={2} />
          <Rect x={tipX} y={tipY} width={tipW} height={20} rx={10} fill={palette.contrast} />
          <SvgText
            x={tipX + tipW / 2}
            y={tipY + 14}
            fontSize={11}
            fontFamily={fonts.uiBold}
            fill={palette.contrastInk}
            textAnchor="middle"
          >
            {tipText}
          </SvgText>
        </>
      )}
    </Svg>
  );
}
