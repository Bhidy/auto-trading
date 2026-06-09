import React, { useEffect } from 'react';
import { View } from 'react-native';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import { useTheme } from '@/theme/ThemeProvider';

/** Pulsing presence indicator (the "live" heartbeat used across the app). */
export function LiveDot({ color, size = 8, active = true }: { color?: string; size?: number; active?: boolean }) {
  const { palette } = useTheme();
  const c = color ?? palette.up;
  const scale = useSharedValue(1);
  const opacity = useSharedValue(0.6);

  useEffect(() => {
    if (!active) {
      scale.value = 1;
      opacity.value = 0;
      return;
    }
    scale.value = withRepeat(
      withSequence(withTiming(2.4, { duration: 1300, easing: Easing.out(Easing.ease) }), withTiming(1, { duration: 0 })),
      -1,
      false,
    );
    opacity.value = withRepeat(
      withSequence(withTiming(0, { duration: 1300, easing: Easing.out(Easing.ease) }), withTiming(0.6, { duration: 0 })),
      -1,
      false,
    );
  }, [active, opacity, scale]);

  const ring = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
    opacity: opacity.value,
  }));

  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      <Animated.View
        style={[{ position: 'absolute', width: size, height: size, borderRadius: size / 2, backgroundColor: c }, ring]}
      />
      <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: c }} />
    </View>
  );
}
