import React, { useMemo, useState } from 'react';
import { type GestureResponderEvent, View } from 'react-native';
import Svg, { Line, Rect } from 'react-native-svg';
import { useTheme } from '@/theme/ThemeProvider';
import { clampIndex, extent } from './util';

export interface Bar {
  t: string | number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

interface Props {
  bars: Bar[];
  width: number;
  height: number;
  onScrub?: (b: Bar | null, index: number) => void;
}

/** Self-contained candlestick renderer: wicks + bodies + volume strip + crosshair. */
export function Candlestick({ bars, width, height, onScrub }: Props) {
  const { palette } = useTheme();
  const [active, setActive] = useState<number | null>(null);

  const padX = 3;
  const padTop = 8;
  const gap = 8;
  const volH = Math.round(height * 0.18);
  const priceH = height - volH - gap - padTop;
  const innerW = width - padX * 2;

  const model = useMemo(() => {
    const clean = bars.filter((b) => isFinite(b.o) && isFinite(b.c) && isFinite(b.h) && isFinite(b.l));
    if (clean.length < 2) return null;
    const [lo, hi] = extent(clean.flatMap((b) => [b.h, b.l]));
    const range = hi - lo || 1;
    const maxVol = Math.max(...clean.map((b) => b.v || 0), 1);
    const slot = innerW / clean.length;
    const bw = Math.max(1.5, Math.min(slot * 0.66, 13));
    const yPrice = (p: number) => padTop + priceH * (1 - (p - lo) / range);
    const center = (i: number) => padX + slot * (i + 0.5);
    return { clean, yPrice, center, bw, maxVol, slot };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, width, height]);

  if (!model) return <View style={{ width, height }} />;
  const { clean, yPrice, center, bw, maxVol } = model;
  const volTop = padTop + priceH + gap;

  const handleTouch = (e: GestureResponderEvent) => {
    const x = e.nativeEvent.locationX - padX;
    const idx = clampIndex(Math.floor((x / innerW) * clean.length), clean.length);
    setActive(idx);
    onScrub?.(clean[idx], idx);
  };
  const clear = () => {
    setActive(null);
    onScrub?.(null, -1);
  };

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
        {clean.map((b, i) => {
          const up = b.c >= b.o;
          const col = up ? palette.up : palette.down;
          const cx = center(i);
          const yO = yPrice(b.o);
          const yC = yPrice(b.c);
          const bodyTop = Math.min(yO, yC);
          const bodyH = Math.max(1, Math.abs(yC - yO));
          const volBarH = Math.max(0.5, (b.v / maxVol) * volH);
          return (
            <React.Fragment key={i}>
              <Line x1={cx} y1={yPrice(b.h)} x2={cx} y2={yPrice(b.l)} stroke={col} strokeWidth={1} opacity={0.9} />
              <Rect x={cx - bw / 2} y={bodyTop} width={bw} height={bodyH} rx={1} fill={col} />
              <Rect x={cx - bw / 2} y={volTop + (volH - volBarH)} width={bw} height={volBarH} rx={0.5} fill={col} opacity={0.32} />
            </React.Fragment>
          );
        })}
        {active != null && (
          <>
            <Line x1={center(active)} y1={padTop} x2={center(active)} y2={padTop + priceH} stroke={palette.muted} strokeWidth={1} strokeDasharray="3 3" />
            <Line x1={padX} y1={yPrice(clean[active].c)} x2={padX + innerW} y2={yPrice(clean[active].c)} stroke={palette.muted} strokeWidth={1} strokeDasharray="3 3" />
          </>
        )}
      </Svg>
    </View>
  );
}
