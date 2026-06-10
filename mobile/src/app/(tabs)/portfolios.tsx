import React, { useMemo } from 'react';
import { View } from 'react-native';
import { router } from 'expo-router';
import { Screen } from '@/components/Screen';
import { PageHeader } from '@/components/PageHeader';
import { Text } from '@/components/Text';
import { Tag } from '@/components/Tag';
import { DeltaPill } from '@/components/DeltaPill';
import { PortfolioCard } from '@/components/PortfolioCard';
import { PressableScale } from '@/components/PressableScale';
import { Skeleton } from '@/components/Skeleton';
import { Icon } from '@/components/Icon';
import { Sparkline } from '@/charts/Sparkline';
import { useEquityHistory, useOverview } from '@/api/hooks';
import { useTheme } from '@/theme/ThemeProvider';
import { cardShadow, radius } from '@/theme/tokens';
import { currency, percent, signedCurrency } from '@/lib/format';
import { haptic } from '@/lib/haptics';
import { fonts } from '@/theme/typography';

export default function Portfolios() {
  const { palette, scheme } = useTheme();
  const { data: overview, isLoading, refetch, isRefetching } = useOverview();
  const { data: allEq } = useEquityHistory('all', '3M');

  const agg = useMemo(() => {
    if (!overview?.length) return null;
    const equity = overview.reduce((s, p) => s + (p.equity || 0), 0);
    const dayPnl = overview.reduce((s, p) => s + (p.dayPnl || 0), 0);
    const initial = overview.reduce((s, p) => s + (p.initialCapital || 0), 0);
    const prev = equity - dayPnl;
    return {
      equity,
      dayPnl,
      dayPnlPct: prev > 0 ? (dayPnl / prev) * 100 : 0,
      totalReturnPct: initial > 0 ? ((equity - initial) / initial) * 100 : 0,
      positions: overview.reduce((s, p) => s + (p.positions || 0), 0),
    };
  }, [overview]);

  const spark = (allEq?.history ?? []).map((p) => p.equity).filter((v) => isFinite(v));

  return (
    <Screen
      padded={false}
      ambient={false}
      refreshing={isRefetching}
      onRefresh={refetch}
      contentContainerStyle={{ paddingBottom: 130, paddingHorizontal: 18 }}
    >
      <PageHeader title="Portfolios" sub="Three autonomous books" />

      <View style={{ gap: 14 }}>

        {/* ── AGGREGATE CARD ── */}
        <PressableScale
          scaleTo={0.98}
          onPress={() => {
            haptic.light();
            router.push('/portfolio/all');
          }}
        >
          <View
            style={{
              backgroundColor: palette.contrast,
              borderRadius: radius.xl,
              padding: 18,
              gap: 14,
            }}
          >
            <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
              <Text style={{ fontFamily: fonts.uiSemibold, fontSize: 12.5, color: palette.contrastMuted, letterSpacing: 0.8 }}>
                ALL PORTFOLIOS
              </Text>
              <Tag label="Aggregate" tone="accent" />
            </View>

            {!agg ? (
              <View style={{ gap: 10 }}>
                <Skeleton width={200} height={38} rounded={10} />
                <Skeleton width={160} height={18} rounded={6} />
              </View>
            ) : (
              <View style={{ flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' }}>
                <View style={{ gap: 6, flex: 1 }}>
                  <Text
                    style={{
                      fontFamily: fonts.uiExtra,
                      fontSize: 34,
                      lineHeight: 40,
                      letterSpacing: -1,
                      color: palette.contrastInk,
                    }}
                  >
                    {currency(agg.equity, { cents: false })}
                  </Text>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <DeltaPill value={agg.dayPnlPct} size="sm" />
                    <Text style={{ fontFamily: fonts.uiMedium, fontSize: 12, color: palette.contrastMuted }}>
                      {signedCurrency(agg.dayPnl, { compact: true })} ·{' '}
                      {percent(agg.totalReturnPct, { signed: true })} inception · {agg.positions} pos
                    </Text>
                  </View>
                </View>
                {spark.length > 2 && (
                  <Sparkline data={spark} width={96} height={42} color="#FF8A3D" strokeWidth={2} fill={false} />
                )}
              </View>
            )}

            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
              <Text style={{ fontFamily: fonts.uiSemibold, fontSize: 12.5, color: palette.contrastInk }}>
                Open the combined book
              </Text>
              <Icon name="chevron-right" size={12} color={palette.contrastInk} strokeWidth={2.4} />
            </View>
          </View>
        </PressableScale>

        {/* ── INDIVIDUAL STRATEGIES ── */}
        <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', marginTop: 6 }}>
          <Text style={{ fontFamily: fonts.uiBold, fontSize: 15, letterSpacing: -0.2, color: palette.ink }}>
            Strategies
          </Text>
          <Text style={{ fontFamily: fonts.uiMedium, fontSize: 12.5, color: palette.muted }}>
            {overview?.length ?? 3} books
          </Text>
        </View>

        {isLoading
          ? [0, 1, 2].map((i) => <Skeleton key={i} width="100%" height={170} rounded={radius.xl} />)
          : overview?.map((p) => <PortfolioCard key={p.id} data={p} />)}

      </View>
    </Screen>
  );
}
