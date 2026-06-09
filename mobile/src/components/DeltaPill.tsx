import React from 'react';
import { View, type ViewStyle } from 'react-native';
import { Text } from './Text';
import { useTheme } from '@/theme/ThemeProvider';
import { radius } from '@/theme/tokens';
import { fonts } from '@/theme/typography';
import { trendOf } from '@/lib/format';

interface Props {
  value: number | null | undefined; // percentage number (e.g. 2.5 => 2.50%)
  text?: string; // override the displayed text
  size?: 'sm' | 'md';
  filled?: boolean;
  style?: ViewStyle;
}

/** P&L delta with directional caret — the canonical bullish/bearish chip. */
export function DeltaPill({ value, text, size = 'md', filled = true, style }: Props) {
  const { palette } = useTheme();
  const t = trendOf(value ?? 0);
  const color = t === 'up' ? palette.up : t === 'down' ? palette.down : palette.muted;
  const bg = t === 'up' ? palette.upSoft : t === 'down' ? palette.downSoft : palette.surfaceInset;
  const caret = t === 'up' ? '▲' : t === 'down' ? '▼' : '•';
  const label = text ?? `${value != null && isFinite(value) ? Math.abs(value).toFixed(2) : '—'}%`;
  const fontSize = size === 'sm' ? 11 : 12.5;

  return (
    <View
      style={[
        {
          flexDirection: 'row',
          alignItems: 'center',
          gap: 4,
          paddingHorizontal: filled ? 8 : 0,
          paddingVertical: filled ? 3 : 0,
          borderRadius: radius.pill,
          backgroundColor: filled ? bg : 'transparent',
        },
        style,
      ]}
    >
      <Text style={{ color, fontSize: fontSize - 2, fontFamily: fonts.uiBold }}>{caret}</Text>
      <Text style={{ color, fontSize, fontFamily: fonts.monoMedium }}>{label}</Text>
    </View>
  );
}
