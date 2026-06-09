/**
 * Formatting helpers — currency, percent, compact numbers, dates.
 * Institutional display rules: always show sign on P&L, never fabricate precision.
 */

export type Trend = 'up' | 'down' | 'flat';

export function trendOf(value: number | null | undefined): Trend {
  if (value == null || !isFinite(value) || Math.abs(value) < 1e-9) return 'flat';
  return value > 0 ? 'up' : 'down';
}

const USD = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const USD0 = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

export function currency(value: number | null | undefined, opts?: { compact?: boolean; cents?: boolean }): string {
  if (value == null || !isFinite(value)) return '—';
  if (opts?.compact) return '$' + compact(value);
  return opts?.cents === false ? USD0.format(value) : USD.format(value);
}

/** value is a fraction-of-100 percentage (e.g. 2.5 => "2.50%"). */
export function percent(value: number | null | undefined, opts?: { signed?: boolean; digits?: number }): string {
  if (value == null || !isFinite(value)) return '—';
  const digits = opts?.digits ?? 2;
  const sign = opts?.signed && value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}%`;
}

/** value is a ratio (e.g. 0.025 => "2.50%"). */
export function percentRatio(value: number | null | undefined, opts?: { signed?: boolean; digits?: number }): string {
  if (value == null || !isFinite(value)) return '—';
  return percent(value * 100, opts);
}

export function compact(value: number | null | undefined): string {
  if (value == null || !isFinite(value)) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

export function signedCurrency(value: number | null | undefined, opts?: { compact?: boolean }): string {
  if (value == null || !isFinite(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return sign + currency(Math.abs(value), opts);
}

export function qty(value: number | null | undefined): string {
  if (value == null || !isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs === 0) return '0';
  if (abs < 1) return value.toFixed(6).replace(/0+$/, '').replace(/\.$/, '');
  if (Number.isInteger(value)) return value.toLocaleString('en-US');
  return value.toLocaleString('en-US', { maximumFractionDigits: 4 });
}

export function price(value: number | null | undefined): string {
  if (value == null || !isFinite(value)) return '—';
  const abs = Math.abs(value);
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 2 : 4;
  return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function shortDate(input: string | number | Date): string {
  const d = new Date(input);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export function timeOf(input: string | number | Date): string {
  const d = new Date(input);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

export function relativeTime(input: string | number | Date, now?: number): string {
  const d = new Date(input).getTime();
  if (isNaN(d)) return '—';
  const diff = Math.max(0, (now ?? Date.now()) - d);
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'now';
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const days = Math.floor(h / 24);
  return `${days}d`;
}
