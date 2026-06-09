/**
 * HTTP client for the Auto Trading API.
 * Reads are public; mutations attach the Keychain-stored Bearer token.
 * The server fails closed without a valid token, so reads can never trade.
 */
import { API_BASE_URL } from '@/lib/constants';
import { getAccessToken } from '@/lib/auth';

export class ApiError extends Error {
  status: number;
  body?: unknown;
  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  auth?: boolean;
  timeoutMs?: number;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = false, timeoutMs = 20_000 } = opts;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth) {
    const token = await getAccessToken();
    if (!token) throw new ApiError('Trading access token is not configured.', 401);
    headers.Authorization = `Bearer ${token}`;
  }

  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    const text = await res.text();
    let json: unknown = null;
    if (text) {
      try {
        json = JSON.parse(text);
      } catch {
        json = text;
      }
    }

    if (!res.ok) {
      const fromBody =
        json && typeof json === 'object' && 'error' in json ? String((json as { error: unknown }).error) : null;
      throw new ApiError(fromBody || `Request failed (${res.status})`, res.status, json);
    }
    return json as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if ((e as Error)?.name === 'AbortError') throw new ApiError('Request timed out.', 408);
    throw new ApiError((e as Error)?.message ?? 'Network error', 0);
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body, auth: true }),
  patch: <T,>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body, auth: true }),
  del: <T,>(path: string) => request<T>(path, { method: 'DELETE', auth: true }),
};

/** ISO date `days` ago — non-1D bar requests must always send an explicit start. */
export function isoDaysAgo(days: number): string {
  const d = new Date(Date.now() - days * 86_400_000);
  return d.toISOString().slice(0, 10);
}
