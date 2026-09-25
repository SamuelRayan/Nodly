import { Stack } from 'expo-router';

/** Family sign-in: index (email) → verify (the emailed code). */
export default function SignInLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
