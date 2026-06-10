/**
 * Design 3.0 "Cloud Pastel" tokens — single source of truth for the Auto Trading app.
 * White canvas, warm pastel tint cards, one espresso contrast surface, orange reserved
 * for CTAs/active states. Green/red stay strictly P&L semantics.
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
  surfaceAlt: string; // soft warm row / elevated section
  surfaceInset: string; // wells / inputs / skeletons
  ink: string;
  inkSoft: string;
  muted: string;
  line: string;
  hairline: string;
  teal: string; // primary accent (brand orange)
  tealDark: string; // hover / pressed
  tealSoft: string; // soft accent background
  up: string; // P&L positive
  down: string; // P&L negative
  upSoft: string;
  downSoft: string;
  overlay: string; // scrim
  glassTint: string; // legacy glass keys (onboarding / sheets)
  glassFill: string;
  glassStroke: string;
  glassHighlight: string;
  glowTeal: string; // ambient orb color (dark mode only)
  tintPeach: string; // pastel card 1
  tintCream: string; // pastel card 2
  tintMist: string; // pastel card 3 (neutral)
  contrast: string; // espresso contrast card bg
  contrastInk: string; // text on contrast card
  contrastMuted: string; // secondary text on contrast card
  chartFill: string; // area under hero chart line
}

const light: Palette = {
  scheme: 'light',
  page: '#FFFFFF',
  surface: '#FFFFFF',
  surfaceAlt: '#FAF6F2',
  surfaceInset: '#F5F0EA',
  ink: '#16120E',
  inkSoft: '#4A4036',
  muted: '#9A8F84',
  line: 'rgba(22,18,14,0.08)',
  hairline: 'rgba(22,18,14,0.14)',
  teal: '#E55A1F',
  tealDark: '#C9461A',
  tealSoft: '#FFEDE2',
  up: '#1FA05A',
  down: '#D7402B',
  upSoft: '#E7F6EC',
  downSoft: '#FBEAE7',
  overlay: 'rgba(22,18,14,0.40)',
  glassTint: 'rgba(255,255,255,0.80)',
  glassFill: 'rgba(255,255,255,0.88)',
  glassStroke: 'rgba(22,18,14,0.08)',
  glassHighlight: 'rgba(255,255,255,0.92)',
  glowTeal: 'rgba(229,90,31,0.10)',
  tintPeach: '#FFEDE2',
  tintCream: '#FFF4EA',
  tintMist: '#F5F2EF',
  contrast: '#171210',
  contrastInk: '#FFFFFF',
  contrastMuted: 'rgba(255,244,236,0.58)',
  chartFill: '#FFF1E8',
};

const dark: Palette = {
  scheme: 'dark',
  page: '#0F0B08',
  surface: '#1A130D',
  surfaceAlt: '#211811',
  surfaceInset: '#271D14',
  ink: '#FFF4EC',
  inkSoft: '#E6D8CC',
  muted: '#A89C90',
  line: 'rgba(255,255,255,0.08)',
  hairline: 'rgba(255,255,255,0.14)',
  teal: '#FF8A3D',
  tealDark: '#FFA86A',
  tealSoft: 'rgba(229,90,31,0.16)',
  up: '#34D399',
  down: '#FB7185',
  upSoft: 'rgba(52,211,153,0.14)',
  downSoft: 'rgba(251,113,133,0.14)',
  overlay: 'rgba(0,0,0,0.55)',
  glassTint: 'rgba(20,12,6,0.62)',
  glassFill: 'rgba(38,22,12,0.42)',
  glassStroke: 'rgba(255,170,106,0.16)',
  glassHighlight: 'rgba(255,217,189,0.20)',
  glowTeal: 'rgba(242,107,31,0.20)',
  tintPeach: '#2B1D12',
  tintCream: '#271F14',
  tintMist: '#221B16',
  contrast: '#FFF1E8',
  contrastInk: '#171210',
  contrastMuted: 'rgba(23,18,16,0.60)',
  chartFill: 'rgba(229,90,31,0.10)',
};

export const palettes = { light, dark } as const;

export const radius = {
  xs: 8,
  sm: 12,
  md: 16,
  lg: 20,
  xl: 26,
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

/** Strategy card pastel variants — peach / espresso / cream, in portfolio order. */
export type CardVariant = 'peach' | 'contrast' | 'cream';
export const portfolioVariant: Record<string, CardVariant> = {
  portfolio_1: 'peach',
  portfolio_2: 'contrast',
  portfolio_3: 'cream',
};

/** Splash / hero gradients (from brand kit — onboarding only). */
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
        shadowColor: '#2A1A0E',
        shadowOffset: { width: 0, height: 10 },
        shadowOpacity: 0.05,
        shadowRadius: 22,
        elevation: 3,
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
    shadowOpacity: 0.28,
    shadowRadius: 16,
    elevation: 6,
  };
}
