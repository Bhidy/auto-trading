/** Staggered entrance — every section floats up with a soft spring. */
import React from 'react';
import Animated, { FadeInDown } from 'react-native-reanimated';
import type { ViewStyle } from 'react-native';

export function Reveal({
  index = 0,
  children,
  style,
}: {
  index?: number;
  children: React.ReactNode;
  style?: ViewStyle;
}) {
  return (
    <Animated.View
      entering={FadeInDown.delay(70 * index)
        .springify()
        .damping(18)
        .stiffness(160)}
      style={style}
    >
      {children}
    </Animated.View>
  );
}
