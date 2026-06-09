import React from 'react';
import { Platform } from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';
import { SymbolView, type SFSymbol } from 'expo-symbols';
import { useTheme } from '@/theme/ThemeProvider';

export type IconName =
  | 'home'
  | 'portfolios'
  | 'markets'
  | 'orders'
  | 'settings'
  | 'search'
  | 'plus'
  | 'close'
  | 'chevron-right'
  | 'chevron-left'
  | 'chevron-down'
  | 'arrow-up-right'
  | 'arrow-down-right'
  | 'lock'
  | 'shield'
  | 'bell'
  | 'globe'
  | 'bolt'
  | 'news'
  | 'clock'
  | 'theme';

/** SF Symbol on iOS (true native), hand-drawn SVG stroke icon elsewhere (web preview / Android). */
const MAP: Record<IconName, { sf: SFSymbol; d: string | string[]; filled?: boolean }> = {
  home: { sf: 'house.fill', d: 'M4 11.5 12 4.5l8 7M6 10v9.5h12V10' },
  portfolios: { sf: 'square.stack.3d.up.fill', d: ['M12 3 4 7l8 4 8-4-8-4Z', 'm4 12 8 4 8-4', 'm4 17 8 4 8-4'] },
  markets: { sf: 'chart.xyaxis.line', d: ['M4 19V5', 'M4 19h16', 'm7 14 3.2-4 3 2.5L17.5 7'] },
  orders: { sf: 'list.bullet.rectangle.portrait.fill', d: ['M7 3.5h10a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2Z', 'M9 8h6M9 12h6M9 16h4'] },
  settings: { sf: 'gearshape.fill', d: ['M12 8.6a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8Z', 'M19.4 12a7.4 7.4 0 0 0-.1-1.1l2-1.5-2-3.4-2.3 1a7.6 7.6 0 0 0-1.9-1.1L14.7 3h-5.4l-.4 2.9c-.7.3-1.3.6-1.9 1.1l-2.3-1-2 3.4 2 1.5a7.4 7.4 0 0 0 0 2.2l-2 1.5 2 3.4 2.3-1c.6.5 1.2.8 1.9 1.1l.4 2.9h5.4l.4-2.9c.7-.3 1.3-.6 1.9-1.1l2.3 1 2-3.4-2-1.5c.06-.36.1-.73.1-1.1Z'] },
  search: { sf: 'magnifyingglass', d: ['M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Z', 'm15.5 15.5 4.5 4.5'] },
  plus: { sf: 'plus', d: 'M12 5v14M5 12h14' },
  close: { sf: 'xmark', d: 'M6 6l12 12M18 6 6 18' },
  'chevron-right': { sf: 'chevron.right', d: 'm9 5 7 7-7 7' },
  'chevron-left': { sf: 'chevron.left', d: 'm15 5-7 7 7 7' },
  'chevron-down': { sf: 'chevron.down', d: 'm5 9 7 7 7-7' },
  'arrow-up-right': { sf: 'arrow.up.right', d: 'M7 17 17 7M9 7h8v8' },
  'arrow-down-right': { sf: 'arrow.down.right', d: 'M7 7l10 10M17 9v8H9' },
  lock: { sf: 'lock.fill', d: ['M7 11V8a5 5 0 0 1 10 0v3', 'M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1Z'] },
  shield: { sf: 'checkmark.shield.fill', d: ['M12 3 5 6v5c0 4.5 3 8.2 7 9.5 4-1.3 7-5 7-9.5V6l-7-3Z', 'm9 12 2.2 2.2L15.5 10'] },
  bell: { sf: 'bell.fill', d: ['M6 16v-5a6 6 0 1 1 12 0v5l1.5 2.5h-15L6 16Z', 'M10 20.5a2.2 2.2 0 0 0 4 0'] },
  globe: { sf: 'globe', d: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z', 'M3 12h18', 'M12 3c2.5 2.4 3.8 5.5 3.8 9S14.5 18.6 12 21c-2.5-2.4-3.8-5.5-3.8-9S9.5 5.4 12 3Z'] },
  bolt: { sf: 'bolt.fill', d: 'M13 3 5 13.5h5L11 21l8-10.5h-5L13 3Z' },
  news: { sf: 'newspaper.fill', d: ['M5 4.5h11a2 2 0 0 1 2 2V19a1.5 1.5 0 0 0 3 0V8.5M5 4.5a1 1 0 0 0-1 1V18a2.5 2.5 0 0 0 2.5 2.5H19.5M5 4.5h9', 'M8 9h6M8 13h6M8 17h4'] },
  clock: { sf: 'clock.fill', d: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z', 'M12 7v5l3.5 2'] },
  theme: { sf: 'circle.lefthalf.filled', d: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z', 'M12 3v18'] },
};

interface Props {
  name: IconName;
  size?: number;
  color?: string;
  strokeWidth?: number;
}

export function Icon({ name, size = 22, color, strokeWidth = 1.8 }: Props) {
  const { palette } = useTheme();
  const c = color ?? palette.ink;
  const spec = MAP[name];

  if (Platform.OS === 'ios') {
    return <SymbolView name={spec.sf} size={size} tintColor={c} resizeMode="scaleAspectFit" />;
  }

  const paths = Array.isArray(spec.d) ? spec.d : [spec.d];
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {paths.map((d, i) => (
        <Path key={i} d={d} stroke={c} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" fill="none" />
      ))}
      {name === 'clock' && <Circle cx={12} cy={12} r={0.5} fill={c} />}
    </Svg>
  );
}
