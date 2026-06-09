/**
 * Order ticket — token + Face ID gated manual order entry on the paper book.
 * Defaults to LIMIT (house risk doctrine); market orders remain available.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { View } from 'react-native';
import { router } from 'expo-router';
import { Sheet } from './Sheet';
import { Text } from './Text';
import { Button } from './Button';
import { Field } from './Field';
import { Icon } from './Icon';
import { PressableScale } from './PressableScale';
import { usePlaceOrder } from '@/api/hooks';
import { authorizeAction, hasAccessToken } from '@/lib/auth';
import { useTheme } from '@/theme/ThemeProvider';
import { radius } from '@/theme/tokens';
import { PORTFOLIOS, type PortfolioId } from '@/lib/constants';
import { currency } from '@/lib/format';
import { haptic } from '@/lib/haptics';

interface Props {
  visible: boolean;
  onClose: () => void;
  symbol: string;
  lastPrice?: number;
}

type Side = 'buy' | 'sell';
type OType = 'limit' | 'market';
type Tif = 'day' | 'gtc';

export function OrderTicket({ visible, onClose, symbol, lastPrice }: Props) {
  const { palette } = useTheme();
  const [pid, setPid] = useState<PortfolioId>('portfolio_1');
  const [side, setSide] = useState<Side>('buy');
  const [type, setType] = useState<OType>('limit');
  const [tif, setTif] = useState<Tif>('day');
  const [qty, setQty] = useState('1');
  const [limit, setLimit] = useState(lastPrice ? String(Math.round(lastPrice * 100) / 100) : '');
  const [error, setError] = useState<string | null>(null);
  const [placedId, setPlacedId] = useState<string | null>(null);

  const placeOrder = usePlaceOrder(pid);

  // Prefill the limit price from the live quote once available.
  useEffect(() => {
    if (!(visible && !limit && lastPrice)) return;
    const id = requestAnimationFrame(() => setLimit(String(Math.round(lastPrice * 100) / 100)));
    return () => cancelAnimationFrame(id);
  }, [visible, lastPrice, limit]);

  const qtyNum = parseFloat(qty) || 0;
  const limitNum = parseFloat(limit) || 0;
  const estimated = useMemo(() => {
    const px = type === 'limit' ? limitNum : (lastPrice ?? 0);
    return qtyNum * px;
  }, [qtyNum, limitNum, type, lastPrice]);

  const reset = () => {
    setError(null);
    setPlacedId(null);
  };

  const submit = async () => {
    setError(null);
    if (!(await hasAccessToken())) {
      setError('No trading access token configured. Add it in Settings → Security.');
      haptic.warning();
      return;
    }
    if (qtyNum <= 0) {
      setError('Quantity must be greater than zero.');
      return;
    }
    if (type === 'limit' && limitNum <= 0) {
      setError('A limit price is required for limit orders.');
      return;
    }
    const authz = await authorizeAction(`${side.toUpperCase()} ${qtyNum} ${symbol}`);
    if (!authz.ok) {
      setError(authz.reason === 'no-token' ? 'No trading access token configured.' : 'Biometric confirmation failed.');
      haptic.error();
      return;
    }
    try {
      const order = await placeOrder.mutateAsync({
        symbol,
        qty: qtyNum,
        side,
        type,
        time_in_force: tif,
        ...(type === 'limit' ? { limit_price: limitNum } : {}),
      });
      haptic.success();
      setPlacedId(order?.id ?? 'submitted');
    } catch (e) {
      haptic.error();
      setError((e as Error).message);
    }
  };

  const chip = (active: boolean, color?: string) => ({
    flex: 1,
    alignItems: 'center' as const,
    paddingVertical: 11,
    borderRadius: radius.pill,
    backgroundColor: active ? (color ?? palette.teal) : palette.surfaceInset,
    borderWidth: 1,
    borderColor: active ? 'transparent' : palette.line,
  });

  return (
    <Sheet
      visible={visible}
      onClose={() => {
        reset();
        onClose();
      }}
    >
      {placedId ? (
        <View style={{ gap: 16, alignItems: 'center', paddingVertical: 10 }}>
          <View
            style={{
              width: 64,
              height: 64,
              borderRadius: 32,
              backgroundColor: palette.upSoft,
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Icon name="shield" size={30} color={palette.up} />
          </View>
          <View style={{ alignItems: 'center', gap: 4 }}>
            <Text variant="title">Order submitted</Text>
            <Text variant="caption" dim align="center">
              {side.toUpperCase()} {qty} {symbol} · {type.toUpperCase()}
              {type === 'limit' ? ` @ ${currency(limitNum)}` : ''} · routed to your paper account.
            </Text>
          </View>
          <Button
            label="View orders"
            full
            onPress={() => {
              reset();
              onClose();
              router.push('/orders');
            }}
          />
          <Button
            label="Done"
            variant="ghost"
            full
            onPress={() => {
              reset();
              onClose();
            }}
          />
        </View>
      ) : (
        <View style={{ gap: 14 }}>
          <View style={{ gap: 2 }}>
            <Text variant="overline" color="teal">
              Order ticket
            </Text>
            <Text variant="display">{symbol}</Text>
            {lastPrice != null && (
              <Text variant="caption" dim>
                Last {currency(lastPrice)} · paper account
              </Text>
            )}
          </View>

          {/* Book selector */}
          <View style={{ flexDirection: 'row', gap: 8 }}>
            {PORTFOLIOS.map((p) => (
              <PressableScale key={p.id} scaleTo={0.95} onPress={() => { haptic.select(); setPid(p.id); }} style={chip(pid === p.id)}>
                <Text variant="label" style={{ color: pid === p.id ? '#FFF' : palette.muted }}>
                  {p.short}
                </Text>
              </PressableScale>
            ))}
          </View>

          {/* Side */}
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <PressableScale scaleTo={0.95} onPress={() => { haptic.select(); setSide('buy'); }} style={chip(side === 'buy', palette.up)}>
              <Text variant="label" style={{ color: side === 'buy' ? '#FFF' : palette.muted }}>
                BUY
              </Text>
            </PressableScale>
            <PressableScale scaleTo={0.95} onPress={() => { haptic.select(); setSide('sell'); }} style={chip(side === 'sell', palette.down)}>
              <Text variant="label" style={{ color: side === 'sell' ? '#FFF' : palette.muted }}>
                SELL
              </Text>
            </PressableScale>
          </View>

          {/* Type + TIF */}
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <PressableScale scaleTo={0.95} onPress={() => { haptic.select(); setType('limit'); }} style={chip(type === 'limit')}>
              <Text variant="label" style={{ color: type === 'limit' ? '#FFF' : palette.muted }}>
                LIMIT
              </Text>
            </PressableScale>
            <PressableScale scaleTo={0.95} onPress={() => { haptic.select(); setType('market'); }} style={chip(type === 'market')}>
              <Text variant="label" style={{ color: type === 'market' ? '#FFF' : palette.muted }}>
                MARKET
              </Text>
            </PressableScale>
            <PressableScale scaleTo={0.95} onPress={() => { haptic.select(); setTif(tif === 'day' ? 'gtc' : 'day'); }} style={chip(true, palette.surfaceInset)}>
              <Text variant="label" style={{ color: palette.ink }}>
                {tif.toUpperCase()}
              </Text>
            </PressableScale>
          </View>

          {/* Qty + limit price */}
          <View style={{ flexDirection: 'row', gap: 10 }}>
            <Field label="Quantity" value={qty} onChangeText={setQty} keyboardType="decimal-pad" placeholder="0" />
            {type === 'limit' && (
              <Field label="Limit price" value={limit} onChangeText={setLimit} keyboardType="decimal-pad" placeholder="0.00" suffix="USD" />
            )}
          </View>

          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text variant="caption" dim>
              Estimated {side === 'buy' ? 'cost' : 'proceeds'}
            </Text>
            <Text variant="monoL">{currency(estimated)}</Text>
          </View>

          {error && (
            <Text variant="caption" color="down">
              {error}
            </Text>
          )}

          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Icon name="lock" size={14} color={palette.muted} />
            <Text variant="caption" dim style={{ flex: 1 }}>
              Confirmed with Face ID · executed via the token-secured API · paper only.
            </Text>
          </View>

          <Button
            label={`${side === 'buy' ? 'Buy' : 'Sell'} ${symbol}`}
            variant={side === 'buy' ? 'primary' : 'danger'}
            size="lg"
            full
            loading={placeOrder.isPending}
            onPress={submit}
          />
        </View>
      )}
    </Sheet>
  );
}
