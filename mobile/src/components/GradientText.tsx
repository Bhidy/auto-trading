/** Gradient-filled text via mask — the hero-numeral treatment. */
import React from 'react';
import { Platform, Text as RNText, type TextStyle } from 'react-native';
import MaskedView from '@react-native-masked-view/masked-view';
import { LinearGradient } from 'expo-linear-gradient';
import { useTheme } from '@/theme/ThemeProvider';

interface Props {
  text: string;
  style: TextStyle; // must set fontFamily + fontSize
  colors?: readonly [string, string, ...string[]];
}

export function GradientText({ text, style, colors }: Props) {
  const { scheme } = useTheme();
  const ramp =
    colors ??
    (scheme === 'dark'
      ? (['#FFF1E8', '#FFC396', '#FF8A3D'] as const)
      : (['#1A0F08', '#7A3414', '#E55A1F'] as const));

  // masked-view has no real mask on web — fall back to a solid brand tone there.
  if (Platform.OS === 'web') {
    return <RNText style={[style, { color: scheme === 'dark' ? '#FFE3CE' : '#2A1208' }]}>{text}</RNText>;
  }

  return (
    <MaskedView maskElement={<RNText style={[style, { backgroundColor: 'transparent' }]}>{text}</RNText>}>
      <LinearGradient colors={ramp} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1.4 }}>
        <RNText style={[style, { opacity: 0 }]}>{text}</RNText>
      </LinearGradient>
    </MaskedView>
  );
}
