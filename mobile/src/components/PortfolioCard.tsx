import React from 'react';
import { View } from 'react-native';
import { router } from 'expo-router';
import { LiveDot } from './LiveDot';
import { Text } from './Text';
import { PressableScale } from './PressableScale';
import { Icon } from './Icon';
import { Sparkline } from '@/charts/Sparkline';
import { useEquityHistory } from '@/api/hooks';
import { useTheme } from '@/theme/ThemeProvider';
import { portfolioVariant, radius, type CardVariant } from '@/theme/tokens';
import type { PortfolioOverview } from '@/api/types';
import { metaFor } from '@/lib/constants';
import { currency, percent, trendOf } from '@/lib/format';
import { haptic } from '@/lib/haptics';
import { fonts } from '@/theme/typography';

const SHORT_NAMES: Record<string, string> = {
  portfolio_1: 'Self-improving brain',
  portfolio_2: 'Capitol shadow',
  portfolio_3: 'Cautious sniper',
};

const SPARK_COLOR: Record<CardVariant, string> = {
  peach: '#E55A1F',
  contrast: '#FF8A3D',
  cream: '#C9461A',
};

/** Strategy card 3.0 — pastel peach / espresso / cream tiles (reference crypto-card style). */
export function PortfolioCard({ data }: { data: PortfolioOverview; index?: number }) {
  const { palette } = useTheme();
  const meta = metaFor(data.id);
  const variant: CardVariant = portfolioVariant[data.id] ?? 'peach';
  const { data: eq } = useEquityHistory(data.id as never, '3M');
  const [sparkW, setSparkW] = React.useState(0);
  const spark = (eq?.history ?? []).map((p) => p.equity).filter((v) => isFinite(v));

  const contrast = variant === 'contrast';
  const bg = contrast ? palette.contrast : variant === 'peach' ? palette.tintPeach : palette.tintCream;
  const ink = contrast ? palette.contrastInk : palette.ink;
  const mutedC = contrast ? palette.contrastMuted : palette.muted;
  const t = trendOf(data.dayPnlPct ?? 0);
  const deltaColor =
    t === 'up' ? (contrast ? '#7ED9A5' : palette.up) : t === 'down' ? (contrast ? '#FF9A8B' : palette.down) : mutedC;
  const sign = t === 'up' ? '+' : t === 'down' ? '−' : '';

  return (
    <PressableScale
      scaleTo={0.98}
      onPress={() => {
        haptic.light();
        router.push(`/portfolio/${data.id}`);
      }}
    >
      <View style={{ backgroundColor: bg, borderRadius: radius.xl, padding: 18, gap: 14 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 11 }}>
          <View
            style={{
              width: 38,
              height: 38,
              borderRadius: 19,
              backgroundColor: contrast ? 'rgba(255,244,236,0.12)' : palette.surface,
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Text style={{ fontFamily: fonts.uiExtra, fontSize: 13, color: ink }}>{meta.short}</Text>
          </View>
          <View style={{ flex: 1, gap: 1 }}>
            <Text variant="headline" numberOfLines={1} style={{ color: ink }}>
              {SHORT_NAMES[data.id] ?? meta.label}
            </Text>
            <Text variant="caption" numberOfLines={1} style={{ color: mutedC }}>
              {meta.tagline}
            </Text>
          </View>
          {data.liveConnected && <LiveDot size={7} color={contrast ? '#7ED9A5' : palette.up} />}
        </View>

        <View style={{ flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <View style={{ gap: 3 }}>
            <Text style={{ fontFamily: fonts.uiExtra, fontSize: 26, lineHeight: 31, letterSpacing: -0.7, color: ink }}>
              {currency(data.equity, { cents: false })}
            </Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 7 }}>
              <Text style={{ fontFamily: fonts.uiBold, fontSize: 12.5, color: deltaColor }}>
                {sign}
                {Math.abs(data.dayPnlPct ?? 0).toFixed(2)}% today
              </Text>
              <Text variant="caption" style={{ color: mutedC }}>
                {percent(data.totalReturn, { signed: true })} all-time
              </Text>
            </View>
          </View>
          <View style={{ alignItems: 'flex-end', gap: 1 }}>
            <Text style={{ fontFamily: fonts.uiExtra, fontSize: 17, color: ink }}>{data.positions}</Text>
            <Text variant="caption" style={{ color: mutedC }}>
              positions
            </Text>
          </View>
        </View>

        {spark.length > 2 && (
          <View style={{ marginHorizontal: -4 }} onLayout={(e) => setSparkW(e.nativeEvent.layout.width)}>
            {sparkW > 0 && (
              <Sparkline data={spark} width={sparkW} height={46} color={SPARK_COLOR[variant]} strokeWidth={2.2} fill={false} />
            )}
          </View>
        )}

        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
          <Text variant="label" style={{ color: contrast ? palette.contrastInk : palette.tealDark, fontSize: 12.5 }}>
            Open this book
          </Text>
          <Icon name="chevron-right" size={12} color={contrast ? palette.contrastInk : palette.tealDark} strokeWidth={2.4} />
        </View>
      </View>
    </PressableScale>
  );
}
