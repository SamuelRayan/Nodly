import Constants from 'expo-constants';

/** The display name, in one place on the app side (CLAUDE.md). */
export const APP_NAME = 'Nodly';

export type Store = 'galaxy' | 'play' | 'ios';

function required(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(`${name} is not set: copy mobile/.env.example to mobile/.env`);
  }
  return value;
}

// EXPO_PUBLIC_* values are inlined at build time, so they must be read with static names.
export const config = {
  apiUrl: required('EXPO_PUBLIC_API_URL', process.env.EXPO_PUBLIC_API_URL).replace(/\/$/, ''),
  supabaseUrl: required('EXPO_PUBLIC_SUPABASE_URL', process.env.EXPO_PUBLIC_SUPABASE_URL),
  supabasePublishableKey: required(
    'EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY',
    process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
  ),
  store: (process.env.EXPO_PUBLIC_STORE ?? 'galaxy') as Store,
  // RevenueCat's Test Store key: development builds only (CLAUDE.md §10: never ship it; the
  // SDK also refuses it in release builds). Store keys per build profile come later.
  revenuecatKey: __DEV__ ? process.env.EXPO_PUBLIC_REVENUECAT_TEST_STORE_KEY : undefined,
  easProjectId:
    (Constants.expoConfig?.extra?.eas?.projectId as string | undefined) ??
    Constants.easConfig?.projectId,
};
