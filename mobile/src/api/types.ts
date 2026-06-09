/** API models — pragmatic typings for the Auto Trading dashboard API. */

export interface PortfolioOverview {
  id: string;
  label: string;
  equity: number;
  cash: number;
  dayPnl: number;
  dayPnlPct: number;
  positions: number;
  totalReturn: number; // percent
  initialCapital: number;
  liveConnected: boolean;
  strategy: string;
}

export interface PortfolioSummary {
  id: string;
  label: string;
  account_number?: string;
  strategy?: string;
  equity: number;
  cash: number;
  day_pnl: number;
  day_pnl_pct: number;
  positions_count: number;
  halted?: boolean;
  halt_reason?: string | null;
  live_connected?: boolean;
}

export interface Position {
  symbol: string;
  qty: string | number;
  side: 'long' | 'short';
  avg_entry_price: string | number;
  current_price: string | number;
  market_value: string | number;
  cost_basis?: string | number;
  unrealized_pl: string | number;
  unrealized_plpc: string | number; // ratio
  change_today?: string | number; // ratio
  asset_class?: string;
  exchange?: string;
}

export interface Order {
  id: string;
  client_order_id?: string;
  symbol: string;
  qty?: string | number;
  notional?: string | number;
  filled_qty?: string | number;
  side: 'buy' | 'sell';
  type: string;
  status: string;
  time_in_force?: string;
  limit_price?: string | number | null;
  stop_price?: string | number | null;
  filled_avg_price?: string | number | null;
  submitted_at?: string;
  filled_at?: string | null;
  created_at?: string;
  order_class?: string;
}

export interface TradeLogEntry {
  date?: string;
  timestamp?: string;
  symbol: string;
  side?: string;
  action?: string;
  qty?: number;
  entry_price?: number;
  exit_price?: number;
  pnl?: number;
  reason?: string;
  status?: string;
  [k: string]: unknown;
}

export interface PortfolioDetails {
  id: string;
  label: string;
  currency?: string;
  benchmark?: string;
  live_connected?: boolean;
  halted?: boolean;
  halt_reason?: string | null;
  account?: Record<string, unknown> & {
    equity?: string | number;
    last_equity?: string | number;
    cash?: string | number;
    buying_power?: string | number;
    portfolio_value?: string | number;
    account_number?: string;
  };
  positions: Position[];
  orders: Order[];
  trade_log: TradeLogEntry[];
  signals?: Record<string, unknown>;
  strategy_params?: Record<string, unknown>;
  learning_report?: Record<string, unknown>;
}

export interface EquityPointApi {
  date: string;
  equity: number;
  profit_loss?: number;
  profit_loss_pct?: number;
}

export interface EquityHistory {
  source?: string;
  base_value?: number;
  history: EquityPointApi[];
}

export interface Quote {
  price: number;
  change: number;
  changePct: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  bid?: number;
  ask?: number;
  bidSize?: number;
  askSize?: number;
}

export type QuotesMap = Record<string, Quote>;

export interface BarApi {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface MarketClock {
  timestamp?: string;
  is_open: boolean;
  next_open?: string;
  next_close?: string;
}

export interface NewsItem {
  id?: number | string;
  headline: string;
  summary?: string;
  author?: string;
  source?: string;
  url?: string;
  symbols?: string[];
  created_at?: string;
  updated_at?: string;
  images?: { size: string; url: string }[];
}

export interface SectorQuote {
  price: number;
  changePct: number;
  name: string;
  volume?: number;
}

export interface MoversResponse {
  gainers: { symbol: string; percent_change: number; price: number; change: number }[];
  losers: { symbol: string; percent_change: number; price: number; change: number }[];
}

export interface TailRisk {
  portfolio_id: string;
  n_obs: number;
  var_95?: { var_pct: number | null; cvar_pct: number | null; n?: number };
  var_99?: { var_pct: number | null; cvar_pct: number | null; n?: number };
  note?: string;
}

export interface UnifiedOrders {
  executed: (Order & { _portfolio_id?: string; _portfolio_label?: string; date?: string; entry_price?: number; reason?: string })[];
  open: (Order & { _portfolio_id?: string; _portfolio_label?: string })[];
  canceled: (Order & { _portfolio_id?: string; _portfolio_label?: string })[];
  fetched_at?: string;
}

export interface PlaceOrderInput {
  symbol: string;
  qty: number;
  side: 'buy' | 'sell';
  type: 'market' | 'limit' | 'stop' | 'stop_limit';
  time_in_force?: 'day' | 'gtc';
  limit_price?: number;
  stop_price?: number;
}
