import React from 'react';
import { View } from 'react-native';
import { router } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import { LiveDot } from './LiveDot';
import { GlassCard } from './GlassCard';
import { Text } from './Text';
import { Tag } from './Tag';
import { DeltaPill } from './DeltaPill';
import { PressableScale } from './PressableScale';
import { Icon, type IconName } from './Icon';
import { Sparkline } from '@/charts/Sparkline';
import { useEquityHistory } from '@/api/hooks';
import { useTheme } from '@/theme/ThemeProvider';
import type { PortfolioOverview } from '@/api/types';
import { metaFor } from '@/lib/constants';
import { currency, percent } from '@/lib/format';
import { haptic } from '@/lib/haptics';
import { fonts } from '@/theme/typography';

const ICONS: Record<string, IconName> = {
  portfolio_1: 'bolt',
  portfolio_2: 'globe',
  portfolio_3: 'markets',
};

/** Strategy tile 2.0 — glass, gradient identity chip, hero sparkline. */
export function PortfolioCard({ data }: { data: PortfolioOverview; index?: number }) {
  const { palette, scheme } = useTheme();
  const meta = metaFor(data.id);
  const { data: eq } = useEquityHistory(data.id as never, '3M');
  const [sparkW, setSparkW] = React.useState(0);
  const spark = (eq?.history ?? []).map((p) => p.equity).filter((v) => isFinite(v));
  const up = data.dayPnlPct >= 0;

  return (
    <PressableScale
      scaleTo={0.98}
      onPress={() => {
        haptic.light();
        router.push(`/portfolio/${data.id}`);
      }}
    >
      <GlassCard style={{ gap: 14 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 11 }}>
          <View style={{ width: 38, height: 38, borderRadius: 13, overflow: 'hidden' }}>
            <LinearGradient
              colors={scheme === 'dark' ? ['#FF8A3D', '#C9461A'] : ['#F26B1F', '#A33A14']}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
              style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}
            >
              <Icon name={ICONS[data.id] ?? 'bolt'} size={18} color="#FFF1E8" />
            </LinearGradient>
          </View>
          <View style={{ flex: 1, gap: 1 }}>
            <Text variant="headline">{meta.label}</Text>
            <Text variant="caption" dim numberOfLines={1}>
              {meta.tagline}
            </Text>
          </View>
          <Tag label={data.liveConnected ? 'Live' : 'Synced'} tone={data.liveConnected ? 'live' : 'neutral'} live={data.liveConnected} />
        </View>

        {spark.length > 2 && (
          <View style={{ marginHorizontal: -4 }} onLayout={(e) => setSparkW(e.nativeEvent.layout.width)}>
            {sparkW > 0 && (
              <Sparkline data={spark} width={sparkW} height={56} color={up ? palette.up : palette.down} strokeWidth={2.4} />
            )}
          </View>
        )}

        <View style={{ flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <View style={{ gap: 4 }}>
            <Text style={{ fontFamily: fonts.serif, fontSize: 30, lineHeight: 34, color: palette.ink }}>
              {currency(data.equity, { cents: false })}
            </Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <DeltaPill value={data.dayPnlPct} size="sm" />
              <Text variant="caption" dim>
                today · {percent(data.totalReturn, { signed: true })} all-time
              </Text>
            </View>
          </View>
          <View style={{ alignItems: 'flex-end', gap: 2 }}>
            <Text variant="monoL">{data.positions}</Text>
            <Text variant="overline" dim>
              positions
            </Text>
          </View>
        </View>
      </GlassCard>
    </PressableScale>
  );
}

/* ─── Compact card for the Home screen horizontal scroll ─── */

const CARD_W = 226;
const CONTENT_W = CARD_W - 32; // 16px padding each side

const STRATEGY_NAMES: Record<string, string> = {
  portfolio_1: 'Brain',
  portfolio_2: 'Capitol',
  portfolio_3: 'Sniper',
};

export function CompactPortfolioCard({ data }: { data: PortfolioOverview }) {
  const { palette, scheme } = useTheme();
  const meta = metaFor(data.id);
  const { data: eq } = useEquityHistory(data.id as never, '3M');
  const spark = (eq?.history ?? []).map((p) => p.equity).filter((v) => isFinite(v));
  const up = (data.dayPnlPct ?? 0) >= 0;
  // 3 % day = full bar; clamp 0–100
  const barPct = Math.min(100, (Math.abs(data.dayPnlPct ?? 0) / 3) * 100);
  const barW = Math.round((barPct / 100) * CONTENT_W);

  return (
    <PressableScale
      scaleTo={0.97}
      onPress={() => {
        haptic.light();
        router.push(`/portfolio/${data.id}`);
      }}
    >
      <GlassCard padded={false} rounded="lg" style={{ width: CARD_W }}>
        {/* Orange gradient accent — 3 px top strip */}
        <LinearGradient
          colors={scheme === 'dark' ? ['#FF8A3D', '#E55A1F'] : ['#F26B1F', '#C9461A']}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 0 }}
          style={{ height: 3 }}
        />

        <View style={{ padding: 16, gap: 12 }}>
          {/* Header: icon + name + live dot */}
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 9 }}>
            <View
              style={{
                width: 30,
                height: 30,
                borderRadius: 9,
                backgroundColor: palette.tealSoft,
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Icon name={ICONS[data.id] ?? 'bolt'} size={15} color={palette.teal} />
            </View>
            <Text variant="label" numberOfLines={1} style={{ flex: 1 }}>
              {STRATEGY_NAMES[data.id] ?? meta.short}
            </Text>
            {data.liveConnected && <LiveDot size={7} color={palette.up} />}
          </View>

          {/* Equity + delta */}
          <View style={{ gap: 5 }}>
            <Text
              style={{
                fontFamily: fonts.serif,
                fontSize: 27,
                lineHeight: 31,
                letterSpacing: -0.6,
                color: palette.ink,
              }}
            >
              {currency(data.equity, { cents: false })}
            </Text>
            <DeltaPill value={data.dayPnlPct} size="sm" />
          </View>

          {/* Performance bar — widest bar = best day */}
          <View style={{ gap: 5 }}>
            <View
              style={{
                height: 3,
                width: CONTENT_W,
                borderRadius: 2,
                backgroundColor: palette.surfaceInset,
                overflow: 'hidden',
              }}
            >
              {barW > 0 && (
                <View
                  style={{
                    height: 3,
                    width: barW,
                    borderRadius: 2,
                    backgroundColor: up ? palette.up : palette.down,
                  }}
                />
              )}
            </View>
            <Text variant="caption" dim style={{ fontSize: 10, letterSpacing: 0.3 }}>
              {up ? '↑ Gaining' : '↓ Declining'} today
            </Text>
          </View>
        </View>

        {/* Sparkline bleeds to card edges — no extra padding */}
        {spark.length > 2 && (
          <Sparkline
            data={spark}
            width={CARD_W}
            height={44}
            color={up ? palette.up : palette.down}
            strokeWidth={1.8}
          />
        )}
      </GlassCard>
    </PressableScale>
  );
}
