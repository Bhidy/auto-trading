import React from 'react';
import { RefreshControl, ScrollView, type ScrollViewProps, View } from 'react-native';
import { useTheme } from '@/theme/ThemeProvider';
import { AmbientBackground } from './AmbientBackground';

interface Props extends ScrollViewProps {
  scroll?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  padded?: boolean;
  ambient?: boolean;
}

/** Themed page container — living ambient backdrop + optional pull-to-refresh. */
export function Screen({
  scroll = true,
  refreshing = false,
  onRefresh,
  padded = true,
  ambient = true,
  children,
  contentContainerStyle,
  style,
  ...rest
}: Props) {
  const { palette } = useTheme();
  const pad = padded ? { paddingHorizontal: 18 } : null;

  const body = !scroll ? (
    <View style={[{ flex: 1 }, pad, style]}>{children}</View>
  ) : (
    <ScrollView
      {...rest}
      style={[{ flex: 1 }, style]}
      contentContainerStyle={[{ paddingBottom: 132 }, pad, contentContainerStyle]}
      showsVerticalScrollIndicator={false}
      refreshControl={
        onRefresh ? (
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={palette.teal}
            colors={[palette.teal]}
            progressBackgroundColor={palette.surface}
          />
        ) : undefined
      }
    >
      {children}
    </ScrollView>
  );

  return (
    <View style={{ flex: 1, backgroundColor: palette.page }}>
      {ambient && <AmbientBackground />}
      {body}
    </View>
  );
}
