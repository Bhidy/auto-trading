import React, { useMemo, useState } from 'react';
import { View } from 'react-native';
import { Screen } from '@/components/Screen';
import { ScreenHeader } from '@/components/ScreenHeader';
import { Card } from '@/components/Card';
import { Text } from '@/components/Text';
import { Tag } from '@/components/Tag';
import { Divider } from '@/components/Divider';
import { Skeleton } from '@/components/Skeleton';
import { SegmentedControl } from '@/components/SegmentedControl';
import { ClockPill } from '@/components/ClockPill';
import { Button } from '@/components/Button';
import { useCancelOrder, useUnifiedOrders } from '@/api/hooks';
import { authorizeAction, hasAccessToken } from '@/lib/auth';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';
import { metaFor, type PortfolioId } from '@/lib/constants';
import { price, qty as fmtQty, shortDate, timeOf } from '@/lib/format';
import { haptic } from '@/lib/haptics';
import type { Order } from '@/api/types';

const TABS = ['Open', 'Executed', 'Canceled'] as const;

type Annotated = Order & {
  _portfolio_id?: string;
  _portfolio_label?: string;
  date?: string;
  entry_price?: number;
  reason?: string;
};

const num = (v: unknown) => {
  const x = typeof v === 'string' ? parseFloat(v) : typeof v === 'number' ? v : NaN;
  return isFinite(x) ? x : null;
};

function OrderRow({ order, tab, onCancel }: { order: Annotated; tab: (typeof TABS)[number]; onCancel?: () => void }) {
  const side = (order.side ?? '').toUpperCase();
  const buy = side === 'BUY';
  const qtyV = num(order.qty) ?? num(order.filled_qty);
  const px = num(order.filled_avg_price) ?? num(order.limit_price) ?? num(order.entry_price);
  const when = order.filled_at ?? order.submitted_at ?? order.created_at ?? order.date;
  const pid = order._portfolio_id;

  return (
    <View style={{ paddingVertical: 12, gap: 8 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 9 }}>
        <Tag label={side || 'ORDER'} tone={buy ? 'up' : 'down'} />
        <Text variant="bodyStrong" style={{ flex: 1 }}>
          {order.symbol}
          <Text variant="caption" dim>
            {'  '}
            {qtyV != null ? fmtQty(qtyV) : '—'} {px != null ? `@ $${price(px)}` : `· ${order.type ?? ''}`}
          </Text>
        </Text>
        <Text variant="caption" dim style={{ fontFamily: fonts.mono }}>
          {when ? `${shortDate(when)} ${timeOf(when)}` : ''}
        </Text>
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        {pid && <Tag label={metaFor(pid).short} tone="accent" />}
        <Text variant="caption" dim style={{ flex: 1 }} numberOfLines={1}>
          {order.reason ?? order.status ?? ''}
        </Text>
        {tab === 'Open' && onCancel && (
          <Button label="Cancel" variant="ghost" size="sm" onPress={onCancel} />
        )}
      </View>
      {tab === 'Open' && (order.limit_price != null || order.stop_price != null) && (
        <Text variant="caption" dim style={{ fontFamily: fonts.mono }}>
          {order.limit_price != null ? `limit $${price(num(order.limit_price))}` : ''}
          {order.stop_price != null ? `  stop $${price(num(order.stop_price))}` : ''}
          {order.time_in_force ? `  ${String(order.time_in_force).toUpperCase()}` : ''}
        </Text>
      )}
    </View>
  );
}

export default function Orders() {
  const { palette } = useTheme();
  const [tab, setTab] = useState<(typeof TABS)[number]>('Executed');
  const { data, isLoading, refetch, isRefetching } = useUnifiedOrders('all');
  const [error, setError] = useState<string | null>(null);
  const cancelP1 = useCancelOrder('portfolio_1');
  const cancelP2 = useCancelOrder('portfolio_2');
  const cancelP3 = useCancelOrder('portfolio_3');

  const rows = useMemo<Annotated[]>(() => {
    if (!data) return [];
    const list = tab === 'Open' ? data.open : tab === 'Executed' ? data.executed : data.canceled;
    return (list ?? []) as Annotated[];
  }, [data, tab]);

  const counts = {
    Open: data?.open?.length ?? 0,
    Executed: data?.executed?.length ?? 0,
    Canceled: data?.canceled?.length ?? 0,
  };

  const handleCancel = async (order: Annotated) => {
    setError(null);
    if (!(await hasAccessToken())) {
      setError('No trading access token configured — add it in Settings to manage orders.');
      haptic.warning();
      return;
    }
    const authz = await authorizeAction(`Cancel ${order.symbol} order`);
    if (!authz.ok) {
      setError('Biometric confirmation failed.');
      haptic.error();
      return;
    }
    const pid = (order._portfolio_id ?? 'portfolio_1') as PortfolioId;
    const m = pid === 'portfolio_2' ? cancelP2 : pid === 'portfolio_3' ? cancelP3 : cancelP1;
    try {
      await m.mutateAsync(order.id);
      haptic.success();
    } catch (e) {
      haptic.error();
      setError((e as Error).message);
    }
  };

  return (
    <Screen refreshing={isRefetching} onRefresh={refetch}>
      <ScreenHeader title="Orders" eyebrow="Execution" right={<ClockPill />} />

      <View style={{ gap: 14 }}>
        <SegmentedControl options={TABS} value={tab} onChange={setTab} />

        {/* Counts strip */}
        <View style={{ flexDirection: 'row', gap: 10 }}>
          {TABS.map((t) => (
            <Card key={t} padded={12} style={{ flex: 1, gap: 3, alignItems: 'center' }}>
              <Text variant="overline" dim>
                {t}
              </Text>
              <Text variant="monoL">{data ? counts[t] : '—'}</Text>
            </Card>
          ))}
        </View>

        {error && (
          <Card style={{ borderColor: palette.down }}>
            <Text variant="caption" color="down">
              {error}
            </Text>
          </Card>
        )}

        <Card padded={false} style={{ paddingHorizontal: 16, paddingVertical: 4 }}>
          {isLoading && (
            <View style={{ gap: 10, paddingVertical: 14 }}>
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} width="100%" height={48} rounded={10} />
              ))}
            </View>
          )}
          {!isLoading && rows.length === 0 && (
            <View style={{ paddingVertical: 26, alignItems: 'center', gap: 4 }}>
              <Text variant="bodyStrong">Nothing here</Text>
              <Text variant="caption" dim>
                No {tab.toLowerCase()} orders across the book.
              </Text>
            </View>
          )}
          {rows.slice(0, 40).map((o, i) => (
            <View key={`${o.id ?? i}-${i}`}>
              {i > 0 && <Divider />}
              <OrderRow order={o} tab={tab} onCancel={tab === 'Open' && o.id ? () => handleCancel(o) : undefined} />
            </View>
          ))}
        </Card>

        {data?.fetched_at && (
          <Text variant="caption" dim align="center">
            Synced {timeOf(data.fetched_at)} · auto-refreshes every 30s
          </Text>
        )}
      </View>
    </Screen>
  );
}
