import React from 'react';
import { View, type ViewProps } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useTheme } from '@/theme/ThemeProvider';
import { radius, space } from '@/theme/tokens';

interface Props extends ViewProps {
  padded?: boolean | number;
  elevated?: boolean;
  inset?: boolean;
  rounded?: keyof typeof radius;
}

/**
 * Standard surface — translucent glass tint (no blur cost), gradient hairline,
 * specular top edge. Harmonizes with GlassCard across every screen.
 */
export function Card({ padded = true, elevated = false, inset = false, rounded = 'lg', style, children, ...rest }: Props) {
  const { palette, scheme } = useTheme();
  const pad = padded === true ? space.lg : padded === false ? 0 : padded;

  return (
    <View
      {...rest}
      style={[
        elevated && {
          shadowColor: '#000000',
          shadowOffset: { width: 0, height: 12 },
          shadowOpacity: scheme === 'dark' ? 0.45 : 0.09,
          shadowRadius: 22,
          elevation: 8,
        },
        style,
      ]}
    >
      <View
        style={{
          backgroundColor: inset ? palette.surfaceInset : palette.glassFill,
          borderRadius: radius[rounded],
          borderWidth: 1,
          borderColor: palette.glassStroke,
          padding: pad,
          overflow: 'hidden',
        }}
      >
        <LinearGradient
          colors={[palette.glassHighlight, 'rgba(255,255,255,0)']}
          style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1.5, opacity: 0.8 }}
        />
        {children}
      </View>
    </View>
  );
}
