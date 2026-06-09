import React, { useMemo } from 'react';
import { View } from 'react-native';
import { router } from 'expo-router';
import { Screen } from '@/components/Screen';
import { ScreenHeader } from '@/components/ScreenHeader';
import { Card } from '@/components/Card';
import { GlassCard } from '@/components/GlassCard';
import { Reveal } from '@/components/Reveal';
import { Text } from '@/components/Text';
import { Tag } from '@/components/Tag';
import { ClockPill } from '@/components/ClockPill';
import { DeltaPill } from '@/components/DeltaPill';
import { PortfolioCard } from '@/components/PortfolioCard';
import { PressableScale } from '@/components/PressableScale';
import { Skeleton } from '@/components/Skeleton';
import { Icon } from '@/components/Icon';
import { Sparkline } from '@/charts/Sparkline';
import { useEquityHistory, useOverview } from '@/api/hooks';
import { useTheme } from '@/theme/ThemeProvider';
import { currency, percent } from '@/lib/format';
import { haptic } from '@/lib/haptics';
import { fonts } from '@/theme/typography';

export default function Portfolios() {
  const { palette } = useTheme();
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
      dayPnlPct: prev > 0 ? (dayPnl / prev) * 100 : 0,
      totalReturnPct: initial > 0 ? ((equity - initial) / initial) * 100 : 0,
      positions: overview.reduce((s, p) => s + (p.positions || 0), 0),
    };
  }, [overview]);

  const spark = (allEq?.history ?? []).map((p) => p.equity).filter((v) => isFinite(v));

  return (
    <Screen refreshing={isRefetching} onRefresh={refetch}>
      <ScreenHeader title="Portfolios" eyebrow="The book" right={<ClockPill />} />

      <View style={{ gap: 14 }}>
        {/* Aggregate book */}
        <Reveal index={0}>
        <PressableScale
          scaleTo={0.98}
          onPress={() => {
            haptic.light();
            router.push('/portfolio/all');
          }}
        >
          <GlassCard glow style={{ gap: 14 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
              <Text variant="overline" dim>
                All portfolios
              </Text>
              <Tag label="Aggregate" tone="accent" />
            </View>
            {!agg ? (
              <Skeleton width={220} height={34} />
            ) : (
              <View style={{ flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' }}>
                <View style={{ gap: 6 }}>
                  <Text variant="monoXL" style={{ fontFamily: fonts.serif, fontSize: 34, lineHeight: 40 }}>
                    {currency(agg.equity, { cents: false })}
                  </Text>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                    <DeltaPill value={agg.dayPnlPct} size="sm" />
                    <Text variant="caption" dim>
                      today · {percent(agg.totalReturnPct, { signed: true })} inception · {agg.positions} positions
                    </Text>
                  </View>
                </View>
                {spark.length > 2 && <Sparkline data={spark} width={92} height={40} />}
              </View>
            )}
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <Text variant="label" color="teal">
                Open the combined book
              </Text>
              <Icon name="chevron-right" size={13} color={palette.teal} />
            </View>
          </GlassCard>
        </PressableScale>
        </Reveal>

        {/* Individual strategies */}
        {isLoading && (
          <View style={{ gap: 14 }}>
            {[0, 1, 2].map((i) => (
              <Card key={i} style={{ gap: 10 }}>
                <Skeleton width={170} height={18} />
                <Skeleton width="100%" height={72} rounded={12} />
              </Card>
            ))}
          </View>
        )}
        {overview?.map((p, i) => (
          <Reveal key={p.id} index={1 + i}>
            <PortfolioCard data={p} />
          </Reveal>
        ))}
      </View>
    </Screen>
  );
}
