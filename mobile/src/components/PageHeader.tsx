import React from 'react';
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text } from './Text';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';

interface Props {
  title: string;
  sub?: string;
  right?: React.ReactNode;
}

/** Tab-screen header — big friendly title, optional sub line and right slot. */
export function PageHeader({ title, sub, right }: Props) {
  const { palette } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View
      style={{
        paddingTop: insets.top + 12,
        paddingBottom: 16,
        flexDirection: 'row',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        gap: 12,
      }}
    >
      <View style={{ flex: 1, gap: 3 }}>
        <Text style={{ fontFamily: fonts.uiExtra, fontSize: 26, lineHeight: 32, letterSpacing: -0.6, color: palette.ink }}>
          {title}
        </Text>
        {!!sub && (
          <Text variant="caption" dim>
            {sub}
          </Text>
        )}
      </View>
      {right}
    </View>
  );
}
