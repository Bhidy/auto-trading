/**
 * Typography system — Plus Jakarta Sans everywhere (friendly geometric rounded),
 * DM Serif Display reserved for the brand wordmark, JetBrains Mono for data/codes.
 * Font family keys match @expo-google-fonts exports.
 */
import type { TextStyle } from 'react-native';

export const fonts = {
  serif: 'DMSerifDisplay_400Regular',
  serifItalic: 'DMSerifDisplay_400Regular_Italic',
  ui: 'PlusJakartaSans_400Regular',
  uiMedium: 'PlusJakartaSans_500Medium',
  uiSemibold: 'PlusJakartaSans_600SemiBold',
  uiBold: 'PlusJakartaSans_700Bold',
  uiExtra: 'PlusJakartaSans_800ExtraBold',
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
  displayXL: { fontFamily: fonts.uiExtra, fontSize: 50, lineHeight: 56, letterSpacing: -1.6 },
  displayL: { fontFamily: fonts.uiExtra, fontSize: 38, lineHeight: 44, letterSpacing: -1.1 },
  display: { fontFamily: fonts.uiExtra, fontSize: 28, lineHeight: 34, letterSpacing: -0.7 },
  title: { fontFamily: fonts.uiExtra, fontSize: 22, lineHeight: 28, letterSpacing: -0.4 },
  headline: { fontFamily: fonts.uiBold, fontSize: 17, lineHeight: 23, letterSpacing: -0.2 },
  subtitle: { fontFamily: fonts.uiSemibold, fontSize: 16, lineHeight: 22 },
  body: { fontFamily: fonts.uiMedium, fontSize: 15, lineHeight: 22 },
  bodyStrong: { fontFamily: fonts.uiBold, fontSize: 15, lineHeight: 22 },
  label: { fontFamily: fonts.uiSemibold, fontSize: 13, lineHeight: 18 },
  caption: { fontFamily: fonts.uiMedium, fontSize: 12, lineHeight: 16 },
  overline: { fontFamily: fonts.uiBold, fontSize: 11, lineHeight: 14, letterSpacing: 1.2, textTransform: 'uppercase' },
  mono: { fontFamily: fonts.mono, fontSize: 13, lineHeight: 18 },
  monoL: { fontFamily: fonts.monoMedium, fontSize: 17, lineHeight: 22, letterSpacing: -0.2 },
  monoXL: { fontFamily: fonts.monoMedium, fontSize: 28, lineHeight: 32, letterSpacing: -0.6 },
};
