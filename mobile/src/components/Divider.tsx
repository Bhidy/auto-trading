import React from 'react';
import { View } from 'react-native';
import { useTheme } from '@/theme/ThemeProvider';

export function Divider({ spacing = 0, inset = 0 }: { spacing?: number; inset?: number }) {
  const { palette } = useTheme();
  return (
    <View style={{ height: 1, backgroundColor: palette.line, marginVertical: spacing, marginHorizontal: inset }} />
  );
}
