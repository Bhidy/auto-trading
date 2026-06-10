import React, { useMemo, useState } from 'react';
import { View } from 'react-native';
import { Screen } from '@/components/Screen';
import { PageHeader } from '@/components/PageHeader';
import { FilterPills } from '@/components/FilterPills';
import { Text } from '@/components/Text';
import { Tag } from '@/components/Tag';
import { Divider } from '@/components/Divider';
import { Skeleton } from '@/components/Skeleton';
import { Button } from '@/components/Button';
import { useCancelOrder, useUnifiedOrders } from '@/api/hooks';
import { authorizeAction, hasAccessToken } from '@/lib/auth';
import { useTheme } from '@/theme/ThemeProvider';
import { fonts } from '@/theme/typography';
import { cardShadow, radius } from '@/theme/tokens';
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
  const { palette } = useTheme();
  const side = (order.side ?? '').toUpperCase();
  const buy = side === 'BUY';
  const qtyV = num(order.qty) ?? num(order.filled_qty);
  const px = num(order.filled_avg_price) ?? num(order.limit_price) ?? num(order.entry_price);
  const when = order.filled_at ?? order.submitted_at ?? order.created_at ?? order.date;
  const pid = order._portfolio_id;

  return (
    <View style={{ paddingVertical: 13, gap: 7 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 9 }}>
        <Tag label={side || 'ORDER'} tone={buy ? 'up' : 'down'} />
        <Text style={{ fontFamily: fonts.uiBold, fontSize: 14, color: palette.ink, flex: 1 }}>
          {order.symbol}
          {'  '}
          <Text style={{ fontFamily: fonts.ui, fontSize: 12.5, color: palette.muted }}>
            {qtyV != null ? fmtQty(qtyV) : '—'}{px != null ? ` @ $${price(px)}` : ` · ${order.type ?? ''}`}
          </Text>
        </Text>
        <Text style={{ fontFamily: fonts.mono, fontSize: 11.5, color: palette.muted }}>
          {when ? `${shortDate(when)} ${timeOf(when)}` : ''}
        </Text>
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        {pid && <Tag label={metaFor(pid).short} tone="accent" />}
        <Text style={{ fontFamily: fonts.uiMedium, fontSize: 12, color: palette.muted, flex: 1 }} numberOfLines={1}>
          {order.reason ?? order.status ?? ''}
        </Text>
        {tab === 'Open' && onCancel && (
          <Button label="Cancel" variant="ghost" size="sm" onPress={onCancel} />
        )}
      </View>
      {tab === 'Open' && (order.limit_price != null || order.stop_price != null) && (
        <Text style={{ fontFamily: fonts.mono, fontSize: 11.5, color: palette.muted }}>
          {order.limit_price != null ? `limit $${price(num(order.limit_price))}` : ''}
          {order.stop_price != null ? `  stop $${price(num(order.stop_price))}` : ''}
          {order.time_in_force ? `  ${String(order.time_in_force).toUpperCase()}` : ''}
        </Text>
      )}
    </View>
  );
}

export default function Orders() {
  const { palette, scheme } = useTheme();
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
      <PageHeader title="Orders" sub="All portfolios" />

      <View style={{ gap: 14 }}>

        {/* Tab filter */}
        <FilterPills options={TABS} value={tab} onChange={(v) => setTab(v as typeof tab)} stretch />

        {/* Counts row */}
        <View style={{ flexDirection: 'row', gap: 10 }}>
          {TABS.map((t) => (
            <View key={t} style={{ flex: 1, ...flatCard, padding: 12, gap: 3, alignItems: 'center' }}>
              <Text style={{ fontFamily: fonts.uiSemibold, fontSize: 11, color: palette.muted, letterSpacing: 0.6 }}>
                {t.toUpperCase()}
              </Text>
              <Text style={{ fontFamily: fonts.monoMedium, fontSize: 20, color: palette.ink }}>
                {data ? counts[t] : '—'}
              </Text>
            </View>
          ))}
        </View>

        {/* Error banner */}
        {error && (
          <View style={{ ...flatCard, borderColor: palette.down, padding: 13 }}>
            <Text style={{ fontFamily: fonts.uiMedium, fontSize: 13, color: palette.down }}>{error}</Text>
          </View>
        )}

        {/* Order list */}
        <View style={flatCard}>
          {isLoading && (
            <View style={{ gap: 10, padding: 16 }}>
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} width="100%" height={48} rounded={10} />
              ))}
            </View>
          )}
          {!isLoading && rows.length === 0 && (
            <View style={{ paddingVertical: 30, alignItems: 'center', gap: 5 }}>
              <Text style={{ fontFamily: fonts.uiBold, fontSize: 15, color: palette.ink }}>Nothing here</Text>
              <Text style={{ fontFamily: fonts.uiMedium, fontSize: 13, color: palette.muted }}>
                No {tab.toLowerCase()} orders across the book.
              </Text>
            </View>
          )}
          {rows.slice(0, 40).map((o, i) => (
            <View key={`${o.id ?? i}-${i}`} style={{ paddingHorizontal: 16 }}>
              {i > 0 && <Divider />}
              <OrderRow
                order={o}
                tab={tab}
                onCancel={tab === 'Open' && o.id ? () => handleCancel(o) : undefined}
              />
            </View>
          ))}
        </View>

        {data?.fetched_at && (
          <Text style={{ fontFamily: fonts.uiMedium, fontSize: 12, color: palette.muted, textAlign: 'center' }}>
            Synced {timeOf(data.fetched_at)} · auto-refreshes every 30s
          </Text>
        )}
      </View>
    </Screen>
  );
}
