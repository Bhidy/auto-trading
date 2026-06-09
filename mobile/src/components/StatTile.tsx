import React from 'react';
import { View, type ViewStyle } from 'react-native';
import { Text } from './Text';

interface Props {
  label: string;
  children: React.ReactNode;
  hint?: React.ReactNode;
  align?: 'left' | 'center';
  style?: ViewStyle;
}

export function StatTile({ label, children, hint, align = 'left', style }: Props) {
  return (
    <View style={[{ gap: 5, alignItems: align === 'center' ? 'center' : 'flex-start' }, style]}>
      <Text variant="overline" dim>
        {label}
      </Text>
      {children}
      {hint}
    </View>
  );
}
