/**
 * App-wide constants: API base, portfolio identities, market universe, refresh cadences.
 * API base can be overridden via app config `extra.apiBaseUrl` (defaults to production).
 * Web dev preview talks to the local dashboard server (prod CORS only allows :3000 origins);
 * native always talks to production.
 */
import { Platform } from 'react-native';
import Constants from 'expo-constants';

const WEB_DEV = Platform.OS === 'web' && typeof __DEV__ !== 'undefined' && __DEV__;

export const API_BASE_URL: string =
  (Constants.expoConfig?.extra?.apiBaseUrl as string | undefined) ??
  (WEB_DEV ? 'http://localhost:3001' : 'https://autotradingportfolios.vercel.app');

/** Greeting name for the home header (single-operator personal app). */
export const OWNER_FIRST_NAME = 'Mohamed';

export type PortfolioId = 'all' | 'portfolio_1' | 'portfolio_2' | 'portfolio_3';

export interface PortfolioMeta {
  id: PortfolioId;
  label: string;
  short: string;
  tagline: string;
  strategy: string;
  account?: string;
  symbol: string; // SF Symbol name
}

export const PORTFOLIOS: PortfolioMeta[] = [
  {
    id: 'portfolio_1',
    label: 'Self-Improving Brain',
    short: 'P1',
    tagline: 'Multi-factor quant + regime detection',
    strategy: 'Adaptive multi-factor scoring with market-regime detection, relative-strength ranking and a walk-forward-gated self-learning loop.',
    account: 'PA3HULQQ8OOH',
    symbol: 'brain.head.profile',
  },
  {
    id: 'portfolio_2',
    label: 'Capitol Shadow',
    short: 'P2',
    tagline: 'Copy-trade US politicians',
    strategy: 'Mirrors disclosed congressional trades surfaced via Capitol Trades, filtered for liquidity and conviction.',
    account: 'PA38R564MIS7',
    symbol: 'building.columns',
  },
  {
    id: 'portfolio_3',
    label: 'Cautious Sniper',
    short: 'P3',
    tagline: 'Fundamental screen + breakout + news',
    strategy: 'Fundamental screen into technical breakout entries, confirmed by news sentiment, with bracketed risk control.',
    account: 'PA3M3WI7C58W',
    symbol: 'scope',
  },
];

export const ALL_META: PortfolioMeta = {
  id: 'all',
  label: 'All Portfolios',
  short: 'ALL',
  tagline: 'Aggregate book across all strategies',
  strategy: 'Combined view of the three autonomous strategies.',
  symbol: 'square.stack.3d.up',
};

export function metaFor(id: string): PortfolioMeta {
  return PORTFOLIOS.find((p) => p.id === id) ?? ALL_META;
}

/** Index instruments for the home/markets marquee. */
export const MARKET_INDICES = ['SPY', 'QQQ', 'DIA', 'IWM'] as const;

/** Default watchlist for Market Pulse. */
export const DEFAULT_WATCHLIST = [
  'NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'SPY', 'QQQ',
] as const;

export const SECTOR_ETFS: { symbol: string; name: string }[] = [
  { symbol: 'XLK', name: 'Technology' },
  { symbol: 'XLF', name: 'Financials' },
  { symbol: 'XLE', name: 'Energy' },
  { symbol: 'XLV', name: 'Health Care' },
  { symbol: 'XLY', name: 'Cons. Disc.' },
  { symbol: 'XLI', name: 'Industrials' },
  { symbol: 'XLP', name: 'Cons. Staples' },
  { symbol: 'XLU', name: 'Utilities' },
];

export const CRYPTO_SYMBOLS = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'LTC/USD'] as const;

/** Chart period → Alpaca timeframe mapping (mirrors market-pulse.js invariants). */
export const CHART_PERIODS = ['1D', '1W', '1M', '3M', '6M', '1Y'] as const;
export type ChartPeriod = (typeof CHART_PERIODS)[number];

export const PERIOD_TIMEFRAME: Record<ChartPeriod, string> = {
  '1D': '5Min',
  '1W': '1Hour',
  '1M': '1Day',
  '3M': '1Day',
  '6M': '1Day',
  '1Y': '1Day',
};

/** Auto-refresh cadences (ms) — mirror the website's intervals. */
export const REFRESH = {
  overview: 60_000,
  detail: 30_000,
  quotes: 15_000,
  marketFast: 12_000,
  orders: 30_000,
  clock: 60_000,
} as const;
