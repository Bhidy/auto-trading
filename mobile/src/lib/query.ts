/** Shared React Query client — tuned for a live trading dashboard. */
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      gcTime: 5 * 60_000,
      retry: 2,
      refetchOnReconnect: true,
    },
  },
});
