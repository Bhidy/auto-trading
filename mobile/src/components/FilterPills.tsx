import React from 'react';
import { ScrollView, View, type ViewStyle } from 'react-native';
import { Text } from './Text';
import { PressableScale } from './PressableScale';
import { useTheme } from '@/theme/ThemeProvider';
import { radius } from '@/theme/tokens';
import { haptic } from '@/lib/haptics';

interface Props<T extends string> {
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  /** Stretch pills to share the full row width. */
  stretch?: boolean;
  /** Horizontal scroll when options overflow. */
  scrollable?: boolean;
  style?: ViewStyle;
}

/** Friendly pill selector — espresso active pill on a bare row (reference style). */
export function FilterPills<T extends string>({ options, value, onChange, stretch, scrollable, style }: Props<T>) {
  const { palette } = useTheme();

  const pills = options.map((opt) => {
    const active = opt === value;
    return (
      <PressableScale
        key={opt}
        scaleTo={0.94}
        onPress={() => {
          if (!active) {
            haptic.select();
            onChange(opt);
          }
        }}
        style={{
          paddingVertical: 7,
          paddingHorizontal: 14,
          borderRadius: radius.pill,
          backgroundColor: active ? palette.contrast : 'transparent',
          alignItems: 'center',
          ...(stretch ? { flex: 1 } : null),
        }}
      >
        <Text
          variant="label"
          style={{ color: active ? palette.contrastInk : palette.muted, fontSize: 12.5 }}
        >
          {opt}
        </Text>
      </PressableScale>
    );
  });

  if (scrollable) {
    return (
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ gap: 4, alignItems: 'center' }}
        style={style}
      >
        {pills}
      </ScrollView>
    );
  }

  return (
    <View style={[{ flexDirection: 'row', gap: 4, alignItems: 'center', justifyContent: stretch ? undefined : 'center' }, style]}>
      {pills}
    </View>
  );
}
