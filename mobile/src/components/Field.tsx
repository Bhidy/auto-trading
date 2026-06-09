import React from 'react';
import { TextInput, View, type KeyboardTypeOptions } from 'react-native';
import { Text } from './Text';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';
import { radius } from '@/theme/tokens';

interface Props {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  placeholder?: string;
  keyboardType?: KeyboardTypeOptions;
  autoCapitalize?: 'none' | 'characters';
  secure?: boolean;
  suffix?: string;
}

/** Labeled input — mono numerals, inset well, themed. */
export function Field({ label, value, onChangeText, placeholder, keyboardType, autoCapitalize = 'none', secure, suffix }: Props) {
  const { palette } = useTheme();
  return (
    <View style={{ gap: 6, flex: 1 }}>
      <Text variant="overline" dim>
        {label}
      </Text>
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          backgroundColor: palette.surfaceInset,
          borderRadius: radius.sm,
          borderWidth: 1,
          borderColor: palette.line,
          paddingHorizontal: 12,
        }}
      >
        <TextInput
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={palette.muted}
          keyboardType={keyboardType}
          autoCapitalize={autoCapitalize}
          autoCorrect={false}
          secureTextEntry={secure}
          style={{
            flex: 1,
            color: palette.ink,
            fontFamily: fonts.monoMedium,
            fontSize: 16,
            paddingVertical: 12,
          }}
        />
        {suffix ? (
          <Text variant="caption" dim>
            {suffix}
          </Text>
        ) : null}
      </View>
    </View>
  );
}
