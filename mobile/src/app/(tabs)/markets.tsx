import React from 'react';
import { ScrollView, View } from 'react-native';
import { router } from 'expo-router';
import { Screen } from '@/components/Screen';
import { PageHeader } from '@/components/PageHeader';
import { Text } from '@/components/Text';
import { QuoteRow } from '@/components/QuoteRow';
import { Divider } from '@/components/Divider';
import { Skeleton } from '@/components/Skeleton';
import { PressableScale } from '@/components/PressableScale';
import { useMovers, useNews, useQuotes, useSectors } from '@/api/hooks';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';
import { cardShadow, radius } from '@/theme/tokens';
import { DEFAULT_WATCHLIST, MARKET_INDICES, SECTOR_ETFS } from '@/lib/constants';
import { percent, price, relativeTime } from '@/lib/format';
import { haptic } from '@/lib/haptics';

const INDEX_NAMES: Record<string, string> = {
  SPY: 'S&P 500', QQQ: 'Nasdaq', DIA: 'Dow', IWM: 'Russell',
};

export default function Markets() {
  const { palette, scheme } = useTheme();
  const { data: quotes, refetch, isRefetching } = useQuotes([...DEFAULT_WATCHLIST, ...MARKET_INDICES]);
  const { data: sectors } = useSectors();
  const { data: movers } = useMovers(5);
  const { data: news } = useNews();

  const goSymbol = (s: string) => router.push(`/symbol/${encodeURIComponent(s)}`);

  const flatCard = {
    backgroundColor: palette.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: palette.line,
    ...cardShadow(scheme),
  };

  return (
    <Screen
      padded={false}
      ambient={false}
      refreshing={isRefetching}
      onRefresh={refetch}
      contentContainerStyle={{ paddingBottom: 130, paddingHorizontal: 18 }}
    >
      <PageHeader title="Market pulse" sub="US equities" />

      <View style={{ gap: 20 }}>

        {/* ── INDEX CHIPS ── */}
        <View style={{ flexDirection: 'row', gap: 8 }}>
          {MARKET_INDICES.map((sym) => {
            const q = quotes?.[sym];
            const up = (q?.changePct ?? 0) >= 0;
            return (
              <PressableScale
                key={sym}
                scaleTo={0.96}
                onPress={() => { haptic.select(); goSymbol(sym); }}
                style={{ flex: 1, ...flatCard, padding: 12, gap: 5 }}
              >
                <Text style={{ fontFamily: fonts.uiBold, fontSize: 11, color: palette.teal }}>{sym}</Text>
                {!q ? (
                  <Skeleton width="100%" height={16} rounded={4} />
                ) : (
                  <>
                    <Text style={{ fontFamily: fonts.monoMedium, fontSize: 14, color: palette.ink, letterSpacing: -0.2 }}>
                      ${price(q.price)}
                    </Text>
                    <Text style={{ fontFamily: fonts.uiBold, fontSize: 11, color: up ? palette.up : palette.down }}>
                      {up ? '+' : '−'}{Math.abs(q.changePct ?? 0).toFixed(2)}%
                    </Text>
                  </>
                )}
              </PressableScale>
            );
          })}
        </View>

        {/* ── WATCHLIST ── */}
        <View>
          <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
            <Text style={{ fontFamily: fonts.uiBold, fontSize: 17, letterSpacing: -0.3, color: palette.ink }}>Watchlist</Text>
            <Text style={{ fontFamily: fonts.uiMedium, fontSize: 12, color: palette.muted }}>live · 15s</Text>
          </View>
          <View style={flatCard}>
            {DEFAULT_WATCHLIST.map((s, i) => (
              <View key={s} style={{ paddingHorizontal: 16 }}>
                {i > 0 && <Divider />}
                <QuoteRow symbol={s} quote={quotes?.[s]} onPress={() => goSymbol(s)} />
              </View>
            ))}
          </View>
        </View>

        {/* ── SECTORS ── */}
        <View>
          <Text style={{ fontFamily: fonts.uiBold, fontSize: 17, letterSpacing: -0.3, color: palette.ink, marginBottom: 12 }}>
            Sectors
          </Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingVertical: 2 }}>
            {SECTOR_ETFS.map((s) => {
              const q = sectors?.[s.symbol];
              const up = (q?.changePct ?? 0) >= 0;
              return (
                <PressableScale
                  key={s.symbol}
                  scaleTo={0.95}
                  onPress={() => { haptic.select(); goSymbol(s.symbol); }}
                  style={{
                    paddingHorizontal: 13,
                    paddingVertical: 9,
                    borderRadius: radius.pill,
                    backgroundColor: q ? (up ? palette.upSoft : palette.downSoft) : palette.surfaceInset,
                    borderWidth: 1,
                    borderColor: palette.line,
                    flexDirection: 'row',
                    gap: 7,
                    alignItems: 'center',
                  }}
                >
                  <Text style={{ fontFamily: fonts.uiSemibold, fontSize: 12, color: palette.ink }}>{s.name}</Text>
                  {q ? (
                    <Text style={{ fontFamily: fonts.monoMedium, fontSize: 11.5, color: up ? palette.up : palette.down }}>
                      {percent(q.changePct, { signed: true, digits: 1 })}
                    </Text>
                  ) : (
                    <Skeleton width={34} height={12} />
                  )}
                </PressableScale>
              );
            })}
          </ScrollView>
        </View>

        {/* ── TODAY'S MOVERS ── */}
        <View>
          <Text style={{ fontFamily: fonts.uiBold, fontSize: 17, letterSpacing: -0.3, color: palette.ink, marginBottom: 12 }}>
            {"Today's movers"}
          </Text>
          <View style={{ ...flatCard, padding: 16 }}>
            {!movers ? (
              <Skeleton width="100%" height={110} rounded={10} />
            ) : (
              <View style={{ flexDirection: 'row', gap: 16 }}>
                <View style={{ flex: 1, gap: 10 }}>
                  <Text style={{ fontFamily: fonts.uiBold, fontSize: 11, color: palette.up, letterSpacing: 0.6 }}>
                    GAINERS
                  </Text>
                  {movers.gainers.slice(0, 4).map((g) => (
                    <PressableScale
                      key={g.symbol}
                      onPress={() => goSymbol(g.symbol)}
                      style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}
                    >
                      <Text style={{ fontFamily: fonts.uiBold, fontSize: 13.5, color: palette.ink }}>{g.symbol}</Text>
                      <Text style={{ fontFamily: fonts.monoMedium, fontSize: 12.5, color: palette.up }}>
                        {percent(g.percent_change, { signed: true, digits: 1 })}
                      </Text>
                    </PressableScale>
                  ))}
                </View>
                <View style={{ width: 1, backgroundColor: palette.line }} />
                <View style={{ flex: 1, gap: 10 }}>
                  <Text style={{ fontFamily: fonts.uiBold, fontSize: 11, color: palette.down, letterSpacing: 0.6 }}>
                    LOSERS
                  </Text>
                  {movers.losers.slice(0, 4).map((l) => (
                    <PressableScale
                      key={l.symbol}
                      onPress={() => goSymbol(l.symbol)}
                      style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}
                    >
                      <Text style={{ fontFamily: fonts.uiBold, fontSize: 13.5, color: palette.ink }}>{l.symbol}</Text>
                      <Text style={{ fontFamily: fonts.monoMedium, fontSize: 12.5, color: palette.down }}>
                        {percent(l.percent_change, { signed: true, digits: 1 })}
                      </Text>
                    </PressableScale>
                  ))}
                </View>
              </View>
            )}
          </View>
        </View>

        {/* ── MARKET WIRE ── */}
        <View>
          <Text style={{ fontFamily: fonts.uiBold, fontSize: 17, letterSpacing: -0.3, color: palette.ink, marginBottom: 12 }}>
            Market wire
          </Text>
          <View style={flatCard}>
            {!news && (
              <View style={{ gap: 12, padding: 16 }}>
                {[0, 1, 2].map((i) => <Skeleton key={i} width="100%" height={52} rounded={10} />)}
              </View>
            )}
            {news?.slice(0, 8).map((n, i) => (
              <View key={n.id ?? i} style={{ paddingHorizontal: 16 }}>
                {i > 0 && <Divider />}
                <View style={{ paddingVertical: 14, gap: 6 }}>
                  <Text style={{ fontFamily: fonts.uiSemibold, fontSize: 13.5, color: palette.ink, lineHeight: 19 }} numberOfLines={2}>
                    {n.headline}
                  </Text>
                  <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
                    <View style={{ backgroundColor: palette.tealSoft, paddingHorizontal: 7, paddingVertical: 2, borderRadius: 4 }}>
                      <Text style={{ fontFamily: fonts.uiBold, fontSize: 10.5, color: palette.teal, letterSpacing: 0.5 }}>
                        {n.source ?? n.author ?? 'Wire'}
                      </Text>
                    </View>
                    <Text style={{ fontFamily: fonts.ui, fontSize: 11.5, color: palette.muted }}>
                      {n.created_at ? relativeTime(n.created_at) : ''}
                    </Text>
                    {!!n.symbols?.length && (
                      <Text style={{ fontFamily: fonts.uiMedium, fontSize: 11.5, color: palette.muted, flex: 1 }} numberOfLines={1}>
                        {n.symbols.slice(0, 3).join(' · ')}
                      </Text>
                    )}
                  </View>
                </View>
              </View>
            ))}
            {news && news.length === 0 && (
              <View style={{ paddingVertical: 22, alignItems: 'center' }}>
                <Text style={{ fontFamily: fonts.uiMedium, fontSize: 13, color: palette.muted }}>
                  No fresh headlines right now.
                </Text>
              </View>
            )}
          </View>
        </View>

      </View>
    </Screen>
  );
}
