/**
 * Gated-trading security: the DASHBOARD_ACCESS_TOKEN is stored in the iOS Keychain
 * (expo-secure-store) and never leaves the device except as a Bearer header to the
 * Auto Trading API. Every mutation is additionally gated by Face ID / Touch ID.
 *
 * Server-side, the API fails closed (503) without a valid token, so a missing or
 * wrong token can never execute a trade.
 */
import * as SecureStore from 'expo-secure-store';
import * as LocalAuthentication from 'expo-local-authentication';

const TOKEN_KEY = 'rw.dashboard.token';

export async function getAccessToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(TOKEN_KEY);
  } catch {
    return null;
  }
}

export async function setAccessToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(TOKEN_KEY, token.trim(), {
    keychainAccessible: SecureStore.WHEN_UNLOCKED,
  });
}

export async function clearAccessToken(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
  } catch {
    /* noop */
  }
}

export async function hasAccessToken(): Promise<boolean> {
  return !!(await getAccessToken());
}

export interface BiometricSupport {
  hardware: boolean;
  enrolled: boolean;
  type: 'face' | 'fingerprint' | 'none';
}

export async function biometricSupport(): Promise<BiometricSupport> {
  try {
    const hardware = await LocalAuthentication.hasHardwareAsync();
    const enrolled = await LocalAuthentication.isEnrolledAsync();
    const types = await LocalAuthentication.supportedAuthenticationTypesAsync();
    const type = types.includes(LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION)
      ? 'face'
      : types.includes(LocalAuthentication.AuthenticationType.FINGERPRINT)
        ? 'fingerprint'
        : 'none';
    return { hardware, enrolled, type };
  } catch {
    return { hardware: false, enrolled: false, type: 'none' };
  }
}

export type AuthorizeReason = 'no-token' | 'biometric-failed' | 'biometric-error';

export interface AuthorizeResult {
  ok: boolean;
  reason?: AuthorizeReason;
}

/**
 * Authorize a sensitive action. Requires (1) a stored access token and
 * (2) a successful biometric check when biometrics are enrolled.
 */
export async function authorizeAction(promptMessage: string): Promise<AuthorizeResult> {
  const token = await getAccessToken();
  if (!token) return { ok: false, reason: 'no-token' };

  const { hardware, enrolled } = await biometricSupport();
  if (!hardware || !enrolled) {
    // No biometrics enrolled — the server token gate still applies.
    return { ok: true };
  }

  try {
    const res = await LocalAuthentication.authenticateAsync({
      promptMessage,
      cancelLabel: 'Cancel',
      disableDeviceFallback: false,
    });
    return res.success ? { ok: true } : { ok: false, reason: 'biometric-failed' };
  } catch {
    return { ok: false, reason: 'biometric-error' };
  }
}
