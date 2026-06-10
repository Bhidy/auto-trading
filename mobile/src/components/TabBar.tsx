import React from 'react';
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Animated, { useAnimatedStyle, withSpring } from 'react-native-reanimated';
import { PressableScale } from './PressableScale';
import { Text } from './Text';
import { Icon, type IconName } from './Icon';
import { useTheme } from '@/theme/ThemeProvider';
import { cardShadow, radius } from '@/theme/tokens';
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

function TabItem({ route, focused, onPress }: { route: TabRoute; focused: boolean; onPress: () => void }) {
  const { palette } = useTheme();
  const meta = TAB_META[route.name] ?? { label: route.name, icon: 'home' as IconName };

  const lift = useAnimatedStyle(() => ({
    transform: [{ scale: withSpring(focused ? 1.05 : 1, { damping: 15, stiffness: 220 }) }],
  }));

  return (
    <PressableScale scaleTo={0.9} onPress={onPress} style={{ flex: 1, alignItems: 'center' }}>
      <Animated.View style={[{ alignItems: 'center', gap: 3, paddingVertical: 7, width: '100%' }, lift]}>
        <View
          style={{
            width: 50,
            height: 30,
            borderRadius: 15,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: focused ? palette.tealSoft : 'transparent',
          }}
        >
          <Icon
            name={meta.icon}
            size={20}
            color={focused ? palette.teal : palette.muted}
            strokeWidth={focused ? 2.2 : 1.8}
          />
        </View>
        <Text
          style={{
            color: focused ? palette.teal : palette.muted,
            fontSize: 9.5,
            fontFamily: focused ? 'PlusJakartaSans_700Bold' : 'PlusJakartaSans_600SemiBold',
            letterSpacing: 0.2,
          }}
        >
          {meta.label}
        </Text>
      </Animated.View>
    </PressableScale>
  );
}

/** Floating white dock — flat, hairline border, soft diffuse shadow (Design 3.0). */
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
          flexDirection: 'row',
          paddingVertical: 4,
          paddingHorizontal: 6,
          borderRadius: radius.xl,
          backgroundColor: palette.surface,
          borderWidth: 1,
          borderColor: palette.line,
          ...cardShadow(scheme),
          shadowOpacity: scheme === 'light' ? 0.10 : 0.45,
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
      </View>
    </View>
  );
}
