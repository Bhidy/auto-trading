import React, { useEffect, useState } from 'react';
import { View } from 'react-native';
import { Redirect } from 'expo-router';
import { useTheme } from '@/theme/ThemeProvider';
import { storage, KEYS } from '@/lib/storage';

/** Entry gate: first launch → 3D onboarding; otherwise straight to the app. */
export default function Gate() {
  const { palette } = useTheme();
  const [state, setState] = useState<'loading' | 'onboarding' | 'app'>('loading');

  useEffect(() => {
    let active = true;
    storage
      .getBool(KEYS.onboarded)
      .then((seen) => active && setState(seen ? 'app' : 'onboarding'))
      .catch(() => active && setState('onboarding'));
    return () => {
      active = false;
    };
  }, []);

  if (state === 'loading') return <View style={{ flex: 1, backgroundColor: palette.page }} />;
  return <Redirect href={state === 'app' ? '/home' : '/onboarding'} />;
}
