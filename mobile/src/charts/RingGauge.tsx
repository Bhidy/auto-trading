/** Animated gradient ring gauge — draws itself in with a spring sweep. */
import React, { useEffect, useId } from 'react';
import { View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Stop } from 'react-native-svg';
import Animated, { useAnimatedProps, useSharedValue, withDelay, withTiming, Easing } from 'react-native-reanimated';
import { Text } from '@/components/Text';
import { useTheme } from '@/theme/ThemeProvider';

const AnimatedCircle = Animated.createAnimatedComponent(Circle);

interface Props {
  /** 0..1 fill of the ring */
  progress: number;
  size?: number;
  thickness?: number;
  colors?: [string, string];
  label?: string;
  value?: string;
  delay?: number;
}

export function RingGauge({ progress, size = 92, thickness = 9, colors, label, value, delay = 150 }: Props) {
  const { palette, scheme } = useTheme();
  const gid = useId().replace(/:/g, '');
  const r = (size - thickness) / 2;
  const c = size / 2;
  const circumference = 2 * Math.PI * r;
  const clamped = Math.max(0.02, Math.min(1, isFinite(progress) ? progress : 0.02));

  const anim = useSharedValue(0);
  useEffect(() => {
    anim.value = 0;
    anim.value = withDelay(delay, withTiming(clamped, { duration: 950, easing: Easing.out(Easing.cubic) }));
  }, [clamped, delay, anim]);

  const animatedProps = useAnimatedProps(() => ({
    strokeDashoffset: circumference * (1 - anim.value),
  }));

  const ramp = colors ?? (scheme === 'dark' ? (['#FF8A3D', '#F26B1F'] as [string, string]) : (['#F26B1F', '#C9461A'] as [string, string]));

  return (
    <View style={{ width: size, alignItems: 'center', gap: 6 }}>
      <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
        <Svg width={size} height={size}>
          <Defs>
            <LinearGradient id={`rg${gid}`} x1="0" y1="0" x2="1" y2="1">
              <Stop offset="0" stopColor={ramp[0]} />
              <Stop offset="1" stopColor={ramp[1]} />
            </LinearGradient>
          </Defs>
          {/* Track */}
          <Circle cx={c} cy={c} r={r} stroke={palette.surfaceInset} strokeWidth={thickness} fill="none" />
          {/* Glow underlay */}
          <AnimatedCircle
            cx={c}
            cy={c}
            r={r}
            stroke={ramp[0]}
            strokeOpacity={0.25}
            strokeWidth={thickness + 5}
            strokeLinecap="round"
            fill="none"
            strokeDasharray={`${circumference}`}
            animatedProps={animatedProps}
            transform={`rotate(-90 ${c} ${c})`}
          />
          {/* Fill */}
          <AnimatedCircle
            cx={c}
            cy={c}
            r={r}
            stroke={`url(#rg${gid})`}
            strokeWidth={thickness}
            strokeLinecap="round"
            fill="none"
            strokeDasharray={`${circumference}`}
            animatedProps={animatedProps}
            transform={`rotate(-90 ${c} ${c})`}
          />
        </Svg>
        {value != null && (
          <View style={{ position: 'absolute', alignItems: 'center' }}>
            <Text variant="monoL" style={{ fontSize: size * 0.19 }}>
              {value}
            </Text>
          </View>
        )}
      </View>
      {label ? (
        <Text variant="overline" dim>
          {label}
        </Text>
      ) : null}
    </View>
  );
}
