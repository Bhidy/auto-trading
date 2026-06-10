import React, { useEffect, useState } from 'react';
import { Platform, View } from 'react-native';
import { Screen } from '@/components/Screen';
import { PageHeader } from '@/components/PageHeader';
import { FilterPills } from '@/components/FilterPills';
import { Text } from '@/components/Text';
import { Tag } from '@/components/Tag';
import { Button } from '@/components/Button';
import { Divider } from '@/components/Divider';
import { Field } from '@/components/Field';
import { Icon } from '@/components/Icon';
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
import { fonts } from '@/theme/typography';
import { cardShadow, radius } from '@/theme/tokens';
import { haptic } from '@/lib/haptics';

const THEME_OPTIONS = ['Dark', 'Light', 'System'] as const;
const PREF_MAP: Record<(typeof THEME_OPTIONS)[number], ThemePref> = { Dark: 'dark', Light: 'light', System: 'system' };
const LABEL_MAP: Record<ThemePref, (typeof THEME_OPTIONS)[number]> = { dark: 'Dark', light: 'Light', system: 'System' };

function SectionIcon({ name }: { name: 'settings' | 'lock' | 'globe' | 'bolt' }) {
  const { palette } = useTheme();
  return (
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
      <Icon name={name} size={17} color={palette.teal} />
    </View>
  );
}

export default function Settings() {
  const { palette, pref, setPref, scheme } = useTheme();
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

  const flatCard = {
    backgroundColor: palette.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: palette.line,
    ...cardShadow(scheme),
  };

  const sectionTitle = (label: string) => (
    <Text style={{ fontFamily: fonts.uiBold, fontSize: 15, letterSpacing: -0.2, color: palette.ink }}>
      {label}
    </Text>
  );

  return (
    <Screen
      padded={false}
      ambient={false}
      contentContainerStyle={{ paddingBottom: 130, paddingHorizontal: 18 }}
    >
      <PageHeader title="Settings" sub="Control room" />

      <View style={{ gap: 20 }}>

        {/* ── APPEARANCE ── */}
        <View style={{ ...flatCard, padding: 16, gap: 14 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <SectionIcon name="settings" />
            {sectionTitle('Appearance')}
          </View>
          <FilterPills
            options={THEME_OPTIONS}
            value={LABEL_MAP[pref]}
            onChange={(v) => setPref(PREF_MAP[v as typeof THEME_OPTIONS[number]])}
            stretch
          />
          <Text style={{ fontFamily: fonts.uiMedium, fontSize: 12.5, color: palette.muted, lineHeight: 18 }}>
            Dark Solar is the native terminal experience. Light Paper mirrors the day theme.
          </Text>
        </View>

        {/* ── TRADING SECURITY ── */}
        <View style={{ ...flatCard, padding: 16, gap: 16 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
              <SectionIcon name="lock" />
              {sectionTitle('Trading security')}
            </View>
            <Tag
              label={tokenSet ? 'Armed' : 'Read-only'}
              tone={tokenSet ? 'live' : 'neutral'}
              live={!!tokenSet}
            />
          </View>

          <Text style={{ fontFamily: fonts.uiMedium, fontSize: 12.5, color: palette.muted, lineHeight: 18 }}>
            Live actions (orders, closes, cancels) require the dashboard access token — stored only in the iOS
            Keychain. Every action additionally requires{' '}
            {bio?.type === 'face' ? 'Face ID' : bio?.type === 'fingerprint' ? 'Touch ID' : 'biometric confirmation'}.
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
              style={{
                fontFamily: fonts.uiMedium,
                fontSize: 12.5,
                color: notice.includes('enabled') || notice.includes('stored') ? palette.up : palette.down,
                lineHeight: 17,
              }}
            >
              {notice}
            </Text>
          )}
        </View>

        {/* ── BROKER CONNECTIONS ── */}
        <View style={{ ...flatCard }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 16 }}>
            <SectionIcon name="globe" />
            {sectionTitle('Broker connections')}
          </View>
          <Divider />
          {PORTFOLIOS.map((p, i) => {
            const live = overview?.find((o) => o.id === p.id)?.liveConnected;
            return (
              <View key={p.id}>
                {i > 0 && <Divider />}
                <View style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 14, paddingHorizontal: 16, gap: 12 }}>
                  <View style={{ flex: 1, gap: 2 }}>
                    <Text style={{ fontFamily: fonts.uiBold, fontSize: 14, color: palette.ink }}>{p.label}</Text>
                    <Text style={{ fontFamily: fonts.uiMedium, fontSize: 12, color: palette.muted }}>
                      Alpaca paper · {p.account}
                    </Text>
                  </View>
                  <Tag label={live ? 'Connected' : 'Synced'} tone={live ? 'live' : 'neutral'} live={!!live} />
                </View>
              </View>
            );
          })}
        </View>

        {/* ── ABOUT ── */}
        <View style={{ ...flatCard, padding: 16, gap: 12 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <SectionIcon name="bolt" />
            {sectionTitle('About')}
          </View>
          <View style={{ gap: 5 }}>
            <Text style={{ fontFamily: fonts.uiMedium, fontSize: 12.5, color: palette.muted, lineHeight: 18 }}>
              Auto Trading by RiseWealth — three autonomous strategies, one paper book.
            </Text>
            <Text style={{ fontFamily: fonts.mono, fontSize: 11.5, color: palette.muted }}>
              {API_BASE_URL}
            </Text>
            <Text style={{ fontFamily: fonts.uiMedium, fontSize: 12.5, color: palette.muted }}>
              Paper trading only. Not financial advice.
            </Text>
          </View>
        </View>

      </View>
    </Screen>
  );
}
