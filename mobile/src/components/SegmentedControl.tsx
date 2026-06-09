import React, { useState } from 'react';
import { type LayoutChangeEvent, View } from 'react-native';
import Animated, { useAnimatedStyle, withTiming } from 'react-native-reanimated';
import { PressableScale } from './PressableScale';
import { Text } from './Text';
import { useTheme } from '@/theme/ThemeProvider';
import { radius } from '@/theme/tokens';
import { haptic } from '@/lib/haptics';

interface Props<T extends string> {
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
}

/** Period / mode selector with a sliding indicator pill. */
export function SegmentedControl<T extends string>({ options, value, onChange }: Props<T>) {
  const { palette } = useTheme();
  const [width, setWidth] = useState(0);

  const idx = Math.max(0, options.indexOf(value));
  const usable = Math.max(0, width - 6);
  const seg = options.length ? usable / options.length : 0;

  const indicator = useAnimatedStyle(() => ({
    transform: [{ translateX: withTiming(idx * seg, { duration: 220 }) }],
    width: seg,
  }));

  return (
    <View
      onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)}
      style={{ flexDirection: 'row', backgroundColor: palette.surfaceInset, borderRadius: radius.pill, padding: 3 }}
    >
      {seg > 0 && (
        <Animated.View
          style={[
            {
              position: 'absolute',
              top: 3,
              bottom: 3,
              left: 3,
              borderRadius: radius.pill,
              backgroundColor: palette.surface,
              borderWidth: 1,
              borderColor: palette.line,
            },
            indicator,
          ]}
        />
      )}
      {options.map((o) => (
        <PressableScale
          key={o}
          scaleTo={0.94}
          onPress={() => {
            haptic.select();
            onChange(o);
          }}
          style={{ flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: 8 }}
        >
          <Text variant="label" style={{ color: o === value ? palette.ink : palette.muted }}>
            {o}
          </Text>
        </PressableScale>
      ))}
    </View>
  );
}
