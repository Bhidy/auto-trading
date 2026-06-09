import React from 'react';
import { ScrollView, View } from 'react-native';
import { Text } from './Text';
import { DeltaPill } from './DeltaPill';
import { GlassCard } from './GlassCard';
import { Skeleton } from './Skeleton';
import { useQuotes } from '@/api/hooks';
import { MARKET_INDICES } from '@/lib/constants';
import { price } from '@/lib/format';

const NAMES: Record<string, string> = { SPY: 'S&P 500', QQQ: 'Nasdaq 100', DIA: 'Dow Jones', IWM: 'Russell 2000' };

/** Horizontally scrolling index quotes — floating glass chips. */
export function IndexStrip() {
  const { data, isLoading } = useQuotes(MARKET_INDICES);

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={{ gap: 10, paddingVertical: 6, paddingHorizontal: 2 }}
    >
      {MARKET_INDICES.map((sym) => {
        const q = data?.[sym];
        return (
          <GlassCard key={sym} padded={13} rounded="md" style={{ minWidth: 136 }}>
            <View style={{ gap: 6 }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <Text variant="overline" color="teal">
                  {sym}
                </Text>
                <Text variant="caption" dim numberOfLines={1} style={{ maxWidth: 72 }}>
                  {NAMES[sym]}
                </Text>
              </View>
              {isLoading || !q ? (
                <Skeleton width={86} height={20} />
              ) : (
                <>
                  <Text variant="monoL">${price(q.price)}</Text>
                  <DeltaPill value={q.changePct} size="sm" filled={false} />
                </>
              )}
            </View>
          </GlassCard>
        );
      })}
    </ScrollView>
  );
}
