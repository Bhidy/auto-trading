/**
 * Liquid-glass surface — blur fill, gradient hairline, specular top edge, deep soft shadow.
 * The signature container of Design 2.0.
 */
import React from 'react';
import { Platform, View, type ViewProps } from 'react-native';
import { BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
import { useTheme } from '@/theme/ThemeProvider';
import { radius as radii, space } from '@/theme/tokens';

interface Props extends ViewProps {
  padded?: boolean | number;
  rounded?: keyof typeof radii;
  intensity?: number;
  glow?: boolean; // warm ambient glow shadow
}

export function GlassCard({ padded = true, rounded = 'lg', intensity, glow = false, style, children, ...rest }: Props) {
  const { palette, scheme } = useTheme();
  const pad = padded === true ? space.lg : padded === false ? 0 : padded;
  const r = radii[rounded];
  const dark = scheme === 'dark';

  return (
    <View
      {...rest}
      style={[
        {
          borderRadius: r,
          // Soft elevation + optional solar glow
          shadowColor: glow ? '#E55A1F' : '#000000',
          shadowOffset: { width: 0, height: glow ? 10 : 14 },
          shadowOpacity: glow ? 0.28 : dark ? 0.5 : 0.1,
          shadowRadius: glow ? 26 : 24,
          elevation: 10,
        },
        style,
      ]}
    >
      <View style={{ borderRadius: r, overflow: 'hidden' }}>
        {/* Blur + tint fill */}
        <BlurView
          intensity={intensity ?? (Platform.OS === 'android' ? 0 : dark ? 28 : 40)}
          tint={dark ? 'dark' : 'light'}
          style={{ backgroundColor: Platform.OS === 'android' ? palette.surface : palette.glassFill }}
        >
          {/* Specular top edge */}
          <LinearGradient
            colors={[palette.glassHighlight, 'rgba(255,255,255,0)']}
            style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1.5, opacity: 0.9 }}
          />
          <View style={{ padding: pad }}>{children}</View>
        </BlurView>
        {/* Gradient hairline border */}
        <View
          pointerEvents="none"
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            borderRadius: r,
            borderWidth: 1,
            borderColor: palette.glassStroke,
          }}
        />
      </View>
    </View>
  );
}
