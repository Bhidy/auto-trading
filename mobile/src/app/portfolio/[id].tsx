import React, { useMemo, useState } from 'react';
import { Alert, Platform, useWindowDimensions, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Screen } from '@/components/Screen';
import { Card } from '@/components/Card';
import { GlassCard } from '@/components/GlassCard';
import { Reveal } from '@/components/Reveal';
import { Text } from '@/components/Text';
import { Tag } from '@/components/Tag';
import { Button } from '@/components/Button';
import { DeltaPill } from '@/components/DeltaPill';
import { Divider } from '@/components/Divider';
import { Icon } from '@/components/Icon';
import { PressableScale } from '@/components/PressableScale';
import { Skeleton } from '@/components/Skeleton';
import { Sheet } from '@/components/Sheet';
import { HoldingRow } from '@/components/HoldingRow';
import { StatTile } from '@/components/StatTile';
import { AnimatedNumber } from '@/components/AnimatedNumber';
import { EquityChart, type EquityPoint } from '@/charts/EquityChart';
import { Donut, type DonutSlice } from '@/charts/Donut';
import { useClosePosition, useDetails, useEquityHistory, useSummary, useTailRisk } from '@/api/hooks';
import { normalizePositions, type CanonicalPosition } from '@/api/normalize';
import { authorizeAction, hasAccessToken } from '@/lib/auth';
import { useTheme } from '@/theme/ThemeProvider';
import { solar } from '@/theme/tokens';
import { fonts } from '@/theme/typography';
import { metaFor, type PortfolioId } from '@/lib/constants';
import { currency, percent, qty as fmtQty, price, shortDate, signedCurrency } from '@/lib/format';
import { haptic } from '@/lib/haptics';

const PERIODS = ['1W', '1M', '3M', '6M', '1Y', 'ALL'] as const;
const DONUT_COLORS: string[] = [solar[600], solar[400], solar[800], solar[300], solar[700], solar[200], solar[500]];

const num = (v: string | number | undefined | null) => {
  const n = typeof v === 'string' ? parseFloat(v) : (v ?? NaN);
  return isFinite(n) ? n : 0;
};

export default function PortfolioDetail() {
  const params = useLocalSearchParams<{ id: string }>();
  const id = (['all', 'portfolio_1', 'portfolio_2', 'portfolio_3'].includes(params.id ?? '') ? params.id : 'all') as PortfolioId;
  const meta = metaFor(id);
  const { palette } = useTheme();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();

  const [period, setPeriod] = useState<(typeof PERIODS)[number]>('3M');
  const [scrub, setScrub] = useState<EquityPoint | null>(null);
  const [closing, setClosing] = useState<CanonicalPosition | null>(null);
  const [closeError, setCloseError] = useState<string | null>(null);

  const { data: summary, refetch: r1, isRefetching: rf1 } = useSummary(id);
  const { data: details, refetch: r2, isRefetching: rf2 } = useDetails(id);
  const { data: equity } = useEquityHistory(id, period);
  const { data: risk } = useTailRisk(id);
  const closePosition = useClosePosition(id);

  const positions = useMemo(
    () => normalizePositions(details?.positions).sort((a, b) => Math.abs(b.marketValue) - Math.abs(a.marketValue)),
    [details?.positions],
  );

  const equityValue = summary?.equity ?? 0;

  const donut = useMemo<DonutSlice[]>(() => {
    if (!positions.length) return [];
    const top = positions.slice(0, 6).map((p, i) => ({
      label: p.symbol,
      value: Math.abs(p.marketValue),
      color: DONUT_COLORS[i % DONUT_COLORS.length],
    }));
    const rest = positions.slice(6).reduce((s, p) => s + Math.abs(p.marketValue), 0);
    const cash = Math.max(0, summary?.cash ?? 0);
    const slices = [...top];
    if (rest > 0) slices.push({ label: 'Other', value: rest, color: solar[100] });
    if (cash > 0) slices.push({ label: 'Cash', value: cash, color: palette.scheme === 'dark' ? '#3A2A1E' : '#EADFD4' });
    return slices;
  }, [positions, summary?.cash, palette.scheme]);

  const history = equity?.history ?? [];
  const chartWidth = width - 36 - 32;

  const startCloseFlow = async (p: CanonicalPosition) => {
    setCloseError(null);
    if (!(await hasAccessToken())) {
      setClosing(null);
      const msg = 'Add your trading access token in Settings to enable live actions.';
      if (Platform.OS === 'web') setCloseError(msg);
      else
        Alert.alert('Trading locked', msg, [
          { text: 'Open Settings', onPress: () => router.push('/settings') },
          { text: 'Cancel', style: 'cancel' },
        ]);
      return;
    }
    setClosing(p);
  };

  const confirmClose = async (percentage: number) => {
    if (!closing) return;
    setCloseError(null);
    const authz = await authorizeAction(`Close ${percentage}% of ${closing.symbol}`);
    if (!authz.ok) {
      setCloseError(
        authz.reason === 'no-token'
          ? 'No trading access token configured. Add it in Settings.'
          : 'Biometric confirmation failed.',
      );
      haptic.error();
      return;
    }
    try {
      await closePosition.mutateAsync({ symbol: closing.symbol, percentage });
      haptic.success();
      setClosing(null);
    } catch (e) {
      haptic.error();
      setCloseError((e as Error).message);
    }
  };

  return (
    <Screen refreshing={rf1 || rf2} onRefresh={() => Promise.all([r1(), r2()])} padded={false}>
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
            else router.replace('/portfolios');
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
          <Icon name="chevron-left" size={16} color={palette.ink} strokeWidth={2.2} />
        </PressableScale>
        <View style={{ flex: 1, gap: 1 }}>
          <Text variant="headline">{meta.label}</Text>
          <Text variant="caption" dim>
            {meta.account ? `${meta.account} · ` : ''}
            {meta.tagline}
          </Text>
        </View>
        <Tag
          label={summary?.halted ? 'Halted' : summary?.live_connected !== false ? 'Live' : 'Synced'}
          tone={summary?.halted ? 'down' : summary?.live_connected !== false ? 'live' : 'neutral'}
          live={!summary?.halted && summary?.live_connected !== false}
        />
      </View>

      <View style={{ paddingHorizontal: 18, gap: 14 }}>
        {/* Equity hero + chart */}
        <Reveal index={0}>
        <GlassCard glow style={{ gap: 14 }}>
          <View style={{ gap: 4 }}>
            <Text variant="overline" dim>
              {scrub ? shortDate(scrub.date) : 'Portfolio equity'}
            </Text>
            {summary ? (
              <AnimatedNumber
                value={scrub ? scrub.equity : equityValue}
                format={(n) => currency(n)}
                variant="monoXL"
                style={{ fontFamily: fonts.serif, fontSize: 42, lineHeight: 48, letterSpacing: -0.6 }}
              />
            ) : (
              <Skeleton width={210} height={36} />
            )}
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              {scrub ? (
                <Text variant="caption" dim>
                  {signedCurrency(scrub.profit_loss ?? null)} ({percent(scrub.profit_loss_pct ?? null, { signed: true })}) vs
                  period start
                </Text>
              ) : (
                <>
                  <DeltaPill value={summary?.day_pnl_pct ?? null} size="sm" />
                  <Text variant="caption" dim>
                    {signedCurrency(summary?.day_pnl ?? null)} today
                  </Text>
                </>
              )}
            </View>
          </View>

          {history.length > 1 ? (
            <EquityChart
              data={history}
              width={chartWidth}
              height={190}
              baseValue={equity?.base_value}
              onScrub={(p) => setScrub(p)}
            />
          ) : (
            <Skeleton width="100%" height={190} rounded={12} />
          )}

          <View style={{ flexDirection: 'row', backgroundColor: palette.surfaceInset, borderRadius: 999, padding: 3 }}>
            {PERIODS.map((p) => (
              <PressableScale
                key={p}
                scaleTo={0.94}
                onPress={() => {
                  haptic.select();
                  setPeriod(p);
                  setScrub(null);
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

          <View style={{ flexDirection: 'row' }}>
            <StatTile label="Cash" style={{ flex: 1 }}>
              <Text variant="monoL">{currency(summary?.cash ?? null, { cents: false })}</Text>
            </StatTile>
            <StatTile label="Buying power" style={{ flex: 1 }}>
              <Text variant="monoL">
                {currency(details?.account?.buying_power != null ? num(details.account.buying_power) : null, {
                  cents: false,
                })}
              </Text>
            </StatTile>
            <StatTile label="Positions" style={{ flex: 1 }}>
              <Text variant="monoL">{summary?.positions_count ?? '—'}</Text>
            </StatTile>
          </View>
        </GlassCard>
        </Reveal>

        {/* Halt banner */}
        {summary?.halted && (
          <Card style={{ backgroundColor: palette.downSoft, borderColor: palette.down, gap: 4 }}>
            <Text variant="bodyStrong" color="down">
              Trading halted
            </Text>
            <Text variant="caption" dim>
              {summary.halt_reason || 'Risk guardrails paused this book.'}
            </Text>
          </Card>
        )}

        {/* Tail risk — only with a meaningful sample (no fabricated zeros) */}
        {id !== 'all' && risk && risk.n_obs >= 20 && (risk.var_95?.var_pct != null || risk.var_99?.var_pct != null) && (
          <Card style={{ gap: 12 }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <Text variant="subtitle">Tail risk</Text>
              <Text variant="caption" dim>
                {risk.n_obs} daily obs
              </Text>
            </View>
            <View style={{ flexDirection: 'row' }}>
              <StatTile label="VaR 95" style={{ flex: 1 }}>
                <Text variant="monoL" color="down">
                  {percent(risk.var_95?.var_pct ?? null, { digits: 2 })}
                </Text>
              </StatTile>
              <StatTile label="CVaR 95" style={{ flex: 1 }}>
                <Text variant="monoL" color="down">
                  {percent(risk.var_95?.cvar_pct ?? null, { digits: 2 })}
                </Text>
              </StatTile>
              <StatTile label="VaR 99" style={{ flex: 1 }}>
                <Text variant="monoL" color="down">
                  {percent(risk.var_99?.var_pct ?? null, { digits: 2 })}
                </Text>
              </StatTile>
            </View>
            <Text variant="caption" dim>
              Historical one-day loss thresholds from the live equity curve.
            </Text>
          </Card>
        )}

        {/* Allocation */}
        {donut.length > 0 && (
          <Card style={{ gap: 6 }}>
            <Text variant="subtitle">Allocation</Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 18 }}>
              <Donut slices={donut} size={150} thickness={20} centerTitle="Book" centerValue={currency(equityValue, { compact: true })} />
              <View style={{ flex: 1, gap: 8 }}>
                {donut.slice(0, 7).map((s) => {
                  const total = donut.reduce((x, d) => x + d.value, 0);
                  return (
                    <View key={s.label} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                      <View style={{ width: 9, height: 9, borderRadius: 3, backgroundColor: s.color }} />
                      <Text variant="caption" style={{ flex: 1 }}>
                        {s.label}
                      </Text>
                      <Text variant="caption" dim style={{ fontFamily: fonts.mono }}>
                        {total ? ((s.value / total) * 100).toFixed(1) : '0.0'}%
                      </Text>
                    </View>
                  );
                })}
              </View>
            </View>
          </Card>
        )}

        {/* Holdings */}
        <Card padded={false} style={{ paddingHorizontal: 16, paddingVertical: 6 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 12 }}>
            <Text variant="subtitle">Holdings</Text>
            <Text variant="caption" dim>
              {positions.length} open · hold to manage
            </Text>
          </View>
          <Divider />
          {!details && (
            <View style={{ gap: 10, paddingVertical: 14 }}>
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} width="100%" height={40} rounded={10} />
              ))}
            </View>
          )}
          {details && positions.length === 0 && (
            <View style={{ paddingVertical: 22, alignItems: 'center', gap: 4 }}>
              <Text variant="bodyStrong">All cash</Text>
              <Text variant="caption" dim>
                No open positions in this book right now.
              </Text>
            </View>
          )}
          {positions.map((p, i) => (
            <View key={`${p.symbol}-${i}`}>
              {i > 0 && <Divider />}
              <HoldingRow
                position={p}
                weightPct={p.weightPct ?? (equityValue > 0 ? (Math.abs(p.marketValue) / equityValue) * 100 : undefined)}
                onPress={() => router.push(`/symbol/${encodeURIComponent(p.symbol)}`)}
                onLongPress={() => startCloseFlow(p)}
              />
            </View>
          ))}
        </Card>

        {/* Recent activity */}
        {(details?.trade_log?.length ?? 0) > 0 && (
          <Card padded={false} style={{ paddingHorizontal: 16, paddingVertical: 6 }}>
            <View style={{ paddingVertical: 12 }}>
              <Text variant="subtitle">Recent activity</Text>
            </View>
            <Divider />
            {details!.trade_log.slice(-6).reverse().map((t, i) => {
              const side = (t.side ?? t.action ?? '').toString().toUpperCase();
              const buy = side.includes('BUY');
              return (
                <View key={i}>
                  {i > 0 && <Divider />}
                  <View style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 12, gap: 10 }}>
                    <Tag label={side || 'TRADE'} tone={buy ? 'up' : 'down'} />
                    <View style={{ flex: 1, gap: 2 }}>
                      <Text variant="bodyStrong">
                        {t.symbol}{' '}
                        <Text variant="caption" dim>
                          {fmtQty(t.qty ?? null)} @ ${price(t.entry_price ?? t.exit_price ?? null)}
                        </Text>
                      </Text>
                      {!!t.reason && (
                        <Text variant="caption" dim numberOfLines={1}>
                          {String(t.reason)}
                        </Text>
                      )}
                    </View>
                    <Text variant="caption" dim>
                      {t.date ? shortDate(t.date) : ''}
                    </Text>
                  </View>
                </View>
              );
            })}
          </Card>
        )}

        {closeError && !closing && (
          <Card style={{ borderColor: palette.down, gap: 4 }}>
            <Text variant="caption" color="down">
              {closeError}
            </Text>
          </Card>
        )}
      </View>

      {/* Close-position sheet (token + Face ID gated) */}
      <Sheet visible={!!closing} onClose={() => setClosing(null)}>
        {closing && (
          <View style={{ gap: 16 }}>
            <View style={{ gap: 4 }}>
              <Text variant="overline" color="teal">
                Manage position
              </Text>
              <Text variant="display">{closing.symbol}</Text>
              <Text variant="caption" dim>
                {fmtQty(closing.qty)} shares · {currency(closing.marketValue)} ·{' '}
                {signedCurrency(closing.unrealizedPl)} unrealized
              </Text>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Icon name="lock" size={15} color={palette.muted} />
              <Text variant="caption" dim style={{ flex: 1 }}>
                Confirmed with Face ID and executed on your paper account via the secured API.
              </Text>
            </View>
            {closeError && (
              <Text variant="caption" color="down">
                {closeError}
              </Text>
            )}
            <View style={{ gap: 10 }}>
              <Button
                label={`Close 50% of ${closing.symbol}`}
                variant="subtle"
                full
                size="lg"
                loading={closePosition.isPending}
                onPress={() => confirmClose(50)}
              />
              <Button
                label={`Close full position`}
                variant="danger"
                full
                size="lg"
                loading={closePosition.isPending}
                onPress={() => confirmClose(100)}
              />
              <Button label="Cancel" variant="ghost" full onPress={() => setClosing(null)} />
            </View>
          </View>
        )}
      </Sheet>
    </Screen>
  );
}
