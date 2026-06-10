import React, { useMemo, useState } from 'react';
import { View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Screen } from '@/components/Screen';
import { Text } from '@/components/Text';
import { Tag } from '@/components/Tag';
import { DeltaPill } from '@/components/DeltaPill';
import { Skeleton } from '@/components/Skeleton';
import { MoneyText } from '@/components/MoneyText';
import { FilterPills } from '@/components/FilterPills';
import { PortfolioCard } from '@/components/PortfolioCard';
import { LineChart } from '@/charts/LineChart';
import { useEquityHistory, useOverview, useQuotes } from '@/api/hooks';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';
import { cardShadow, radius } from '@/theme/tokens';
import { price, percent, signedCurrency } from '@/lib/format';
import { MARKET_INDICES, OWNER_FIRST_NAME } from '@/lib/constants';

const TIMEFRAMES = ['1D', '1W', '1M', '3M', '6M', '1Y'] as const;
type TF = (typeof TIMEFRAMES)[number];

const INDEX_NAMES: Record<string, string> = {
  SPY: 'S&P 500',
  QQQ: 'Nasdaq',
  DIA: 'Dow Jones',
  IWM: 'Russell 2K',
};

export default function Home() {
  const { palette, scheme } = useTheme();
  const insets = useSafeAreaInsets();
  const { width: screenW } = useWindowDimensions();
  const [tf, setTf] = useState<TF>('3M');

  const { data: overview, isLoading, refetch, isRefetching } = useOverview();
  const { data: eqHistory } = useEquityHistory('all', tf);
  const { data: quotes } = useQuotes(MARKET_INDICES);

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

  const chartData = (eqHistory?.history ?? []).map((p) => p.equity).filter((v) => isFinite(v));

  return (
    <Screen
      scroll
      padded={false}
      ambient={false}
      refreshing={isRefetching}
      onRefresh={refetch}
      contentContainerStyle={{ paddingBottom: 130 }}
    >
      {/* ── HEADER ── */}
      <View style={{ paddingHorizontal: 18, paddingTop: insets.top + 18, marginBottom: 22 }}>
        <View style={{ flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <View style={{ gap: 2 }}>
            <Text style={{ fontFamily: fonts.uiSemibold, fontSize: 13, color: palette.muted }}>
              Hello, {OWNER_FIRST_NAME} 👋
            </Text>
            <Text style={{ fontFamily: fonts.uiExtra, fontSize: 24, letterSpacing: -0.6, lineHeight: 30, color: palette.ink }}>
              Your portfolio
            </Text>
          </View>
          {agg && (
            <Tag
              label={agg.live ? 'Live' : 'Synced'}
              tone={agg.live ? 'live' : 'neutral'}
              live={agg.live}
              style={{ marginTop: 4 }}
            />
          )}
        </View>
      </View>

      {/* ── HERO BALANCE ── */}
      <View style={{ alignItems: 'center', gap: 8, paddingHorizontal: 18, marginBottom: 20 }}>
        <Text style={{ fontFamily: fonts.uiSemibold, fontSize: 12, color: palette.muted, letterSpacing: 1.2 }}>
          TOTAL VALUE
        </Text>
        {isLoading || !agg ? (
          <View style={{ gap: 10, alignItems: 'center' }}>
            <Skeleton width={240} height={62} rounded={14} />
            <Skeleton width={180} height={22} rounded={8} />
            <Skeleton width={120} height={16} rounded={6} />
          </View>
        ) : (
          <>
            <MoneyText value={agg.equity} size={54} />
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
              <DeltaPill value={agg.dayPnlPct} />
              <Text style={{ fontFamily: fonts.uiMedium, fontSize: 13.5, color: palette.muted }}>
                {signedCurrency(agg.dayPnl)} today
              </Text>
            </View>
            <Text style={{ fontFamily: fonts.ui, fontSize: 12.5, color: palette.muted }}>
              {percent(agg.totalReturnPct, { signed: true, digits: 2 })} all-time return
            </Text>
          </>
        )}
      </View>

      {/* ── HERO CHART (edge-to-edge) ── */}
      {chartData.length > 2 ? (
        <LineChart data={chartData} width={screenW} height={170} grid tooltip />
      ) : (
        <View
          style={{
            marginHorizontal: 18,
            height: 170,
            borderRadius: radius.lg,
            backgroundColor: palette.surfaceAlt,
          }}
        />
      )}

      {/* ── TIMEFRAME PILLS ── */}
      <View style={{ paddingHorizontal: 12, marginTop: 10, marginBottom: 28 }}>
        <FilterPills
          options={TIMEFRAMES}
          value={tf}
          onChange={(v) => setTf(v as TF)}
          stretch
        />
      </View>

      {/* ── YOUR STRATEGIES ── */}
      <View style={{ paddingHorizontal: 18, marginBottom: 28 }}>
        <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14 }}>
          <Text style={{ fontFamily: fonts.uiBold, fontSize: 17, letterSpacing: -0.3, color: palette.ink }}>
            Your strategies
          </Text>
          <Text style={{ fontFamily: fonts.uiMedium, fontSize: 12.5, color: palette.muted }}>
            3 autonomous books
          </Text>
        </View>
        <View style={{ gap: 12 }}>
          {isLoading
            ? [0, 1, 2].map((i) => <Skeleton key={i} width="100%" height={170} rounded={radius.xl} />)
            : overview?.map((p) => <PortfolioCard key={p.id} data={p} />)}
        </View>
      </View>

      {/* ── US MARKETS ── */}
      <View style={{ paddingHorizontal: 18 }}>
        <Text style={{ fontFamily: fonts.uiBold, fontSize: 17, letterSpacing: -0.3, color: palette.ink, marginBottom: 14 }}>
          US markets
        </Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
          {MARKET_INDICES.map((sym) => {
            const q = quotes?.[sym];
            const up = (q?.changePct ?? 0) >= 0;
            return (
              <View
                key={sym}
                style={{
                  width: '47.5%',
                  backgroundColor: palette.surface,
                  borderRadius: radius.lg,
                  borderWidth: 1,
                  borderColor: palette.line,
                  padding: 14,
                  gap: 6,
                  ...cardShadow(scheme),
                }}
              >
                <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                  <Text style={{ fontFamily: fonts.uiBold, fontSize: 11.5, color: palette.teal }}>{sym}</Text>
                  <Text style={{ fontFamily: fonts.ui, fontSize: 10.5, color: palette.muted }} numberOfLines={1}>
                    {INDEX_NAMES[sym]}
                  </Text>
                </View>
                {!q ? (
                  <Skeleton width={90} height={19} rounded={5} />
                ) : (
                  <>
                    <Text style={{ fontFamily: fonts.monoMedium, fontSize: 16, color: palette.ink, letterSpacing: -0.3 }}>
                      ${price(q.price)}
                    </Text>
                    <Text style={{ fontFamily: fonts.uiBold, fontSize: 12, color: up ? palette.up : palette.down }}>
                      {up ? '+' : '−'}
                      {Math.abs(q.changePct ?? 0).toFixed(2)}%
                    </Text>
                  </>
                )}
              </View>
            );
          })}
        </View>
      </View>
    </Screen>
  );
}
