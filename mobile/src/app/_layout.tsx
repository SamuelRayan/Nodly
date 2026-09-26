import '@/i18n';

import { QueryClientProvider } from '@tanstack/react-query';
import { SplashScreen, Stack } from 'expo-router';
import { useEffect, useState } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { queryClient } from '@/api/query';
import { SessionProvider, useMe, useSession } from '@/auth/session';
import { Loading } from '@/components/ui';
import { registerForPush } from '@/push/notifications';
import { useNotificationRouting } from '@/push/useNotificationRouting';
import { useAppStore } from '@/state/app';
import { ThemeProvider } from '@/theme';

void SplashScreen.preventAutoHideAsync();

type Status =
  | 'loading'
  | 'welcome'
  | 'family-signin'
  | 'onboarding'
  | 'family-error'
  | 'family'
  | 'elder-pair'
  | 'elder';

/** Where this phone should be, from its stored mode, the Supabase session and /v1/me. */
function useStatus(): Status {
  const { hydrated, mode, deviceToken } = useAppStore();
  const { ready, session } = useSession();
  const me = useMe(mode === 'family');

  if (!hydrated || !ready) {
    return 'loading';
  }
  if (mode === null) {
    return 'welcome';
  }
  if (mode === 'elder') {
    return deviceToken ? 'elder' : 'elder-pair';
  }
  if (!session) {
    return 'family-signin';
  }
  if (me.isPending) {
    return 'loading';
  }
  if (me.isError) {
    return 'family-error';
  }
  return me.data.onboarding.complete ? 'family' : 'onboarding';
}

function RootNavigator() {
  const status = useStatus();
  // Once anything has been shown, the splash screen is gone for good.
  const [splashHidden, setSplashHidden] = useState(false);
  if (status !== 'loading' && !splashHidden) {
    setSplashHidden(true); // adjusting state while rendering, as React recommends
  }
  useEffect(() => {
    if (splashHidden) {
      SplashScreen.hide();
    }
  }, [splashHidden]);

  // Taps on notifications and their buttons ("I'm okay", "I'm on it").
  useNotificationRouting(status === 'elder' ? 'elder' : status === 'family' ? 'family' : 'other');

  // Register this phone for push once it knows who it belongs to.
  useEffect(() => {
    if (status === 'family' || status === 'onboarding') {
      void registerForPush('user');
    } else if (status === 'elder') {
      void registerForPush('device');
    }
  }, [status]);

  if (status === 'loading') {
    // First launch: the splash screen is still up. Later (e.g. just signed in): a spinner.
    return splashHidden ? <Loading /> : null;
  }
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Protected guard={status === 'welcome'}>
        <Stack.Screen name="welcome" />
      </Stack.Protected>
      <Stack.Protected guard={status === 'family-signin'}>
        <Stack.Screen name="signin" />
      </Stack.Protected>
      <Stack.Protected guard={status === 'onboarding'}>
        <Stack.Screen name="onboarding" />
      </Stack.Protected>
      <Stack.Protected guard={status === 'family-error'}>
        <Stack.Screen name="family-error" />
      </Stack.Protected>
      <Stack.Protected guard={status === 'family'}>
        <Stack.Screen name="(family)" />
      </Stack.Protected>
      <Stack.Protected guard={status === 'elder-pair'}>
        <Stack.Screen name="pair" />
      </Stack.Protected>
      <Stack.Protected guard={status === 'elder'}>
        <Stack.Screen name="home" />
      </Stack.Protected>
    </Stack>
  );
}

function ThemedApp() {
  const mode = useAppStore((state) => state.mode);
  // Elder phones (and the first-launch choice, which elders see too) use the elder scale.
  return (
    <ThemeProvider scale={mode === 'family' ? 'family' : 'elder'}>
      <RootNavigator />
    </ThemeProvider>
  );
}

export default function RootLayout() {
  const hydrate = useAppStore((state) => state.hydrate);
  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <ThemedApp />
        </SessionProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
