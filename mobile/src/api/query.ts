import NetInfo from '@react-native-community/netinfo';
import { focusManager, MutationCache, onlineManager, QueryCache, QueryClient } from '@tanstack/react-query';
import { AppState, type AppStateStatus } from 'react-native';

import { supabase } from '@/auth/supabase';
import { useAppStore } from '@/state/app';

import { ApiError } from './errors';

/** Errors that mean "this phone's credentials are gone" — handled once, app-wide. */
function onAuthError(error: unknown) {
  if (!(error instanceof ApiError)) {
    return;
  }
  const { mode } = useAppStore.getState();
  if (mode === 'elder' && (error.code === 'device_revoked' || error.code === 'invalid_token')) {
    void useAppStore.getState().resetToWelcome('device_revoked');
  }
  if (mode === 'family' && (error.code === 'invalid_token' || error.code === 'not_authenticated')) {
    void supabase.auth.signOut();
  }
}

export const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onAuthError }),
  mutationCache: new MutationCache({ onError: onAuthError }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Retry only what can succeed on its own: no answer, server errors, a just-expired token.
      retry: (failures, error) =>
        failures < 2 &&
        error instanceof ApiError &&
        (error.status === 0 || error.status >= 500 || error.code === 'token_expired'),
    },
    mutations: { retry: false },
  },
});

// Pause and resume queries with connectivity and app focus (TanStack Query on React Native).
onlineManager.setEventListener((setOnline) =>
  NetInfo.addEventListener((state) => setOnline(state.isConnected !== false)),
);
AppState.addEventListener('change', (status: AppStateStatus) => {
  focusManager.setFocused(status === 'active');
});
