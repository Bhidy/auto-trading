import React from 'react';
import { View, type ViewStyle } from 'react-native';
import { Text } from './Text';
import { LiveDot } from './LiveDot';
import { useTheme } from '@/theme/ThemeProvider';
import { radius } from '@/theme/tokens';

type Tone = 'neutral' | 'accent' | 'up' | 'down' | 'live';

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
    neutral: { bg: palette.surfaceInset, fg: palette.muted },
    accent: { bg: palette.tealSoft, fg: palette.teal },
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
          paddingHorizontal: 9,
          paddingVertical: 4,
          flexDirection: 'row',
          alignItems: 'center',
          gap: 5,
          alignSelf: 'flex-start',
        },
        style,
      ]}
    >
      {live && <LiveDot color={c.fg} size={6} />}
      <Text variant="overline" style={{ color: c.fg }}>
        {label}
      </Text>
    </View>
  );
}
