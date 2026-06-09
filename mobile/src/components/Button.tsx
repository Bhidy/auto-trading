import React from 'react';
import { ActivityIndicator, View, type ViewStyle } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { PressableScale } from './PressableScale';
import { Text } from './Text';
import { useTheme } from '@/theme/ThemeProvider';
import { ctaShadow, radius } from '@/theme/tokens';
import { haptic } from '@/lib/haptics';

type Variant = 'primary' | 'ghost' | 'danger' | 'subtle';
type Size = 'sm' | 'md' | 'lg';

interface Props {
  label: string;
  onPress?: () => void;
  variant?: Variant;
  size?: Size;
  disabled?: boolean;
  loading?: boolean;
  icon?: React.ReactNode;
  full?: boolean;
  style?: ViewStyle;
}

/** Pill CTA — primary carries the solar gradient + glow; danger glows red. */
export function Button({ label, onPress, variant = 'primary', size = 'md', disabled, loading, icon, full, style }: Props) {
  const { palette, scheme } = useTheme();
  const height = size === 'lg' ? 56 : size === 'sm' ? 38 : 48;
  const paddingHorizontal = size === 'lg' ? 26 : size === 'sm' ? 14 : 20;

  const gradient: [string, string] | null =
    variant === 'primary'
      ? scheme === 'dark'
        ? ['#FF8A3D', '#E55A1F']
        : ['#F26B1F', '#C9461A']
      : variant === 'danger'
        ? ['#FB7185', '#E5484D']
        : null;

  const fg =
    variant === 'primary' || variant === 'danger' ? '#FFFFFF' : variant === 'subtle' ? palette.teal : palette.ink;

  const inner = (
    <View
      style={{
        height,
        paddingHorizontal,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
      }}
    >
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <>
          {icon}
          <Text variant={size === 'sm' ? 'label' : 'bodyStrong'} style={{ color: fg }}>
            {label}
          </Text>
        </>
      )}
    </View>
  );

  return (
    <PressableScale
      disabled={disabled || loading}
      onPress={() => {
        haptic.light();
        onPress?.();
      }}
      style={[
        {
          borderRadius: radius.pill,
          opacity: disabled ? 0.45 : 1,
          alignSelf: full ? 'stretch' : 'flex-start',
          overflow: 'visible',
        },
        (variant === 'primary' || variant === 'danger') && ctaShadow(),
        style,
      ]}
    >
      {gradient ? (
        <LinearGradient
          colors={gradient}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={{ borderRadius: radius.pill, overflow: 'hidden' }}
        >
          {inner}
        </LinearGradient>
      ) : (
        <View
          style={{
            borderRadius: radius.pill,
            overflow: 'hidden',
            backgroundColor: variant === 'subtle' ? palette.tealSoft : 'transparent',
            borderWidth: variant === 'ghost' ? 1 : 0,
            borderColor: palette.hairline,
          }}
        >
          {inner}
        </View>
      )}
    </PressableScale>
  );
}
