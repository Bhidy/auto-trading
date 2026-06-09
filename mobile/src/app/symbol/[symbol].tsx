import React, { useMemo, useState } from 'react';
import { useWindowDimensions, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Screen } from '@/components/Screen';
import { Card } from '@/components/Card';
import { Text } from '@/components/Text';
import { Button } from '@/components/Button';
import { DeltaPill } from '@/components/DeltaPill';
import { Divider } from '@/components/Divider';
import { Icon } from '@/components/Icon';
import { PressableScale } from '@/components/PressableScale';
import { Skeleton } from '@/components/Skeleton';
import { StatTile } from '@/components/StatTile';
import { OrderTicket } from '@/components/OrderTicket';
import { Candlestick, type Bar } from '@/charts/Candlestick';
import { useBars, useNews, useQuotes } from '@/api/hooks';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';
import { CHART_PERIODS, type ChartPeriod } from '@/lib/constants';
import { compact, price, relativeTime, shortDate, timeOf } from '@/lib/format';
import { haptic } from '@/lib/haptics';

export default function SymbolDetail() {
  const params = useLocalSearchParams<{ symbol: string }>();
  const symbol = decodeURIComponent(params.symbol ?? 'SPY').toUpperCase();
  const { palette } = useTheme();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();

  const [period, setPeriod] = useState<ChartPeriod>('3M');
  const [scrubBar, setScrubBar] = useState<Bar | null>(null);
  const [ticketOpen, setTicketOpen] = useState(false);

  const { data: quotes, refetch, isRefetching } = useQuotes([symbol]);
  const { data: bars, isLoading: barsLoading } = useBars(symbol, period);
  const { data: news } = useNews();
  const quote = quotes?.[symbol];

  const symbolNews = useMemo(
    () => (news ?? []).filter((n) => !n.symbols?.length || n.symbols.includes(symbol)).slice(0, 6),
    [news, symbol],
  );

  const chartBars: Bar[] = useMemo(
    () => (bars ?? []).map((b) => ({ t: b.t, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v })),
    [bars],
  );

  const chartWidth = width - 36 - 32;
  const intraday = period === '1D' || period === '1W';

  return (
    <Screen refreshing={isRefetching} onRefresh={refetch} padded={false}>
      {/* Top bar */}
      <View
        style={{
          paddingTop: insets.top + 8,
          paddingHorizontal: 14,
          paddingBottom: 10,
          flexDirection: 'row',
          alignItems: 'center',
          gap: 10,
        }}
      >
        <PressableScale
          onPress={() => {
            haptic.select();
            if (router.canGoBack()) router.back();
            else router.replace('/markets');
          }}
          style={{
            width: 38,
            height: 38,
            borderRadius: 19,
            backgroundColor: palette.surface,
            borderWidth: 1,
            borderColor: palette.line,
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Icon name="chevron-left" size={16} strokeWidth={2.2} />
        </PressableScale>
        <View style={{ flex: 1 }}>
          <Text variant="display">{symbol}</Text>
        </View>
        <Button label="Trade" size="sm" onPress={() => setTicketOpen(true)} />
      </View>

      <View style={{ paddingHorizontal: 18, gap: 14 }}>
        {/* Quote hero + candles */}
        <Card elevated style={{ gap: 14 }}>
          <View style={{ gap: 4 }}>
            <Text variant="overline" dim>
              {scrubBar ? `${shortDate(scrubBar.t)}${intraday ? ` · ${timeOf(scrubBar.t)}` : ''}` : 'Last price'}
            </Text>
            {scrubBar ? (
              <View style={{ gap: 4 }}>
                <Text variant="monoXL" style={{ fontSize: 32, lineHeight: 38 }}>
                  ${price(scrubBar.c)}
                </Text>
                <Text variant="caption" dim style={{ fontFamily: fonts.mono }}>
                  O {price(scrubBar.o)}  H {price(scrubBar.h)}  L {price(scrubBar.l)}  V {compact(scrubBar.v)}
                </Text>
              </View>
            ) : quote ? (
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
                <Text variant="monoXL" style={{ fontSize: 32, lineHeight: 38 }}>
                  ${price(quote.price)}
                </Text>
                <DeltaPill value={quote.changePct} />
              </View>
            ) : (
              <Skeleton width={200} height={34} />
            )}
          </View>

          {barsLoading ? (
            <Skeleton width="100%" height={230} rounded={12} />
          ) : chartBars.length > 1 ? (
            <Candlestick bars={chartBars} width={chartWidth} height={230} onScrub={(b) => setScrubBar(b)} />
          ) : (
            <View style={{ height: 230, alignItems: 'center', justifyContent: 'center', gap: 4 }}>
              <Text variant="bodyStrong">No bars for this range</Text>
              <Text variant="caption" dim>
                {intraday ? 'Market data resumes with the next session.' : 'Try another period.'}
              </Text>
            </View>
          )}

          <View style={{ flexDirection: 'row', backgroundColor: palette.surfaceInset, borderRadius: 999, padding: 3 }}>
            {CHART_PERIODS.map((p) => (
              <PressableScale
                key={p}
                scaleTo={0.94}
                onPress={() => {
                  haptic.select();
                  setPeriod(p);
                  setScrubBar(null);
                }}
                style={{
                  flex: 1,
                  alignItems: 'center',
                  paddingVertical: 7,
                  borderRadius: 999,
                  backgroundColor: p === period ? palette.surface : 'transparent',
                  borderWidth: p === period ? 1 : 0,
                  borderColor: palette.line,
                }}
              >
                <Text variant="label" style={{ color: p === period ? palette.ink : palette.muted, fontSize: 12 }}>
                  {p}
                </Text>
              </PressableScale>
            ))}
          </View>
        </Card>

        {/* Session stats */}
        <Card style={{ gap: 12 }}>
          <Text variant="subtitle">Session</Text>
          <View style={{ flexDirection: 'row' }}>
            <StatTile label="Open" style={{ flex: 1 }}>
              <Text variant="monoL">{quote?.open != null ? `$${price(quote.open)}` : '—'}</Text>
            </StatTile>
            <StatTile label="High" style={{ flex: 1 }}>
              <Text variant="monoL" color="up">
                {quote?.high != null ? `$${price(quote.high)}` : '—'}
              </Text>
            </StatTile>
            <StatTile label="Low" style={{ flex: 1 }}>
              <Text variant="monoL" color="down">
                {quote?.low != null ? `$${price(quote.low)}` : '—'}
              </Text>
            </StatTile>
          </View>
          <View style={{ flexDirection: 'row' }}>
            <StatTile label="Volume" style={{ flex: 1 }}>
              <Text variant="monoL">{compact(quote?.volume ?? null)}</Text>
            </StatTile>
            <StatTile label="Bid" style={{ flex: 1 }}>
              <Text variant="monoL">{quote?.bid != null && quote.bid > 0 ? `$${price(quote.bid)}` : '—'}</Text>
            </StatTile>
            <StatTile label="Ask" style={{ flex: 1 }}>
              <Text variant="monoL">{quote?.ask != null && quote.ask > 0 ? `$${price(quote.ask)}` : '—'}</Text>
            </StatTile>
          </View>
        </Card>

        {/* Symbol wire */}
        {symbolNews.length > 0 && (
          <Card padded={false} style={{ paddingHorizontal: 16, paddingVertical: 6 }}>
            <View style={{ paddingVertical: 12 }}>
              <Text variant="subtitle">On the wire</Text>
            </View>
            <Divider />
            {symbolNews.map((n, i) => (
              <View key={n.id ?? i}>
                {i > 0 && <Divider />}
                <View style={{ paddingVertical: 12, gap: 4 }}>
                  <Text variant="bodyStrong" numberOfLines={2}>
                    {n.headline}
                  </Text>
                  <View style={{ flexDirection: 'row', gap: 8 }}>
                    <Text variant="caption" color="teal">
                      {n.source ?? n.author ?? 'Wire'}
                    </Text>
                    <Text variant="caption" dim>
                      {n.created_at ? relativeTime(n.created_at) : ''}
                    </Text>
                  </View>
                </View>
              </View>
            ))}
          </Card>
        )}
      </View>

      <OrderTicket visible={ticketOpen} onClose={() => setTicketOpen(false)} symbol={symbol} lastPrice={quote?.price} />
    </Screen>
  );
}
