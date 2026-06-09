import React, { useMemo } from 'react';
import { ScrollView, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Screen } from '@/components/Screen';
import { Text } from '@/components/Text';
import { Tag } from '@/components/Tag';
import { DeltaPill } from '@/components/DeltaPill';
import { Skeleton } from '@/components/Skeleton';
import { Reveal } from '@/components/Reveal';
import { GradientText } from '@/components/GradientText';
import { Wordmark } from '@/components/Wordmark';
import { IndexStrip } from '@/components/IndexStrip';
import { CompactPortfolioCard } from '@/components/PortfolioCard';
import { Sparkline } from '@/charts/Sparkline';
import { useEquityHistory, useOverview } from '@/api/hooks';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';
import { currency, percent, signedCurrency } from '@/lib/format';

export default function Home() {
  const { palette } = useTheme();
  const insets = useSafeAreaInsets();
  const { width: screenW } = useWindowDimensions();
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
      live: overview.every((p) => p.liveConnected),
    };
  }, [overview]);

  const spark = (allEq?.history ?? []).map((p) => p.equity).filter((v) => isFinite(v));
  const sparkUp = (agg?.dayPnlPct ?? 0) >= 0;

  return (
    <Screen refreshing={isRefetching} onRefresh={refetch}>

      {/* ── MINIMAL HEADER ── */}
      <View
        style={{
          paddingTop: insets.top + 12,
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 4,
        }}
      >
        <Wordmark size={22} />
        {agg && (
          <Tag
            label={agg.live ? 'All systems live' : 'Synced'}
            tone={agg.live ? 'live' : 'neutral'}
            live={agg.live}
          />
        )}
      </View>

      <View>
        {/* ── HERO: CENTERED EQUITY ── */}
        <Reveal index={0}>
          <View style={{ alignItems: 'center', paddingTop: 32, paddingBottom: 8, gap: 14 }}>
            <Text variant="overline" dim style={{ letterSpacing: 2.5 }}>
              TOTAL PORTFOLIO
            </Text>
            {isLoading || !agg ? (
              <View style={{ gap: 12, alignItems: 'center' }}>
                <Skeleton width={260} height={68} rounded={14} />
                <Skeleton width={180} height={22} rounded={8} />
              </View>
            ) : (
              <>
                <GradientText
                  text={currency(agg.equity, { cents: false })}
                  style={{
                    fontFamily: fonts.serif,
                    fontSize: 62,
                    lineHeight: 68,
                    letterSpacing: -2,
                    textAlign: 'center',
                  }}
                />
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                  <DeltaPill value={agg.dayPnlPct} />
                  <Text variant="body" dim>
                    {signedCurrency(agg.dayPnl)} today
                  </Text>
                </View>
                <Text variant="caption" dim style={{ marginTop: -4 }}>
                  {percent(agg.totalReturnPct, { signed: true, digits: 2 })} since inception
                </Text>
              </>
            )}
          </View>
        </Reveal>

        {/* ── AGGREGATE EQUITY SPARKLINE (edge-to-edge) ── */}
        <Reveal index={1}>
          <View style={{ marginHorizontal: -18, marginTop: 12, marginBottom: 44 }}>
            {spark.length > 2 ? (
              <Sparkline
                data={spark}
                width={screenW}
                height={96}
                color={sparkUp ? palette.up : palette.down}
                strokeWidth={2.5}
              />
            ) : (
              <View style={{ height: 96 }} />
            )}
          </View>
        </Reveal>

        {/* ── YOUR STRATEGIES ── */}
        <Reveal index={2}>
          <View style={{ gap: 16, marginBottom: 44 }}>
            <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' }}>
              <Text variant="overline" dim>YOUR STRATEGIES</Text>
              <Text variant="caption" dim>3 autonomous books</Text>
            </View>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ gap: 12, paddingRight: 18 }}
              style={{ marginHorizontal: -18, paddingLeft: 18 }}
            >
              {isLoading
                ? [0, 1, 2].map((i) => (
                    <Skeleton key={i} width={226} height={172} rounded={20} />
                  ))
                : overview?.map((p) => <CompactPortfolioCard key={p.id} data={p} />)}
            </ScrollView>
          </View>
        </Reveal>

        {/* ── US MARKETS ── */}
        <Reveal index={3}>
          <View style={{ gap: 16, marginBottom: 44 }}>
            <Text variant="overline" dim>US MARKETS</Text>
            <View style={{ marginHorizontal: -18 }}>
              <View style={{ paddingHorizontal: 16 }}>
                <IndexStrip />
              </View>
            </View>
          </View>
        </Reveal>

        {/* ── FOOTER ── */}
        <Text variant="caption" dim align="center" style={{ marginBottom: 8 }}>
          Paper trading · autonomous · audited daily
        </Text>
      </View>
    </Screen>
  );
}
