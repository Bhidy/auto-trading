/**
 * Living backdrop — deep vertical wash + slowly drifting solar glow orbs.
 * Sits behind every screen so content floats as glass above it.
 */
import React, { useEffect } from 'react';
import { StyleSheet, useWindowDimensions, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import Svg, { Circle, Defs, RadialGradient, Stop } from 'react-native-svg';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';
import { useTheme } from '@/theme/ThemeProvider';

function Orb({
  size,
  color,
  x,
  y,
  driftX,
  driftY,
  duration,
}: {
  size: number;
  color: string;
  x: number;
  y: number;
  driftX: number;
  driftY: number;
  duration: number;
}) {
  const t = useSharedValue(0);

  useEffect(() => {
    t.value = withRepeat(withTiming(1, { duration, easing: Easing.inOut(Easing.sin) }), -1, true);
  }, [duration, t]);

  const style = useAnimatedStyle(() => ({
    transform: [{ translateX: x + t.value * driftX }, { translateY: y + t.value * driftY }],
  }));

  return (
    <Animated.View style={[{ position: 'absolute', width: size, height: size }, style]} pointerEvents="none">
      <Svg width={size} height={size}>
        <Defs>
          <RadialGradient id="orb" cx="50%" cy="50%" r="50%">
            <Stop offset="0%" stopColor={color} stopOpacity={1} />
            <Stop offset="60%" stopColor={color} stopOpacity={0.35} />
            <Stop offset="100%" stopColor={color} stopOpacity={0} />
          </RadialGradient>
        </Defs>
        <Circle cx={size / 2} cy={size / 2} r={size / 2} fill="url(#orb)" />
      </Svg>
    </Animated.View>
  );
}

export function AmbientBackground() {
  const { palette, scheme } = useTheme();
  const { width, height } = useWindowDimensions();

  const colors =
    scheme === 'dark'
      ? (['#150B05', '#0E0805', '#080403'] as const)
      : (['#FFF3E6', '#FFF7F0', '#FDEFE3'] as const);

  const orbColor = palette.glowTeal;
  const orb2 = scheme === 'dark' ? 'rgba(255,138,61,0.13)' : 'rgba(255,168,106,0.22)';

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <LinearGradient colors={colors} style={StyleSheet.absoluteFill} />
      <Orb size={width * 1.25} color={orbColor} x={-width * 0.35} y={-width * 0.45} driftX={26} driftY={20} duration={9000} />
      <Orb size={width * 0.95} color={orb2} x={width * 0.45} y={height * 0.28} driftX={-22} driftY={30} duration={12000} />
      <Orb size={width * 1.1} color={orbColor} x={-width * 0.2} y={height * 0.66} driftX={18} driftY={-24} duration={11000} />
    </View>
  );
}
