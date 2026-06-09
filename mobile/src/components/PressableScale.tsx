import React from 'react';
import { Pressable, type PressableProps, type GestureResponderEvent } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

interface Props extends PressableProps {
  scaleTo?: number;
  dimTo?: number;
  haptics?: () => void;
}

/** A pressable with a tactile spring-down scale — the base interaction primitive. */
export function PressableScale({ scaleTo = 0.97, dimTo = 0.9, style, onPressIn, onPressOut, children, ...rest }: Props) {
  const scale = useSharedValue(1);
  const opacity = useSharedValue(1);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
    opacity: opacity.value,
  }));

  /* eslint-disable react-hooks/immutability -- Reanimated shared values are mutable by design */
  const handleIn = (e: GestureResponderEvent) => {
    scale.value = withTiming(scaleTo, { duration: 90 });
    opacity.value = withTiming(dimTo, { duration: 90 });
    onPressIn?.(e);
  };
  const handleOut = (e: GestureResponderEvent) => {
    scale.value = withTiming(1, { duration: 160 });
    opacity.value = withTiming(1, { duration: 160 });
    onPressOut?.(e);
  };
  /* eslint-enable react-hooks/immutability */

  return (
    <AnimatedPressable {...rest} onPressIn={handleIn} onPressOut={handleOut} style={[animatedStyle, style]}>
      {children as React.ReactNode}
    </AnimatedPressable>
  );
}
