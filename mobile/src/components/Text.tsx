import React from 'react';
import { Text as RNText, type TextProps, type TextStyle } from 'react-native';
import { useTheme } from '@/theme/ThemeProvider';
import { typeScale, fonts, type TypeVariant } from '@/theme/typography';
import type { Palette } from '@/theme/tokens';

const PALETTE_KEYS = new Set<keyof Palette>([
  'page', 'surface', 'surfaceAlt', 'surfaceInset', 'ink', 'inkSoft', 'muted',
  'line', 'hairline', 'teal', 'tealDark', 'tealSoft', 'up', 'down',
  'tintPeach', 'tintCream', 'tintMist', 'contrast', 'contrastInk', 'contrastMuted',
]);

interface Props extends TextProps {
  variant?: TypeVariant;
  color?: keyof Palette | (string & {});
  align?: TextStyle['textAlign'];
  dim?: boolean;
  italic?: boolean;
}

export function Text({ variant = 'body', color, align, dim, italic, style, ...rest }: Props) {
  const { palette } = useTheme();
  const resolved = color
    ? PALETTE_KEYS.has(color as keyof Palette)
      ? (palette[color as keyof Palette] as string)
      : (color as string)
    : dim
      ? palette.muted
      : palette.ink;

  return (
    <RNText
      {...rest}
      style={[
        typeScale[variant],
        { color: resolved },
        align ? { textAlign: align } : null,
        italic ? { fontFamily: fonts.serifItalic } : null,
        style,
      ]}
    />
  );
}
