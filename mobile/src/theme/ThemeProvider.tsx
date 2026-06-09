/**
 * Theme context — Dark Solar / Light Paper, persisted, system-aware.
 * Defaults to Dark Solar (the premium terminal experience).
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useColorScheme as useDeviceScheme } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { palettes, type ColorScheme, type Palette } from './tokens';

export type ThemePref = 'system' | 'light' | 'dark';
const KEY = 'rw.theme.pref';

interface ThemeContextValue {
  palette: Palette;
  scheme: ColorScheme;
  pref: ThemePref;
  setPref: (p: ThemePref) => void;
  toggle: () => void;
  ready: boolean;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const device = useDeviceScheme();
  const [pref, setPrefState] = useState<ThemePref>('dark');
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    AsyncStorage.getItem(KEY)
      .then((v) => {
        if (active && (v === 'light' || v === 'dark' || v === 'system')) setPrefState(v);
      })
      .finally(() => active && setReady(true));
    return () => {
      active = false;
    };
  }, []);

  const setPref = useCallback((p: ThemePref) => {
    setPrefState(p);
    AsyncStorage.setItem(KEY, p).catch(() => {});
  }, []);

  const scheme: ColorScheme = pref === 'system' ? (device === 'light' ? 'light' : 'dark') : pref;
  const palette = palettes[scheme];

  const toggle = useCallback(() => {
    setPref(scheme === 'dark' ? 'light' : 'dark');
  }, [scheme, setPref]);

  const value = useMemo<ThemeContextValue>(
    () => ({ palette, scheme, pref, setPref, toggle, ready }),
    [palette, scheme, pref, setPref, toggle, ready],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider');
  return ctx;
}
