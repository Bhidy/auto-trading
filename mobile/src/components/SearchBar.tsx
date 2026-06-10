import React from 'react';
import { TextInput, View, type ViewStyle } from 'react-native';
import { Icon } from './Icon';
import { useTheme } from '@/theme/ThemeProvider';
import { radius } from '@/theme/tokens';
import { fonts } from '@/theme/typography';

interface Props {
  value: string;
  onChangeText: (v: string) => void;
  placeholder?: string;
  style?: ViewStyle;
}

/** Soft rounded search well (reference "Search people, stocks & crypto"). */
export function SearchBar({ value, onChangeText, placeholder = 'Search symbols', style }: Props) {
  const { palette } = useTheme();

  return (
    <View
      style={[
        {
          flexDirection: 'row',
          alignItems: 'center',
          gap: 10,
          backgroundColor: palette.surfaceAlt,
          borderRadius: radius.md,
          paddingHorizontal: 14,
          paddingVertical: 2,
        },
        style,
      ]}
    >
      <Icon name="search" size={17} color={palette.muted} />
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={palette.muted}
        autoCapitalize="characters"
        autoCorrect={false}
        returnKeyType="search"
        style={{
          flex: 1,
          fontFamily: fonts.uiMedium,
          fontSize: 15,
          color: palette.ink,
          paddingVertical: 11,
        }}
      />
    </View>
  );
}
