import React from 'react';
import { View } from 'react-native';
import { Text } from './Text';
import { LiveDot } from './LiveDot';
import { useTheme } from '@/theme/ThemeProvider';
import { radius } from '@/theme/tokens';
import { useMarketClock } from '@/api/hooks';

/** Live market-session pill — green heartbeat when NYSE is open. */
export function ClockPill() {
  const { palette } = useTheme();
  const { data } = useMarketClock();
  const open = data?.is_open === true;
  const color = open ? palette.up : palette.muted;

  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: 7,
        paddingHorizontal: 11,
        paddingVertical: 7,
        borderRadius: radius.pill,
        borderWidth: 1,
        borderColor: palette.line,
        backgroundColor: palette.surface,
      }}
    >
      <LiveDot color={color} size={7} active={open} />
      <Text variant="overline" style={{ color }}>
        {data ? (open ? 'Market open' : 'Closed') : '· · ·'}
      </Text>
    </View>
  );
}
