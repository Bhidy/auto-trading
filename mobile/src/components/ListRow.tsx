import React from 'react';
import { View, type ViewStyle } from 'react-native';
import { Text } from './Text';
import { PressableScale } from './PressableScale';
import { useTheme } from '@/theme/ThemeProvider';
import { radius } from '@/theme/tokens';
import { fonts } from '@/theme/typography';
import { trendOf } from '@/lib/format';
import { haptic } from '@/lib/haptics';

interface Props {
  monogram?: string;
  title: string;
  sub?: string;
  value?: string;
  /** Percentage number, e.g. 1.34 → +1.34% */
  delta?: number | null;
  /** Espresso featured row (reference "stock list" first row). */
  contrast?: boolean;
  right?: React.ReactNode;
  onPress?: () => void;
  style?: ViewStyle;
}

/** Rounded asset/list row — light tint by default, espresso contrast variant. */
export function ListRow({ monogram, title, sub, value, delta, contrast = false, right, onPress, style }: Props) {
  const { palette } = useTheme();
  const t = trendOf(delta ?? 0);
  const upC = contrast ? '#7ED9A5' : palette.up;
  const downC = contrast ? '#FF9A8B' : palette.down;
  const deltaColor = t === 'up' ? upC : t === 'down' ? downC : contrast ? palette.contrastMuted : palette.muted;
  const sign = delta != null && isFinite(delta) ? (delta > 0 ? '+' : delta < 0 ? '−' : '') : '';

  const body = (
    <View
      style={[
        {
          flexDirection: 'row',
          alignItems: 'center',
          gap: 12,
          paddingVertical: 13,
          paddingHorizontal: 14,
          borderRadius: radius.lg - 2,
          backgroundColor: contrast ? palette.contrast : palette.surfaceAlt,
        },
        style,
      ]}
    >
      {monogram != null && (
        <View
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            backgroundColor: contrast ? 'rgba(255,244,236,0.12)' : palette.surface,
            borderWidth: contrast ? 0 : 1,
            borderColor: palette.line,
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text
            style={{
              fontFamily: fonts.uiExtra,
              fontSize: 13,
              color: contrast ? palette.contrastInk : palette.ink,
            }}
          >
            {monogram.slice(0, 2)}
          </Text>
        </View>
      )}

      <View style={{ flex: 1, gap: 1 }}>
        <Text variant="bodyStrong" numberOfLines={1} style={{ color: contrast ? palette.contrastInk : palette.ink }}>
          {title}
        </Text>
        {!!sub && (
          <Text variant="caption" numberOfLines={1} style={{ color: contrast ? palette.contrastMuted : palette.muted }}>
            {sub}
          </Text>
        )}
      </View>

      {right}

      {(value != null || delta != null) && (
        <View style={{ alignItems: 'flex-end', gap: 1 }}>
          {value != null && (
            <Text
              style={{
                fontFamily: fonts.uiBold,
                fontSize: 14.5,
                color: contrast ? palette.contrastInk : palette.ink,
              }}
            >
              {value}
            </Text>
          )}
          {delta != null && isFinite(delta) && (
            <Text style={{ fontFamily: fonts.uiBold, fontSize: 12.5, color: deltaColor }}>
              {sign}
              {Math.abs(delta).toFixed(2)}%
            </Text>
          )}
        </View>
      )}
    </View>
  );

  if (!onPress) return body;
  return (
    <PressableScale
      scaleTo={0.98}
      onPress={() => {
        haptic.select();
        onPress();
      }}
    >
      {body}
    </PressableScale>
  );
}
