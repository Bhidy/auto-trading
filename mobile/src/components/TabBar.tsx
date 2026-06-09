import React from 'react';
import { Platform, View } from 'react-native';
import { BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Animated, { useAnimatedStyle, withSpring } from 'react-native-reanimated';
import { PressableScale } from './PressableScale';
import { Text } from './Text';
import { Icon, type IconName } from './Icon';
import { useTheme } from '@/theme/ThemeProvider';
import { radius } from '@/theme/tokens';
import { haptic } from '@/lib/haptics';

const TAB_META: Record<string, { label: string; icon: IconName }> = {
  home: { label: 'Home', icon: 'home' },
  portfolios: { label: 'Portfolios', icon: 'portfolios' },
  markets: { label: 'Markets', icon: 'markets' },
  orders: { label: 'Orders', icon: 'orders' },
  settings: { label: 'Settings', icon: 'settings' },
};

/** Minimal structural typing for the navigation props (avoids a direct dep on @react-navigation). */
interface TabRoute {
  key: string;
  name: string;
}
interface TabBarProps {
  state: { index: number; routes: TabRoute[] };
  navigation: {
    emit: (e: { type: 'tabPress'; target: string; canPreventDefault: true }) => { defaultPrevented: boolean };
    navigate: (name: string) => void;
  };
}

function TabItem({
  route,
  focused,
  onPress,
}: {
  route: TabRoute;
  focused: boolean;
  onPress: () => void;
}) {
  const { palette, scheme } = useTheme();
  const meta = TAB_META[route.name] ?? { label: route.name, icon: 'home' as IconName };
  const color = focused ? (scheme === 'dark' ? '#FFD9BD' : '#FFFFFF') : palette.muted;

  const lift = useAnimatedStyle(() => ({
    transform: [{ scale: withSpring(focused ? 1.06 : 1, { damping: 15, stiffness: 220 }) }],
  }));

  return (
    <PressableScale scaleTo={0.9} onPress={onPress} style={{ flex: 1, alignItems: 'center' }}>
      <Animated.View style={[{ alignItems: 'center', gap: 4, paddingVertical: 6, width: '100%' }, lift]}>
        <View
          style={{
            width: 52,
            height: 32,
            borderRadius: 16,
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'hidden',
          }}
        >
          {focused && (
            <LinearGradient
              colors={scheme === 'dark' ? ['#FF8A3D', '#E55A1F'] : ['#F26B1F', '#C9461A']}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
              style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, opacity: 0.92 }}
            />
          )}
          <Icon name={meta.icon} size={21} color={color} strokeWidth={focused ? 2.2 : 1.8} />
        </View>
        <Text
          variant="overline"
          style={{ color: focused ? palette.teal : palette.muted, fontSize: 9, letterSpacing: 0.8 }}
        >
          {meta.label}
        </Text>
      </Animated.View>
    </PressableScale>
  );
}

/** Floating liquid-glass dock with a glowing active pill. */
export function TabBar({ state, navigation }: TabBarProps) {
  const { palette, scheme } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View
      pointerEvents="box-none"
      style={{ position: 'absolute', left: 16, right: 16, bottom: Math.max(insets.bottom, 14) }}
    >
      <View
        style={{
          borderRadius: radius.xl,
          shadowColor: '#000',
          shadowOffset: { width: 0, height: 14 },
          shadowOpacity: scheme === 'dark' ? 0.55 : 0.16,
          shadowRadius: 26,
          elevation: 14,
        }}
      >
        <View style={{ borderRadius: radius.xl, overflow: 'hidden' }}>
          <BlurView
            intensity={Platform.OS === 'android' ? 0 : 48}
            tint={scheme === 'dark' ? 'dark' : 'light'}
            style={{
              flexDirection: 'row',
              paddingVertical: 8,
              paddingHorizontal: 6,
              backgroundColor: Platform.OS === 'android' ? palette.surface : palette.glassFill,
            }}
          >
            {state.routes.map((route, index) => (
              <TabItem
                key={route.key}
                route={route}
                focused={state.index === index}
                onPress={() => {
                  haptic.select();
                  const event = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
                  if (state.index !== index && !event.defaultPrevented) navigation.navigate(route.name);
                }}
              />
            ))}
          </BlurView>
          <View
            pointerEvents="none"
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              borderRadius: radius.xl,
              borderWidth: 1,
              borderColor: palette.glassStroke,
            }}
          />
          <LinearGradient
            colors={[palette.glassHighlight, 'rgba(255,255,255,0)']}
            style={{ position: 'absolute', top: 0, left: 16, right: 16, height: 1.5, opacity: 0.8 }}
          />
        </View>
      </View>
    </View>
  );
}
