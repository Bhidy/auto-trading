import React from 'react';
import { View } from 'react-native';
import { Text } from './Text';
import { DeltaPill } from './DeltaPill';
import { PressableScale } from './PressableScale';
import { Skeleton } from './Skeleton';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';
import type { Quote } from '@/api/types';
import { price } from '@/lib/format';
import { haptic } from '@/lib/haptics';

const NAMES: Record<string, string> = {
  SPY: 'S&P 500 ETF',
  QQQ: 'Nasdaq 100 ETF',
  DIA: 'Dow Jones ETF',
  IWM: 'Russell 2000 ETF',
  NVDA: 'NVIDIA',
  AAPL: 'Apple',
  MSFT: 'Microsoft',
  GOOGL: 'Alphabet',
  AMZN: 'Amazon',
  TSLA: 'Tesla',
  META: 'Meta Platforms',
};

/** Watchlist row — monogram, name, live price, day delta. */
export function QuoteRow({ symbol, quote, onPress }: { symbol: string; quote?: Quote; onPress?: () => void }) {
  const { palette } = useTheme();
  return (
    <PressableScale
      scaleTo={0.985}
      onPress={() => {
        haptic.select();
        onPress?.();
      }}
      style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 12, gap: 12 }}
    >
      <View
        style={{
          width: 40,
          height: 40,
          borderRadius: 13,
          backgroundColor: palette.tealSoft,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text style={{ fontFamily: fonts.uiExtra, fontSize: 12, color: palette.teal }}>{symbol.slice(0, 4)}</Text>
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="bodyStrong">{symbol}</Text>
        <Text variant="caption" dim numberOfLines={1}>
          {NAMES[symbol] ?? 'US Equity'}
        </Text>
      </View>
      {quote ? (
        <View style={{ alignItems: 'flex-end', gap: 3 }}>
          <Text variant="monoL">${price(quote.price)}</Text>
          <DeltaPill value={quote.changePct} size="sm" filled={false} />
        </View>
      ) : (
        <Skeleton width={84} height={30} />
      )}
    </PressableScale>
  );
}
