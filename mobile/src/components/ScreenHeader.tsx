import React from 'react';
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text } from './Text';
import { Wordmark } from './Wordmark';

interface Props {
  title?: string;
  eyebrow?: string;
  wordmark?: boolean;
  right?: React.ReactNode;
  subtitle?: string;
}

/** Page header — serif title or brand lockup, with an optional right-side widget. */
export function ScreenHeader({ title, eyebrow, wordmark, right, subtitle }: Props) {
  const insets = useSafeAreaInsets();
  return (
    <View style={{ paddingTop: insets.top + 14, paddingBottom: 14, gap: 4 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <View style={{ gap: 4, flex: 1 }}>
          {eyebrow ? (
            <Text variant="overline" color="teal">
              {eyebrow}
            </Text>
          ) : null}
          {wordmark ? <Wordmark size={26} /> : title ? <Text variant="display">{title}</Text> : null}
        </View>
        {right}
      </View>
      {subtitle ? (
        <Text variant="body" dim>
          {subtitle}
        </Text>
      ) : null}
    </View>
  );
}
