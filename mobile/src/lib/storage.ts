/** Non-sensitive key/value preferences (AsyncStorage). Tokens live in lib/auth.ts. */
import AsyncStorage from '@react-native-async-storage/async-storage';

export const KEYS = {
  onboarded: 'rw.onboarded',
  watchlist: 'rw.watchlist',
  lang: 'rw.lang',
} as const;

export const storage = {
  get: (k: string) => AsyncStorage.getItem(k),
  set: (k: string, v: string) => AsyncStorage.setItem(k, v),
  remove: (k: string) => AsyncStorage.removeItem(k),
  getBool: async (k: string) => (await AsyncStorage.getItem(k)) === '1',
  setBool: (k: string, v: boolean) => AsyncStorage.setItem(k, v ? '1' : '0'),
  getJSON: async <T,>(k: string, fallback: T): Promise<T> => {
    try {
      const raw = await AsyncStorage.getItem(k);
      return raw ? (JSON.parse(raw) as T) : fallback;
    } catch {
      return fallback;
    }
  },
  setJSON: (k: string, v: unknown) => AsyncStorage.setItem(k, JSON.stringify(v)),
};
