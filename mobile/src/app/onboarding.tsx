/**
 * 3D onboarding — three slides over a living molten solar core.
 * The core's turbulence, tempo and glow morph as you swipe (genesis → discipline → compounding).
 */
import React, { useRef, useState } from 'react';
import {
  Dimensions,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  ScrollView,
  View,
} from 'react-native';
import { router } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { LinearGradient } from 'expo-linear-gradient';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Animated, { useAnimatedStyle, withSpring, withTiming } from 'react-native-reanimated';
import { Text } from '@/components/Text';
import { Button } from '@/components/Button';
import { Wordmark } from '@/components/Wordmark';
import { PressableScale } from '@/components/PressableScale';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { SolarCanvas } from '@/three/SolarCanvas';
import type { Mood } from '@/three/SolarSceneContent';
import { storage, KEYS } from '@/lib/storage';
import { haptic } from '@/lib/haptics';
import { fonts } from '@/theme/typography';

const { width: W } = Dimensions.get('window');

const SLIDES = [
  {
    eyebrow: 'The book',
    title: 'Three minds.\nOne living book.',
    body: 'Self-Improving Brain, Capitol Shadow and Cautious Sniper — three autonomous strategies trading a $300K paper book on real market data, end to end, with no human in the loop.',
  },
  {
    eyebrow: 'The discipline',
    title: 'Risk is the\nreligion.',
    body: 'Hardcoded loss limits, ATR stops, kill-switch drawdown protection and a walk-forward-gated learning loop. Every decision is logged, reconciled and auditable.',
  },
  {
    eyebrow: 'The edge',
    title: 'Watch the edge\ncompound.',
    body: 'Live equity curves, positions, fills, signals and market pulse — institutional-grade telemetry streamed to your pocket in real time.',
  },
] as const;

function Dot({ index, page }: { index: number; page: number }) {
  const active = index === page;
  const style = useAnimatedStyle(() => ({
    width: withSpring(active ? 26 : 7, { damping: 16, stiffness: 180 }),
    opacity: withTiming(active ? 1 : 0.38, { duration: 200 }),
  }));
  return (
    <Animated.View
      style={[{ height: 7, borderRadius: 4, backgroundColor: '#FF8A3D' }, style]}
    />
  );
}

export default function Onboarding() {
  const insets = useSafeAreaInsets();
  const mood = useRef<Mood>({ progress: 0 });
  const scrollRef = useRef<ScrollView>(null);
  const [page, setPage] = useState(0);

  const finish = () => {
    haptic.success();
    storage.setBool(KEYS.onboarded, true).catch(() => {});
    router.replace('/home');
  };

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const x = e.nativeEvent.contentOffset.x;
    const p = Math.max(0, Math.min(2, x / W));
    mood.current.progress = p;
    const rounded = Math.round(p);
    if (rounded !== page) {
      setPage(rounded);
      haptic.select();
    }
  };

  const next = () => {
    if (page >= 2) {
      finish();
      return;
    }
    scrollRef.current?.scrollTo({ x: (page + 1) * W, animated: true });
  };

  const last = page === 2;

  return (
    <View style={{ flex: 1, backgroundColor: '#0A0403' }}>
      <StatusBar style="light" />

      {/* Living background */}
      <View style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}>
        <LinearGradient
          colors={['#2A1208', '#1A0A05', '#0A0403']}
          style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}
        />
        <ErrorBoundary fallback={<View style={{ flex: 1 }} />}>
          <SolarCanvas mood={mood} />
        </ErrorBoundary>
        {/* Legibility scrim over the lower half */}
        <LinearGradient
          colors={['rgba(10,4,3,0)', 'rgba(10,4,3,0.55)', 'rgba(10,4,3,0.92)']}
          locations={[0.35, 0.62, 1]}
          style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}
          pointerEvents="none"
        />
      </View>

      {/* Top bar */}
      <View
        style={{
          position: 'absolute',
          top: insets.top + 14,
          left: 24,
          right: 24,
          flexDirection: 'row',
          justifyContent: 'space-between',
          alignItems: 'center',
          zIndex: 10,
        }}
      >
        <Wordmark size={21} />
        {!last && (
          <PressableScale onPress={finish} style={{ paddingVertical: 6, paddingHorizontal: 4 }}>
            <Text variant="label" style={{ color: 'rgba(255,241,232,0.62)' }}>
              Skip
            </Text>
          </PressableScale>
        )}
      </View>

      {/* Slides */}
      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onScroll={onScroll}
        scrollEventThrottle={16}
        contentContainerStyle={{ alignItems: 'flex-end' }}
        style={{ flex: 1 }}
      >
        {SLIDES.map((s, i) => (
          <View
            key={i}
            style={{ width: W, paddingHorizontal: 26, paddingBottom: insets.bottom + 168, gap: 14 }}
          >
            <Text variant="overline" style={{ color: '#FF8A3D' }}>
              {s.eyebrow}
            </Text>
            <Text
              style={{ fontFamily: fonts.serif, fontSize: 42, lineHeight: 47, color: '#FFF1E8', letterSpacing: -0.4 }}
            >
              {s.title}
            </Text>
            <Text variant="body" style={{ color: 'rgba(255,241,232,0.72)', maxWidth: 330 }}>
              {s.body}
            </Text>
          </View>
        ))}
      </ScrollView>

      {/* Footer: dots + CTA */}
      <View
        style={{
          position: 'absolute',
          left: 26,
          right: 26,
          bottom: insets.bottom + 30,
          gap: 22,
          zIndex: 10,
        }}
      >
        <View style={{ flexDirection: 'row', gap: 6, alignItems: 'center' }}>
          {SLIDES.map((_, i) => (
            <Dot key={i} index={i} page={page} />
          ))}
        </View>
        <Button label={last ? 'Enter the terminal' : 'Continue'} size="lg" full onPress={next} />
      </View>
    </View>
  );
}
