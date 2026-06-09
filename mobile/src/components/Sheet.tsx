import React from 'react';
import { Modal, Pressable, View } from 'react-native';
import Animated, { FadeIn, SlideInDown } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '@/theme/ThemeProvider';
import { radius } from '@/theme/tokens';

interface Props {
  visible: boolean;
  onClose: () => void;
  children: React.ReactNode;
}

/** Bottom sheet — scrim + grab handle + slide-up card. */
export function Sheet({ visible, onClose, children }: Props) {
  const { palette } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <Modal visible={visible} transparent animationType="none" onRequestClose={onClose}>
      <View style={{ flex: 1, justifyContent: 'flex-end' }}>
        <Animated.View entering={FadeIn.duration(180)} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}>
          <Pressable style={{ flex: 1, backgroundColor: palette.overlay }} onPress={onClose} />
        </Animated.View>
        <Animated.View
          entering={SlideInDown.springify().damping(19).stiffness(180)}
          style={{
            backgroundColor: palette.surface,
            borderTopLeftRadius: radius.xl,
            borderTopRightRadius: radius.xl,
            borderWidth: 1,
            borderColor: palette.line,
            paddingHorizontal: 20,
            paddingTop: 10,
            paddingBottom: insets.bottom + 20,
            gap: 14,
          }}
        >
          <View
            style={{
              alignSelf: 'center',
              width: 40,
              height: 4.5,
              borderRadius: 3,
              backgroundColor: palette.hairline,
              marginBottom: 4,
            }}
          />
          {children}
        </Animated.View>
      </View>
    </Modal>
  );
}
