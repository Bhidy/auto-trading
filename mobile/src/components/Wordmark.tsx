import React from 'react';
import { View } from 'react-native';
import { Text } from './Text';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';

/** Brand lockup: "Auto" in ink + "Trading." in teal, italic DM Serif Display. */
export function Wordmark({ size = 22 }: { size?: number }) {
  const { palette } = useTheme();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
      <Text style={{ fontFamily: fonts.serifItalic, fontSize: size, color: palette.ink }}>Auto </Text>
      <Text style={{ fontFamily: fonts.serifItalic, fontSize: size, color: palette.teal }}>Trading.</Text>
    </View>
  );
}
