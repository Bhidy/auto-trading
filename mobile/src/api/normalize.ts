/**
 * Position normalizer — the dashboard API returns transformed positions
 * (quantity/avgCost/lastPrice/marketValue, percent-scaled plpc, weight, sector),
 * while raw Alpaca endpoints use qty/avg_entry_price/current_price/market_value
 * with ratio-scaled plpc. Everything downstream consumes this canonical shape.
 */

export interface CanonicalPosition {
  symbol: string;
  qty: number;
  side: 'long' | 'short';
  avgEntry: number;
  last: number;
  marketValue: number;
  costBasis: number;
  unrealizedPl: number;
  unrealizedPlPct: number; // percent (e.g. -1.57 => -1.57%)
  dayPct: number; // percent
  weightPct?: number; // percent of book, when provided
  sector?: string;
  assetClass?: string;
}

type Raw = Record<string, unknown>;

const n = (v: unknown): number => {
  const x = typeof v === 'string' ? parseFloat(v) : typeof v === 'number' ? v : NaN;
  return isFinite(x) ? x : NaN;
};

const first = (...vals: unknown[]): number => {
  for (const v of vals) {
    const x = n(v);
    if (!isNaN(x)) return x;
  }
  return 0;
};

export function normalizePosition(raw: Raw): CanonicalPosition {
  const qty = first(raw.quantity, raw.qty);
  const avgEntry = first(raw.avgCost, raw.avg_entry_price);
  const last = first(raw.lastPrice, raw.current_price);
  const marketValue = first(raw.marketValue, raw.market_value, qty * last);
  const costBasis = first(raw.cost_basis, qty * avgEntry);
  const unrealizedPl = first(raw.unrealized_pl, marketValue - costBasis);

  // plpc: dashboard shape is already percent; raw Alpaca is a ratio.
  let unrealizedPlPct: number;
  if (raw.avgCost !== undefined || raw.quantity !== undefined) {
    unrealizedPlPct = first(raw.unrealized_plpc);
  } else {
    unrealizedPlPct = first(raw.unrealized_plpc) * 100;
  }
  if (!isFinite(unrealizedPlPct) || unrealizedPlPct === 0) {
    unrealizedPlPct = costBasis !== 0 ? (unrealizedPl / Math.abs(costBasis)) * 100 : 0;
  }

  const dayPct =
    raw.dayChangePct !== undefined
      ? first(raw.dayChangePct)
      : raw.change_today !== undefined && raw.avgCost === undefined
        ? first(raw.change_today) * 100
        : first(raw.change_today);

  const weight = n(raw.weight);

  return {
    symbol: String(raw.symbol ?? '—'),
    qty,
    side: raw.side === 'short' ? 'short' : 'long',
    avgEntry,
    last,
    marketValue,
    costBasis,
    unrealizedPl,
    unrealizedPlPct,
    dayPct,
    weightPct: isNaN(weight) ? undefined : weight,
    sector: typeof raw.sector === 'string' ? raw.sector : undefined,
    assetClass: typeof raw.asset_class === 'string' ? raw.asset_class : undefined,
  };
}

export function normalizePositions(raw: unknown): CanonicalPosition[] {
  if (!raw) return [];
  const list = Array.isArray(raw) ? raw : typeof raw === 'object' ? Object.values(raw as Record<string, Raw>) : [];
  return list
    .filter((p): p is Raw => !!p && typeof p === 'object')
    .map(normalizePosition)
    .filter((p) => p.symbol !== '—');
}
