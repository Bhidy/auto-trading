/**
 * React Query hooks — one hook per feature surface, with the website's refresh cadences.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, isoDaysAgo } from './client';
import type {
  BarApi,
  EquityHistory,
  MarketClock,
  MoversResponse,
  NewsItem,
  PlaceOrderInput,
  PortfolioDetails,
  PortfolioOverview,
  PortfolioSummary,
  QuotesMap,
  SectorQuote,
  TailRisk,
  UnifiedOrders,
  Order,
} from './types';
import { REFRESH, type ChartPeriod, PERIOD_TIMEFRAME, type PortfolioId } from '@/lib/constants';

export function useOverview() {
  return useQuery({
    queryKey: ['overview'],
    queryFn: () => api.get<PortfolioOverview[]>('/api/portfolios/overview'),
    refetchInterval: REFRESH.overview,
  });
}

export function useSummary(id: PortfolioId) {
  return useQuery({
    queryKey: ['summary', id],
    queryFn: () => api.get<PortfolioSummary>(`/api/portfolio/${id}/summary`),
    refetchInterval: REFRESH.detail,
  });
}

export function useDetails(id: PortfolioId) {
  return useQuery({
    queryKey: ['details', id],
    queryFn: () => api.get<PortfolioDetails>(`/api/portfolio/${id}/details`),
    refetchInterval: REFRESH.detail,
  });
}

const EQUITY_PERIOD: Record<string, string> = {
  '1W': '1W',
  '1M': '1M',
  '3M': '3M',
  '6M': '6M',
  '1Y': '1A',
  ALL: 'all',
};

export function useEquityHistory(id: PortfolioId, period: string) {
  return useQuery({
    queryKey: ['equity', id, period],
    queryFn: () =>
      api.get<EquityHistory>(
        `/api/portfolio/${id}/equity-history?period=${encodeURIComponent(EQUITY_PERIOD[period] ?? period)}&timeframe=1D`,
      ),
    refetchInterval: REFRESH.detail,
  });
}

export function useQuotes(symbols: readonly string[]) {
  const list = symbols.join(',');
  return useQuery({
    queryKey: ['quotes', list],
    queryFn: () => api.get<QuotesMap>(`/api/market/quotes?symbols=${encodeURIComponent(list)}`),
    refetchInterval: REFRESH.quotes,
    enabled: symbols.length > 0,
  });
}

const PERIOD_START_DAYS: Record<ChartPeriod, number | null> = {
  '1D': null, // server defaults intraday start
  '1W': 8,
  '1M': 32,
  '3M': 95,
  '6M': 185,
  '1Y': 370,
};

export function useBars(symbol: string | null, period: ChartPeriod) {
  return useQuery({
    queryKey: ['bars', symbol, period],
    queryFn: () => {
      const timeframe = PERIOD_TIMEFRAME[period];
      const days = PERIOD_START_DAYS[period];
      // Invariant (CLAUDE.md): every non-1D request sends an explicit start.
      const start = days != null ? `&start=${isoDaysAgo(days)}` : '';
      const limit = period === '1D' ? 200 : 500;
      return api.get<BarApi[]>(
        `/api/market/bars/${encodeURIComponent(symbol!)}?timeframe=${timeframe}&limit=${limit}${start}`,
      );
    },
    refetchInterval: period === '1D' || period === '1W' ? 20_000 : 60_000,
    enabled: !!symbol,
  });
}

export function useMarketClock() {
  return useQuery({
    queryKey: ['clock'],
    queryFn: () => api.get<MarketClock>('/api/market-clock'),
    refetchInterval: REFRESH.clock,
  });
}

export function useNews(limit = 12) {
  return useQuery({
    queryKey: ['news', limit],
    queryFn: () => api.get<NewsItem[]>(`/api/market-news?limit=${limit}`),
    refetchInterval: 120_000,
  });
}

export function useSectors() {
  return useQuery({
    queryKey: ['sectors'],
    queryFn: () => api.get<Record<string, SectorQuote>>('/api/market/sectors'),
    refetchInterval: 60_000,
  });
}

export function useMovers(top = 8) {
  return useQuery({
    queryKey: ['movers', top],
    queryFn: () => api.get<MoversResponse>(`/api/market/movers?top=${top}`),
    refetchInterval: 60_000,
  });
}

export function useTailRisk(id: PortfolioId) {
  return useQuery({
    queryKey: ['tail-risk', id],
    queryFn: () => api.get<TailRisk>(`/api/portfolio/${id}/tail-risk`),
    staleTime: 10 * 60_000,
    enabled: id !== 'all',
  });
}

export function useUnifiedOrders(portfolioId: PortfolioId | 'all') {
  return useQuery({
    queryKey: ['orders-unified', portfolioId],
    queryFn: () => api.get<UnifiedOrders>(`/api/orders/unified?portfolio_id=${portfolioId}`),
    refetchInterval: REFRESH.orders,
  });
}

/* ---------------- Mutations (token + biometric gated upstream) ---------------- */

export function usePlaceOrder(id: PortfolioId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: PlaceOrderInput) => api.post<Order>(`/api/portfolio/${id}/order`, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['orders-unified'] });
      qc.invalidateQueries({ queryKey: ['details', id] });
    },
  });
}

export function useClosePosition(id: PortfolioId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ symbol, percentage }: { symbol: string; percentage?: number }) =>
      api.post(`/api/portfolio/${id}/position/${encodeURIComponent(symbol)}/close`, {
        percentage: percentage ?? 100,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['details', id] });
      qc.invalidateQueries({ queryKey: ['summary', id] });
      qc.invalidateQueries({ queryKey: ['overview'] });
    },
  });
}

export function useCancelOrder(id: PortfolioId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (orderId: string) => api.del(`/api/portfolio/${id}/order/${orderId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['orders-unified'] }),
  });
}
