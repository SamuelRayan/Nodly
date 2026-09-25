import { Stack } from 'expo-router';

import { useTheme } from '@/theme';

// A deep link (e.g. nodly://invite/<code>) still has the family home underneath it to go back to.
// https://docs.expo.dev/router/advanced/router-settings/
export const unstable_settings = { anchor: 'index' };

export default function FamilyLayout() {
  const { colors } = useTheme();
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: colors.surface },
        headerTintColor: colors.text,
        contentStyle: { backgroundColor: colors.background },
      }}
    />
  );
}
