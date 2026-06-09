import React, { useEffect } from 'react';
import { type DimensionValue, type ViewStyle } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useSharedValue, withRepeat, withTiming } from 'react-native-reanimated';
import { useTheme } from '@/theme/ThemeProvider';

export function Skeleton({
  width = '100%',
  height = 16,
  rounded = 8,
  style,
}: {
  width?: DimensionValue;
  height?: number;
  rounded?: number;
  style?: ViewStyle;
}) {
  const { palette } = useTheme();
  const opacity = useSharedValue(0.45);

  useEffect(() => {
    opacity.value = withRepeat(withTiming(0.95, { duration: 850, easing: Easing.inOut(Easing.ease) }), -1, true);
  }, [opacity]);

  const animated = useAnimatedStyle(() => ({ opacity: opacity.value }));

  return (
    <Animated.View
      style={[{ width, height, borderRadius: rounded, backgroundColor: palette.surfaceInset }, animated, style]}
    />
  );
}
