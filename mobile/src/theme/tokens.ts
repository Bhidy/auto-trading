/**
 * RiseWealth design tokens — single source of truth for the Auto Trading app.
 * Mirrors docs/branding/risewealth-tokens.css and the CLAUDE.md brand kit.
 * Warm solar palette only; green/red are reserved strictly for P&L semantics.
 */

export const solar = {
  50: '#FFF1E8',
  100: '#FFD9BD',
  200: '#FFC396',
  300: '#FFA86A',
  400: '#FF8A3D',
  500: '#F26B1F',
  600: '#E55A1F', // primary
  700: '#C9461A',
  800: '#A33A14',
  900: '#6A220A',
} as const;

export type ColorScheme = 'light' | 'dark';

export interface Palette {
  scheme: ColorScheme;
  page: string;
  surface: string;
  surfaceAlt: string; // elevated card
  surfaceInset: string; // wells / inputs
  ink: string;
  inkSoft: string;
  muted: string;
  line: string;
  hairline: string;
  teal: string; // primary accent
  tealDark: string; // hover / pressed
  tealSoft: string; // soft background
  up: string; // P&L positive
  down: string; // P&L negative
  upSoft: string;
  downSoft: string;
  overlay: string; // scrim
  glassTint: string; // blur tint
  glassFill: string; // translucent card fill over ambient backdrop
  glassStroke: string; // gradient-ish hairline for glass edges
  glassHighlight: string; // specular top edge
  glowTeal: string; // ambient orb color
}

const light: Palette = {
  scheme: 'light',
  page: '#FFFFFF',
  surface: '#FFFFFF',
  surfaceAlt: '#FFFCF8',
  surfaceInset: '#FBF1E8',
  ink: '#1A0F08',
  inkSoft: '#3A2A1E',
  muted: '#7A6B5E',
  line: 'rgba(26,15,8,0.07)',
  hairline: 'rgba(26,15,8,0.12)',
  teal: '#E55A1F',
  tealDark: '#C9461A',
  tealSoft: '#FFF1E8',
  up: '#1E9E5A',
  down: '#E5484D',
  upSoft: 'rgba(30,158,90,0.12)',
  downSoft: 'rgba(229,72,77,0.12)',
  overlay: 'rgba(26,15,8,0.40)',
  glassTint: 'rgba(255,247,240,0.72)',
  glassFill: 'rgba(255,255,255,0.62)',
  glassStroke: 'rgba(26,15,8,0.10)',
  glassHighlight: 'rgba(255,255,255,0.85)',
  glowTeal: 'rgba(229,90,31,0.16)',
};

const dark: Palette = {
  scheme: 'dark',
  page: '#0E0805',
  surface: '#1A0F08',
  surfaceAlt: '#221409',
  surfaceInset: '#17100A',
  ink: '#FFF1E8',
  inkSoft: '#E8D9CC',
  muted: '#A39A92',
  line: 'rgba(255,255,255,0.08)',
  hairline: 'rgba(255,255,255,0.14)',
  teal: '#FF8A3D',
  tealDark: '#FFA86A',
  tealSoft: 'rgba(229,90,31,0.15)',
  up: '#34D399',
  down: '#FB7185',
  upSoft: 'rgba(52,211,153,0.14)',
  downSoft: 'rgba(251,113,133,0.14)',
  overlay: 'rgba(0,0,0,0.55)',
  glassTint: 'rgba(20,12,6,0.62)',
  glassFill: 'rgba(38,22,12,0.42)',
  glassStroke: 'rgba(255,170,106,0.16)',
  glassHighlight: 'rgba(255,217,189,0.20)',
  glowTeal: 'rgba(242,107,31,0.22)',
};

export const palettes = { light, dark } as const;

export const radius = {
  xs: 8,
  sm: 12,
  md: 14, // 0.85rem cards
  lg: 20,
  xl: 28,
  pill: 999,
} as const;

/** 4-pt spacing grid. */
export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
} as const;

/** Portfolio identity accents (warm ramp only). */
export const portfolioAccent: Record<string, string> = {
  all: solar[600],
  portfolio_1: '#F26B1F',
  portfolio_2: '#C9461A',
  portfolio_3: '#FF8A3D',
};

/** Splash / hero gradients (from brand kit). */
export const gradients = {
  embered: ['#2A1208', '#1A0A05', '#0A0403'] as const,
  solar: ['#FFD9BD', '#FF8A3D', '#F26B1F', '#C9461A'] as const,
  midnight: ['#0A0604', '#050302'] as const,
};

export interface Shadow {
  shadowColor: string;
  shadowOffset: { width: number; height: number };
  shadowOpacity: number;
  shadowRadius: number;
  elevation: number;
}

export function cardShadow(scheme: ColorScheme): Shadow {
  return scheme === 'light'
    ? {
        shadowColor: '#1A0F08',
        shadowOffset: { width: 0, height: 8 },
        shadowOpacity: 0.07,
        shadowRadius: 18,
        elevation: 4,
      }
    : {
        shadowColor: '#000000',
        shadowOffset: { width: 0, height: 10 },
        shadowOpacity: 0.45,
        shadowRadius: 22,
        elevation: 8,
      };
}

export function ctaShadow(): Shadow {
  return {
    shadowColor: '#E55A1F',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.32,
    shadowRadius: 18,
    elevation: 6,
  };
}
