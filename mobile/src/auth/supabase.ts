import 'react-native-url-polyfill/auto';

import { createClient, processLock } from '@supabase/supabase-js';
import { AppState } from 'react-native';

import { config } from '@/config';
import { chunkedSecureStorage } from '@/storage/secure';

// Supabase's React Native setup: https://supabase.com/docs/guides/getting-started/quickstarts/expo-react-native
// The session lives in SecureStore (chunked), not AsyncStorage.
export const supabase = createClient(config.supabaseUrl, config.supabasePublishableKey, {
  auth: {
    storage: chunkedSecureStorage,
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: false,
    lock: processLock,
  },
});

// Refresh the session only while the app is in the foreground (Supabase's recommendation).
AppState.addEventListener('change', (state) => {
  if (state === 'active') {
    void supabase.auth.startAutoRefresh();
  } else {
    void supabase.auth.stopAutoRefresh();
  }
});

/** Email one-time codes: Nodly's template sends 6–8 digits, no link. */
export const OTP_PATTERN = /^[0-9]{6,8}$/;
