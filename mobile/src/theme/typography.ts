/**
 * Typography system — DM Serif Display (display/money), Manrope (UI),
 * JetBrains Mono (data/codes). Font family keys match @expo-google-fonts exports.
 */
import type { TextStyle } from 'react-native';

export const fonts = {
  serif: 'DMSerifDisplay_400Regular',
  serifItalic: 'DMSerifDisplay_400Regular_Italic',
  ui: 'Manrope_400Regular',
  uiMedium: 'Manrope_500Medium',
  uiSemibold: 'Manrope_600SemiBold',
  uiBold: 'Manrope_700Bold',
  uiExtra: 'Manrope_800ExtraBold',
  mono: 'JetBrainsMono_400Regular',
  monoMedium: 'JetBrainsMono_500Medium',
} as const;

export type TypeVariant =
  | 'displayXL'
  | 'displayL'
  | 'display'
  | 'title'
  | 'headline'
  | 'subtitle'
  | 'body'
  | 'bodyStrong'
  | 'label'
  | 'caption'
  | 'overline'
  | 'mono'
  | 'monoL'
  | 'monoXL';

export const typeScale: Record<TypeVariant, TextStyle> = {
  displayXL: { fontFamily: fonts.serif, fontSize: 52, lineHeight: 56, letterSpacing: -0.5 },
  displayL: { fontFamily: fonts.serif, fontSize: 40, lineHeight: 44, letterSpacing: -0.4 },
  display: { fontFamily: fonts.serif, fontSize: 30, lineHeight: 36, letterSpacing: -0.3 },
  title: { fontFamily: fonts.uiExtra, fontSize: 22, lineHeight: 28, letterSpacing: -0.2 },
  headline: { fontFamily: fonts.uiBold, fontSize: 18, lineHeight: 24, letterSpacing: -0.1 },
  subtitle: { fontFamily: fonts.uiSemibold, fontSize: 16, lineHeight: 22 },
  body: { fontFamily: fonts.ui, fontSize: 15, lineHeight: 22 },
  bodyStrong: { fontFamily: fonts.uiSemibold, fontSize: 15, lineHeight: 22 },
  label: { fontFamily: fonts.uiSemibold, fontSize: 13, lineHeight: 18 },
  caption: { fontFamily: fonts.uiMedium, fontSize: 12, lineHeight: 16 },
  overline: { fontFamily: fonts.uiBold, fontSize: 10.5, lineHeight: 14, letterSpacing: 1.4, textTransform: 'uppercase' },
  mono: { fontFamily: fonts.mono, fontSize: 13, lineHeight: 18 },
  monoL: { fontFamily: fonts.monoMedium, fontSize: 17, lineHeight: 22, letterSpacing: -0.2 },
  monoXL: { fontFamily: fonts.monoMedium, fontSize: 28, lineHeight: 32, letterSpacing: -0.6 },
};
