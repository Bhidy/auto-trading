import React from 'react';
import { ScrollView, View } from 'react-native';
import { router } from 'expo-router';
import { Screen } from '@/components/Screen';
import { ScreenHeader } from '@/components/ScreenHeader';
import { Card } from '@/components/Card';
import { GlassCard } from '@/components/GlassCard';
import { Reveal } from '@/components/Reveal';
import { Text } from '@/components/Text';
import { ClockPill } from '@/components/ClockPill';
import { IndexStrip } from '@/components/IndexStrip';
import { QuoteRow } from '@/components/QuoteRow';
import { Divider } from '@/components/Divider';
import { Skeleton } from '@/components/Skeleton';
import { PressableScale } from '@/components/PressableScale';
import { useMovers, useNews, useQuotes, useSectors } from '@/api/hooks';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';
import { radius } from '@/theme/tokens';
import { DEFAULT_WATCHLIST, SECTOR_ETFS } from '@/lib/constants';
import { percent, relativeTime } from '@/lib/format';
import { haptic } from '@/lib/haptics';

export default function Markets() {
  const { palette } = useTheme();
  const { data: quotes, refetch, isRefetching } = useQuotes(DEFAULT_WATCHLIST);
  const { data: sectors } = useSectors();
  const { data: movers } = useMovers(5);
  const { data: news } = useNews();

  const goSymbol = (s: string) => router.push(`/symbol/${encodeURIComponent(s)}`);

  return (
    <Screen refreshing={isRefetching} onRefresh={refetch}>
      <ScreenHeader title="Market Pulse" eyebrow="US markets" right={<ClockPill />} />

      <View style={{ gap: 24 }}>

        {/* ── INDEX OVERVIEW ── */}
        <Reveal index={0}>
          <View style={{ marginHorizontal: -18 }}>
            <View style={{ paddingHorizontal: 16 }}>
              <IndexStrip />
            </View>
          </View>
        </Reveal>

        {/* ── WATCHLIST ── */}
        <Reveal index={1}>
          <Card padded={false} style={{ paddingHorizontal: 16, paddingVertical: 4 }}>
            <View
              style={{
                flexDirection: 'row',
                justifyContent: 'space-between',
                alignItems: 'center',
                paddingVertical: 14,
              }}
            >
              <Text variant="subtitle">Watchlist</Text>
              <Text variant="caption" dim>live · 15s</Text>
            </View>
            <Divider />
            {DEFAULT_WATCHLIST.map((s, i) => (
              <View key={s}>
                {i > 0 && <Divider />}
                <QuoteRow symbol={s} quote={quotes?.[s]} onPress={() => goSymbol(s)} />
              </View>
            ))}
          </Card>
        </Reveal>

        {/* ── SECTORS ── */}
        <Reveal index={2}>
          <View style={{ gap: 12 }}>
            <Text variant="overline" dim>Sector performance</Text>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ gap: 8, paddingVertical: 2 }}
            >
              {SECTOR_ETFS.map((s) => {
                const q = sectors?.[s.symbol];
                const up = (q?.changePct ?? 0) >= 0;
                return (
                  <PressableScale
                    key={s.symbol}
                    scaleTo={0.95}
                    onPress={() => {
                      haptic.select();
                      goSymbol(s.symbol);
                    }}
                    style={{
                      paddingHorizontal: 13,
                      paddingVertical: 9,
                      borderRadius: radius.pill,
                      backgroundColor: q
                        ? up
                          ? palette.upSoft
                          : palette.downSoft
                        : palette.surfaceInset,
                      borderWidth: 1,
                      borderColor: palette.line,
                      flexDirection: 'row',
                      gap: 7,
                      alignItems: 'center',
                    }}
                  >
                    <Text variant="label">{s.name}</Text>
                    {q ? (
                      <Text
                        variant="caption"
                        style={{
                          color: up ? palette.up : palette.down,
                          fontFamily: fonts.monoMedium,
                        }}
                      >
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
        </Reveal>

        {/* ── TODAY'S MOVERS ── */}
        <Reveal index={3}>
          <GlassCard style={{ gap: 16 }}>
            <Text variant="subtitle">{"Today's movers"}</Text>
            {!movers ? (
              <Skeleton width="100%" height={110} rounded={12} />
            ) : (
              <View style={{ flexDirection: 'row', gap: 16 }}>
                <View style={{ flex: 1, gap: 10 }}>
                  <Text variant="overline" color="up">Gainers</Text>
                  {movers.gainers.slice(0, 4).map((g) => (
                    <PressableScale
                      key={g.symbol}
                      onPress={() => goSymbol(g.symbol)}
                      style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}
                    >
                      <Text variant="bodyStrong">{g.symbol}</Text>
                      <Text variant="mono" color="up">
                        {percent(g.percent_change, { signed: true, digits: 1 })}
                      </Text>
                    </PressableScale>
                  ))}
                </View>
                <View style={{ width: 1, backgroundColor: palette.line }} />
                <View style={{ flex: 1, gap: 10 }}>
                  <Text variant="overline" color="down">Losers</Text>
                  {movers.losers.slice(0, 4).map((l) => (
                    <PressableScale
                      key={l.symbol}
                      onPress={() => goSymbol(l.symbol)}
                      style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}
                    >
                      <Text variant="bodyStrong">{l.symbol}</Text>
                      <Text variant="mono" color="down">
                        {percent(l.percent_change, { signed: true, digits: 1 })}
                      </Text>
                    </PressableScale>
                  ))}
                </View>
              </View>
            )}
          </GlassCard>
        </Reveal>

        {/* ── MARKET WIRE ── */}
        <Reveal index={4}>
          <Card padded={false} style={{ paddingHorizontal: 16, paddingVertical: 4 }}>
            <View style={{ paddingVertical: 14 }}>
              <Text variant="subtitle">Market wire</Text>
            </View>
            <Divider />
            {!news && (
              <View style={{ gap: 12, paddingVertical: 14 }}>
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} width="100%" height={52} rounded={10} />
                ))}
              </View>
            )}
            {news?.slice(0, 8).map((n, i) => (
              <View key={n.id ?? i}>
                {i > 0 && <Divider />}
                <View style={{ paddingVertical: 14, gap: 7 }}>
                  <Text variant="bodyStrong" numberOfLines={2}>
                    {n.headline}
                  </Text>
                  <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
                    {/* Source pill */}
                    <View
                      style={{
                        backgroundColor: palette.tealSoft,
                        paddingHorizontal: 7,
                        paddingVertical: 2,
                        borderRadius: 4,
                      }}
                    >
                      <Text
                        variant="overline"
                        color="teal"
                        style={{ letterSpacing: 0.5 }}
                      >
                        {n.source ?? n.author ?? 'Wire'}
                      </Text>
                    </View>
                    <Text variant="caption" dim>
                      {n.created_at ? relativeTime(n.created_at) : ''}
                    </Text>
                    {!!n.symbols?.length && (
                      <Text
                        variant="caption"
                        dim
                        numberOfLines={1}
                        style={{ flex: 1 }}
                      >
                        {n.symbols.slice(0, 3).join(' · ')}
                      </Text>
                    )}
                  </View>
                </View>
              </View>
            ))}
            {news && news.length === 0 && (
              <View style={{ paddingVertical: 22, alignItems: 'center' }}>
                <Text variant="caption" dim>No fresh headlines right now.</Text>
              </View>
            )}
          </Card>
        </Reveal>
      </View>
    </Screen>
  );
}
