import React, { useEffect, useRef, useState } from 'react';
import type { TextStyle } from 'react-native';
import { Text } from './Text';
import type { TypeVariant } from '@/theme/typography';
import type { Palette } from '@/theme/tokens';

interface Props {
  value: number;
  format: (n: number) => string;
  variant?: TypeVariant;
  color?: keyof Palette | (string & {});
  duration?: number;
  style?: TextStyle;
}

const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

/** Count-up number that eases from its previous value to the new one. */
export function AnimatedNumber({ value, format, variant = 'monoXL', color, duration = 750, style }: Props) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const from = fromRef.current;
    const to = value;
    if (from === to) return;

    let start = 0;
    const step = (ts: number) => {
      if (!isFinite(to)) {
        setDisplay(to);
        fromRef.current = to;
        return;
      }
      if (!start) start = ts;
      const p = Math.min(1, (ts - start) / duration);
      setDisplay(from + (to - from) * easeOutCubic(p));
      if (p < 1) {
        rafRef.current = requestAnimationFrame(step);
      } else {
        fromRef.current = to;
      }
    };
    rafRef.current = requestAnimationFrame(step);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      fromRef.current = value;
    };
  }, [value, duration]);

  return (
    <Text variant={variant} color={color} style={style}>
      {format(display)}
    </Text>
  );
}
