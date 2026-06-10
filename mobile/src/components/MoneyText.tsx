import React from 'react';
import { Text as RNText, type TextStyle } from 'react-native';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';

interface Props {
  value: number | null | undefined;
  size?: number;
  color?: string;
  centsColor?: string;
  cents?: boolean;
  align?: TextStyle['textAlign'];
  style?: TextStyle;
}

/** Big friendly money figure — dollars in ink, cents dimmed (reference style). */
export function MoneyText({ value, size = 48, color, centsColor, cents = true, align, style }: Props) {
  const { palette } = useTheme();
  const ink = color ?? palette.ink;

  if (value == null || !isFinite(value)) {
    return (
      <RNText style={[{ fontFamily: fonts.uiExtra, fontSize: size, color: ink, textAlign: align }, style]}>—</RNText>
    );
  }

  const formatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  }).format(value);
  const [dollars, centPart] = formatted.split('.');

  return (
    <RNText
      style={[
        {
          fontFamily: fonts.uiExtra,
          fontSize: size,
          lineHeight: Math.round(size * 1.14),
          letterSpacing: -size * 0.03,
          color: ink,
          textAlign: align,
        },
        style,
      ]}
    >
      {dollars}
      {cents && centPart != null && (
        <RNText style={{ color: centsColor ?? palette.muted }}>.{centPart}</RNText>
      )}
    </RNText>
  );
}
