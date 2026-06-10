import React from 'react';
import { View, type ViewStyle } from 'react-native';
import { Text } from './Text';
import { LiveDot } from './LiveDot';
import { useTheme } from '@/theme/ThemeProvider';
import { radius } from '@/theme/tokens';
import { fonts } from '@/theme/typography';

type Tone = 'neutral' | 'accent' | 'up' | 'down' | 'live';

/** Friendly status pill — soft fill, sentence-case label (Design 3.0). */
export function Tag({
  label,
  tone = 'neutral',
  live = false,
  style,
}: {
  label: string;
  tone?: Tone;
  live?: boolean;
  style?: ViewStyle;
}) {
  const { palette } = useTheme();
  const map: Record<Tone, { bg: string; fg: string }> = {
    neutral: { bg: palette.surfaceAlt, fg: palette.muted },
    accent: { bg: palette.tealSoft, fg: palette.tealDark },
    up: { bg: palette.upSoft, fg: palette.up },
    down: { bg: palette.downSoft, fg: palette.down },
    live: { bg: palette.upSoft, fg: palette.up },
  };
  const c = map[tone];

  return (
    <View
      style={[
        {
          backgroundColor: c.bg,
          borderRadius: radius.pill,
          paddingHorizontal: 10,
          paddingVertical: 4.5,
          flexDirection: 'row',
          alignItems: 'center',
          gap: 5,
          alignSelf: 'flex-start',
        },
        style,
      ]}
    >
      {live && <LiveDot color={c.fg} size={6} />}
      <Text style={{ color: c.fg, fontFamily: fonts.uiBold, fontSize: 11.5, lineHeight: 15 }}>{label}</Text>
    </View>
  );
}
