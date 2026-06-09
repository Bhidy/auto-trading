import React from 'react';
import { View } from 'react-native';
import { Text } from './Text';
import { DeltaPill } from './DeltaPill';
import { PressableScale } from './PressableScale';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';
import type { CanonicalPosition } from '@/api/normalize';
import { currency, price, qty as fmtQty, signedCurrency } from '@/lib/format';
import { haptic } from '@/lib/haptics';

/** Position row — symbol identity, size, live value and unrealized P&L. */
export function HoldingRow({
  position,
  weightPct,
  onPress,
  onLongPress,
}: {
  position: CanonicalPosition;
  weightPct?: number;
  onPress?: () => void;
  onLongPress?: () => void;
}) {
  const { palette } = useTheme();
  const weight = weightPct ?? position.weightPct;

  return (
    <PressableScale
      scaleTo={0.985}
      onPress={() => {
        haptic.select();
        onPress?.();
      }}
      onLongPress={() => {
        haptic.medium();
        onLongPress?.();
      }}
      delayLongPress={350}
      style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 13, gap: 12 }}
    >
      {/* Symbol monogram */}
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
        <Text style={{ fontFamily: fonts.uiExtra, fontSize: 12.5, color: palette.teal }}>
          {position.symbol.replace('/USD', '').slice(0, 4)}
        </Text>
      </View>

      <View style={{ flex: 1, gap: 3 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Text variant="bodyStrong">{position.symbol}</Text>
          {position.side === 'short' && (
            <Text variant="overline" color="down">
              Short
            </Text>
          )}
          {position.assetClass === 'crypto' && (
            <Text variant="overline" dim>
              Crypto
            </Text>
          )}
        </View>
        <Text variant="caption" dim>
          {fmtQty(position.qty)} @ ${price(position.avgEntry)}
          {weight != null && isFinite(weight) ? `  ·  ${weight.toFixed(1)}%` : ''}
        </Text>
      </View>

      <View style={{ alignItems: 'flex-end', gap: 3 }}>
        <Text variant="monoL">{currency(position.marketValue, { cents: false })}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Text
            variant="caption"
            style={{ color: position.unrealizedPl >= 0 ? palette.up : palette.down, fontFamily: fonts.mono }}
          >
            {signedCurrency(position.unrealizedPl)}
          </Text>
          <DeltaPill value={position.unrealizedPlPct} size="sm" filled={false} />
        </View>
      </View>
    </PressableScale>
  );
}
