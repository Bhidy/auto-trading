import React, { useEffect, useState } from 'react';
import { Platform, View } from 'react-native';
import { Screen } from '@/components/Screen';
import { ScreenHeader } from '@/components/ScreenHeader';
import { Card } from '@/components/Card';
import { GlassCard } from '@/components/GlassCard';
import { Text } from '@/components/Text';
import { Tag } from '@/components/Tag';
import { Button } from '@/components/Button';
import { Divider } from '@/components/Divider';
import { Field } from '@/components/Field';
import { Icon } from '@/components/Icon';
import { SegmentedControl } from '@/components/SegmentedControl';
import { Reveal } from '@/components/Reveal';
import { useOverview } from '@/api/hooks';
import {
  biometricSupport,
  clearAccessToken,
  hasAccessToken,
  setAccessToken,
  type BiometricSupport,
} from '@/lib/auth';
import { useTheme, type ThemePref } from '@/theme';
import { PORTFOLIOS, API_BASE_URL } from '@/lib/constants';
import { haptic } from '@/lib/haptics';

const THEME_OPTIONS = ['Dark', 'Light', 'System'] as const;
const PREF_MAP: Record<(typeof THEME_OPTIONS)[number], ThemePref> = { Dark: 'dark', Light: 'light', System: 'system' };
const LABEL_MAP: Record<ThemePref, (typeof THEME_OPTIONS)[number]> = { dark: 'Dark', light: 'Light', system: 'System' };

export default function Settings() {
  const { palette, pref, setPref } = useTheme();
  const { data: overview } = useOverview();

  const [tokenInput, setTokenInput] = useState('');
  const [tokenSet, setTokenSet] = useState<boolean | null>(null);
  const [bio, setBio] = useState<BiometricSupport | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    hasAccessToken().then(setTokenSet).catch(() => setTokenSet(false));
    biometricSupport().then(setBio).catch(() => null);
  }, []);

  const saveToken = async () => {
    setNotice(null);
    if (!tokenInput.trim()) {
      setNotice('Paste the DASHBOARD_ACCESS_TOKEN value first.');
      return;
    }
    try {
      await setAccessToken(tokenInput);
      setTokenInput('');
      setTokenSet(true);
      haptic.success();
      setNotice('Token stored securely. Live actions are now enabled.');
    } catch {
      haptic.error();
      setNotice(
        Platform.OS === 'web'
          ? 'Secure storage requires the device app — open this in Expo Go.'
          : 'Could not store the token securely on this device.',
      );
    }
  };

  const removeToken = async () => {
    await clearAccessToken();
    setTokenSet(false);
    haptic.warning();
    setNotice('Token removed — the app is now read-only.');
  };

  return (
    <Screen>
      <ScreenHeader title="Settings" eyebrow="Control room" />

      <View style={{ gap: 20 }}>

        {/* ── APPEARANCE ── */}
        <Reveal index={0}>
          <Card style={{ gap: 14 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
              <View
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 11,
                  backgroundColor: palette.tealSoft,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Icon name="settings" size={17} color={palette.teal} />
              </View>
              <Text variant="subtitle">Appearance</Text>
            </View>
            <SegmentedControl
              options={THEME_OPTIONS}
              value={LABEL_MAP[pref]}
              onChange={(v) => setPref(PREF_MAP[v])}
            />
            <Text variant="caption" dim>
              Dark Solar is the native terminal experience. Light Paper mirrors the day theme.
            </Text>
          </Card>
        </Reveal>

        {/* ── TRADING SECURITY ── */}
        <Reveal index={1}>
          <GlassCard glow style={{ gap: 16 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
                <View
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 11,
                    backgroundColor: palette.tealSoft,
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <Icon name="lock" size={17} color={palette.teal} />
                </View>
                <Text variant="subtitle">Trading security</Text>
              </View>
              <Tag
                label={tokenSet ? 'Armed' : 'Read-only'}
                tone={tokenSet ? 'live' : 'neutral'}
                live={!!tokenSet}
              />
            </View>

            <Text variant="caption" dim>
              Live actions (orders, closes, cancels) require the dashboard access token — stored only in the iOS Keychain.
              Every action additionally requires{' '}
              {bio?.type === 'face'
                ? 'Face ID'
                : bio?.type === 'fingerprint'
                  ? 'Touch ID'
                  : 'biometric confirmation'}
              .
            </Text>

            {tokenSet ? (
              <Button label="Remove token (back to read-only)" variant="ghost" full onPress={removeToken} />
            ) : (
              <View style={{ gap: 10 }}>
                <Field
                  label="Access token"
                  value={tokenInput}
                  onChangeText={setTokenInput}
                  placeholder="DASHBOARD_ACCESS_TOKEN"
                  secure
                />
                <Button label="Store in Keychain" full onPress={saveToken} />
              </View>
            )}

            {notice && (
              <Text
                variant="caption"
                color={notice.includes('enabled') || notice.includes('stored') ? 'up' : 'down'}
              >
                {notice}
              </Text>
            )}
          </GlassCard>
        </Reveal>

        {/* ── BROKER CONNECTIONS ── */}
        <Reveal index={2}>
          <Card padded={false} style={{ paddingHorizontal: 16, paddingVertical: 4 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 14 }}>
              <View
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 11,
                  backgroundColor: palette.tealSoft,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Icon name="globe" size={17} color={palette.teal} />
              </View>
              <Text variant="subtitle">Broker connections</Text>
            </View>
            <Divider />
            {PORTFOLIOS.map((p, i) => {
              const live = overview?.find((o) => o.id === p.id)?.liveConnected;
              return (
                <View key={p.id}>
                  {i > 0 && <Divider />}
                  <View style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 14, gap: 12 }}>
                    <View style={{ flex: 1, gap: 2 }}>
                      <Text variant="bodyStrong">{p.label}</Text>
                      <Text variant="caption" dim>
                        Alpaca paper · {p.account}
                      </Text>
                    </View>
                    <Tag
                      label={live ? 'Connected' : 'Synced'}
                      tone={live ? 'live' : 'neutral'}
                      live={!!live}
                    />
                  </View>
                </View>
              );
            })}
          </Card>
        </Reveal>

        {/* ── ABOUT ── */}
        <Reveal index={3}>
          <Card style={{ gap: 10 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
              <View
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 11,
                  backgroundColor: palette.tealSoft,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Icon name="bolt" size={17} color={palette.teal} />
              </View>
              <Text variant="subtitle">About</Text>
            </View>
            <View style={{ gap: 5 }}>
              <Text variant="caption" dim>
                Auto Trading by RiseWealth — three autonomous strategies, one paper book.
              </Text>
              <Text variant="caption" dim>
                API · {API_BASE_URL}
              </Text>
              <Text variant="caption" dim>
                Paper trading only. Not financial advice.
              </Text>
            </View>
          </Card>
        </Reveal>
      </View>
    </Screen>
  );
}
